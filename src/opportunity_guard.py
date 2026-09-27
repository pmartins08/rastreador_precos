from __future__ import annotations


_OBSERVATIONS: list[dict] = []


def historical_bonus(context: dict | None) -> float:
    if not isinstance(context, dict) or not context.get("available"):
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
    """Ranking de compra observacional, sem alterar Value/tier/alertas.

    Value continua a ser o sinal principal (80%). Gaming é reintroduzido de
    forma explícita (20%) porque o Value geral também recompensa mobilidade e
    produtividade. O pequeno bónus histórico distingue preço normal de momento
    realmente oportuno. A escala continua aproximadamente 0..150.
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


def install(tracker_module) -> None:
    if getattr(tracker_module, "_OPPORTUNITY_GUARD_INSTALLED", False):
        return

    base_record_offer = tracker_module.record_offer
    base_main = tracker_module.main

    def record_offer(history, item, spec, assessment, tier):
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        details = assessment.get("detalhes") if isinstance(assessment.get("detalhes"), dict) else {}
        opportunity = calculate_opportunity(
            float(assessment.get("value_score", 0.0) or 0.0),
            float(details.get("Gaming", 0.0) or 0.0),
            assessment.get("historical_price"),
        )
        assessment["opportunity_score"] = opportunity["score"]
        assessment["opportunity_components"] = opportunity

        entries = history.get("offers", {}).get(key, [])
        if entries and isinstance(entries[-1], dict):
            entry = entries[-1]
            entry["opportunity_score"] = opportunity["score"]
            entry["opportunity_components"] = opportunity
            _OBSERVATIONS.append({
                "url": entry.get("url"),
                "timestamp": entry.get("timestamp"),
                "store": entry.get("loja"),
                "title": entry.get("titulo"),
                "price": float(entry.get("effective_price", entry.get("price", item.get("preco", 0.0))) or 0.0),
                "value": float(entry.get("effective_value_score", entry.get("value_score", assessment.get("value_score", 0.0))) or 0.0),
                "tier": entry.get("effective_tier", entry.get("tier", tier)),
                "stock": entry.get("stock"),
                "score": opportunity["score"],
                "gaming": opportunity["gaming"],
            })
        return previous, key

    def main():
        _OBSERVATIONS.clear()
        run = base_main()
        eligible = [row for row in _OBSERVATIONS if row.get("stock") is not False]
        eligible.sort(key=lambda row: (-float(row["score"]), -float(row["value"]), float(row["price"]), str(row.get("url") or "")))
        positions = {
            (str(row.get("url") or ""), str(row.get("timestamp") or "")): index
            for index, row in enumerate(eligible, start=1)
        }
        snapshot = []
        for index, row in enumerate(eligible[:30], start=1):
            snapshot.append({
                "position": index,
                "store": row.get("store"),
                "title": row.get("title"),
                "url": row.get("url"),
                "price": round(float(row.get("price") or 0.0), 2),
                "value": round(float(row.get("value") or 0.0), 1),
                "gaming": round(float(row.get("gaming") or 0.0), 1),
                "opportunity_score": round(float(row.get("score") or 0.0), 1),
                "tier": row.get("tier"),
            })

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

            runs = (history.get("learning", {}) or {}).get("runs", [])
            if runs and isinstance(runs[-1], dict):
                runs[-1]["opportunity_snapshot"] = snapshot
                runs[-1]["opportunity_ranked"] = len(eligible)
            tracker_module.save_json(tracker_module.HISTORY_PATH, history)
        except Exception:
            if hasattr(tracker_module, "LOGGER"):
                tracker_module.LOGGER.warning("Opportunity Rank calculado, mas não foi possível persistir posições")

        if isinstance(run, dict):
            run["opportunity_snapshot"] = snapshot
            run["opportunity_ranked"] = len(eligible)
        if snapshot and hasattr(tracker_module, "LOGGER"):
            tracker_module.LOGGER.info(
                "Opportunity Rank | top=%s",
                ", ".join(
                    f"{row['position']}:{row.get('store')}@{row['price']:.2f}€ O={row['opportunity_score']:.1f} V={row['value']:.1f}"
                    for row in snapshot[:5]
                ),
            )
        return run

    tracker_module.record_offer = record_offer
    tracker_module.main = main
    tracker_module._OPPORTUNITY_GUARD_INSTALLED = True
