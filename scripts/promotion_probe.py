"""Diagnóstico de promoções sem NTFY nem escrita de estado operacional."""
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
import runner  # noqa: E402  instala as guards reais
import tracker  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="Radio Popular")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data").glob("*.json")
    }
    config = tracker.load_json(tracker.CONFIG_PATH)
    tracker.LEARNING = tracker.load_learning()
    tracker.RUN_STARTED = time.monotonic()
    tracker.RUN_DEADLINE = tracker.RUN_STARTED + 300
    tracker.MAX_REQUESTS = 80
    tracker.MAX_REQUESTS_PER_STORE = 50
    tracker.MAX_DETAIL_FETCHES = 20
    tracker.REQUESTS_USED = 0
    tracker.REQUESTS_BY_STORE = defaultdict(int)
    tracker.DETAIL_FETCHES_USED = 0

    cat = next(row for row in config["category_urls"] if row["loja"] == args.store)
    items, stats = tracker.scan_store(dict(cat), config, config["settings"])
    promoted = []
    for item in items:
        promotions = item.get("promotions") or []
        if not promotions or item.get("preco") is None:
            continue
        economics = tracker.promotion_economics(promotions, float(item["preco"]))
        promoted.append({
            "title": item.get("titulo"),
            "url": item.get("url"),
            "price": item.get("preco"),
            "stock": item.get("stock"),
            "sources": item.get("discovery_sources"),
            "promotions": promotions,
            "economics": economics,
        })
    promoted.sort(key=lambda row: (-float(row["economics"]["checkout_discount_eur"]), float(row["price"])))

    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data").glob("*.json")
    }
    report = {
        "version": tracker.VERSION,
        "store": args.store,
        "candidates": len(items),
        "promotion_candidates": len(promoted),
        "requests": int(tracker.REQUESTS_BY_STORE.get(args.store, 0)),
        "stats": stats,
        "items": promoted,
        "state_unchanged": before == after,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PROMOTION_PROBE " + json.dumps(report, ensure_ascii=False), flush=True)
    if before != after:
        raise RuntimeError("O diagnóstico alterou o estado operacional")


if __name__ == "__main__":
    main()
