"""Avalia em live os candidatos promocionais sem gravar history/NTFY."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runner  # noqa: E402
import tracker  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data").glob("*.json")
    }
    config = tracker.load_json(tracker.CONFIG_PATH)
    settings = config.get("settings", {})
    weights = config.get("weights", {})
    tracker.LEARNING = tracker.load_learning()
    tracker.RUN_STARTED = time.monotonic()
    tracker.RUN_DEADLINE = tracker.RUN_STARTED + 360
    tracker.MAX_REQUESTS = 80
    tracker.MAX_REQUESTS_PER_STORE = 60
    tracker.MAX_DETAIL_FETCHES = 30
    tracker.REQUESTS_USED = 0
    tracker.REQUESTS_BY_STORE = defaultdict(int)
    tracker.DETAIL_FETCHES_USED = 0

    cat = next(row for row in config["category_urls"] if row["loja"] == "Radio Popular")
    items, stats = tracker.scan_store(dict(cat), config, settings)
    promoted = [item for item in items if item.get("promotions")]
    rows = []
    for discovered in promoted:
        landing_price = discovered.get("preco")
        result, status = tracker.enrich(dict(discovered), config)
        row = {
            "title": discovered.get("titulo"),
            "url": discovered.get("url"),
            "landing_price": landing_price,
            "error": status.get("error"),
        }
        if status.get("error") or result.get("preco") is None:
            rows.append(row)
            continue
        price = float(result["preco"])
        spec = result.get("specs") or tracker.scraper.specs(result.get("titulo", ""))
        assessment = tracker.score_allow_unknown(spec, price, weights, settings)
        economics = tracker.promotion_economics(result.get("promotions") or discovered.get("promotions"), price)
        promo_assessment = tracker.score_allow_unknown(
            spec, float(economics["effective_checkout_price"]), weights, settings
        )
        normal_tier = (
            tracker.scraper.tier_from_value(assessment["value_score"], settings)
            if assessment.get("status") == "ACEITE"
            else None
        )
        promo_tier = (
            tracker.scraper.tier_from_value(promo_assessment["value_score"], settings)
            if promo_assessment.get("status") == "ACEITE"
            else None
        )
        row.update({
            "title": result.get("titulo"),
            "price": round(price, 2),
            "price_live_confirmed": bool(result.get("promotion_price_live_confirmed")),
            "discount_eur": economics["checkout_discount_eur"],
            "checkout_price": economics["effective_checkout_price"],
            "normal_status": assessment.get("status"),
            "normal_value": assessment.get("value_score"),
            "normal_tier": normal_tier,
            "promo_status": promo_assessment.get("status"),
            "promo_value": promo_assessment.get("value_score"),
            "promo_tier": promo_tier,
            "alerts": assessment.get("alertas") or promo_assessment.get("alertas") or [],
            "cpu": spec.get("cpu_modelo"),
            "gpu": spec.get("gpu_modelo") or spec.get("gpu_tipo"),
            "ram_gb": spec.get("ram_gb"),
            "storage_tb": spec.get("armazenamento_tb"),
            "keyboard_pt": spec.get("teclado_pt"),
            "ean": result.get("ean"),
            "mpn": result.get("mpn"),
        })
        rows.append(row)

    rows.sort(key=lambda row: (row.get("promo_status") != "ACEITE", -(row.get("promo_value") or 0), row.get("price") or 99999))
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data").glob("*.json")
    }
    report = {
        "version": tracker.VERSION,
        "promotion_candidates": len(promoted),
        "evaluated": len(rows),
        "live_confirmed": sum(bool(row.get("price_live_confirmed")) for row in rows),
        "accepted": sum(row.get("promo_status") == "ACEITE" for row in rows),
        "requests": int(tracker.REQUESTS_BY_STORE.get("Radio Popular", 0)),
        "stats": stats,
        "items": rows,
        "state_unchanged": before == after,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PROMOTION_EVALUATION " + json.dumps(report, ensure_ascii=False), flush=True)
    if before != after:
        raise RuntimeError("O diagnóstico alterou o estado operacional")


if __name__ == "__main__":
    main()
