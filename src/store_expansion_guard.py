"""Bounded discovery and fair selection for additional Portuguese retailers."""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import unquote


def laptop_candidate(item, scraper):
    text = scraper.norm(unquote(str(item.get("titulo") or "")))
    if re.search(r"\b(?:desktop|all.in.one|mini.pc|monitor|impressora|mochila|carregador|coluna|tablet|consola|legion\s+go|rog\s+ally)\b", text):
        return False
    if re.search(r"\b(?:portatil|laptop|notebook|chromebook)\b", text):
        return True
    # MEO titles omit 'portátil'. Require a laptop family and screen size.
    families = r"legion|loq|ideapad|thinkpad|thinkbook|yoga|vivobook|zenbook|expertbook|omnibook|elitebook|probook|nitro|swift|aspire|aero|aorus|tuf|omen|victus"
    return bool(re.search(rf"\b(?:{families})\b", text) and re.search(r"\b(?:1[0-8])(?:[.,]\d+)?\s*(?:\"|''|polegadas)", text))


def fair_selection(ranked, spec_cache, limit, quota):
    if limit <= 0:
        return []
    cap = min(limit // 3, quota * len({row.get("loja") for row in ranked}))
    groups = defaultdict(list)
    for item in ranked:
        if not item.get("specs") and item.get("url") not in spec_cache:
            groups[item.get("loja")].append(item)
    chosen, seen = [], set()
    for index in range(quota):
        for rows in groups.values():
            if len(chosen) >= cap:
                break
            if index < len(rows):
                row = rows[index]
                key = (row.get("loja"), row.get("url"))
                if key not in seen:
                    chosen.append(row)
                    seen.add(key)
    for row in ranked:
        if len(chosen) >= limit:
            break
        key = (row.get("loja"), row.get("url"))
        if key not in seen:
            chosen.append(row)
            seen.add(key)
    return chosen


def install(scraper, tracker):
    if getattr(tracker, "_STORE_EXPANSION_INSTALLED", False):
        return
    base_discover = scraper.discover_category
    base_select = tracker.select_with_cache

    def discover(html, cat, limit):
        rows = base_discover(html, cat, limit)
        if cat.get("laptop_only"):
            rows = [row for row in rows if row.get("stock") is not False and laptop_candidate(row, scraper)]
        return rows

    def select(items, spec_cache, limit, weights, settings):
        quota = max(0, int(settings.get("min_new_candidates_per_store", 0)))
        if not quota:
            return base_select(items, spec_cache, limit, weights, settings)
        ranked = base_select(items, spec_cache, max(limit, len(items)), weights, settings)
        return fair_selection(ranked, spec_cache, limit, quota)

    scraper.discover_category = discover
    tracker.select_with_cache = select
    tracker._STORE_EXPANSION_INSTALLED = True
