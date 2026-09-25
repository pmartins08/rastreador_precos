from __future__ import annotations

import threading
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import promotion_value_guard as promotion_value


_DEFAULT_PROBE_STORES = {
    "Darty",
    "FNAC",
    "Globaldata",
    "UPTECHBOX",
    "Radio Popular",
}
_LOCAL = threading.local()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def probe_due(
    previous_meta: dict | None,
    item: dict,
    settings: dict,
    *,
    current_time: datetime | None = None,
) -> bool:
    """Decide quando uma ficha deve ser revista por promoções de produto/carrinho."""
    stores = settings.get("product_promotion_probe_stores")
    if isinstance(stores, (list, tuple, set)):
        enabled = {str(value) for value in stores if str(value).strip()}
    else:
        enabled = _DEFAULT_PROBE_STORES
    if str(item.get("loja") or "") not in enabled:
        return False

    stamp = _parse_timestamp(
        (previous_meta or {}).get("product_promotion_checked_at")
        if isinstance(previous_meta, dict)
        else None
    )
    if stamp is None:
        return True

    now = current_time or _now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - stamp).total_seconds() / 3600.0)
    ttl = max(1.0, float(settings.get("product_promotion_probe_ttl_hours", 6.0)))
    return age_hours >= ttl


def _targeted_promotion_contexts(html: str) -> list[str]:
    """Extrai apenas blocos pequenos que parecem promoções ligadas ao checkout."""
    soup = BeautifulSoup(html or "", "html.parser")
    contexts: list[str] = []
    seen: set[str] = set()
    for node in soup.find_all(string=True):
        raw = " ".join(str(node or "").split())
        lower = raw.lower()
        if "carrinho" not in lower and "cup" not in lower and "código" not in lower and "codigo" not in lower:
            continue
        if "%" not in raw and "€" not in raw:
            continue

        current = getattr(node, "parent", None)
        best = raw
        for _ in range(4):
            if current is None:
                break
            text = " ".join(current.get_text(" ", strip=True).split())
            if 0 < len(text) <= 900:
                best = text
            if len(text) > 900:
                break
            current = getattr(current, "parent", None)
        marker = best.lower()
        if marker and marker not in seen:
            seen.add(marker)
            contexts.append(best)
    return contexts[:20]


def extract_live_product_promotions(html: str, *, store: str, title: str = "") -> list[dict]:
    """Deteta promoções explícitas na própria ficha, sem inventar desconto a partir do PVPR."""
    promotions = list(
        promotion_value.extract_product_promotions(html, store=store, title=title)
    )
    for context in _targeted_promotion_contexts(html):
        promotions.extend(
            promotion_value.parse_promotion_text(
                context,
                source="product_page_live",
                eligibility="explicit",
            )
        )
    return promotion_value.dedupe(promotions)


def _structured_price(tracker_module, soup, response_url: str, title: str) -> float | None:
    parser = getattr(tracker_module, "jsonld_primary_product", None)
    if not callable(parser):
        return None
    try:
        product = parser(soup, response_url, title)
        value = product.get("preco") if isinstance(product, dict) else None
        return float(value) if value is not None else None
    except (TypeError, ValueError, KeyError):
        return None


def install(tracker_module) -> None:
    """Liga promoções da ficha live ao motor promocional sem pedidos HTTP extra."""
    if getattr(tracker_module, "_PRODUCT_PROMOTION_GUARD_INSTALLED", False):
        return

    base_adaptive_fetch = tracker_module.adaptive_fetch
    base_enrich = tracker_module.enrich
    base_needs_price_refresh = tracker_module.needs_price_refresh
    base_record_offer = tracker_module.record_offer

    def adaptive_fetch(url, config, timeout_s=8.0, *, store=None, method="page", **kwargs):
        response, profile, outcome = base_adaptive_fetch(
            url,
            config,
            timeout_s,
            store=store,
            method=method,
            **kwargs,
        )
        if str(method).startswith("product") and response is not None and outcome == "http_success":
            _LOCAL.last_product_page = {
                "store": str(store or ""),
                "method": str(method),
                "url": str(getattr(response, "url", url) or url),
                "html": str(getattr(response, "text", "") or ""),
            }
        return response, profile, outcome

    def enrich(item: dict, config: dict):
        _LOCAL.last_product_page = None
        result, status = base_enrich(item, config)
        page = getattr(_LOCAL, "last_product_page", None)
        _LOCAL.last_product_page = None

        if status.get("error") or not isinstance(page, dict) or not page.get("html"):
            return result, status

        title = str(result.get("titulo") or item.get("titulo") or "")
        store = str(result.get("loja") or item.get("loja") or "")
        promotions = extract_live_product_promotions(
            page["html"],
            store=store,
            title=title,
        )
        checked_at = tracker_module.now_iso()
        result["product_promotion_checked_at"] = checked_at
        result["product_promotion_fingerprint"] = promotion_value.fingerprint(promotions)

        if not promotions:
            return result, status

        result["promotions"] = promotion_value.dedupe(
            [*(result.get("promotions") or []), *promotions]
        )

        soup = BeautifulSoup(page["html"], "html.parser")
        structured_price = _structured_price(
            tracker_module,
            soup,
            str(page.get("url") or result.get("url") or ""),
            title,
        )
        preferred = getattr(tracker_module, "preferred_page_price", None)
        live_price = None
        if callable(preferred):
            try:
                live_price = preferred(soup, structured_price)
            except (TypeError, ValueError):
                live_price = None
        if live_price is not None:
            try:
                numeric_price = float(live_price)
            except (TypeError, ValueError):
                numeric_price = None
            if numeric_price is not None and 200.0 <= numeric_price <= 10000.0:
                result["preco"] = numeric_price

        try:
            raw_price = float(result.get("preco"))
        except (TypeError, ValueError):
            return result, status

        economics = promotion_value.economics(result.get("promotions"), raw_price)
        if float(economics.get("checkout_discount_eur") or 0.0) > 0.0:
            result["promotion_product_live_confirmed"] = True
            result["promotion_price_live_confirmed"] = True
            result["promotion_economics"] = economics
        return result, status

    def needs_price_refresh(previous_meta, item, settings, *, current_time=None):
        if base_needs_price_refresh(
            previous_meta,
            item,
            settings,
            current_time=current_time,
        ):
            return True
        return probe_due(
            previous_meta,
            item,
            settings,
            current_time=current_time,
        )

    def record_offer(history, item, spec, assessment, tier):
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        entries = history.get("offers", {}).get(key, [])
        if entries and isinstance(entries[-1], dict):
            entries[-1]["product_promotion_checked_at"] = item.get(
                "product_promotion_checked_at"
            )
            entries[-1]["product_promotion_fingerprint"] = item.get(
                "product_promotion_fingerprint"
            )
            entries[-1]["promotion_product_live_confirmed"] = bool(
                item.get("promotion_product_live_confirmed")
            )
            if item.get("promotions"):
                entries[-1]["promotions"] = promotion_value.dedupe(item.get("promotions"))
        return previous, key

    tracker_module.adaptive_fetch = adaptive_fetch
    tracker_module.enrich = enrich
    tracker_module.needs_price_refresh = needs_price_refresh
    tracker_module.record_offer = record_offer
    tracker_module._PRODUCT_PROMOTION_GUARD_INSTALLED = True
