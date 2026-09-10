from __future__ import annotations

import copy


def install(tracker_module) -> None:
    """Reabre sitemap uma vez quando a estratégia configurada muda.

    A aprendizagem antiga é arquivada por versão em `discovery_history`; apenas
    o estado ativo de `sitemap` começa fresco para a estratégia nova. Sem a chave
    `sitemap_strategy_version` esta camada é um no-op.
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
        current_version = str(current.get("strategy_version") or "legacy") if isinstance(current, dict) else "legacy"

        if isinstance(current, dict) and current_version != version:
            history = bucket.setdefault("discovery_history", {}).setdefault("sitemap", {})
            history.setdefault(current_version, copy.deepcopy(current))
            discovery["sitemap"] = {}

        items, stat = base_scan_store(cat, config, settings)
        active = bucket.setdefault("discovery", {}).setdefault("sitemap", {})
        if isinstance(active, dict):
            active["strategy_version"] = version
        stat["sitemap_strategy_version"] = version
        stat["sitemap_strategy_reset"] = current_version != version
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED = True
