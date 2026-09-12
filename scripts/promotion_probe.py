"""Diagnóstico de promoções sem NTFY nem escrita de estado operacional."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runner  # noqa: E402  instala as guards reais
import tracker  # noqa: E402


def inspect_campaign(cat: dict, config: dict) -> dict:
    route = next(
        (row for row in cat.get("campaign_urls", []) if isinstance(row, dict) and row.get("label") == "50_por_250_set_2026"),
        None,
    )
    if not route:
        return {}
    response, profile, outcome = tracker.adaptive_fetch(
        route["url"], config, 8, store=cat["loja"], method="promotion_inspect"
    )
    if response is None:
        return {"outcome": outcome, "profile": profile}
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        full = urljoin(str(response.url), str(anchor.get("href") or ""))
        if full in seen or not tracker.scraper.same_host(full, str(response.url)):
            continue
        seen.add(full)
        if not any(marker in full.lower() for marker in ("/produto/", "/product/", "/portatil/", "/laptop/")):
            continue
        node = anchor
        context = anchor.get_text(" ", strip=True)
        classes = []
        for _ in range(4):
            classes.extend(getattr(node, "get", lambda *_: [])("class", []) or [])
            parent = getattr(node, "parent", None)
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            if text and len(text) < 1200:
                context = text
            node = parent
        links.append({
            "url": full,
            "text": context[:600],
            "classes": sorted(set(str(value) for value in classes))[:20],
        })
    raw_paths = sorted(set(re.findall(r"/(?:produto|product)/[^\"'<>\\s]+", response.text, re.I)))[:100]
    jsonld = tracker.scraper.jsonld_products(soup)
    script_samples = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        lower = raw.lower()
        if any(token in lower for token in ("/produto/", '"products"', '"price"', "algolia", "__next_data__")):
            compact = re.sub(r"\s+", " ", raw)
            script_samples.append(compact[:1200])
            if len(script_samples) >= 8:
                break
    return {
        "status": int(response.status_code),
        "outcome": outcome,
        "profile": profile,
        "url": str(response.url),
        "html_bytes": len(response.content or b""),
        "title": soup.title.get_text(" ", strip=True) if soup.title else "",
        "anchors_total": len(soup.find_all("a", href=True)),
        "productish_links_count": len(links),
        "productish_links": links[:60],
        "raw_product_paths_count": len(raw_paths),
        "raw_product_paths": raw_paths,
        "jsonld_products_count": len(jsonld),
        "jsonld_products": jsonld[:20],
        "script_samples": script_samples,
    }


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
    campaign_debug = inspect_campaign(cat, config) if args.store == "Radio Popular" else {}
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
        "campaign_debug": campaign_debug,
        "state_unchanged": before == after,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = dict(report)
    summary["campaign_debug"] = {
        key: value for key, value in campaign_debug.items()
        if key not in {"productish_links", "raw_product_paths", "jsonld_products", "script_samples"}
    }
    print("PROMOTION_PROBE " + json.dumps(summary, ensure_ascii=False), flush=True)
    if before != after:
        raise RuntimeError("O diagnóstico alterou o estado operacional")


if __name__ == "__main__":
    main()
