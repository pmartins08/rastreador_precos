"""Paginação do catálogo público Radio Popular, igual ao carregador getProducts."""
from __future__ import annotations

import math
from types import SimpleNamespace
from urllib.parse import urlencode

from bs4 import BeautifulSoup


def listing_state(html: str):
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.select_one("[data-products-page][data-products-total]")
    if grid is None:
        return None
    try:
        total = max(0, int(grid.get("data-products-total", 0)))
        per_page = max(1, int(grid.get("data-products-per-page", 12)))
        current_page = max(1, int(grid.get("data-products-page-number", 1)))
    except (TypeError, ValueError):
        return None
    fields = []
    for field in soup.select("#filters .filter-form input[name]"):
        if field.has_attr("disabled"):
            continue
        if field.get("type") in ("checkbox", "radio") and not field.has_attr("checked"):
            continue
        fields.append((field["name"], field.get("value", "")))
    return {
        "total": total, "per_page": per_page, "current_page": current_page,
        "payload": {
            "method": "getProducts",
            "page": grid.get("data-products-page", ""),
            "where": grid.get("data-products-where", ""),
            "filters": urlencode(fields),
            "limit": per_page,
            "order": grid.get("data-products-order", "relevancia asc"),
        },
    }


def collect_remaining(tracker, response, route_cat, target, candidates, source, stat, discover):
    state = listing_state(response.text)
    if state is None or state["payload"]["page"] != "destaque":
        return 0
    report = stat.setdefault("promotion_pagination", {
        "pages": 1, "listing_total": state["total"], "complete": False,
    })
    max_pages = max(1, min(20, int(route_cat.get("max_promotion_pages", 20))))
    end_page = math.ceil(state["total"] / state["per_page"])
    gained = 0
    def links(html):
        return {a["href"] for a in BeautifulSoup(html, "html.parser").select('a[href*="/produto/"]')}
    observed = links(response.text)
    seen = {tuple(sorted(observed))}
    store = "Radio Popular"
    method = "campaign_public_pagination"
    profile = tracker.profile_order(store, method)[0]
    for page in range(state["current_page"] + 1, min(end_page, max_pages) + 1):
        payload = dict(state["payload"], offset=(page - 1) * state["per_page"])
        try:
            result = None
            for attempt in range(2):
                if not tracker.consume_request(store):
                    report["stop_reason"] = "request_budget_exhausted"
                    break
                try:
                    result = tracker.requests.post(
                        "https://www.radiopopular.pt/ajax", data=payload, timeout=15,
                        impersonate=profile,
                        headers={**tracker.headers(profile), "Referer": response.url},
                        allow_redirects=False,
                    )
                    break
                except Exception:
                    tracker.record_learning(store, profile, "request_error", method)
                    if attempt == 1:
                        raise
            if result is None:
                break
            outcome, _ = tracker.classify(result)
            tracker.record_learning(store, profile, "success" if outcome == "http_success" else outcome, method)
            if outcome != "http_success":
                report["stop_reason"] = outcome
                break
            data = result.json()
            html = data.get("modules") if isinstance(data, dict) else None
            if not isinstance(data, dict) or int(data.get("total", 0)) > state["total"]:
                report["stop_reason"] = "listing_scope_changed"
                break
            if not isinstance(html, str) or not html.strip():
                report["stop_reason"] = "empty_page"
                break
            page_links = links(html)
            marker = tuple(sorted(page_links))
            if not page_links:
                report["stop_reason"] = "missing_product_links"
                break
            if marker in seen:
                report["stop_reason"] = "repeated_page"
                break
            seen.add(marker)
            observed.update(page_links)
            fragment = SimpleNamespace(text=html, url=response.url, status_code=200)
            gained += discover(fragment, route_cat, target, candidates, source, stat)
            report["pages"] += 1
        except Exception as exc:
            tracker.LOGGER.warning("Paginação campanha | Radio Popular | página %s | %s", page, type(exc).__name__)
            report["stop_reason"] = "request_or_payload_error"
            break
    else:
        report["complete"] = end_page <= max_pages
        if not report["complete"]:
            report["stop_reason"] = "page_limit"
    report["additional_candidates"] = gained
    report["listing_items_seen"] = len(observed)
    tracker.LOGGER.info("Campanha paginada | Radio Popular | %s", report)
    return gained
