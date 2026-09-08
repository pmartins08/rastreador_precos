from __future__ import annotations

from contextvars import ContextVar


_PREMIUM_GPU_OK: ContextVar[bool] = ContextVar("premium_gpu_ok", default=True)


def premium_gpu_status(spec: dict, weights: dict) -> dict:
    """Decide se existe evidência de GPU suficiente para Ouro/Diamante.

    Não altera o Value nem rejeita o produto. Apenas impede que informação
    incompleta sobre a GPU seja compensada por CPU/preço/RAM ao atribuir tiers
    premium.
    """
    gpu_type = str(spec.get("gpu_tipo") or "desconhecida").lower()
    model = str(spec.get("gpu_modelo") or "").strip().lower() or None
    gpu_base = {str(key).lower(): value for key, value in (weights.get("gpu_base") or {}).items()}

    if gpu_type == "dedicada":
        if model and model in gpu_base:
            return {
                "confirmed": True,
                "status": "DEDICADA_MAPEADA",
                "model": model,
                "reason": None,
            }
        return {
            "confirmed": False,
            "status": "DEDICADA_NAO_MAPEADA",
            "model": model,
            "reason": "GPU dedicada detetada, mas o modelo exato não está mapeado pelo cérebro.",
        }

    if gpu_type == "integrada":
        return {
            "confirmed": False,
            "status": "INTEGRADA_SEM_CLASSE_PREMIUM",
            "model": model,
            "reason": "GPU integrada detetada, mas ainda não existe classe de performance premium explícita.",
        }

    return {
        "confirmed": False,
        "status": "GPU_DESCONHECIDA",
        "model": model,
        "reason": "GPU não identificada com confiança suficiente.",
    }


def install(scraper_module, tracker_module) -> None:
    """Limita Ouro/Diamante a produtos com GPU confirmada.

    O loop de scoring do tracker é sequencial após a fase concorrente de fetch.
    ContextVar mantém ainda assim a decisão isolada por contexto de execução.
    """
    if getattr(tracker_module, "_GPU_GUARD_INSTALLED", False):
        return

    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_tier_from_value = scraper_module.tier_from_value

    def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
        status = premium_gpu_status(spec, weights)
        _PREMIUM_GPU_OK.set(bool(status["confirmed"]))
        spec["gpu_tier_guard"] = status
        assessment = base_score_allow_unknown(spec, price, weights, settings)
        assessment["gpu_tier_guard"] = status
        return assessment

    def tier_from_value(value: float, settings: dict) -> str | None:
        tier = base_tier_from_value(value, settings)
        if tier in {"OURO", "DIAMANTE"} and not _PREMIUM_GPU_OK.get():
            # O Value bruto é preservado; só o rótulo de confiança é limitado.
            return "PRATA"
        return tier

    tracker_module.score_allow_unknown = score_allow_unknown
    scraper_module.tier_from_value = tier_from_value
    tracker_module._GPU_GUARD_INSTALLED = True
