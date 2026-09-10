from __future__ import annotations

from urllib.parse import urljoin


def _shopify_candidates(payload: object, cat: dict, tracker_module) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        return []

    out: list[dict] = []
    limit = max(1, int(cat.get("catalog_json_candidate_limit", cat.get("target_candidates", 60))))
    for product in payload["products"]:
        if not isinstance(product, dict):
            continue
        title = str(product.get("title") or "").strip()
        handle = str(product.get("handle") or "").strip()
        if not title or not handle or not tracker_module.scraper.eligible(title):
            continue

        variants = [value for value in (product.get("variants") or []) if isinstance(value, dict)]
        available = [value for value in variants if value.get("available") is True]
        priced_pool = available or variants
        priced = []
        for variant in priced_pool:
            price = tracker_module.scraper.parse_price_value(variant.get("price"))
            if price is not None:
                priced.append((float(price), variant))
        if not priced:
            continue
        price, variant = min(priced, key=lambda row: row[0])

        stock_values = [value.get("available") for value in variants if "available" in value]
        stock = True if any(value is True for value in stock_values) else False if stock_values and all(value is False for value in stock_values) else None
        url = urljoin(cat["url"], f"/products/{handle}")
        row = {
            "loja": cat["loja"],
            "titulo": title,
            "preco": price,
            "url": url,
            "stock": stock,
            "detail_source": "catalog_json_seed",
            "discovery_sources": ["catalog_json"],
        }
        sku = variant.get("sku")
        if sku:
            row["sku"] = str(sku).strip()
        barcode = str(variant.get("barcode") or "").strip()
        if barcode and tracker_module.gtin_valid(barcode):
            row["ean"] = barcode
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _single_public_fetch(tracker_module, url: str, config: dict, store: str, method: str, timeout_s: float):
    profiles = tracker_module.profile_order(store, method)
    if not profiles or not tracker_module.consume_request(store):
        return None, None, "request_budget_exhausted"
    profile = profiles[0]
    try:
        response = tracker_module.requests.get(
            url,
            timeout=timeout_s,
            impersonate=profile,
            headers=tracker_module.headers(profile),
            allow_redirects=True,
        )
        outcome, _retryable = tracker_module.classify(response)
        tracker_module.record_learning(
            store,
            profile,
            "success" if outcome == "http_success" else "blocked" if outcome in tracker_module.BLOCK_OUTCOMES else outcome,
            method,
        )
        return response, profile, outcome
    except Exception:
        tracker_module.record_learning(store, profile, "request_error", method)
        return None, profile, "request_error"


def install(tracker_module) -> None:
    """Testa catálogos JSON públicos opcionais como complemento, nunca como bypass."""
    if getattr(tracker_module, "_CATALOG_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store

    def scan_store(cat: dict, config: dict, settings: dict):
        items, stat = base_scan_store(cat, config, settings)
        url = str(cat.get("public_catalog_json_url") or "").strip()
        threshold = max(0, int(cat.get("catalog_json_below", cat.get("target_candidates", 60))))
        if not url or len(items) >= threshold or not tracker_module.budget_available(cat["loja"]):
            return items, stat

        store = str(cat["loja"])
        method = "catalog_json"
        before_requests = int(tracker_module.REQUESTS_BY_STORE.get(store, 0))
        response, _profile, outcome = _single_public_fetch(
            tracker_module,
            url,
            config,
            store,
            method,
            max(2.0, float(cat.get("catalog_json_timeout_s", 6.0))),
        )
        found = []
        if response is not None and outcome == "http_success":
            try:
                found = _shopify_candidates(response.json(), cat, tracker_module)
            except Exception:
                found = []

        known = {str(item.get("url")) for item in items if item.get("url")}
        added = 0
        for item in found:
            if item["url"] in known:
                continue
            items.append(item)
            known.add(item["url"])
            added += 1

        spent = max(0, int(tracker_module.REQUESTS_BY_STORE.get(store, 0)) - before_requests)
        tracker_module.record_discovery_yield(store, method, spent, added)
        stat.setdefault("fontes_descoberta", {}).setdefault("catalog_json", 0)
        stat["fontes_descoberta"]["catalog_json"] += added
        stat.setdefault("rendimento_descoberta", {})[method] = {
            "requests": spent,
            "new_candidates": added,
            "yield": round(added / max(1, spent), 3),
        }
        stat["catalog_json_outcome"] = outcome
        stat["candidatos"] = len(items)
        if items:
            stat["bloqueada"] = False
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._CATALOG_GUARD_INSTALLED = True
