from __future__ import annotations

import copy


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

    Sem a chave `sitemap_strategy_version` esta camada é um no-op.
    """
    if getattr(tracker_module, "_SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store

    def scan_store(cat: dict, config: dict, settings: dict):
        version = str(cat.get("sitemap_strategy_version") or "").strip()
        if not version:
            return base_scan_store(cat, config, settings)

        store = str(cat["loja"])
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

        items, stat = base_scan_store(cat, config, settings)
        active = bucket.setdefault("discovery", {}).setdefault("sitemap", {})
        if isinstance(active, dict):
            active["strategy_version"] = version
        stat["sitemap_strategy_version"] = version
        stat["sitemap_strategy_reset"] = changed
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED = True
