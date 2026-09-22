from __future__ import annotations

from copy import deepcopy

from decision_truth import decision_truth, normalize_tier


_EMPTY_TIERS = {"DIAMANTE": 0, "OURO": 0, "PRATA": 0, "BRONZE": 0}


def _tier_counts() -> dict[str, int]:
    return dict(_EMPTY_TIERS)


def _latest_offer(history: dict, key: str) -> dict | None:
    offers = history.get("offers", {}) if isinstance(history, dict) else {}
    entries = offers.get(key, []) if isinstance(offers, dict) else []
    if isinstance(entries, list) and entries and isinstance(entries[-1], dict):
        return entries[-1]
    return None


def _truth_from_entry(entry: dict, *, diamond_threshold: float = 120.0) -> dict:
    return decision_truth(
        base_value_score=entry.get("value_score"),
        base_tier=entry.get("tier"),
        promotion_value_score=entry.get("promotion_value_score"),
        promotion_tier=entry.get("promotion_tier"),
        promotion_confirmed=bool(entry.get("promotion_price_live_confirmed")),
        promotion_discount_eur=entry.get("promotion_discount_eur", 0.0),
        diamond_threshold=diamond_threshold,
    )


def _annotate_entry(entry: dict, truth: dict) -> None:
    promotion_applied = bool(truth.get("promotion_applied"))
    entry["base_value_score"] = truth.get("base_value_score")
    entry["base_tier"] = truth.get("base_tier")
    entry["effective_value_score"] = truth.get("effective_value_score")
    entry["effective_tier"] = truth.get("effective_tier")
    entry["effective_price"] = (
        entry.get("promotion_checkout_price") if promotion_applied else entry.get("price")
    )
    entry["promotion_applied"] = promotion_applied
    entry["decision_truth_schema"] = 1


def install(tracker_module) -> None:
    """Liga a Decision Truth Layer às superfícies operacionais da V9.

    A V8.8.9 continua a calcular o tier base no loop principal. Esta camada
    mantém esse valor para auditoria, mas torna `effective_tier` a visão canónica
    para heartbeat, resumo persistido e TOP logs. Promoções só entram na decisão
    quando o runtime promocional já confirmou preço/elegibilidade.
    """
    if getattr(tracker_module, "_DECISION_TRUTH_RUNTIME_GUARD_INSTALLED", False):
        return

    base_record_offer = tracker_module.record_offer
    base_send_heartbeat = tracker_module.send_heartbeat
    base_main = tracker_module.main
    base_info = tracker_module.LOGGER.info

    state = {
        "active": False,
        "diamond_threshold": 120.0,
        "effective_tiers": _tier_counts(),
        "base_tiers": _tier_counts(),
        "records": [],
        "promotion_applied": 0,
    }

    def reset_state() -> None:
        state["effective_tiers"] = _tier_counts()
        state["base_tiers"] = _tier_counts()
        state["records"] = []
        state["promotion_applied"] = 0

    def record_offer(history, item, spec, assessment, tier):
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        entry = _latest_offer(history, key)
        if not isinstance(entry, dict):
            return previous, key

        if state["active"]:
            threshold = state["diamond_threshold"]
        else:
            settings = tracker_module.load_json(tracker_module.CONFIG_PATH).get("settings", {})
            threshold = float(settings.get("diamante_value_min", 120.0))
        truth = _truth_from_entry(entry, diamond_threshold=threshold)
        _annotate_entry(entry, truth)

        if state["active"]:
            base_tier = normalize_tier(truth.get("base_tier"))
            effective_tier = normalize_tier(truth.get("effective_tier"))
            if base_tier:
                state["base_tiers"][base_tier] += 1
            if effective_tier:
                state["effective_tiers"][effective_tier] += 1
            state["promotion_applied"] += int(bool(truth.get("promotion_applied")))

            state["records"].append(
                {
                    "loja": entry.get("loja") or item.get("loja"),
                    "titulo": entry.get("titulo") or item.get("titulo"),
                    "url": entry.get("url") or item.get("url"),
                    "raw_price": entry.get("price"),
                    "effective_price": entry.get("effective_price"),
                    "score_ranking": entry.get("score_ranking"),
                    **deepcopy(truth),
                }
            )
        return previous, key

    def send_heartbeat(run: dict) -> bool:
        if state["active"]:
            base_tiers = dict(run.get("tiers") or state["base_tiers"])
            effective_tiers = dict(state["effective_tiers"])
            run["base_tiers"] = base_tiers
            run["effective_tiers"] = effective_tiers
            # `tiers` passa a ser a vista canónica para consumidores existentes.
            run["tiers"] = effective_tiers
            run["decision_truth"] = {
                "schema_version": 1,
                "accepted_count": sum(effective_tiers.values()),
                "promotion_applied_count": int(state["promotion_applied"]),
                "base_tiers": base_tiers,
                "effective_tiers": effective_tiers,
            }
            top = sorted(
                state["records"],
                key=lambda row: float(row.get("effective_value_score") or 0.0),
                reverse=True,
            )[:8]
            run["effective_top"] = [
                {
                    "loja": row.get("loja"),
                    "titulo": row.get("titulo"),
                    "url": row.get("url"),
                    "price": row.get("effective_price"),
                    "value_score": row.get("effective_value_score"),
                    "tier": row.get("effective_tier"),
                    "promotion_applied": bool(row.get("promotion_applied")),
                }
                for row in top
            ]
        return base_send_heartbeat(run)

    def info(message, *args, **kwargs):
        text = str(message)
        if state["active"] and text.startswith("TOP |"):
            # O TOP base é suprimido; a versão canónica é emitida no fim da run.
            return None
        if state["active"] and "| D=%d O=%d P=%d B=%d" in text and len(args) >= 4:
            fixed = list(args)
            counts = state["effective_tiers"]
            fixed[-4:] = [
                counts["DIAMANTE"],
                counts["OURO"],
                counts["PRATA"],
                counts["BRONZE"],
            ]
            return base_info(message, *fixed, **kwargs)
        return base_info(message, *args, **kwargs)

    def main(*args, **kwargs):
        reset_state()
        settings = tracker_module.load_json(tracker_module.CONFIG_PATH).get("settings", {})
        state["diamond_threshold"] = float(settings.get("diamante_value_min", 120.0))
        state["active"] = True
        try:
            run = base_main(*args, **kwargs)
            effective_tiers = dict(state["effective_tiers"])
            accepted = int(run.get("total_accepted", 0)) if isinstance(run, dict) else 0
            observed = sum(effective_tiers.values())
            if accepted != observed:
                tracker_module.LOGGER.warning(
                    "V9 Decision Truth mismatch | aceites=%d | tiers_efetivos=%d",
                    accepted,
                    observed,
                )

            base_info(
                "V9 Decision Truth | aceites=%d | promo_aplicada=%d | D=%d O=%d P=%d B=%d",
                observed,
                int(state["promotion_applied"]),
                effective_tiers["DIAMANTE"],
                effective_tiers["OURO"],
                effective_tiers["PRATA"],
                effective_tiers["BRONZE"],
            )
            for row in sorted(
                state["records"],
                key=lambda value: float(value.get("effective_value_score") or 0.0),
                reverse=True,
            )[:8]:
                base_info(
                    "TOP | %s | %.2f€ | Value %.1f | Rank %.1f | %s | %s",
                    row.get("loja") or "?",
                    float(row.get("effective_price") or row.get("raw_price") or 0.0),
                    float(row.get("effective_value_score") or 0.0),
                    float(row.get("score_ranking") or 0.0),
                    row.get("effective_tier") or "—",
                    row.get("titulo") or "?",
                )
            return run
        finally:
            state["active"] = False

    tracker_module.record_offer = record_offer
    tracker_module.send_heartbeat = send_heartbeat
    tracker_module.LOGGER.info = info
    tracker_module.main = main
    tracker_module._DECISION_TRUTH_RUNTIME_STATE = state
    tracker_module._DECISION_TRUTH_RUNTIME_GUARD_INSTALLED = True
