"""Reproduz acesso no runner, sem chamar main/ntfy nem gravar data/."""
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
import runner
import tracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stores", nargs="+", default=["Darty", "Worten", "CHIP7", "PcComponentes", "PCDiga"])
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("O diagnóstico não escreve no estado operacional.")
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "data").glob("*.json")}
    config = tracker.load_json(tracker.CONFIG_PATH)
    tracker.LEARNING = tracker.load_learning()
    tracker.RUN_STARTED = time.monotonic()
    tracker.RUN_DEADLINE = tracker.RUN_STARTED + 300
    tracker.MAX_REQUESTS = 100
    tracker.MAX_REQUESTS_PER_STORE = 35
    tracker.MAX_DETAIL_FETCHES = 25
    tracker.REQUESTS_USED = 0
    tracker.REQUESTS_BY_STORE = defaultdict(int)
    tracker.DETAIL_FETCHES_USED = 0
    report = {"version": tracker.VERSION, "timestamp": tracker.now_iso(), "stores": {}}
    for cat in config["category_urls"]:
        store = cat["loja"]
        if store not in args.stores:
            continue
        start = time.monotonic()
        items, stats = tracker.scan_store(dict(cat), config, config["settings"])
        samples = []
        for item in items[:3]:
            if not tracker.budget_available(store):
                break
            product, status = tracker.enrich(item, config)
            spec = product.get("specs", {})
            samples.append({
                "url": item["url"], "title": product.get("titulo"), "price": product.get("preco"),
                "access": status, "price_status": spec.get("price_status"),
                "price_confidence": spec.get("price_confidence"),
            })
        # One direct public request reports actual status/body shape, independently
        # of a route being skipped by historic learning. No profile/IP rotation.
        import requests
        from urllib.parse import urljoin
        routes = [("category", cat["url"]), ("robots", urljoin(cat["url"], "/robots.txt"))]
        if cat.get("public_catalog_json_url"):
            routes.append(("catalog", cat["public_catalog_json_url"]))
        observed = []
        for kind, url in routes:
            if not tracker.consume_request(store):
                break
            try:
                response = requests.get(url, timeout=8, headers={"User-Agent": "rastreador-precos/8.8.9 (+https://github.com/pmartins08/rastreador_precos)"})
                row = {"kind": kind, "url": url, "status": response.status_code,
                       "content_type": response.headers.get("Content-Type"), "bytes": len(response.content)}
                if response.status_code == 200:
                    if kind == "robots":
                        row["rules"] = response.text[:8000]
                    elif kind == "catalog":
                        payload = response.json()
                        row["products"] = len(payload.get("products", []))
                        row["parsed"] = len(__import__("catalog_guard")._shopify_candidates(payload, cat, tracker))
                    else:
                        soup = tracker.BeautifulSoup(response.text, "html.parser")
                        row["title"] = soup.title.get_text() if soup.title else ""
                        row["jsonld"] = len(soup.select('script[type="application/ld+json"]'))
                        row["parsed"] = len(tracker.scraper.discover_category(response.text, cat, 80))
                observed.append(row)
            except Exception as exc:
                observed.append({"kind": kind, "url": url, "error_type": type(exc).__name__})
        report["stores"][store] = {"stats": stats, "samples": samples, "requests": tracker.REQUESTS_BY_STORE[store],
                                    "seconds": round(time.monotonic() - start, 2), "observed": observed}
        print(json.dumps({"store": store, **report["stores"][store]}, ensure_ascii=False), flush=True)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "data").glob("*.json")}
    report["state_unchanged"] = before == after
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if before != after:
        raise RuntimeError("O diagnóstico alterou o estado operacional.")


if __name__ == "__main__":
    main()
