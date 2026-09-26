from __future__ import annotations

import copy

from search_index_guard import install as install_search_index_guard


# Recuperação conservadora das lojas que o GitHub Actions vê frequentemente
# bloqueadas na categoria principal. Só usa fontes públicas; não tenta contornar
# desafios, autenticação, checkout ou endpoints privados.
_RECOVERY = {
    "PCDiga": {
        # PCDiga: Brave encontra preços e DDG acrescenta URLs; a pesquisa 5070
        # sem filtro de RAM aumenta cobertura sem custo adicional de queries.
        "version": "pcdiga-cloud-edge-v3",
        "sitemap_enabled": False,
        "replace_extra_routes": [],
        "search_index_enabled": True,
        "search_index_queries": ["portatil RTX 5070", "portatil RTX 5060 32GB"],
        "search_index_engines": ["brave", "duckduckgo"],
        "search_index_max_queries": 2,
        "search_index_trigger_below": 6,
    },
    "PcComponentes": {
        # PcComponentes: Brave é a fonte com rendimento consistente. Separamos
        # 24 GB e 32 GB na RTX 5070 para recuperar OMEN/LOQ 24 GB sem tornar a
        # pesquisa demasiado genérica; preço continua sempre INDEX_ONLY.
        "version": "pccomponentes-awin-v2",
        "sitemap_enabled": False,
        "replace_extra_routes": [],
        "search_index_enabled": True,
        "search_index_queries": [
            "portatil RTX 5070 32GB",
            "portatil RTX 5070 24GB",
            "portatil RTX 5060 32GB",
        ],
        "search_index_engines": ["brave"],
        "search_index_max_queries": 3,
        "search_index_trigger_below": 6,
    },
    "CHIP7": {
        # Diagnóstico limpo em GitHub Actions (2026-09-25): categoria normal,
        # variante index.php, gaming, robots.txt e sitemap devolvem Cloudflare
        # 403. Mantemos apenas a categoria base como sonda barata e paramos as
        # restantes rotas até surgir uma fonte pública estruturada/autorizada.
        "version": "chip7-cloud-edge-v2",
        "sitemap_enabled": False,
        "replace_extra_routes": [],
    },
    "Worten": {
        "version": "worten-index-hints-v3-reopen",
        "replace_versions": {"", "legacy", "worten-index-hints-v2"},
        "sitemap_enabled": True,
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


def _copy_routes(routes: list) -> list:
    return [dict(route) if isinstance(route, dict) else route for route in routes]


def _recovery_cat(cat: dict) -> dict:
    """Aplica apenas política pública de acesso, sem alterar o cérebro."""
    store = str(cat.get("loja") or "")
    policy = _RECOVERY.get(store)
    if not policy:
        return cat

    out = dict(cat)
    configured_version = str(out.get("sitemap_strategy_version") or "")
    replace_versions = policy.get("replace_versions")
    if replace_versions is None or configured_version in replace_versions:
        out["sitemap_strategy_version"] = policy["version"]

    if "sitemap_enabled" in policy:
        out["sitemap_enabled"] = bool(policy["sitemap_enabled"])
    if "sitemap_probe_limit" in policy:
        out["sitemap_probe_limit"] = max(
            int(out.get("sitemap_probe_limit", 0) or 0),
            int(policy.get("sitemap_probe_limit", 0) or 0),
        )
    if "max_sitemaps" in policy:
        out["max_sitemaps"] = max(
            int(out.get("max_sitemaps", 0) or 0),
            int(policy.get("max_sitemaps", 0) or 0),
        )

    for key in (
        "search_index_enabled",
        "search_index_queries",
        "search_index_engines",
        "search_index_max_queries",
        "search_index_trigger_below",
    ):
        if key in policy:
            out[key] = copy.deepcopy(policy[key])

    configured_hints = [str(value) for value in out.get("sitemap_child_hints", []) if value]
    out["sitemap_child_hints"] = list(
        dict.fromkeys([*configured_hints, *policy.get("sitemap_child_hints", [])])
    )

    if "replace_extra_routes" in policy:
        routes = _copy_routes(list(policy.get("replace_extra_routes", [])))
    else:
        routes = _copy_routes(list(out.get("extra_discovery_urls", [])))
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


def install(tracker_module) -> None:
    """Aplica política de discovery público e epochs de sitemap por loja.

    Quando a estratégia muda, apenas o contexto HTTP de sitemap é reaberto. A
    aprendizagem global, scoring, Value, tiers, matching, histórico de preços e
    NTFY ficam intactos. Search-index é composto antes desta camada para receber
    a configuração de recuperação já normalizada por loja.
    """
    if getattr(tracker_module, "_SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED", False):
        return

    # O runtime real tem estes componentes. A condição mantém este guard
    # testável/independente quando usado com módulos mínimos nos testes unitários.
    required = (
        "scraper", "requests", "consume_request", "budget_available", "headers",
        "record_learning", "record_discovery_yield", "LOGGER",
    )
    if all(hasattr(tracker_module, name) for name in required):
        install_search_index_guard(tracker_module)
    base_scan_store = tracker_module.scan_store

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

    tracker_module.scan_store = scan_store
    tracker_module._SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED = True
