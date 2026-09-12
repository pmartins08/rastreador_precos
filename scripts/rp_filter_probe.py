"""Testa filtros públicos da campanha Radio Popular sem alterar estado."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runner  # noqa: E402
import tracker  # noqa: E402


def filtered(base: str, params: list[tuple[str, str]]) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment))


def main() -> None:
    config = tracker.load_json(tracker.CONFIG_PATH)
    tracker.LEARNING = tracker.load_learning()
    tracker.RUN_STARTED = time.monotonic()
    tracker.RUN_DEADLINE = tracker.RUN_STARTED + 240
    tracker.MAX_REQUESTS = 20
    tracker.MAX_REQUESTS_PER_STORE = 20
    tracker.MAX_DETAIL_FETCHES = 0
    tracker.REQUESTS_USED = 0
    tracker.REQUESTS_BY_STORE = defaultdict(int)
    tracker.DETAIL_FETCHES_USED = 0

    cat = next(row for row in config["category_urls"] if row["loja"] == "Radio Popular")
    route = next(row for row in cat["campaign_urls"] if row.get("label") == "50_por_250_set_2026")
    base = route["url"].split("?", 1)[0]
    candidates = {
        "category_n2": filtered(base, [
            ("filters[category_n2_name][]", "Computadores Portáteis"),
            ("filters[disponibilidade][]", "Ocultar Produtos Indisponíveis"),
        ]),
        "pf_filters": filtered(base, [
            ("pf-filters", "((category eq 'Informática|Computadores Portáteis'))"),
        ]),
        "both": filtered(base, [
            ("filters[category_n2_name][]", "Computadores Portáteis"),
            ("pf-filters", "((category eq 'Informática|Computadores Portáteis'))"),
            ("filters[disponibilidade][]", "Ocultar Produtos Indisponíveis"),
        ]),
    }
    out = {}
    for label, url in candidates.items():
        response, profile, outcome = tracker.adaptive_fetch(
            url, config, 10, store="Radio Popular", method=f"promotion_filter_probe:{label}"
        )
        if response is None:
            out[label] = {"url": url, "outcome": outcome, "profile": profile, "items": []}
            continue
        probe_cat = dict(cat)
        probe_cat["url"] = url
        items = tracker.scraper.discover_category(response.text, probe_cat, 60)
        out[label] = {
            "url": str(response.url),
            "status": response.status_code,
            "outcome": outcome,
            "profile": profile,
            "html_bytes": len(response.content or b""),
            "items": [
                {"title": item.get("titulo"), "price": item.get("preco"), "url": item.get("url")}
                for item in items
            ],
        }
    print("RP_FILTER_PROBE " + json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
