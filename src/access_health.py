"""Estado de cobertura por loja; CI verde não significa acesso às lojas."""
from __future__ import annotations

BLOCKED = {"http_401", "http_403", "http_429", "challenge"}


def summarize_access(run: dict, *, per_store_limit: int, total_limit: int) -> dict:
    stores = {}
    for store, stat in run.get("stores", {}).items():
        sources = stat.get("fontes_descoberta", {})
        current = {name: int(count) for name, count in sources.items()
                   if name not in {"historico", "sitemap_cache"} and int(count or 0) > 0}
        historical = sum(int(sources.get(name, 0) or 0) for name in ("historico", "sitemap_cache"))
        outcome = stat.get("acesso", {}).get("resultado", "not_attempted")
        if current:
            state = "discovery_available"
        elif historical:
            state = "history_only"
        elif outcome in BLOCKED or stat.get("bloqueada"):
            state = "blocked"
        else:
            state = "no_products"
        requests = int(run.get("requests_by_store", {}).get(store, 0))
        stores[store] = {
            "state": state,
            "category_outcome": outcome,
            "current_sources": current,
            "historical_candidates": historical,
            "evaluated": int(stat.get("avaliados", 0)),
            "accepted": int(stat.get("aceites", 0)),
            "requests": requests,
            "store_budget_reached": requests >= per_store_limit,
            "catalog_outcome": stat.get("catalog_json_outcome", "not_configured"),
            "feed_outcome": stat.get("awin_feed_outcome", "not_attempted"),
        }
    return {
        "stores": stores,
        "blocked_stores": [name for name, row in stores.items() if row["state"] == "blocked"],
        "history_only_stores": [name for name, row in stores.items() if row["state"] == "history_only"],
        "total_budget_reached": int(run.get("access_requests", 0)) >= total_limit,
    }
