from __future__ import annotations

import copy
from urllib.parse import urlparse


# Recuperação conservadora das lojas que o GitHub Actions vê frequentemente
# bloqueadas na categoria principal. Só reabre rotas públicas/sitemap; não tenta
# contornar autenticação, checkout ou endpoints privados.
_RECOVERY = {
    "PCDiga": {
        "version": "pcdiga-public-sitemap-v2",
        "force_sitemap": True,
        "sitemap_probe_limit": 12,
        "max_sitemaps": 10,
        "sitemap_child_hints": [
            "product",
            "produto",
            "catalog",
            "portatil",
            "laptop",
            "computador",
        ],
        # robots.txt anuncia www.pcdiga.com/sitemap/sitemap.xml, mas esse URL
        # redireciona para o host público. O runner deve ir diretamente à origem
        # pública para não depender do redirecionamento do edge principal.
        "fetch_rewrites": {
            "https://www.pcdiga.com/sitemap/sitemap.xml":
                "https://public.pcdiga.com/sitemap/sitemap.xml",
        },
        "extra_routes": [
            {
                "label": "computadores_laptop_public",
                "url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop",
            },
            {
                "label": "lenovo_brand_public",
                "url": "https://www.pcdiga.com/portateis-lenovo",
            },
        ],
        # Rotas com filtros são explicitamente bloqueadas no robots da PCDiga e
        # só gastavam requests nas Actions sem produzir candidatos.
        "drop_route_markers": ["filter_by=", "hierarchicalmenu", "categories.level"],
    },
    "PcComponentes": {
        "version": "pccomponentes-public-sitemap-v1",
        "force_sitemap": True,
        "sitemap_probe_limit": 6,
        "max_sitemaps": 8,
        "sitemap_child_hints": [
            "product",
            "produto",
            "catalog",
            "portatil",
            "laptop",
            "computer",
        ],
        "extra_routes": [
            {
                "label": "portateis_public",
                "url": "https://www.pccomponentes.pt/categorias/portateis",
            }
        ],
    },
    "CHIP7": {
        "version": "chip7-public-sitemap-v1",
        "force_sitemap": True,
        "sitemap_probe_limit": 6,
        "max_sitemaps": 8,
        "sitemap_child_hints": [
            "product",
            "produto",
            "catalog",
            "portatil",
            "laptop",
            "computador",
        ],
        "extra_routes": [
            {
                "label": "landing_portateis_public",
                "url": "https://chip7.pt/landing/portateis",
            }
        ],
    },
    "Worten": {
        "version": "worten-index-hints-v3-reopen",
        "replace_versions": {"", "legacy", "worten-index-hints-v2"},
        "force_sitemap": True,
        "sitemap_probe_limit": 6,
        "max_sitemaps": 12,
        "sitemap_child_hints": [
            "informatica",
            "computador",
            "portatil",
            "laptop",
            "product",
            "produto",
            "catalog",
        ],
        "extra_routes": [],
    },
}


def _filter_routes(routes: list, policy: dict) -> list:
    markers = tuple(str(value).lower() for value in policy.get("drop_route_markers", []) if value)
    if not markers:
        return [dict(route) if isinstance(route, dict) else route for route in routes]
    out = []
    for route in routes:
        copied = dict(route) if isinstance(route, dict) else route
        url = str(copied.get("url") if isinstance(copied, dict) else copied or "").lower()
        if any(marker in url for marker in markers):
            continue
        out.append(copied)
    return out


def _recovery_cat(cat: dict) -> dict:
    """Aplica apenas rotas públicas de recuperação, sem alterar o cérebro."""
    store = str(cat.get("loja") or "")
    policy = _RECOVERY.get(store)
    if not policy:
        return cat

    out = dict(cat)
    configured_version = str(out.get("sitemap_strategy_version") or "")
    replace_versions = policy.get("replace_versions")
    if replace_versions is None or configured_version in replace_versions:
        out["sitemap_strategy_version"] = policy["version"]

    if policy.get("force_sitemap"):
        out["sitemap_enabled"] = True
    out["sitemap_probe_limit"] = max(
        int(out.get("sitemap_probe_limit", 0) or 0),
        int(policy.get("sitemap_probe_limit", 0) or 0),
    )
    out["max_sitemaps"] = max(
        int(out.get("max_sitemaps", 0) or 0),
        int(policy.get("max_sitemaps", 0) or 0),
    )

    configured_hints = [str(value) for value in out.get("sitemap_child_hints", []) if value]
    out["sitemap_child_hints"] = list(
        dict.fromkeys([*configured_hints, *policy.get("sitemap_child_hints", [])])
    )

    routes = _filter_routes(list(out.get("extra_discovery_urls", [])), policy)
    existing_urls = {
        str(route.get("url"))
        for route in routes
        if isinstance(route, dict) and route.get("url")
    }
    for route in policy.get("extra_routes", []):
        if str(route.get("url")) not in existing_urls:
            routes.append(dict(route))
            existing_urls.add(str(route.get("url")))
    out["extra_discovery_urls"] = routes
    return out


def _archive_and_reset_sitemap_access(bucket: dict, previous_version: str) -> None:
    """Reabre o método HTTP `sitemap` sem apagar aprendizagem global da loja."""
    contexts = bucket.setdefault("contexts", {})
    methods = bucket.setdefault("methods", {})
    previous_context = contexts.get("sitemap")
    previous_attempts = methods.get("sitemap")

    if previous_context is None and previous_attempts is None:
        return

    history = bucket.setdefault("access_context_history", {}).setdefault("sitemap", {})
    archived = history.setdefault(previous_version, {})
    if previous_context is not None:
        archived.setdefault("contexts", copy.deepcopy(previous_context))
    if previous_attempts is not None:
        archived.setdefault("method_attempts", copy.deepcopy(previous_attempts))

    contexts.pop("sitemap", None)
    methods.pop("sitemap", None)


def _rewrite_fetch_url(store: str | None, method: str, url: str) -> str:
    """Redireciona apenas URLs públicos conhecidos de discovery.

    Não é um bypass de páginas de produto: serve para eliminar redirects que o
    próprio robots.txt da loja anuncia e que falham nos runners cloud.
    """
    if method != "sitemap" or not store:
        return url
    policy = _RECOVERY.get(str(store), {})
    rewrites = policy.get("fetch_rewrites", {})
    return str(rewrites.get(str(url), url))


def install(tracker_module) -> None:
    """Recupera discovery público por loja e reabre estratégias de sitemap.

    A aprendizagem antiga é arquivada por versão. Quando a estratégia muda,
    apenas o contexto HTTP de sitemap é reaberto; a aprendizagem global, scoring,
    Value, tiers, matching, histórico de preços e NTFY ficam intactos.
    """
    if getattr(tracker_module, "_SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    base_adaptive_fetch = tracker_module.adaptive_fetch

    def adaptive_fetch(url: str, config: dict, timeout_s: float = 8.0, *, store=None, method="page"):
        effective_store = store or tracker_module.store_for_url(url, config)
        rewritten = _rewrite_fetch_url(effective_store, method, str(url))
        return base_adaptive_fetch(
            rewritten,
            config,
            timeout_s,
            store=effective_store,
            method=method,
        )

    def scan_store(cat: dict, config: dict, settings: dict):
        working_cat = _recovery_cat(cat)
        version = str(working_cat.get("sitemap_strategy_version") or "").strip()
        if not version:
            return base_scan_store(working_cat, config, settings)

        store = str(working_cat["loja"])
        bucket = tracker_module.bucket(store)
        discovery = bucket.setdefault("discovery", {})
        current = discovery.get("sitemap")
        current_version = (
            str(current.get("strategy_version") or "legacy")
            if isinstance(current, dict)
            else "legacy"
        )
        changed = current_version != version

        if changed:
            if isinstance(current, dict):
                history = bucket.setdefault("discovery_history", {}).setdefault("sitemap", {})
                history.setdefault(current_version, copy.deepcopy(current))
            discovery["sitemap"] = {}
            _archive_and_reset_sitemap_access(bucket, current_version)

        items, stat = base_scan_store(working_cat, config, settings)
        active = bucket.setdefault("discovery", {}).setdefault("sitemap", {})
        if isinstance(active, dict):
            active["strategy_version"] = version
        stat["sitemap_strategy_version"] = version
        stat["sitemap_strategy_reset"] = changed
        stat["sitemap_recovery_policy"] = store in _RECOVERY
        return items, stat

    tracker_module.adaptive_fetch = adaptive_fetch
    tracker_module.scan_store = scan_store
    tracker_module._SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED = True
