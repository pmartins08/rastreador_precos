from __future__ import annotations


VERSION = "8.8.5"


def ram_longevity_target(ram_gb: int | float | None, expandable: bool) -> float | None:
    """Política de longevidade para capacidades intermédias de RAM.

    O cérebro V8 trata corretamente 16 GB e >=32 GB, mas qualquer capacidade
    entre 16 e 32 GB (hoje sobretudo 24 GB) caía no ramo de 40 pontos. Esta
    função corrige apenas essa lacuna, sem alterar os restantes pesos.
    """
    if ram_gb is None:
        return None
    ram = float(ram_gb)
    if 16.0 < ram < 32.0:
        return 95.0 if expandable else 85.0
    return None


def install(scraper_module) -> None:
    """Aplica correções de scoring compatíveis por cima do cérebro V8."""
    if getattr(scraper_module, "_BRAIN_GUARD_INSTALLED", False):
        return

    original_score = scraper_module.score
    scraper_module._BRAIN_GUARD_ORIGINAL_SCORE = original_score

    def score(spec: dict, price_value: float, weights: dict, settings: dict) -> dict:
        result = original_score(spec, price_value, weights, settings)
        if result.get("status") != "ACEITE":
            return result

        target = ram_longevity_target(
            spec.get("ram_gb"), bool(spec.get("ram_expansivel"))
        )
        if target is None:
            return result

        old_ram_long = 40.0
        delta_ram_long = target - old_ram_long
        delta_longevity = delta_ram_long * 0.35
        delta_final = delta_longevity * 0.15
        confidence, _quality_label = scraper_module.quality(spec)
        confidence_multiplier = 0.85 + 0.15 * confidence
        delta_ranking = delta_final * confidence_multiplier

        details = result.setdefault("detalhes", {})
        old_longevity = float(details.get("Longevidade", 0.0))
        details["Longevidade"] = round(old_longevity + delta_longevity, 1)

        result["score_final"] = round(float(result["score_final"]) + delta_final, 1)
        result["score_ranking"] = round(
            float(result["score_ranking"]) + delta_ranking, 1
        )
        result["value_score"] = scraper_module.value_score(
            result["score_ranking"], price_value, settings
        )
        result.setdefault("brain_corrections", []).append(
            {
                "type": "ram_longevity_intermediate",
                "ram_gb": spec.get("ram_gb"),
                "expandable": bool(spec.get("ram_expansivel")),
                "old_ram_longevity": old_ram_long,
                "new_ram_longevity": target,
            }
        )
        return result

    scraper_module.score = score
    scraper_module._BRAIN_GUARD_INSTALLED = True


def uninstall(scraper_module) -> None:
    original = getattr(scraper_module, "_BRAIN_GUARD_ORIGINAL_SCORE", None)
    if original is not None:
        scraper_module.score = original
        delattr(scraper_module, "_BRAIN_GUARD_ORIGINAL_SCORE")
    scraper_module._BRAIN_GUARD_INSTALLED = False
