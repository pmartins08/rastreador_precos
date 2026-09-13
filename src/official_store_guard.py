from __future__ import annotations

from pathlib import Path

from price_tracker.sources import asus


# Calibração histórica de 2026-09-13: 283 identidades distintas, p99 do
# tier_score=114.329, máximo=121.227. Em 118 apenas 2/283 (~0,7%) seriam
# DIAMANTE; em 125 nenhuma oferta histórica conseguiria atingir o tier.
CALIBRATED_DIAMOND_MIN = 118.0


def install(tracker_module) -> None:
    """Normaliza política runtime e mantém fontes oficiais experimentais opt-in."""
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

        # O Value continua inalterado. Só calibramos a fronteira do tier final,
        # que já inclui o multiplicador Gaming. 118 mantém DIAMANTE raro e
        # atingível em vez do antigo 125, que foi inalcançável no histórico.
        settings["diamante_value_min"] = CALIBRATED_DIAMOND_MIN

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
