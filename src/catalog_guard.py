from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


def _laptop_product(product: dict) -> bool:
    text = " ".join(str(product.get(field) or "") for field in ("title", "handle", "product_type"))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    if re.search(r"\b(?:consolas?|consoles?|rog[\s-]+ally|legion[\s-]+go)\b|^(?:monitor|impressora|desktop|all.in.one|mochila|carregador)\b", text):
        return False
    return bool(re.search(r"\b(?:portatil|portateis|laptop|notebook|chromebook)\b", text))


def _shopify_candidates(payload: object, cat: dict, tracker_module) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        return []

    out: list[dict] = []
    limit = max(1, int(cat.get("catalog_json_candidate_limit", cat.get("target_candidates", 60))))
    for product in payload["products"]:
        if not isinstance(product, dict):
            continue
        if cat.get("catalog_laptop_only") and not _laptop_product(product):
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
        # Shopify SKU is merchant-internal metadata. Keep it for diagnostics,
        # but never promote it to tracker `sku`, because that field participates
        # in configuration identity and can produce a FORTE cross-store match.
        sku = variant.get("sku")
        if sku:
            row["_catalog_sku"] = str(sku).strip()
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


def _reusable_live_catalog_price(previous: dict, hint: float, *, now=None, ttl_hours=24) -> float | None:
    spec = previous.get("specs") or {}
    try:
        if float(spec.get("catalog_price_hint")) != float(hint):
            return None
        stamp = datetime.fromisoformat(str(spec.get("price_checked_at")).replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        age = (current - stamp).total_seconds()
        price = float(previous["price"])
        confirmed = float(spec["price_confirmed"])
        if not (0 <= age < float(ttl_hours) * 3600):
            return None
        if not (math.isfinite(price) and price > 0 and abs(price - confirmed) < 0.01):
            return None
        if spec.get("price_page_confidence") not in {"MEDIUM", "HIGH"}:
            return None
        return price
    except (TypeError, ValueError, KeyError, OverflowError):
        return None


def install(tracker_module) -> None:
    """Prefere o catálogo público validado; mantém HTML/sitemap como fallback."""
    if getattr(tracker_module, "_CATALOG_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    base_enrich = getattr(tracker_module, "enrich", None)
    previous_cache = {}
    previous_loaded = False

    def previous_offers():
        nonlocal previous_loaded
        if not previous_loaded:
            loader = getattr(tracker_module, "load_history", None)
            latest = getattr(tracker_module, "latest_offer_by_url", None)
            if loader and latest:
                previous_cache.update(latest(loader()))
            previous_loaded = True
        return previous_cache

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

        # The public catalogue price is a hint; promotions can live only on the
        # product page. Reuse a recent page price only while the hint is unchanged.
        for item in found:
            item["_catalog_price_hint"] = item["preco"]
            previous = previous_offers().get(item["url"], {})
            cached_price = _reusable_live_catalog_price(
                previous, item["preco"], ttl_hours=float(settings.get("price_confirmation_ttl_hours", 24)))
            if previous.get("loja") == cat["loja"] and cached_price is not None:
                item["preco"] = cached_price
                item["_catalog_live_price_cached"] = True
            elif previous.get("loja") == cat["loja"]:
                # Existing Coverage Guard reserves refresh and quarantines cached
                # specs if current page confirmation cannot be obtained.
                item["_coverage_force_live_price"] = True

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

    def enrich(item, config):
        if "_catalog_price_hint" not in item:
            return base_enrich(item, config)
        seed = dict(item)
        hint = seed["_catalog_price_hint"]
        # Do not let the seed's list price override a current promotional price.
        seed["preco"] = None
        result, status = base_enrich(seed, config)
        if status.get("error"):
            return item, status
        spec = dict(result.get("specs") or {})
        try:
            confirmed = float(spec.get("price_confirmed"))
        except (TypeError, ValueError, OverflowError):
            confirmed = float("nan")
        if not math.isfinite(confirmed) or confirmed <= 0 or spec.get("price_page_confidence") not in {"MEDIUM", "HIGH"}:
            return item, {**status, "error": "catalog_live_price_unconfirmed"}
        result = dict(result)
        result["preco"] = confirmed
        spec["catalog_price_hint"] = hint
        result["specs"] = spec
        return result, status

    tracker_module.scan_store = scan_store
    if base_enrich is not None:
        tracker_module.enrich = enrich
    tracker_module._CATALOG_GUARD_INSTALLED = True
