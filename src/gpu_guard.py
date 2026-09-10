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
        "intel arc graphics 140v", "intel arc graphics 140 v",
        "intel arc graphics de 140v", "intel arc graphics de 140 v",
        "intel arc 140v", "intel arc 140 v",
        "intel arc de 140v", "intel arc de 140 v",
        "arc graphics 140v", "arc graphics 140 v",
        "arc graphics de 140v", "arc graphics de 140 v",
        "arc 140v", "arc 140 v", "arc de 140v", "arc de 140 v",
    ),
    "intel arc graphics 130v": (
        "intel arc graphics 130v", "intel arc graphics 130 v",
        "intel arc graphics de 130v", "intel arc graphics de 130 v",
        "intel arc 130v", "intel arc 130 v",
        "intel arc de 130v", "intel arc de 130 v",
        "arc graphics 130v", "arc graphics 130 v",
        "arc graphics de 130v", "arc graphics de 130 v",
        "arc 130v", "arc 130 v", "arc de 130v", "arc de 130 v",
    ),
    "radeon 890m": ("radeon 890m", "radeon 890 m"),
    "radeon 880m": ("radeon 880m", "radeon 880 m"),
    "radeon 860m": ("radeon 860m", "radeon 860 m"),
    "radeon 780m": ("radeon 780m", "radeon 780 m"),
    "radeon 760m": ("radeon 760m", "radeon 760 m"),
    "radeon 680m": ("radeon 680m", "radeon 680 m"),
}


def tier_influence(value: float, gaming_score: float) -> dict:
    """Calcula a influência contínua de Gaming no tier sem alterar o Value."""
    raw_value = float(value)
    gaming = max(0.0, min(100.0, float(gaming_score)))
    multiplier = 0.85 + 0.15 * (gaming / 100.0)
    return {
        "value": raw_value,
        "gaming_score": gaming,
        "multiplier": multiplier,
        "tier_score": raw_value * multiplier,
    }


class TierAwareValue(float):
    """Float normal que transporta apenas o tier_score contínuo da GPU/Gaming."""

    def __new__(cls, value: float, *, gaming_score: float):
        obj = float.__new__(cls, value)
        influence = tier_influence(float(value), float(gaming_score))
        obj.gaming_score = influence["gaming_score"]
        obj.tier_multiplier = influence["multiplier"]
        obj.tier_score = influence["tier_score"]
        return obj


def _contains_alias(text: str, alias: str) -> bool:
    pattern = r"(?<![a-z0-9])" + r"[\s._-]*".join(
        re.escape(part) for part in alias.split()
    ) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def identify_igpu(text: object, scraper_module=None) -> str | None:
    # NFKD decompõe ™ em "TM" (ex.: Arc™ -> ArcTM), o que destrói o token
    # "arc" usado nas aliases. Removemos marcas comerciais antes de qualquer
    # normalização para preservar apenas o nome técnico relevante.
    raw = re.sub(r"[™®©℠]", " ", str(text or ""))
    normalized = (
        scraper_module.norm(raw)
        if scraper_module is not None
        else re.sub(r"\s+", " ", raw.lower()).strip()
    )
    # Retailers usam ainda pontuação no meio do nome. Para matching do modelo
    # só nos interessa a sequência alfanumérica.
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    for model, aliases in IGPU_ALIASES.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            return model
    return None


def igpu_score(model: object) -> float | None:
    return IGPU_BASE.get(str(model or "").strip().lower())


def _upgrade_spec_igpu(spec: dict, scraper_module, title: object = None) -> str | None:
    """Promove GPU genérica/desconhecida para iGPU explícita usando evidência disponível."""
    if not isinstance(spec, dict) or str(spec.get("gpu_tipo") or "").lower() == "dedicada":
        return None
    existing = str(spec.get("gpu_modelo") or "").strip().lower()
    if existing in IGPU_BASE:
        spec["gpu_tipo"] = "integrada"
        return existing

    evidence = spec.get("evidencias") if isinstance(spec.get("evidencias"), dict) else {}
    text_parts = [title]
    text_parts.extend(evidence.values())
    mapped = identify_igpu(" ".join(str(value or "") for value in text_parts), scraper_module)
    if mapped:
        spec["gpu_tipo"] = "integrada"
        spec["gpu_modelo"] = mapped
        detected = list(spec.get("gpu_modelos_detectados") or [])
        if mapped not in detected:
            detected.append(mapped)
        spec["gpu_modelos_detectados"] = detected
        spec.setdefault("fontes", {}).setdefault("gpu_modelo", "gpu_guard_v887")
    return mapped


def premium_gpu_status(spec: dict, weights: dict) -> dict:
    """Descreve a qualidade do reconhecimento GPU; não impõe um teto de tier."""
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
    """Substitui apenas o fallback integrada=15 pela classe explícita."""
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
    """Confirma modelos de GPU e aplica influência contínua de Gaming ao tier."""
    if getattr(tracker_module, "_GPU_GUARD_INSTALLED", False):
        return

    base_gpus = scraper_module.gpus
    base_select_with_cache = tracker_module.select_with_cache
    base_apply_market_evidence = getattr(
        tracker_module, "apply_exact_market_price_evidence", None
    )
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

    scraper_module.gpus = gpus

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        # Migração antecipada e sem requests: melhora pré-ranking e cache quando o
        # título atual já contém o modelo da iGPU.
        for item in items:
            title = item.get("titulo")
            inline = item.get("specs")
            if isinstance(inline, dict):
                _upgrade_spec_igpu(inline, scraper_module, title)

            cached = spec_cache.get(item.get("url")) if isinstance(spec_cache, dict) else None
            if isinstance(cached, dict):
                _upgrade_spec_igpu(cached, scraper_module, title)
        return base_select_with_cache(items, spec_cache, max_items, weights, settings)

    def apply_market_evidence(records: list[dict], settings: dict) -> dict:
        # Ponto autoritativo: aqui cada item já está emparelhado com a spec exata
        # que será pontuada. Corrige cache/live/refresh antes de mercado e scoring.
        for record in records:
            if not isinstance(record, dict):
                continue
            item = record.get("item") if isinstance(record.get("item"), dict) else {}
            spec = record.get("spec")
            if isinstance(spec, dict):
                _upgrade_spec_igpu(spec, scraper_module, item.get("titulo"))
        return base_apply_market_evidence(records, settings)

    def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
        _upgrade_spec_igpu(spec, scraper_module)
        status = premium_gpu_status(spec, weights)
        spec["gpu_tier_guard"] = status
        assessment = base_score_allow_unknown(spec, price, weights, settings)
        assessment = _apply_igpu_scoring(
            assessment, spec, price, settings, scraper_module
        )
        assessment["gpu_tier_guard"] = status

        if assessment.get("value_score") is not None:
            raw_value = float(assessment["value_score"])
            details = assessment.get("detalhes")
            gaming_score = (
                float(details.get("Gaming", 0.0) or 0.0)
                if isinstance(details, dict)
                else 0.0
            )
            wrapped_value = TierAwareValue(raw_value, gaming_score=gaming_score)
            assessment["value_score"] = wrapped_value
            assessment["gpu_tier_influence"] = {
                "raw_value": round(raw_value, 3),
                "gaming_score": round(wrapped_value.gaming_score, 3),
                "multiplier": round(wrapped_value.tier_multiplier, 6),
                "tier_score": round(wrapped_value.tier_score, 3),
            }
        return assessment

    def tier_from_value(value: float, settings: dict) -> str | None:
        adjusted = getattr(value, "tier_score", None)
        return base_tier_from_value(
            float(adjusted) if adjusted is not None else float(value),
            settings,
        )

    tracker_module.select_with_cache = select_with_cache
    if callable(base_apply_market_evidence):
        tracker_module.apply_exact_market_price_evidence = apply_market_evidence
    tracker_module.score_allow_unknown = score_allow_unknown
    scraper_module.tier_from_value = tier_from_value
    tracker_module._GPU_GUARD_INSTALLED = True
