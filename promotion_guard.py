from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


DEFAULT_CAMPAIGNS = {
    "Worten": [
        {
            "label": "regresso_aulas_2026",
            "url": "https://www.worten.pt/campanha/tudo-para-o-regresso-as-aulas",
            "active_from": "2026-08-18",
            "expires_at": "2026-09-21",
            "priority": 120,
        }
    ],
    "PcComponentes": [
        {
            "label": "regresso_aulas_2026",
            "url": "https://www.pccomponentes.pt/campanhas/regresso-as-aulas",
            "expires_at": "2026-09-13",
            "priority": 120,
        }
    ],
    "FNAC": [
        {
            "label": "regresso_aulas_2026",
            "url": "https://www.fnac.pt/regresso-as-aulas",
            "expires_at": "2026-09-30",
            "priority": 115,
        }
    ],
    "Radio Popular": [
        {
            "label": "regresso_aulas_2026",
            "url": "https://www.radiopopular.pt/microsite/regresso-as-aulas-2026",
            "expires_at": "2026-09-15",
            "priority": 115,
        }
    ],
}


def _parse_day(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
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


def _campaigns_for(cat: dict, store: str) -> list[Any]:
    configured = list(cat.get("campaign_urls", []))
    configured.extend(DEFAULT_CAMPAIGNS.get(store, []))
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


def install(tracker_module) -> None:
    """Prioriza campanhas públicas sem alterar scoring nem confiança de preço.

    As campanhas são apenas lead generation. Produtos descobertos por esta via
    continuam obrigatoriamente a passar pelo parsing normal, Brain Guard,
    Price Guard e Market Guard antes de poderem gerar qualquer alerta.
    """
    if getattr(tracker_module, "_PROMOTION_GUARD_INSTALLED", False):
        return

    def discovery_routes(cat: dict, store: str) -> list[dict]:
        routes: list[dict] = []

        for index, raw in enumerate(_campaigns_for(cat, store)):
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

    tracker_module.discovery_routes = discovery_routes
    tracker_module._PROMOTION_GUARD_INSTALLED = True
