from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


PROMOTION_SOURCE = "promocao"


def _parse_day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def route_is_active(route: dict, today: date | None = None) -> bool:
    """Indica se uma rota promocional/segmento deve ser usada hoje."""
    day = today or datetime.now(timezone.utc).date()
    start = _parse_day(route.get("active_from"))
    end = _parse_day(route.get("expires_at"))
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _route(raw: Any, index: int, kind: str) -> dict | None:
    if isinstance(raw, str):
        route = {"url": raw, "label": f"{kind}_{index + 1}"}
    elif isinstance(raw, dict) and raw.get("url"):
        route = dict(raw)
        route["url"] = str(raw["url"])
        route["label"] = str(raw.get("label") or f"{kind}_{index + 1}")
    else:
        return None

    if not route_is_active(route):
        return None

    route["kind"] = kind
    prefix = "campaign" if kind == "promotion" else "segment"
    route["method_key"] = f"{prefix}:{route['label']}"
    route["priority"] = int(route.get("priority", 100 if kind == "promotion" else 0))
    route["yield_score"] = 0.0
    return route


def _campaigns_for(cat: dict) -> list[Any]:
    """Campanhas são configuração, não código.

    Isto mantém o guard genérico: futuras campanhas podem ser adicionadas,
    desativadas ou expiradas sem alterar o runtime.
    """
    configured = list(cat.get("campaign_urls", []))
    seen = set()
    out = []
    for raw in configured:
        url = raw if isinstance(raw, str) else raw.get("url") if isinstance(raw, dict) else None
        marker = str(url or "").rstrip("/").lower()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(raw)
    return out


def _active_campaign_urls(cat: dict) -> set[str]:
    urls = set()
    for index, raw in enumerate(_campaigns_for(cat)):
        route = _route(raw, index, "promotion")
        if route is not None:
            urls.add(str(route["url"]).rstrip("/").lower())
    return urls


def install(tracker_module) -> None:
    """Prioriza campanhas sem alterar o Value ou a confiança de preço.

    A campanha serve apenas para lead generation e pré-ranking. O candidato
    continua a passar pelo scraper, Brain Guard, Price Guard e Market Guard.
    """
    if getattr(tracker_module, "_PROMOTION_GUARD_INSTALLED", False):
        return

    base_discover_html = tracker_module._discover_html
    base_candidate_priority = tracker_module.candidate_priority

    def discovery_routes(cat: dict, store: str) -> list[dict]:
        routes: list[dict] = []

        for index, raw in enumerate(_campaigns_for(cat)):
            route = _route(raw, index, "promotion")
            if route is not None:
                route["yield_score"] = tracker_module.discovery_score(store, route["method_key"])
                routes.append(route)

        for index, raw in enumerate(cat.get("extra_discovery_urls", [])):
            route = _route(raw, index, "segment")
            if route is not None:
                route["yield_score"] = tracker_module.discovery_score(store, route["method_key"])
                routes.append(route)

        return sorted(
            routes,
            key=lambda route: (
                -int(route.get("priority", 0)),
                -float(route.get("yield_score", 0.0)),
                route["label"],
            ),
        )

    def discover_html(response, route_cat, target, candidates, source, stat):
        current = str(route_cat.get("url") or "").rstrip("/").lower()
        effective_source = source
        if current and current in _active_campaign_urls(route_cat):
            effective_source = PROMOTION_SOURCE
            stat.setdefault("fontes_descoberta", {}).setdefault(PROMOTION_SOURCE, 0)
        return base_discover_html(
            response, route_cat, target, candidates, effective_source, stat
        )

    def candidate_priority(item: dict, weights: dict, settings: dict) -> float:
        base = float(base_candidate_priority(item, weights, settings))
        if PROMOTION_SOURCE not in set(item.get("discovery_sources", [])):
            return base
        # Apenas decide o que merece análise primeiro. Não toca no Value final.
        bonus = float(settings.get("promotion_candidate_priority_bonus", 6.0))
        return round(base + max(0.0, min(15.0, bonus)), 3)

    tracker_module.discovery_routes = discovery_routes
    tracker_module._discover_html = discover_html
    tracker_module.candidate_priority = candidate_priority
    tracker_module._PROMOTION_GUARD_INSTALLED = True
