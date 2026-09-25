from __future__ import annotations

import copy
from urllib.parse import unquote, urlparse


# Política de acesso por loja. Quando uma rota pública foi confirmada como
# permanentemente inútil no GitHub Actions, a produção deixa de a martelar e
# mantém apenas o canário barato da categoria. Isto liberta budget HTTP para as
# lojas que conseguem devolver dados reais.
_RECOVERY = {
    "PCDiga": {
        "version": "pcdiga-canary-v2",
        "disable_sitemap": True,
        "suppress_extra_routes": True,
        "disable_product_host_fallbacks": True,
    },
    "PcComponentes": {
        "version": "pccomponentes-canary-v2",
        "disable_sitemap": True,
        "suppress_extra_routes": True,
    },
    "CHIP7": {
        "version": "chip7-canary-v2",
        "disable_sitemap": True,
        "suppress_extra_routes": True,
    },
    "Worten": {
        # O sitemap é público e útil para descoberta, mas as fichas de produto
        # continuam 403 no GitHub Actions. Mantemos só um probe de ficha por run
        # para detetar recuperação, sem gastar dezenas de pedidos.
        "version": "worten-index-hints-v3-reopen",
        "replace_versions": {"", "legacy", "worten-index-hints-v2"},
        "force_sitemap": True,
        "sitemap_probe_limit_override": 1,
        "max_sitemaps_override": 3,
        "sitemap_child_hints": [
            "informatica",
            "computador",
            "portatil",
            "laptop",
            "product",
            "produto",
            "catalog",
        ],
    },
}

_WORTEN_SITEMAP_REJECT_MARKERS = (
    "acessorio",
    "adaptador",
    "bateria",
    "bolsa",
    "cabo",
    "capa",
    "carregador",
    "dock",
    "fonte-alimentacao",
    "mala",
    "mochila",
    "monitor",
    "pelicula",
    "rato",
    "suporte",
    "teclado",
    # O projeto acompanha equipamento novo normal; não gastar detalhe live em
    # páginas de outlet/caixa aberta que já seriam excluídas mais tarde.
    "outlet",
    "caixa-aberta",
    "grade-a",
    "grade-b",
    "grade-c",
    "recondicionado",
    "refurbished",
)


def _worten_sitemap_product_url(url: str) -> bool:
    """Aceita no sitemap Worten apenas URLs que parecem portáteis reais.

    O sitemap contém acessórios e monitores cujos slugs referem modelos de
    portáteis. A regra genérica via marca/família (TUF/LOQ/etc.) era demasiado
    permissiva e fazia gastar probes de produto em páginas sem interesse.
    """
    path = unquote(urlparse(str(url)).path).lower()
    if not path.startswith("/produtos/"):
        return False
    if any(marker in path for marker in _WORTEN_SITEMAP_REJECT_MARKERS):
        return False
    return any(marker in path for marker in ("portatil", "laptop", "macbook"))


def _recovery_cat(cat: dict) -> dict:
    """Aplica a política pública de acesso sem alterar o cérebro de scoring."""
    store = str(cat.get("loja") or "")
    policy = _RECOVERY.get(store)
    if not policy:
        return cat

    out = dict(cat)
    configured_version = str(out.get("sitemap_strategy_version") or "")
    replace_versions = policy.get("replace_versions")
    if replace_versions is None or configured_version in replace_versions:
        out["sitemap_strategy_version"] = policy["version"]

    if policy.get("disable_sitemap"):
        out["sitemap_enabled"] = False
    elif policy.get("force_sitemap"):
        out["sitemap_enabled"] = True

    if "sitemap_probe_limit_override" in policy:
        out["sitemap_probe_limit"] = int(policy["sitemap_probe_limit_override"])
    elif "sitemap_probe_limit" in policy:
        out["sitemap_probe_limit"] = max(
            int(out.get("sitemap_probe_limit", 0) or 0),
            int(policy.get("sitemap_probe_limit", 0) or 0),
        )

    if "max_sitemaps_override" in policy:
        out["max_sitemaps"] = int(policy["max_sitemaps_override"])
    elif "max_sitemaps" in policy:
        out["max_sitemaps"] = max(
            int(out.get("max_sitemaps", 0) or 0),
            int(policy.get("max_sitemaps", 0) or 0),
        )

    configured_hints = [str(value) for value in out.get("sitemap_child_hints", []) if value]
    out["sitemap_child_hints"] = list(
        dict.fromkeys([*configured_hints, *policy.get("sitemap_child_hints", [])])
    )

    if policy.get("suppress_extra_routes"):
        out["extra_discovery_urls"] = []
    else:
        routes = [
            dict(route) if isinstance(route, dict) else route
            for route in out.get("extra_discovery_urls", [])
        ]
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

    if policy.get("disable_product_host_fallbacks"):
        out.pop("product_fetch_host_fallbacks", None)
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
    """Gere mudanças de estratégia e filtros de acesso por loja.

    A aprendizagem antiga de sitemap é arquivada quando a estratégia muda. A
    aprendizagem global da loja é preservada. Rotas confirmadamente bloqueadas
    entram em modo canário barato; fontes públicas produtivas continuam ativas.
    Nada aqui altera Value, tiers, matching, preços ou regras de NTFY.
    """
    if getattr(tracker_module, "_STORE_ACCESS_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    base_product_url = getattr(tracker_module, "_looks_like_product_url", None)

    if callable(base_product_url):
        def looks_like_product_url(url: str, cat: dict) -> bool:
            if not base_product_url(url, cat):
                return False
            if str(cat.get("loja") or "") == "Worten":
                return _worten_sitemap_product_url(url)
            return True

        tracker_module._looks_like_product_url = looks_like_product_url

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
    tracker_module._STORE_ACCESS_GUARD_INSTALLED = True
