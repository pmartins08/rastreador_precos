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
            bucket = reason or "price_out_of_range"
            self.reasons[bucket] = self.reasons.get(bucket, 0) + increment
        _CURRENT_REJECTION_REASON.set(None)
        return RejectionCounter(int(self) + increment, self.reasons)

    def __radd__(self, other):
        return self.__add__(other)


def _tier_rank(value: object) -> int:
    return {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}.get(
        str(value or "").upper(), 0
    )


def _latest_offer(history: dict, key: str) -> dict:
    offers = history.get("offers", {}) if isinstance(history, dict) else {}
    entries = offers.get(key, []) if isinstance(offers, dict) else []
    if isinstance(entries, list) and entries and isinstance(entries[-1], dict):
        return entries[-1]
    return {}


def _notification_reason(
    *, sent: bool, item: dict, assessment: dict, tier: str | None,
    prior: dict | None, latest: dict, settings: dict, suppressed_low_tier: bool,
) -> tuple[str, str | None, float | None, float | None]:
    effective_tier = latest.get("promotion_tier") or tier
    try:
        effective_value = float(
            latest.get("promotion_value_score")
            if latest.get("promotion_value_score") is not None
            else assessment.get("value_score")
        )
    except (TypeError, ValueError):
        effective_value = None
    try:
        effective_price = float(
            latest.get("promotion_checkout_price")
            if latest.get("promotion_checkout_price") is not None
            else item.get("preco")
        )
    except (TypeError, ValueError):
        effective_price = None

    if sent:
        return "sent", effective_tier, effective_value, effective_price
    if item.get("stock") is False:
        return "out_of_stock", effective_tier, effective_value, effective_price
    if assessment.get("status") != "ACEITE":
        return "score_rejected", effective_tier, effective_value, effective_price

    minimum = str(settings.get("alerta_min_tier", "OURO")).upper()
    minimum_rank = max(3, _tier_rank(minimum))
    if suppressed_low_tier or _tier_rank(effective_tier) < minimum_rank:
        return "tier_below_notify", effective_tier, effective_value, effective_price

    try:
        min_value = float(settings.get("min_value_score_alerta", 70.0))
    except (TypeError, ValueError):
        min_value = 70.0
    if effective_value is not None and effective_value < min_value:
        return "value_below_alert_floor", effective_tier, effective_value, effective_price

    if prior:
        prior_tier = prior.get("promotion_tier") or prior.get("tier")
        prior_price = prior.get("promotion_checkout_price")
        if prior_price is None:
            prior_price = prior.get("price")
        try:
            threshold = float(settings.get("alerta_queda_preco_eur", 5.0))
            material_drop = (
                effective_price is not None
                and prior_price is not None
                and effective_price <= float(prior_price) - threshold
            )
        except (TypeError, ValueError):
            material_drop = False
        upgraded = _tier_rank(effective_tier) > _tier_rank(prior_tier)
        if not material_drop and not upgraded:
            return "already_alerted_no_material_change", effective_tier, effective_value, effective_price

    if item.get("promotions") and item.get("promotion_price_live_confirmed") is not True:
        return "promotion_not_live_confirmed", effective_tier, effective_value, effective_price
    return "suppressed_by_runtime_policy", effective_tier, effective_value, effective_price


def install(scraper_module, tracker_module) -> None:
    """Adiciona motivos de rejeição e auditoria de alertas sem mudar decisões."""
    if getattr(tracker_module, "_REJECTION_GUARD_INSTALLED", False):
        return

    base_empty_store_stats = tracker_module._empty_store_stats
    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_price_plausible = scraper_module.price_is_plausible_for_title
    base_maybe_alert = getattr(tracker_module, "maybe_alert", None)

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

    if base_maybe_alert is not None:
        def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
            prior = dict((history.get("alert_state", {}) or {}).get(alert_key) or {})
            sent, suppressed_low_tier = base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )
            latest = _latest_offer(history, alert_key)
            reason, effective_tier, effective_value, effective_price = _notification_reason(
                sent=bool(sent),
                item=item,
                assessment=assessment,
                tier=tier,
                prior=prior or None,
                latest=latest,
                settings=settings,
                suppressed_low_tier=bool(suppressed_low_tier),
            )

            # Guardamos apenas candidatos relevantes ou já alertados, não cada
            # BRONZE do catálogo. É um snapshot por URL, logo não cresce por run.
            raw_value = assessment.get("value_score")
            try:
                worth_auditing = float(effective_value if effective_value is not None else raw_value or 0) >= 105.0
            except (TypeError, ValueError):
                worth_auditing = False
            if worth_auditing or prior or effective_tier in {"OURO", "DIAMANTE"}:
                audit = history.setdefault("notification_audit", {})
                audit[alert_key] = {
                    "timestamp": tracker_module.now_iso(),
                    "loja": item.get("loja"),
                    "titulo": item.get("titulo"),
                    "url": item.get("url"),
                    "sent": bool(sent),
                    "reason": reason,
                    "effective_tier": effective_tier,
                    "effective_value": round(effective_value, 3) if effective_value is not None else None,
                    "effective_price": round(effective_price, 2) if effective_price is not None else None,
                    "price_page_confidence": spec.get("price_page_confidence"),
                    "promotion_live_confirmed": item.get("promotion_price_live_confirmed"),
                    "had_prior_alert": bool(prior),
                }
                if len(audit) > 500:
                    oldest = sorted(
                        audit,
                        key=lambda key: str((audit.get(key) or {}).get("timestamp") or ""),
                    )[: len(audit) - 500]
                    for key in oldest:
                        audit.pop(key, None)
            return sent, suppressed_low_tier

        tracker_module.maybe_alert = maybe_alert

    tracker_module._REJECTION_GUARD_INSTALLED = True
