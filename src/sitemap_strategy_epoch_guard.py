from __future__ import annotations

import copy


# Recuperação conservadora das lojas que o GitHub Actions vê frequentemente
# bloqueadas na categoria principal. Só reabre rotas públicas/sitemap; não tenta
# contornar autenticação, checkout ou endpoints privados.
_RECOVERY = {
    "PCDiga": {
        "version": "pcdiga-public-sitemap-v1",
        "force_sitemap": True,
        "sitemap_probe_limit": 8,
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
                "label": "computadores_laptop_public",
                "url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop",
            }
        ],
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
        # A configuração V9 beta.2 tinha v2, mas o contexto HTTP antigo já tinha
        # entrado em probe. Esta revisão força uma única reabertura controlada.
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

    routes = [dict(route) if isinstance(route, dict) else route for route in out.get("extra_discovery_urls", [])]
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
    """Reabre o método HTTP `sitemap` sem apagar aprendizagem global da loja.

    `access_mode()` decide entrar em probe através de `contexts['sitemap']`.
    Limpar apenas as estatísticas de discovery não chega: uma estratégia nova
    continuaria bloqueada antes do primeiro pedido. Arquivamos o contexto antigo
    e zeramos apenas o método sitemap; perfis e aprendizagem das restantes rotas
    permanecem intactos.
    """
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
    """Reabre sitemap uma vez quando a estratégia configurada muda.

    A aprendizagem antiga é arquivada por versão em `discovery_history`; apenas
    o estado ativo de `sitemap` começa fresco para a estratégia nova. Também é
    reiniciado o contexto HTTP específico de sitemap, porque é esse estado que
    controla o modo `probe`. A aprendizagem global da loja não é apagada.

    Para PCDiga, PcComponentes, CHIP7 e Worten aplica ainda uma política mínima
    de recuperação por rotas públicas. Isto não altera scoring, Value, tiers,
    matching, histórico de preços ou regras de NTFY.
    """
    if getattr(tracker_module, "_SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED", False):
        return

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
