from __future__ import annotations

import re


# Escala conservadora compatível com gpu_base do cérebro:
# RTX 2050 = 30, RTX 3050 = 38.
# As iGPUs variam bastante com TDP/memória; os valores abaixo representam uma
# classe relativa, não um benchmark absoluto nem uma garantia de FPS.
IGPU_BASE = {
    "intel arc graphics 140v": 33.0,
    "radeon 890m": 31.0,
    "radeon 880m": 29.0,
    "intel arc graphics 130v": 28.0,
    "radeon 780m": 27.0,
    "radeon 860m": 23.0,
    "radeon 680m": 22.0,
    "radeon 760m": 21.0,
}

IGPU_ALIASES = {
    "intel arc graphics 140v": (
        "intel arc graphics 140v",
        "intel arc graphics 140 v",
        "intel arc 140v",
        "intel arc 140 v",
        "arc graphics 140v",
        "arc graphics 140 v",
        "arc 140v",
        "arc 140 v",
    ),
    "intel arc graphics 130v": (
        "intel arc graphics 130v",
        "intel arc graphics 130 v",
        "intel arc 130v",
        "intel arc 130 v",
        "arc graphics 130v",
        "arc graphics 130 v",
        "arc 130v",
        "arc 130 v",
    ),
    "radeon 890m": ("radeon 890m", "radeon 890 m"),
    "radeon 880m": ("radeon 880m", "radeon 880 m"),
    "radeon 860m": ("radeon 860m", "radeon 860 m"),
    "radeon 780m": ("radeon 780m", "radeon 780 m"),
    "radeon 760m": ("radeon 760m", "radeon 760 m"),
    "radeon 680m": ("radeon 680m", "radeon 680 m"),
}


class TierAwareValue(float):
    """Float normal com metadado local para a decisão de tier."""

    def __new__(cls, value: float, *, premium_gpu_ok: bool):
        obj = float.__new__(cls, value)
        obj.premium_gpu_ok = bool(premium_gpu_ok)
        return obj


def _contains_alias(text: str, alias: str) -> bool:
    pattern = r"(?<![a-z0-9])" + r"[\s._-]*".join(
        re.escape(part) for part in alias.split()
    ) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def identify_igpu(text: object, scraper_module=None) -> str | None:
    normalized = (
        scraper_module.norm(text)
        if scraper_module is not None
        else re.sub(r"\s+", " ", str(text or "").lower()).strip()
    )
    for model, aliases in IGPU_ALIASES.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            return model
    return None


def igpu_score(model: object) -> float | None:
    return IGPU_BASE.get(str(model or "").strip().lower())


def premium_gpu_status(spec: dict, weights: dict) -> dict:
    """Decide se existe evidência de GPU suficiente para Ouro/Diamante."""
    gpu_type = str(spec.get("gpu_tipo") or "desconhecida").lower()
    model = str(spec.get("gpu_modelo") or "").strip().lower() or None
    gpu_base = {str(key).lower(): value for key, value in (weights.get("gpu_base") or {}).items()}

    if gpu_type == "dedicada":
        if model and model in gpu_base:
            return {
                "confirmed": True,
                "status": "DEDICADA_MAPEADA",
                "model": model,
                "performance_class": float(gpu_base[model]),
                "reason": None,
            }
        return {
            "confirmed": False,
            "status": "DEDICADA_NAO_MAPEADA",
            "model": model,
            "performance_class": None,
            "reason": "GPU dedicada detetada, mas o modelo exato não está mapeado pelo cérebro.",
        }

    if gpu_type == "integrada":
        score_value = igpu_score(model)
        if model and score_value is not None:
            return {
                "confirmed": True,
                "status": "INTEGRADA_MAPEADA",
                "model": model,
                "performance_class": score_value,
                "reason": None,
            }
        return {
            "confirmed": False,
            "status": "INTEGRADA_NAO_MAPEADA",
            "model": model,
            "performance_class": None,
            "reason": "GPU integrada detetada, mas sem modelo/classe de performance explícita.",
        }

    return {
        "confirmed": False,
        "status": "GPU_DESCONHECIDA",
        "model": model,
        "performance_class": None,
        "reason": "GPU não identificada com confiança suficiente.",
    }


def _apply_igpu_scoring(
    assessment: dict,
    spec: dict,
    price: float,
    settings: dict,
    scraper_module,
) -> dict:
    """Substitui apenas o fallback integrado=15 pela classe explícita.

    O cérebro V8 continua intacto. Como Gaming usa GPU a 65% e o resultado
    Gaming pesa 25% no score final, o delta é determinístico e auditável.
    """
    if assessment.get("status") != "ACEITE" or spec.get("gpu_tipo") != "integrada":
        return assessment

    target = igpu_score(spec.get("gpu_modelo"))
    if target is None:
        return assessment

    old_gpu = 15.0
    delta_gpu = float(target) - old_gpu
    delta_gaming = delta_gpu * 0.65
    delta_final = delta_gaming * 0.25
    confidence, _ = scraper_module.quality(spec)
    confidence_multiplier = 0.85 + 0.15 * confidence
    delta_ranking = delta_final * confidence_multiplier

    assessment["score_final"] = round(float(assessment["score_final"]) + delta_final, 1)
    assessment["score_ranking"] = round(
        float(assessment["score_ranking"]) + delta_ranking, 1
    )
    details = assessment.setdefault("detalhes", {})
    details["Gaming"] = round(float(details.get("Gaming", 0.0)) + delta_gaming, 1)

    bonus = float(assessment.get("exceptional_deal_bonus", 0.0) or 0.0)
    original_value_score = getattr(scraper_module, "_PRICE_GUARD_ORIGINALS", {}).get(
        "value_score", scraper_module.value_score
    )
    base_value = float(
        original_value_score(assessment["score_ranking"], float(price), settings)
    )
    assessment["value_score_sem_bonus"] = round(base_value, 1)
    assessment["value_score"] = round(max(0.0, min(150.0, base_value + bonus)), 1)
    assessment["igpu_scoring"] = {
        "model": spec.get("gpu_modelo"),
        "old_generic_gpu_score": old_gpu,
        "mapped_gpu_score": float(target),
        "delta_final": round(delta_final, 3),
    }
    return assessment


def install(scraper_module, tracker_module) -> None:
    """Confirma modelos de GPU e protege tiers premium por produto."""
    if getattr(tracker_module, "_GPU_GUARD_INSTALLED", False):
        return

    base_gpus = scraper_module.gpus
    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_tier_from_value = scraper_module.tier_from_value

    def gpus(text: str):
        models, gpu_type, model = base_gpus(text)
        if gpu_type == "dedicada":
            return models, gpu_type, model
        mapped = identify_igpu(text, scraper_module)
        if mapped:
            return [mapped], "integrada", mapped
        return models, gpu_type, model

    # Instalar o parser primeiro: scraper.specs()/extract() resolvem `gpus`
    # dinamicamente no módulo e passam a transportar o modelo integrado exato.
    scraper_module.gpus = gpus

    def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
        status = premium_gpu_status(spec, weights)
        spec["gpu_tier_guard"] = status
        assessment = base_score_allow_unknown(spec, price, weights, settings)
        assessment = _apply_igpu_scoring(
            assessment, spec, price, settings, scraper_module
        )
        assessment["gpu_tier_guard"] = status
        if assessment.get("value_score") is not None:
            raw_value = float(assessment["value_score"])
            assessment["value_score"] = TierAwareValue(
                raw_value, premium_gpu_ok=bool(status["confirmed"])
            )
        return assessment

    def tier_from_value(value: float, settings: dict) -> str | None:
        tier = base_tier_from_value(float(value), settings)
        premium_gpu_ok = getattr(value, "premium_gpu_ok", True)
        if tier in {"OURO", "DIAMANTE"} and not premium_gpu_ok:
            return "PRATA"
        return tier

    tracker_module.score_allow_unknown = score_allow_unknown
    scraper_module.tier_from_value = tier_from_value
    tracker_module._GPU_GUARD_INSTALLED = True
