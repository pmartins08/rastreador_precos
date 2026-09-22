from __future__ import annotations

from typing import Any


VALID_TIERS = {"BRONZE", "PRATA", "OURO", "DIAMANTE"}
TIER_ORDER = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}
DEFAULT_DIAMOND_VALUE_THRESHOLD = 120.0


def normalize_tier(value: Any) -> str | None:
    """Normaliza apenas tiers conhecidos; valores desconhecidos ficam explícitos."""
    tier = str(value or "").strip().upper()
    return tier if tier in VALID_TIERS else None


def _score_or_none(value: Any) -> float | None:
    """Converte scores runtime (incluindo subclasses de float) num escalar estável.

    O cérebro pode transportar metadata em subclasses de ``float``. A Decision
    Truth Layer já recebe o tier calculado separadamente, por isso deve persistir
    apenas o valor numérico: isso mantém histórico/heartbeat JSON-safe e evita
    operações como ``deepcopy`` tentarem reconstruir tipos runtime especializados.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def force_diamond_for_value(
    value_score: Any,
    tier: Any,
    *,
    threshold: float = DEFAULT_DIAMOND_VALUE_THRESHOLD,
) -> str | None:
    """Aplica a regra de produto: Value estritamente superior a 120 é DIAMANTE.

    A função não tenta reconstruir a lógica completa de tier abaixo do limiar;
    essa responsabilidade continua no cérebro/GPU guard. Aqui existe apenas a
    invariância global que todas as superfícies de observabilidade devem respeitar.
    """
    normalized = normalize_tier(tier)
    numeric_value = _score_or_none(value_score)
    if numeric_value is None:
        return normalized
    if numeric_value > float(threshold):
        return "DIAMANTE"
    return normalized


def promotion_is_effective(
    *,
    promotion_confirmed: bool,
    promotion_discount_eur: Any,
    promotion_value_score: Any,
    promotion_tier: Any,
) -> bool:
    """Indica se a promoção pode substituir a visão base da decisão.

    A validade temporal/elegibilidade é verificada pelas camadas promocionais.
    Esta função exige que essa validação tenha chegado como confirmação explícita,
    exista desconto monetário positivo e haja Value/tier promocional utilizável.
    """
    if promotion_confirmed is not True:
        return False
    try:
        discount = float(promotion_discount_eur or 0.0)
    except (TypeError, ValueError):
        return False
    return (
        discount > 0.0
        and _score_or_none(promotion_value_score) is not None
        and normalize_tier(promotion_tier) is not None
    )


def decision_truth(
    *,
    base_value_score: Any,
    base_tier: Any,
    promotion_value_score: Any = None,
    promotion_tier: Any = None,
    promotion_confirmed: bool = False,
    promotion_discount_eur: Any = 0.0,
    diamond_threshold: float = DEFAULT_DIAMOND_VALUE_THRESHOLD,
) -> dict:
    """Devolve a fonte de verdade V9 para Value/tier base, promo e efetivo.

    O resultado preserva a decisão base para auditoria e produz uma única visão
    ``effective_*`` para ranking, resumo, heartbeat, logs e notificações. Scores
    são sempre escalares ``float``/``None`` para não deixar tipos runtime escapar
    para histórico ou observabilidade.
    """
    base_value = _score_or_none(base_value_score)
    promo_value = _score_or_none(promotion_value_score)

    base_normalized = force_diamond_for_value(
        base_value,
        base_tier,
        threshold=diamond_threshold,
    )

    promo_applied = promotion_is_effective(
        promotion_confirmed=promotion_confirmed,
        promotion_discount_eur=promotion_discount_eur,
        promotion_value_score=promo_value,
        promotion_tier=promotion_tier,
    )

    promo_normalized = None
    if promo_value is not None or promotion_tier is not None:
        promo_normalized = force_diamond_for_value(
            promo_value,
            promotion_tier,
            threshold=diamond_threshold,
        )

    effective_value = promo_value if promo_applied else base_value
    effective_tier = promo_normalized if promo_applied else base_normalized
    effective_tier = force_diamond_for_value(
        effective_value,
        effective_tier,
        threshold=diamond_threshold,
    )

    try:
        discount = float(promotion_discount_eur or 0.0)
    except (TypeError, ValueError):
        discount = 0.0

    return {
        "base_value_score": base_value,
        "base_tier": base_normalized,
        "promotion_value_score": promo_value,
        "promotion_tier": promo_normalized,
        "promotion_confirmed": bool(promotion_confirmed),
        "promotion_discount_eur": discount,
        "promotion_applied": promo_applied,
        "effective_value_score": effective_value,
        "effective_tier": effective_tier,
    }


def tier_meets_minimum(tier: Any, minimum: Any = "OURO") -> bool:
    current = TIER_ORDER.get(normalize_tier(tier) or "", 0)
    required = TIER_ORDER.get(normalize_tier(minimum) or "OURO", 3)
    return current >= required
