from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

import catalog_guard
import promotion_guard
import promotion_live_guard
import promotion_value_guard as promotion_value


PROMOTION_SOURCE = "promocao"
_CAMPAIGN_WORDS = (
    "campanha",
    "promocao",
    "promocoes",
    "week",
    "regresso",
    "desconto",
    "oferta",
    "ganha",
    "voucher",
    "cashback",
    "talao",
    "cupao",
    "leva",
    "paga",
    "pack",
    "compra conjunta",
    "oportunidade",
)
_ALLOWED_ROUTE_PARTS = (
    "/collections/",
    "/pages/",
    "/campanha",
    "/campaign",
    "/promoc",
    "/destaque/",
    "/microsite/",
    "/ofertas",
    "/oportunidades",
)
_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return text.encode("ascii", "ignore").decode().lower()


def _canonical_url(value: object) -> str:
    parsed = urlsplit(str(value or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}".lower()


def _campaign_dates(text: str, *, today: date | None = None) -> tuple[str | None, str | None]:
    """Extrai intervalos de campanha, incluindo datas sem ano explícito."""
    current = today or date.today()
    clean = _norm(text)
    match = re.search(
        r"(?:de\s+)?(\d{1,2})\s*(?:a|ate|-)\s*(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(20\d{2}))?",
        clean,
    )
    if match:
        month = _MONTHS.get(match.group(3))
        if month:
            year = int(match.group(4) or current.year)
            try:
                return (
                    date(year, month, int(match.group(1))).isoformat(),
                    date(year, month, int(match.group(2))).isoformat(),
                )
            except ValueError:
                return None, None

    match = re.search(
        r"(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\s*(?:a|ate|-)\s*"
        r"(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?",
        clean,
    )
    if match:
        start_year = int(match.group(3) or current.year)
        end_year = int(match.group(6) or start_year)
        try:
            return (
                date(start_year, int(match.group(2)), int(match.group(1))).isoformat(),
                date(end_year, int(match.group(5)), int(match.group(4))).isoformat(),
            )
        except ValueError:
            return None, None
    return None, None


def _anchor_context(anchor) -> str:
    node = anchor
    best = anchor.get_text(" ", strip=True)
    for _ in range(5):
        parent = getattr(node, "parent", None)
        if parent is None:
            break
        text = parent.get_text(" ", strip=True)
        if 0 < len(text) <= 1800:
            best = text
        normalized = _norm(text)
        if any(word in normalized for word in _CAMPAIGN_WORDS):
            best = text
            break
        node = parent
    return best


def _campaign_like(href: str, context: str) -> bool:
    parsed = urlsplit(href)
    path = parsed.path.lower()
    if not path or path == "/" or "/products/" in path or "/produto/" in path:
        return False
    normalized = _norm(context)
    route_hint = any(part in path for part in _ALLOWED_ROUTE_PARTS)
    word_hint = any(word in normalized for word in _CAMPAIGN_WORDS)
    return route_hint and word_hint


def detect_campaign_routes(html: str, base_url: str, *, today: date | None = None) -> list[dict]:
    """Descobre campanhas oficiais sem exigir que o banner exponha logo a matemática."""
    soup = BeautifulSoup(html or "", "html.parser")
    base_host = urlsplit(base_url).netloc.lower().removeprefix("www.")
    found: dict[str, dict] = {}

    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, str(anchor.get("href") or ""))
        parsed = urlsplit(href)
        if parsed.netloc.lower().removeprefix("www.") != base_host:
            continue
        context = _anchor_context(anchor)
        promotions = promotion_value.parse_promotion_text(
            context,
            source="promotion_watch",
            eligibility="campaign_listing",
        )
        if not promotions and not _campaign_like(href, context):
            continue

        marker = _canonical_url(href)
        if not marker:
            continue
        start, end = _campaign_dates(context, today=today)
        promo = dict(promotions[0]) if promotions else None
        if promo is not None:
            if start:
                promo.setdefault("valid_from", start)
            if end:
                promo.setdefault("valid_until", end)
        route = {
            "label": f"auto_{hashlib.sha1(marker.encode('utf-8')).hexdigest()[:8]}",
            "url": href,
            "priority": 135 if promo else 118,
            "auto_detected": True,
            "watch_context": context[:500],
        }
        if promo is not None:
            route["promotion"] = promo
        if start:
            route["active_from"] = start
        if end:
            route["expires_at"] = end
        if not promotion_guard.route_is_active(route, today=today):
            continue

        previous = found.get(marker)
        if previous is None or int(route["priority"]) > int(previous.get("priority", 0)):
            found[marker] = route

    return sorted(
        found.values(),
        key=lambda row: (
            -int(bool(row.get("promotion"))),
            -int(bool(row.get("expires_at"))),
            -int(row.get("priority", 0)),
            str(row.get("url") or ""),
        ),
    )[:20]


def _main_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.find("main") or soup.body or soup
    for tag in root.find_all(["header", "footer", "nav", "script", "style", "noscript"]):
        tag.decompose()
    return root.get_text(" ", strip=True)


def verified_route_promotions(route: dict, landing_html: str) -> list[dict]:
    """Só devolve economia monetária depois de confirmação na landing live."""
    live = [
        promo
        for promo in promotion_value.parse_promotion_text(
            _main_text(landing_html),
            source="campaign_page_live",
            eligibility="campaign_listing",
        )
        if promotion_value.is_active(promo)
    ]
    configured = []
    if isinstance(route.get("promotion"), dict):
        promo = dict(route["promotion"])
        promo.setdefault("source", "promotion_watch")
        promo.setdefault("eligibility", "campaign_listing")
        promo.setdefault("applicable", True)
        if route.get("active_from"):
            promo.setdefault("valid_from", route["active_from"])
        if route.get("expires_at"):
            promo.setdefault("valid_until", route["expires_at"])
        configured.append(promo)

    verified = promotion_live_guard._verified_promotions(configured, live)
    return [
        promo for promo in verified
        if promo.get("live_verified") and promotion_value.is_active(promo)
    ]


def shopify_collection_json_url(route_url: str, *, limit: int = 250) -> str | None:
    parsed = urlsplit(str(route_url or ""))
    path = parsed.path.rstrip("/")
    if not re.fullmatch(r"/collections/[^/]+", path, re.I):
        return None
    query = urlencode({"limit": max(1, min(250, int(limit)))})
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/products.json", query, ""))


def _merge_sources(existing: list | None, *values: str) -> list[str]:
    out = []
    for value in [*(existing or []), *values]:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _merge_promoted_rows(items: list[dict], rows: list[dict], route: dict, verified: list[dict]) -> int:
    by_url = {_canonical_url(item.get("url")): item for item in items if item.get("url")}
    added = 0
    for row in rows:
        marker = _canonical_url(row.get("url"))
        if not marker:
            continue
        target = by_url.get(marker)
        if target is None:
            target = dict(row)
            items.append(target)
            by_url[marker] = target
            added += 1
        else:
            for key in ("ean", "titulo", "preco", "stock"):
                if target.get(key) in (None, "") and row.get(key) not in (None, ""):
                    target[key] = row[key]

        target["discovery_sources"] = _merge_sources(
            target.get("discovery_sources"), PROMOTION_SOURCE
        )
        target["promotion_route_url"] = str(route.get("url") or "")
        target["promotion_route_label"] = str(route.get("label") or "")
        target["promotion_campaign_live_confirmed"] = True
        if verified:
            target["promotions"] = promotion_value.dedupe(
                [*(target.get("promotions") or []), *verified]
            )
            # A collection confirma pertença; o preço continua a seguir a política
            # normal da loja. Não marcamos price_live aqui para não transformar o
            # JSON Shopify num atalho ao Price Guard.
            target["promotion_listing_live_confirmed"] = True
    return added


def _watch_urls(cat: dict) -> list[str]:
    out: list[str] = []
    for raw in cat.get("promotion_watch_urls", []):
        value = raw.get("url") if isinstance(raw, dict) else raw
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def install(tracker_module) -> None:
    """Motor V3: descoberta transversal + elegibilidade exata em collections Shopify."""
    if getattr(tracker_module, "_PROMOTION_ENGINE_V3_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    base_adaptive_fetch = tracker_module.adaptive_fetch
    dynamic_routes: dict[str, list[dict]] = {}
    tracker_module._PROMOTION_ENGINE_V3_ROUTES = dynamic_routes

    def scan_store(cat: dict, config: dict, settings: dict):
        store = str(cat.get("loja") or "")
        detected: list[dict] = []
        seen_watch = 0

        for index, watch_url in enumerate(_watch_urls(cat)):
            if not tracker_module.budget_available(store):
                break
            response, _profile, outcome = base_adaptive_fetch(
                watch_url,
                config,
                float(cat.get("promotion_watch_timeout_s", 7.0)),
                store=store,
                method=f"promotion_engine_watch:{index + 1}",
            )
            if response is None or outcome != "http_success":
                continue
            seen_watch += 1
            detected.extend(detect_campaign_routes(response.text, watch_url))

        by_route = {}
        for route in detected:
            by_route.setdefault(_canonical_url(route.get("url")), route)
        dynamic = list(by_route.values())
        dynamic_routes[store] = dynamic

        # O V2 deixa de fazer os mesmos watch requests. Recebe as rotas já
        # detetadas como campaign_urls e mantém toda a sua lógica de prioridade,
        # live validation, Value e alertas.
        effective_cat = dict(cat)
        effective_cat["promotion_watch_urls"] = []
        configured = list(cat.get("campaign_urls", []))
        configured_markers = {
            _canonical_url(raw.get("url") if isinstance(raw, dict) else raw)
            for raw in configured
        }
        effective_cat["campaign_urls"] = [
            *configured,
            *[
                route for route in dynamic
                if _canonical_url(route.get("url")) not in configured_markers
            ],
        ]

        items, stat = base_scan_store(effective_cat, config, settings)
        stat["promotion_engine_watch_pages"] = seen_watch
        stat["promotion_engine_routes"] = len(dynamic)
        stat.setdefault("promotion_engine_collection_rows", 0)
        stat.setdefault("promotion_engine_collection_added", 0)
        stat.setdefault("promotion_engine_verified_rules", 0)

        if not cat.get("promotion_collection_json"):
            return items, stat

        max_routes = max(1, int(cat.get("promotion_collection_max_routes", 6)))
        for route_index, route in enumerate(dynamic[:max_routes], start=1):
            if not tracker_module.budget_available(store):
                break
            collection_url = shopify_collection_json_url(
                str(route.get("url") or ""),
                limit=int(cat.get("promotion_collection_json_limit", 250)),
            )
            if not collection_url:
                continue

            landing_response, _profile, landing_outcome = base_adaptive_fetch(
                str(route["url"]),
                config,
                float(cat.get("promotion_landing_timeout_s", 7.0)),
                store=store,
                method=f"promotion_engine_landing:{route_index}",
            )
            if landing_response is None or landing_outcome != "http_success":
                continue
            verified = verified_route_promotions(route, landing_response.text)
            stat["promotion_engine_verified_rules"] += len(verified)

            response, _profile, outcome = base_adaptive_fetch(
                collection_url,
                config,
                float(cat.get("promotion_collection_timeout_s", 6.0)),
                store=store,
                method=f"promotion_collection_json:{route_index}",
            )
            if response is None or outcome != "http_success":
                continue
            try:
                payload = response.json()
                rows = catalog_guard._shopify_candidates(payload, cat, tracker_module)
            except (ValueError, TypeError, KeyError, OverflowError):
                continue

            stat["promotion_engine_collection_rows"] += len(rows)
            stat["promotion_engine_collection_added"] += _merge_promoted_rows(
                items, rows, route, verified
            )

        stat["candidatos"] = len(items)
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._PROMOTION_ENGINE_V3_INSTALLED = True
