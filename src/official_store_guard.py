from __future__ import annotations

from pathlib import Path

from price_tracker.sources import asus


def install(tracker_module) -> None:
    """Mantém fontes oficiais opt-in sem tocar no cérebro nem gastar quota por defeito."""
    if getattr(tracker_module, "_OFFICIAL_STORE_GUARD_INSTALLED", False):
        return

    base_load_json = tracker_module.load_json

    def load_json(path):
        data = base_load_json(path)
        try:
            is_config = Path(path).resolve() == Path(tracker_module.CONFIG_PATH).resolve()
        except (TypeError, OSError, ValueError):
            is_config = False
        if not is_config or not isinstance(data, dict):
            return data

        config = dict(data)
        settings = dict(config.get("settings") or {})
        # As fontes oficiais experimentais só ficam ativas quando são
        # explicitamente ligadas. Evita gastar pedidos em páginas que hoje
        # devolvem 403/shells JS no runner de produção.
        settings.setdefault("manufacturer_enrichment_enabled", False)
        settings.setdefault("manufacturer_enrichment_max_per_run", 0)
        settings.setdefault("manufacturer_enrichment_max_per_brand", 0)
        settings.setdefault("asus_store_enabled", False)
        config["settings"] = settings

        categories = [dict(row) for row in (config.get("category_urls") or [])]
        if (
            settings.get("asus_store_enabled") is True
            and not any(str(row.get("loja")) == asus.STORE_NAME for row in categories)
        ):
            categories.append(asus.store_config())
        config["category_urls"] = categories
        return config

    tracker_module.load_json = load_json
    tracker_module._OFFICIAL_STORE_GUARD_INSTALLED = True
