from __future__ import annotations

import csv
import gzip
import io
import os
import re
from urllib.parse import urlparse


FEED_LIST_TEMPLATE = "https://productdata.awin.com/datafeed/list/apikey/{api_key}"


def _decode_csv_bytes(content: bytes) -> str:
    raw = bytes(content or b"")
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _csv_rows(content: bytes) -> list[dict[str, str]]:
    text = _decode_csv_bytes(content)
    if not text.strip():
        return []
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text))
    return [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in reader
        if isinstance(row, dict)
    ]


def _header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _row_value(row: dict[str, str], *names: str) -> str:
    normalized = {_header_key(key): value for key, value in row.items()}
    for name in names:
        value = normalized.get(_header_key(name))
        if value:
            return value
    return ""


def _direct_merchant_url(value: object, cat: dict) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        source = urlparse(str(cat.get("url") or ""))
        target = urlparse(raw)
    except ValueError:
        return None
    source_host = source.netloc.lower().removeprefix("www.")
    target_host = target.netloc.lower().removeprefix("www.")
    if not target.scheme.startswith("http") or target_host != source_host:
        return None
    return raw


def _stock_value(row: dict[str, str]) -> bool | None:
    in_stock = _row_value(row, "in_stock", "instock")
    status = _row_value(row, "stock_status", "stockstatus", "availability")
    sale = _row_value(row, "is_for_sale", "isforsale")
    positive = {"1", "true", "yes", "y", "sim", "in stock", "instock", "available"}
    negative = {"0", "false", "no", "n", "nao", "não", "out of stock", "outofstock", "unavailable"}
    for value in (in_stock, status, sale):
        normalized = str(value or "").strip().lower()
        if normalized in negative:
            return False
        if normalized in positive:
            return True
    return None


def _feed_is_laptop(row: dict[str, str], cat: dict, scraper_module) -> bool:
    hints = [
        scraper_module.norm(value)
        for value in cat.get("awin_category_hints", ["portatil", "laptop", "notebook"])
        if value
    ]
    if not hints:
        return True
    text = scraper_module.norm(
        " ".join(
            _row_value(row, field)
            for field in (
                "product_name",
                "merchant_category",
                "category_name",
                "merchant_product_category_path",
                "merchant_product_second_category",
                "merchant_product_third_category",
                "product_type",
            )
        )
    )
    return any(hint in text for hint in hints)


def _feed_candidates(content: bytes, cat: dict, tracker_module) -> list[dict]:
    expected_id = str(cat.get("awin_advertiser_id") or "").strip()
    limit = max(1, int(cat.get("awin_feed_candidate_limit", cat.get("target_candidates", 60))))
    out: list[dict] = []
    seen: set[str] = set()

    for row in _csv_rows(content):
        merchant_id = _row_value(row, "merchant_id", "advertiser_id", "merchantid")
        if expected_id and merchant_id and merchant_id != expected_id:
            continue

        title = _row_value(row, "product_name", "name", "product_title")
        if not title or not tracker_module.scraper.eligible(title):
            continue
        if not _feed_is_laptop(row, cat, tracker_module.scraper):
            continue

        condition = tracker_module.scraper.norm(_row_value(row, "condition"))
        if condition and any(value in condition for value in ("refurb", "recond", "used", "usado", "outlet")):
            continue

        price = None
        for field in ("search_price", "store_price", "price", "base_price"):
            value = tracker_module.scraper.parse_price_value(_row_value(row, field))
            if value is not None:
                price = float(value)
                break
        if price is None:
            continue

        url = _direct_merchant_url(
            _row_value(row, "merchant_deep_link", "merchantdeeplink", "deep_link"), cat
        )
        if not url:
            continue
        if url in seen:
            continue

        stock = _stock_value(row)
        if stock is False:
            continue

        item = {
            "loja": cat["loja"],
            "titulo": title,
            "preco": price,
            "url": url,
            "stock": stock,
            "detail_source": "awin_feed_seed",
            "discovery_sources": ["awin_feed"],
        }
        ean = re.sub(r"\D", "", _row_value(row, "ean", "product_gtin", "gtin"))
        if ean and tracker_module.gtin_valid(ean):
            item["ean"] = ean
        mpn = _row_value(row, "mpn", "model_number", "product_model")
        if mpn:
            item["mpn"] = mpn
        sku = _row_value(row, "merchant_product_id", "product_id", "aw_product_id")
        if sku:
            item["sku"] = sku

        # Specs do feed são evidência útil para pré-ranking/matching, mas não são
        # marcadas como `item['specs']`: a ficha live/cache continua a ser a fonte
        # autoritativa de hardware/teclado no pipeline normal.
        feed_spec_text = " ".join(
            filter(
                None,
                [
                    title,
                    _row_value(row, "specifications"),
                    _row_value(row, "product_model"),
                    _row_value(row, "model_number"),
                ],
            )
        )
        if feed_spec_text:
            item["_awin_spec_hint"] = feed_spec_text[:4000]

        seen.add(url)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _feed_urls_from_list(content: bytes) -> dict[str, str]:
    found: dict[str, str] = {}
    for row in _csv_rows(content):
        advertiser_id = _row_value(row, "Advertiser ID", "advertiser_id", "merchant_id")
        url = _row_value(row, "URL", "download_url", "feed_url")
        joined = _row_value(row, "Membership Status", "membership_status").lower()
        if not advertiser_id or not url:
            continue
        if advertiser_id not in found or "joined" in joined:
            found[advertiser_id] = url
    return found


def _request_bytes(tracker_module, url: str, store: str, method: str, timeout_s: float):
    if not tracker_module.consume_request(store):
        return None, "request_budget_exhausted"
    try:
        response = tracker_module.requests.get(
            url,
            timeout=timeout_s,
            headers={
                "Accept": "text/csv,application/gzip,application/octet-stream,*/*",
                "User-Agent": "rastreador-precos/8.8.9",
            },
            allow_redirects=True,
        )
        code = int(response.status_code)
        if 200 <= code < 300:
            return bytes(response.content), "http_success"
        return None, f"http_{code}"
    except Exception:
        return None, "request_error"


def install(tracker_module) -> None:
    """Usa feeds Awin autorizados quando configurados; sem chave é um no-op."""
    if getattr(tracker_module, "_AWIN_FEED_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    feed_url_cache: dict[str, str] = {}
    list_state = {"loaded": False, "outcome": "not_configured"}

    def load_feed_urls(store: str, timeout_s: float) -> tuple[dict[str, str], str]:
        if list_state["loaded"]:
            return feed_url_cache, str(list_state["outcome"])
        api_key = os.getenv("AWIN_DATAFEED_API_KEY", "").strip()
        if not api_key:
            list_state["loaded"] = True
            list_state["outcome"] = "not_configured"
            return feed_url_cache, "not_configured"

        # A chave nunca é persistida, impressa ou devolvida nas métricas.
        content, outcome = _request_bytes(
            tracker_module,
            FEED_LIST_TEMPLATE.format(api_key=api_key),
            store,
            "awin_feed_list",
            timeout_s,
        )
        list_state["loaded"] = True
        list_state["outcome"] = outcome
        if content:
            feed_url_cache.update(_feed_urls_from_list(content))
        return feed_url_cache, outcome

    def scan_store(cat: dict, config: dict, settings: dict):
        items, stat = base_scan_store(cat, config, settings)
        advertiser_id = str(cat.get("awin_advertiser_id") or "").strip()
        below = max(0, int(cat.get("awin_feed_below", cat.get("target_candidates", 60))))
        if not advertiser_id or len(items) >= below or not tracker_module.budget_available(cat["loja"]):
            return items, stat

        api_key = os.getenv("AWIN_DATAFEED_API_KEY", "").strip()
        if not api_key:
            stat["awin_feed_outcome"] = "not_configured"
            return items, stat

        store = str(cat["loja"])
        timeout_s = max(3.0, float(cat.get("awin_feed_timeout_s", 20.0)))
        urls, list_outcome = load_feed_urls(store, timeout_s)
        feed_url = urls.get(advertiser_id)
        if not feed_url:
            stat["awin_feed_outcome"] = (
                "feed_not_visible" if list_outcome == "http_success" else list_outcome
            )
            return items, stat

        before_requests = int(tracker_module.REQUESTS_BY_STORE.get(store, 0))
        content, outcome = _request_bytes(
            tracker_module, feed_url, store, "awin_feed", timeout_s
        )
        found = _feed_candidates(content or b"", cat, tracker_module) if content else []
        known = {str(item.get("url")) for item in items if item.get("url")}
        added = 0
        for item in found:
            if item["url"] in known:
                continue
            items.append(item)
            known.add(item["url"])
            added += 1

        spent = max(0, int(tracker_module.REQUESTS_BY_STORE.get(store, 0)) - before_requests)
        tracker_module.record_discovery_yield(store, "awin_feed", spent, added)
        stat.setdefault("fontes_descoberta", {}).setdefault("awin_feed", 0)
        stat["fontes_descoberta"]["awin_feed"] += added
        stat.setdefault("rendimento_descoberta", {})["awin_feed"] = {
            "requests": spent,
            "new_candidates": added,
            "yield": round(added / max(1, spent), 3),
        }
        stat["awin_feed_outcome"] = outcome
        stat["candidatos"] = len(items)
        if items:
            stat["bloqueada"] = False
        return items, stat

    # Feed hints can improve pre-ranking before a live detail fetch, while cached
    # specs and live specs remain authoritative for final evaluation.
    base_candidate_priority = tracker_module.candidate_priority

    def candidate_priority(item, weights, settings):
        if item.get("_awin_spec_hint") and not item.get("specs"):
            hinted = dict(item)
            hinted["titulo"] = f"{item.get('titulo', '')} {item['_awin_spec_hint']}"
            return base_candidate_priority(hinted, weights, settings)
        return base_candidate_priority(item, weights, settings)

    tracker_module.scan_store = scan_store
    tracker_module.candidate_priority = candidate_priority
    tracker_module._AWIN_FEED_GUARD_INSTALLED = True
