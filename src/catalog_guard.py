from __future__ import annotations

import math
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


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



def _usable_candidates(rows: list[dict], settings: dict) -> list[dict]:
    minimum = float(settings.get("preco_minimo_global", 250))
    maximum = float(settings.get("budget_hard", 1500))
    # Apply the same budget universe as tracker.main before deciding whether a
    # source provides enough coverage to skip the more expensive fallback.
    return [
        row for row in rows
        if row.get("stock") is not False
        and math.isfinite(float(row["preco"]))
        and minimum <= float(row["preco"]) <= maximum
    ]


def install(tracker_module) -> None:
    """Prefere o catálogo público validado; mantém HTML/sitemap como fallback."""
    if getattr(tracker_module, "_CATALOG_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store

    def read_catalog(cat, config, settings):
        store = str(cat["loja"])
        before = int(tracker_module.REQUESTS_BY_STORE.get(store, 0))
        url = str(cat["public_catalog_json_url"])
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        page_size = max(1, min(250, int(query.get("limit", 250))))
        max_pages = max(1, min(4, int(cat.get("catalog_json_max_pages", 1))))
        row_limit = max(1, int(cat.get("catalog_json_candidate_limit", 250)))
        found, count, pages, outcome = {}, 0, 0, "not_attempted"
        exhausted = False
        seen_pages = set()
        for page in range(1, max_pages + 1):
            page_url = url if page == 1 else urlunsplit(parts._replace(
                query=urlencode({**query, "page": str(page)})))
            response, _profile, outcome = _single_public_fetch(
                tracker_module, page_url, config, store, "catalog_json",
                max(2.0, float(cat.get("catalog_json_timeout_s", 6.0))),
            )
            if response is None or outcome != "http_success":
                break
            try:
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
                    outcome = "invalid_catalog"
                    break
                products = payload["products"]
                fingerprint = tuple(str(p.get("id") or p.get("handle") or "") for p in products if isinstance(p, dict))
                if fingerprint in seen_pages:
                    outcome = "repeated_page"
                    break
                seen_pages.add(fingerprint)
                pages += 1
                count += len(products)
                for row in _usable_candidates(_shopify_candidates(payload, cat, tracker_module), settings):
                    found.setdefault(row["url"], row)
                    if len(found) >= row_limit:
                        break
                exhausted = len(products) < page_size
                if exhausted or len(found) >= row_limit:
                    break
            except (ValueError, TypeError, KeyError, OverflowError):
                outcome = "invalid_catalog"
                break
        if outcome == "http_success" and not found:
            outcome = "no_usable_products"
        spent = max(0, int(tracker_module.REQUESTS_BY_STORE.get(store, 0)) - before)
        return list(found.values()), outcome, spent, count, pages, exhausted

    def scan_store(cat: dict, config: dict, settings: dict):
        url = str(cat.get("public_catalog_json_url") or "").strip()
        primary = bool(url and cat.get("catalog_json_first"))
        threshold = max(1, int(cat.get("catalog_json_below", cat.get("target_candidates", 60))))
        found, outcome, spent, count, pages, exhausted = [], "not_attempted", 0, 0, 0, False

        if primary:
            found, outcome, spent, count, pages, exhausted = read_catalog(cat, config, settings)
            if len(found) >= threshold:
                # A complete stats shape is needed by the outer coverage guard.
                items, stat = [], tracker_module._empty_store_stats()
            else:
                items, stat = base_scan_store(cat, config, settings)
        else:
            items, stat = base_scan_store(cat, config, settings)
            if not url or len(items) >= threshold or not tracker_module.budget_available(cat["loja"]):
                return items, stat
            found, outcome, spent, count, pages, exhausted = read_catalog(cat, config, settings)

        known = {str(item.get("url")) for item in items if item.get("url")}
        added = 0
        for item in found:
            if item["url"] not in known:
                items.append(item)
                known.add(item["url"])
                added += 1

        tracker_module.record_discovery_yield(str(cat["loja"]), "catalog_json", spent, added)
        stat.setdefault("fontes_descoberta", {})["catalog_json"] = added
        stat.setdefault("rendimento_descoberta", {})["catalog_json"] = {
            "requests": spent, "new_candidates": added,
            "yield": round(added / max(1, spent), 3),
        }
        stat.update({
            "catalog_json_outcome": outcome,
            "catalog_json_rows": count,
            "catalog_json_pages": pages,
            "catalog_json_exhausted": exhausted,
            "catalog_json_usable": len(found),
            "catalog_json_primary": primary,
            "catalog_json_fallback": primary and len(found) < threshold,
            "candidatos": len(items),
        })
        if items:
            stat["bloqueada"] = False
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._CATALOG_GUARD_INSTALLED = True
