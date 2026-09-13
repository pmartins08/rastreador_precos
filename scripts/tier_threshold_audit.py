from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import scraper
import hardware_guard
from history_audit import _identity


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    fraction = rank - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _historical_value(record: dict) -> float | None:
    for key in ("promotion_value_score", "value_score"):
        try:
            value = float(record.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None


def _effective_price(record: dict) -> float:
    for key in ("promotion_checkout_price", "price"):
        try:
            value = float(record.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            return value
    return 1000.0


def _gaming_score(record: dict, weights: dict, settings: dict) -> float | None:
    spec = record.get("specs")
    if not isinstance(spec, dict):
        return None
    spec = json.loads(json.dumps(spec))
    hardware_guard.upgrade_spec(spec, scraper, record.get("titulo"))
    # O preço não altera Gaming; usamos o preço histórico só para manter a
    # chamada ao cérebro fiel ao record. O Value resultante é ignorado aqui.
    assessment = scraper.score(spec, _effective_price(record), weights, settings)
    if assessment.get("status") != "ACEITE":
        return None
    details = assessment.get("detalhes") if isinstance(assessment.get("detalhes"), dict) else {}
    try:
        return float(details.get("Gaming"))
    except (TypeError, ValueError):
        return None


def audit(history: dict, config: dict) -> dict:
    weights = config.get("weights", {}) if isinstance(config, dict) else {}
    settings = config.get("settings", {}) if isinstance(config, dict) else {}
    best: dict[str, dict] = {}
    offers = history.get("offers", {}) if isinstance(history, dict) else {}
    for url, entries in offers.items() if isinstance(offers, dict) else []:
        if not isinstance(entries, list):
            continue
        for record in entries:
            if not isinstance(record, dict):
                continue
            raw_value = _historical_value(record)
            if raw_value is None:
                continue
            gaming = _gaming_score(record, weights, settings)
            if gaming is None:
                continue
            multiplier = 0.85 + 0.15 * max(0.0, min(100.0, gaming)) / 100.0
            tier_score = raw_value * multiplier
            row = {
                "identity": _identity({**record, "url": record.get("url") or url}),
                "store": record.get("loja"),
                "title": record.get("titulo"),
                "url": record.get("url") or url,
                "price": _effective_price(record),
                "raw_value": round(raw_value, 3),
                "gaming_score": round(gaming, 3),
                "tier_multiplier": round(multiplier, 6),
                "tier_score": round(tier_score, 3),
                "historical_tier": record.get("promotion_tier") or record.get("tier"),
            }
            current = best.get(row["identity"])
            if current is None or row["tier_score"] > current["tier_score"]:
                best[row["identity"]] = row

    rows = sorted(best.values(), key=lambda row: row["tier_score"], reverse=True)
    scores = [float(row["tier_score"]) for row in rows]
    thresholds = (115, 116, 117, 118, 119, 120, 122, 125)
    return {
        "unique_identities_scored": len(rows),
        "max_tier_score": round(max(scores), 3) if scores else None,
        "p95_tier_score": round(_percentile(scores, 0.95), 3) if scores else None,
        "p98_tier_score": round(_percentile(scores, 0.98), 3) if scores else None,
        "p99_tier_score": round(_percentile(scores, 0.99), 3) if scores else None,
        "threshold_counts": {str(t): sum(score >= t for score in scores) for t in thresholds},
        "top10_by_tier_score": rows[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", default="data/history.json")
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()
    history = json.loads(Path(args.history).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    print("TIER_THRESHOLD_AUDIT_JSON=" + json.dumps(audit(history, config), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
