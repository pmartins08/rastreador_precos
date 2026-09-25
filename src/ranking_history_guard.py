from __future__ import annotations

from collections import defaultdict


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _effective_fields(entry: dict) -> tuple[float, float, str | None]:
    promo_price = _number(entry.get("promotion_checkout_price"))
    promo_value = _number(entry.get("promotion_value_score"))
    promo_tier = entry.get("promotion_tier")
    if promo_price is not None and promo_value is not None and promo_tier:
        return promo_value, promo_price, str(promo_tier)
    value = _number(entry.get("value_score")) or 0.0
    price = _number(entry.get("price")) or 99999.0
    return value, price, entry.get("tier")


def rank_observations(observations: list[dict]) -> list[dict]:
    """Atribui posição global e por loja; empate técnico desempata pelo menor preço."""
    ranked = [dict(row) for row in observations]
    ranked.sort(
        key=lambda row: (
            -float(row.get("effective_value_score") or 0.0),
            float(row.get("effective_price") or 99999.0),
            str(row.get("store") or ""),
            str(row.get("url") or ""),
        )
    )
    store_positions: dict[str, int] = defaultdict(int)
    for index, row in enumerate(ranked, start=1):
        row["ranking_position"] = index
        store = str(row.get("store") or "")
        store_positions[store] += 1
        row["store_ranking_position"] = store_positions[store]
        previous = row.get("previous_ranking_position")
        try:
            previous_int = int(previous) if previous is not None else None
        except (TypeError, ValueError):
            previous_int = None
        row["ranking_position_delta"] = (
            previous_int - index if previous_int is not None else None
        )
    return ranked


def install(tracker_module) -> None:
    """Persiste posições do ranking em cada run sem alterar score, tier ou alertas."""
    if getattr(tracker_module, "_RANKING_HISTORY_GUARD_INSTALLED", False):
        return

    base_record_offer = tracker_module.record_offer
    base_main = tracker_module.main
    observations: list[dict] = []

    def record_offer(history, item, spec, assessment, tier):
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        entries = history.get("offers", {}).get(key, [])
        if entries and isinstance(entries[-1], dict):
            entry = entries[-1]
            effective_value, effective_price, effective_tier = _effective_fields(entry)
            observations.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "url": entry.get("url"),
                    "store": entry.get("loja"),
                    "title": entry.get("titulo"),
                    "configuration_key": entry.get("configuration_key"),
                    "effective_value_score": round(float(effective_value), 3),
                    "effective_price": round(float(effective_price), 2),
                    "effective_tier": effective_tier,
                    "previous_ranking_position": (
                        previous.get("ranking_position")
                        if isinstance(previous, dict)
                        else None
                    ),
                    "previous_store_ranking_position": (
                        previous.get("store_ranking_position")
                        if isinstance(previous, dict)
                        else None
                    ),
                }
            )
        return previous, key

    def main():
        observations.clear()
        run = base_main()
        ranked = rank_observations(observations)
        if not ranked:
            return run

        history = tracker_module.load_history()
        offers = history.get("offers", {}) if isinstance(history.get("offers"), dict) else {}
        by_marker = {
            (str(row.get("url") or ""), str(row.get("timestamp") or "")): row
            for row in ranked
        }
        updated = 0
        changes = 0
        for entries in offers.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                marker = (str(entry.get("url") or ""), str(entry.get("timestamp") or ""))
                row = by_marker.get(marker)
                if row is None:
                    continue
                entry["ranking_position"] = row["ranking_position"]
                entry["store_ranking_position"] = row["store_ranking_position"]
                entry["previous_ranking_position"] = row.get("previous_ranking_position")
                entry["ranking_position_delta"] = row.get("ranking_position_delta")
                entry["effective_price"] = row.get("effective_price")
                entry["effective_value_score"] = row.get("effective_value_score")
                entry["effective_tier"] = row.get("effective_tier")
                updated += 1
                changes += int(
                    row.get("ranking_position_delta") not in (None, 0)
                )

        snapshot = [
            {
                "position": row["ranking_position"],
                "store_position": row["store_ranking_position"],
                "store": row.get("store"),
                "title": row.get("title"),
                "url": row.get("url"),
                "effective_price": row.get("effective_price"),
                "effective_value_score": row.get("effective_value_score"),
                "effective_tier": row.get("effective_tier"),
                "delta": row.get("ranking_position_delta"),
            }
            for row in ranked[:30]
        ]

        runs = (history.get("learning", {}) or {}).get("runs", [])
        target_timestamp = str(run.get("timestamp") or "") if isinstance(run, dict) else ""
        target = None
        if isinstance(runs, list):
            for candidate in reversed(runs):
                if not isinstance(candidate, dict):
                    continue
                if target_timestamp and str(candidate.get("timestamp") or "") == target_timestamp:
                    target = candidate
                    break
            if target is None and runs and isinstance(runs[-1], dict):
                target = runs[-1]
        if isinstance(target, dict):
            target["ranking_positions_recorded"] = updated
            target["ranking_position_changes"] = changes
            target["ranking_snapshot"] = snapshot

        tracker_module.save_json(tracker_module.HISTORY_PATH, history)
        if isinstance(run, dict):
            run["ranking_positions_recorded"] = updated
            run["ranking_position_changes"] = changes
            run["ranking_snapshot"] = snapshot

        tracker_module.LOGGER.info(
            "Ranking histórico | posições=%d | mudanças=%d | top=%s",
            updated,
            changes,
            ", ".join(
                f"{row['ranking_position']}:{row.get('store')}@{float(row.get('effective_price') or 0):.2f}€"
                for row in ranked[:5]
            ),
        )
        return run

    tracker_module.record_offer = record_offer
    tracker_module.main = main
    tracker_module._RANKING_HISTORY_GUARD_INSTALLED = True
