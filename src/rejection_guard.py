from __future__ import annotations

from contextvars import ContextVar


_CURRENT_REJECTION_REASON: ContextVar[str | None] = ContextVar(
    "rejection_reason", default=None
)


def rejection_reason(assessment: dict | None) -> str:
    """Converte mensagens humanas de rejeição em buckets estáveis de telemetria."""
    if not isinstance(assessment, dict):
        return "score_rejected_other"

    alerts = " | ".join(str(value or "") for value in assessment.get("alertas", []))
    text = alerts.lower()
    if "fallback histórico" in text or "fallback historico" in text:
        return "live_price_confirmation_required"
    if "teclado não é português" in text or "teclado nao e portugues" in text:
        return "keyboard_non_pt"
    if "teclado pt não confirmado" in text or "teclado pt nao confirmado" in text:
        return "keyboard_unconfirmed"
    if "8gb ram" in text:
        return "ram_8gb"
    if "limite de peso" in text or ">2.8kg" in text:
        return "overweight"
    return "score_rejected_other"


class RejectionCounter(int):
    """Inteiro JSON-safe que acrescenta motivos sem alterar tracker.main."""

    def __new__(cls, value: int = 0, reasons: dict[str, int] | None = None):
        obj = int.__new__(cls, int(value))
        obj.reasons = reasons if reasons is not None else {}
        return obj

    def __add__(self, other):
        increment = int(other)
        if increment > 0:
            reason = _CURRENT_REJECTION_REASON.get()
            # No loop atual, o único `rejeitados += 1` que não passa antes por
            # plausibilidade ou score é o preço fora do intervalo permitido.
            bucket = reason or "price_out_of_range"
            self.reasons[bucket] = self.reasons.get(bucket, 0) + increment
        _CURRENT_REJECTION_REASON.set(None)
        return RejectionCounter(int(self) + increment, self.reasons)

    def __radd__(self, other):
        return self.__add__(other)


def install(scraper_module, tracker_module) -> None:
    """Adiciona motivos de rejeição por loja sem alterar a lógica de decisão."""
    if getattr(tracker_module, "_REJECTION_GUARD_INSTALLED", False):
        return

    base_empty_store_stats = tracker_module._empty_store_stats
    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_price_plausible = scraper_module.price_is_plausible_for_title

    def empty_store_stats() -> dict:
        stats = base_empty_store_stats()
        reasons: dict[str, int] = {}
        stats["rejection_reasons"] = reasons
        stats["rejeitados"] = RejectionCounter(stats.get("rejeitados", 0), reasons)
        return stats

    def score_allow_unknown(spec, price, weights, settings):
        assessment = base_score_allow_unknown(spec, price, weights, settings)
        if isinstance(assessment, dict) and assessment.get("status") != "ACEITE":
            _CURRENT_REJECTION_REASON.set(rejection_reason(assessment))
        else:
            _CURRENT_REJECTION_REASON.set(None)
        return assessment

    def price_is_plausible_for_title(title, price):
        plausible = bool(base_price_plausible(title, price))
        _CURRENT_REJECTION_REASON.set(None if plausible else "price_implausible")
        return plausible

    tracker_module._empty_store_stats = empty_store_stats
    tracker_module.score_allow_unknown = score_allow_unknown
    scraper_module.price_is_plausible_for_title = price_is_plausible_for_title
    tracker_module._REJECTION_GUARD_INSTALLED = True
