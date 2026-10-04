from __future__ import annotations

from collections import defaultdict

from gpu_guard import TierAwareValue
from purchase_policy import installation_cost, total_cost


_OBSERVATIONS: list[dict] = []


def historical_bonus(context: dict | None) -> float:
    if not isinstance(context, dict) or not context.get("available"):
        return 0.0
    if "days_observed" in context and int(context["days_observed"]) < 3:
        return 0.0
    if context.get("new_low"):
        return 5.0
    if context.get("at_or_near_low"):
        return 3.0
    try:
        delta = float(context.get("delta_vs_average_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        delta = 0.0
    if delta < 0:
        return min(4.0, abs(delta) / 3.0)
    return 0.0


def calculate_opportunity(value: float, gaming: float, historical: dict | None = None) -> dict:
    """Unified purchase utility, also retained as the legacy Opportunity API.

    Base Value contributes 80%, Gaming 20% after scaling to 150; verified
    history can add at most five points. Never apply this twice to Value.
    """
    raw_value = max(0.0, min(150.0, float(value)))
    gaming_score = max(0.0, min(100.0, float(gaming)))
    value_component = raw_value * 0.80
    gaming_component = gaming_score * 1.5 * 0.20
    history_component = historical_bonus(historical)
    score = min(150.0, value_component + gaming_component + history_component)
    return {
        "score": round(score, 1),
        "value_component": round(value_component, 2),
        "gaming_component": round(gaming_component, 2),
        "history_component": round(history_component, 2),
        "value": round(raw_value, 2),
        "gaming": round(gaming_score, 2),
    }


def normalize_value_truth(assessment: dict, *, unified: bool = False) -> dict:
    """Remove do Value o antigo bónus absoluto de preço baixo.

    O cérebro base já recompensa preço através de `price_score`. A camada V8.8
    acrescentava depois `exceptional_deal_bonus`, premiando o preço uma segunda
    vez. Mantemos esse valor apenas para auditoria histórica; Value/tier passam a
    usar `value_score_sem_bonus`.
    """
    if not isinstance(assessment, dict) or assessment.get("status") != "ACEITE":
        return assessment
    base = assessment.get("value_score_sem_bonus")
    if base is None:
        assessment.setdefault("value_truth_schema", 1)
        return assessment
    try:
        base_value = max(0.0, min(150.0, float(base)))
    except (TypeError, ValueError):
        return assessment

    try:
        legacy_bonus = float(assessment.get("exceptional_deal_bonus", 0.0) or 0.0)
    except (TypeError, ValueError):
        legacy_bonus = 0.0
    details = assessment.get("detalhes") if isinstance(assessment.get("detalhes"), dict) else {}
    gaming = float(details.get("Gaming", 0.0) or 0.0)
    components = calculate_opportunity(base_value, gaming, assessment.get("historical_price"))
    final_value = components["score"] if unified else base_value
    wrapped = final_value if unified else TierAwareValue(base_value, gaming_score=gaming)
    if unified:
        assessment["unified_value_components"] = components
        assessment["value_truth_schema"] = 2

    assessment["value_score"] = wrapped
    assessment["value_score_sem_bonus"] = round(base_value, 1)
    assessment["legacy_exceptional_deal_bonus"] = round(legacy_bonus, 1)
    assessment["exceptional_deal_bonus"] = 0.0
    assessment["value_truth_schema"] = 2 if unified else 1
    assessment["gpu_tier_influence"] = {
        "raw_value": round(final_value, 3),
        "gaming_score": round(gaming, 3),
        "multiplier": round(getattr(wrapped, "tier_multiplier", 1.0), 6),
        "tier_score": round(getattr(wrapped, "tier_score", final_value), 3),
    }
    return assessment


def _configuration_key(row: dict) -> str:
    key = str(row.get("configuration_key") or "").strip().lower()
    if key.startswith("ean:") or key.startswith("mpn:"):
        return key
    return f"url:{row.get('url') or ''}"


def deduplicate_observations(rows: list[dict]) -> list[dict]:
    """Uma configuração forte ocupa uma só posição no ranking de decisão."""
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            -float(row.get("score") or 0.0),
            -float(row.get("value") or 0.0),
            float(row.get("price") or 99999.0),
            str(row.get("url") or ""),
        ),
    )
    seen: set[str] = set()
    result: list[dict] = []
    for row in ordered:
        key = _configuration_key(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _latest_configuration_by_url(history: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    offers = history.get("offers", {}) if isinstance(history.get("offers"), dict) else {}
    for entries in offers.values():
        if not isinstance(entries, list) or not entries:
            continue
        entry = entries[-1]
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        key = str(entry.get("configuration_key") or "")
        if key:
            out[str(entry["url"])] = key
    return out


def deduplicate_snapshot(snapshot: list[dict], configuration_by_url: dict[str, str]) -> list[dict]:
    rows = []
    for row in snapshot or []:
        if not isinstance(row, dict):
            continue
        copy = dict(row)
        copy["configuration_key"] = configuration_by_url.get(str(copy.get("url") or ""))
        copy["score"] = float(copy.get("effective_value_score", copy.get("opportunity_score", 0.0)) or 0.0)
        copy["value"] = float(copy.get("effective_value_score", copy.get("value", 0.0)) or 0.0)
        copy["price"] = float(copy.get("effective_price", copy.get("price", 99999.0)) or 99999.0)
        rows.append(copy)
    deduped = deduplicate_observations(rows)
    output = []
    for index, row in enumerate(deduped, start=1):
        row.pop("score", None)
        row.pop("value", None) if "effective_value_score" in row else None
        row.pop("price", None) if "effective_price" in row else None
        row.pop("configuration_key", None)
        row["position"] = index
        output.append(row)
    return output


def install(tracker_module) -> None:
    if getattr(tracker_module, "_OPPORTUNITY_GUARD_INSTALLED", False):
        return
    required = (
        "record_offer",
        "main",
        "load_json",
        "save_json",
        "HISTORY_PATH",
        "score_allow_unknown",
    )
    if not all(hasattr(tracker_module, name) for name in required):
        return

    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_record_offer = tracker_module.record_offer
    base_main = tracker_module.main

    def score_allow_unknown(spec, price, weights, settings):
        if spec.get("keyboard_layout") == "es":
            return {"status": "REJEITADO", "alertas": ["Teclado espanhol confirmado."]}
        result = base_score_allow_unknown(spec, price, weights, settings)
        if result.get("status") != "ACEITE":
            return result
        cost = installation_cost(spec, settings)
        spec["installation_cost_eur"] = cost
        result["installation_cost_eur"] = cost
        result["purchase_total_eur"] = total_cost(price, cost)
        item = spec.get("_purchase_item") or {}
        checkout = float(price)
        if item.get("promotion_price_live_confirmed") is True:
            from promotion_value_guard import economics
            checkout = economics(item.get("promotions") or [], checkout)["effective_checkout_price"]
        if total_cost(checkout, cost) > float(settings.get("budget_hard", 1600.0)):
            return {"status": "REJEITADO", "alertas": ["Custo total com instalação excede orçamento."], "purchase_total_eur": total_cost(checkout, cost)}
        if cost:
            value_fn = getattr(tracker_module.scraper, "_PRICE_GUARD_ORIGINALS", {}).get("value_score", tracker_module.scraper.value_score)
            result["value_score_sem_bonus"] = float(value_fn(result["score_ranking"], total_cost(price, cost), settings))
        if spec.get("os_status") in {"unknown", "conflict"}:
            result.setdefault("alertas", []).append("Sistema operativo por confirmar; custo de instalação não presumido.")
        import historical_guard
        result["historical_price"] = historical_guard.historical_context(historical_guard._BASELINE_STATE, item, float(price)) if item else {}
        result["_purchase_item"] = item
        return normalize_value_truth(result, unified=bool(settings.get("unified_value_enabled", False)))

    if hasattr(tracker_module, "apply_exact_market_price_evidence"):
        base_apply_market = tracker_module.apply_exact_market_price_evidence
        def apply_market(records, settings):
            result = base_apply_market(records, settings)
            for row in records:
                spec, item = row.get("spec"), row.get("item", {})
                if isinstance(spec, dict):
                    if "os_status" not in spec:
                        from purchase_policy import enrich_purchase_specs
                        enrich_purchase_specs(spec, item.get("titulo", ""), [], tracker_module.scraper.norm)
                    spec["_purchase_item"] = {key: item[key] for key in ("url", "loja", "ean", "mpn", "promotions", "promotion_price_live_confirmed") if key in item}
            return result
        tracker_module.apply_exact_market_price_evidence = apply_market

    tracker_module.score_allow_unknown = score_allow_unknown

    # Promoções eram recalculadas por uma função auxiliar depois do score base;
    # normalizamos também esse caminho para impedir que o bónus antigo volte a
    # entrar no Value através de checkout promocional.
    try:
        import promotion_runtime_guard as promotion_runtime

        if not getattr(promotion_runtime, "_VALUE_TRUTH_PATCHED", False):
            base_promo_revalue = promotion_runtime._revalue_from_accepted

            def _revalue_from_accepted(module, assessment, checkout_price, settings):
                result = base_promo_revalue(module, assessment, checkout_price, settings)
                cost = float(assessment.get("installation_cost_eur", 0.0))
                result["purchase_total_eur"] = total_cost(checkout_price, cost)
                if result["purchase_total_eur"] > float(settings.get("budget_hard", 1600.0)):
                    return {"status": "REJEITADO", "alertas": ["Checkout com instalação excede orçamento."]}
                if cost and result.get("status") == "ACEITE":
                    value_fn = getattr(module.scraper, "_PRICE_GUARD_ORIGINALS", {}).get("value_score", module.scraper.value_score)
                    result["value_score_sem_bonus"] = float(value_fn(result["score_ranking"], result["purchase_total_eur"], settings))
                import historical_guard
                item = assessment.get("_purchase_item") or {}
                result["historical_price"] = historical_guard.historical_context(historical_guard._BASELINE_STATE, item, checkout_price) if item else {}
                return normalize_value_truth(result, unified=bool(settings.get("unified_value_enabled", False)))

            promotion_runtime._revalue_from_accepted = _revalue_from_accepted
            promotion_runtime._VALUE_TRUTH_PATCHED = True
    except Exception:
        pass

    def record_offer(history, item, spec, assessment, tier):
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        entries = history.get("offers", {}).get(key, [])
        entry = entries[-1] if entries and isinstance(entries[-1], dict) else None

        effective_value = assessment.get("value_score", 0.0)
        effective_price = item.get("preco", 0.0)
        effective_tier = tier
        if entry is not None:
            if entry.get("effective_value_score") is not None:
                effective_value = entry["effective_value_score"]
            elif entry.get("promotion_value_score") is not None:
                effective_value = entry["promotion_value_score"]
            elif entry.get("value_score") is not None:
                effective_value = entry["value_score"]

            if entry.get("effective_price") is not None:
                effective_price = entry["effective_price"]
            elif entry.get("promotion_checkout_price") is not None:
                effective_price = entry["promotion_checkout_price"]
            elif entry.get("price") is not None:
                effective_price = entry["price"]

            effective_tier = (
                entry.get("effective_tier")
                or entry.get("promotion_tier")
                or entry.get("tier")
                or tier
            )

        details = assessment.get("detalhes") if isinstance(assessment.get("detalhes"), dict) else {}
        opportunity = calculate_opportunity(
            float(effective_value or 0.0),
            float(details.get("Gaming", 0.0) or 0.0),
            assessment.get("historical_price"),
        )
        if assessment.get("value_truth_schema") == 2:
            # Compatibility field: never apply the same formula twice.
            opportunity = dict(assessment.get("unified_value_components") or opportunity)
            opportunity["score"] = float(effective_value or 0.0)
        assessment["opportunity_score"] = opportunity["score"]
        assessment["opportunity_components"] = opportunity

        if entry is not None:
            entry["installation_cost_eur"] = assessment.get("installation_cost_eur", 0.0)
            entry["purchase_total_eur"] = total_cost(effective_price, entry["installation_cost_eur"])
            entry["unified_value_components"] = assessment.get("unified_value_components")
            entry["opportunity_score"] = opportunity["score"]
            entry["opportunity_components"] = opportunity
            entry["value_truth_schema"] = assessment.get("value_truth_schema", 1)
            entry["legacy_exceptional_deal_bonus"] = assessment.get(
                "legacy_exceptional_deal_bonus", 0.0
            )
            _OBSERVATIONS.append(
                {
                    "url": entry.get("url"),
                    "timestamp": entry.get("timestamp"),
                    "store": entry.get("loja"),
                    "title": entry.get("titulo"),
                    "configuration_key": entry.get("configuration_key"),
                    "price": float(effective_price or 0.0),
                    "value": float(effective_value or 0.0),
                    "tier": effective_tier,
                    "stock": entry.get("stock"),
                    "score": opportunity["score"],
                    "gaming": opportunity["gaming"],
                }
            )
        return previous, key

    def main():
        _OBSERVATIONS.clear()
        run = base_main()
        raw_eligible = [row for row in _OBSERVATIONS if row.get("stock") is not False]
        eligible = deduplicate_observations(raw_eligible)
        positions = {
            (str(row.get("url") or ""), str(row.get("timestamp") or "")): index
            for index, row in enumerate(eligible, start=1)
        }
        snapshot = []
        for index, row in enumerate(eligible[:30], start=1):
            snapshot.append(
                {
                    "position": index,
                    "store": row.get("store"),
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "configuration_key": row.get("configuration_key"),
                    "price": round(float(row.get("price") or 0.0), 2),
                    "value": round(float(row.get("value") or 0.0), 1),
                    "gaming": round(float(row.get("gaming") or 0.0), 1),
                    "opportunity_score": round(float(row.get("score") or 0.0), 1),
                    "tier": row.get("tier"),
                }
            )

        try:
            history = tracker_module.load_json(tracker_module.HISTORY_PATH)
            offers = history.get("offers", {}) if isinstance(history.get("offers"), dict) else {}
            for entries in offers.values():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    marker = (str(entry.get("url") or ""), str(entry.get("timestamp") or ""))
                    if marker in positions:
                        entry["opportunity_position"] = positions[marker]

            configuration_by_url = _latest_configuration_by_url(history)
            raw_ranking_snapshot = run.get("ranking_snapshot", []) if isinstance(run, dict) else []
            dedup_ranking = deduplicate_snapshot(raw_ranking_snapshot, configuration_by_url)

            runs = (history.get("learning", {}) or {}).get("runs", [])
            if runs and isinstance(runs[-1], dict):
                runs[-1]["opportunity_snapshot"] = snapshot
                runs[-1]["opportunity_ranked"] = len(eligible)
                runs[-1]["opportunity_raw_offers"] = len(raw_eligible)
                if dedup_ranking:
                    runs[-1]["ranking_snapshot_raw_count"] = len(raw_ranking_snapshot)
                    runs[-1]["ranking_snapshot"] = dedup_ranking[:30]
            tracker_module.save_json(tracker_module.HISTORY_PATH, history)

            if isinstance(run, dict) and dedup_ranking:
                run["ranking_snapshot_raw_count"] = len(raw_ranking_snapshot)
                run["ranking_snapshot"] = dedup_ranking[:30]
        except Exception:
            if hasattr(tracker_module, "LOGGER"):
                tracker_module.LOGGER.warning(
                    "Opportunity/Value Truth calculado, mas não foi possível persistir posições"
                )

        if isinstance(run, dict):
            run["opportunity_snapshot"] = snapshot
            run["opportunity_ranked"] = len(eligible)
            run["opportunity_raw_offers"] = len(raw_eligible)
        if snapshot and hasattr(tracker_module, "LOGGER"):
            tracker_module.LOGGER.info(
                "Opportunity Rank | ofertas=%d | configs=%d | top=%s",
                len(raw_eligible),
                len(eligible),
                ", ".join(
                    f"{row['position']}:{row.get('store')}@{row['price']:.2f}€ O={row['opportunity_score']:.1f} V={row['value']:.1f}"
                    for row in snapshot[:5]
                ),
            )
        return run

    tracker_module.record_offer = record_offer
    tracker_module.main = main
    tracker_module._OPPORTUNITY_GUARD_INSTALLED = True
