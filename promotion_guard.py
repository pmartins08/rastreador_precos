from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _parse_day(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def route_is_active(route: dict, today: date | None = None) -> bool:
    """Indica se uma rota promocional/segmento deve ser usada hoje.

    Datas são opcionais e inclusivas. Uma campanha expirada desaparece da
    exploração sem ser necessário remover imediatamente a configuração.
    """
    day = today or datetime.now(timezone.utc).date()
    start = _parse_day(route.get("active_from"))
    end = _parse_day(route.get("expires_at"))
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _route(raw: Any, index: int, kind: str, tracker_module) -> dict | None:
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


def install(tracker_module) -> None:
    """Prioriza campanhas públicas sem alterar scoring nem confiança de preço.

    A promoção é apenas uma pista de descoberta. Todos os candidatos continuam
    a passar pelo mesmo parsing, cérebro, Price Guard e Market Guard.
    """
    if getattr(tracker_module, "_PROMOTION_GUARD_INSTALLED", False):
        return

    def discovery_routes(cat: dict, store: str) -> list[dict]:
        routes: list[dict] = []

        for index, raw in enumerate(cat.get("campaign_urls", [])):
            route = _route(raw, index, "promotion", tracker_module)
            if route is not None:
                route["yield_score"] = tracker_module.discovery_score(
                    store, route["method_key"]
                )
                routes.append(route)

        for index, raw in enumerate(cat.get("extra_discovery_urls", [])):
            route = _route(raw, index, "segment", tracker_module)
            if route is not None:
                route["yield_score"] = tracker_module.discovery_score(
                    store, route["method_key"]
                )
                routes.append(route)

        # Campanhas primeiro; dentro da mesma prioridade continua a vencer o
        # método que historicamente encontra mais candidatos por request.
        return sorted(
            routes,
            key=lambda route: (
                -int(route.get("priority", 0)),
                -float(route.get("yield_score", 0.0)),
                route["label"],
            ),
        )

    tracker_module.discovery_routes = discovery_routes
    tracker_module._PROMOTION_GUARD_INSTALLED = True
