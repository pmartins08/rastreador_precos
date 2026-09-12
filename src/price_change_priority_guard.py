from __future__ import annotations

import re
from urllib.parse import urlparse

import promotion_value_guard as promotion_value


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.rstrip("/").lower()
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}".lower()


def _normal_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inject_value_transition(message: str, old_value: float, new_value: float) -> str:
    delta = new_value - old_value
    line = f"Variação Value: {old_value:.1f} → {new_value:.1f} (Δ {delta:+.1f})"
    if line in message:
        return message
    lines = str(message).splitlines()
    if lines and lines[-1].strip().lower().startswith(("http://", "https://")):
        lines.insert(len(lines) - 1, line)
    else:
        lines.append(line)
    return "\n".join(lines)


def install(tracker_module) -> None:
    """Prioriza alterações materiais e torna a variação de Value visível no alerta.

    Não altera score, Value, tier ou critérios de envio. A prioridade continua a
    servir apenas para garantir que uma alteração material de preço chega à
    avaliação. Se essa avaliação gerar uma notificação, acrescenta o Value de
    referência, o Value recalculado e o respetivo delta.
    """
    if getattr(tracker_module, "_PRICE_CHANGE_PRIORITY_GUARD_INSTALLED", False):
        return

    base_candidate_priority = tracker_module.candidate_priority
    base_maybe_alert = getattr(tracker_module, "maybe_alert", None)
    index_holder: dict[str, object] = {}

    def indexes():
        if index_holder:
            return index_holder
        history = tracker_module.compact_history(tracker_module.load_history())
        latest = tracker_module.latest_offer_by_url(history)
        by_url = {}
        by_ean = {}
        by_mpn = {}
        for previous in latest.values():
            if not isinstance(previous, dict):
                continue
            store = str(previous.get("loja") or "")
            url = _canonical_url(previous.get("url"))
            if store and url:
                by_url[(store, url)] = previous
            ean = _normal_id(previous.get("ean"))
            if store and ean:
                by_ean[(store, ean)] = previous
            mpn = _normal_id(previous.get("mpn"))
            if store and mpn:
                by_mpn[(store, mpn)] = previous
        index_holder.update({"by_url": by_url, "by_ean": by_ean, "by_mpn": by_mpn})
        return index_holder

    def previous_for(item: dict):
        idx = indexes()
        store = str(item.get("loja") or "")
        if not store:
            return None
        url = _canonical_url(item.get("url"))
        if url:
            previous = idx["by_url"].get((store, url))
            if previous:
                return previous
        ean = _normal_id(item.get("ean"))
        if ean:
            previous = idx["by_ean"].get((store, ean))
            if previous:
                return previous
        mpn = _normal_id(item.get("mpn"))
        if mpn:
            return idx["by_mpn"].get((store, mpn))
        return None

    def candidate_priority(item, weights, settings):
        base = float(base_candidate_priority(item, weights, settings))
        previous = previous_for(item)
        if not isinstance(previous, dict):
            return base
        try:
            old_price = float(previous.get("price"))
            current_price = float(item.get("preco"))
        except (TypeError, ValueError):
            return base

        delta = old_price - current_price
        threshold = max(
            0.01,
            float(
                settings.get(
                    "historical_price_change_priority_min_eur",
                    settings.get("alerta_queda_preco_eur", 5.0),
                )
            ),
        )
        if abs(delta) + 1e-9 < threshold:
            return base

        # Quedas têm prioridade muito maior porque podem criar uma nova
        # oportunidade OURO/DIAMANTE. Subidas também são recalculadas, mas não
        # devem roubar slots às oportunidades.
        if delta > 0:
            bonus = float(settings.get("historical_price_drop_priority_bonus", 500.0))
        else:
            bonus = float(settings.get("historical_price_rise_priority_bonus", 100.0))
        return round(base + bonus, 3)

    def value_transition(history, item, assessment, previous, alert_key, settings):
        current_normal = _float_or_none(
            assessment.get("value_score") if isinstance(assessment, dict) else None
        )
        if current_normal is None:
            return None

        alert_state = history.get("alert_state", {}) if isinstance(history, dict) else {}
        prior = alert_state.get(alert_key) if isinstance(alert_state, dict) else None
        prior = prior if isinstance(prior, dict) else {}

        # Promoções confirmadas usam como Value efetivo o checkout derivado. Na
        # primeira elegibilidade mostramos o impacto normal -> promo; numa
        # alteração posterior mostramos promo anterior -> promo recalculado.
        promotions = promotion_value.dedupe(item.get("promotions") or [])
        if (
            promotions
            and item.get("promotion_price_live_confirmed") is True
            and item.get("preco") is not None
            and callable(getattr(tracker_module, "promotion_revalue_assessment", None))
        ):
            economics = promotion_value.economics(promotions, float(item["preco"]))
            if float(economics.get("checkout_discount_eur") or 0.0) > 0.0:
                promo_assessment = tracker_module.promotion_revalue_assessment(
                    assessment,
                    float(economics["effective_checkout_price"]),
                    settings,
                )
                promo_current = _float_or_none(
                    promo_assessment.get("value_score")
                    if isinstance(promo_assessment, dict)
                    and promo_assessment.get("status") == "ACEITE"
                    else None
                )
                if promo_current is not None:
                    promo_previous = _float_or_none(prior.get("promotion_value_score"))
                    baseline = promo_previous if promo_previous is not None else current_normal
                    if abs(promo_current - baseline) >= 0.05:
                        return baseline, promo_current
                    return None

        baseline = _float_or_none(prior.get("value_score"))
        if baseline is None and isinstance(previous, dict):
            baseline = _float_or_none(previous.get("value_score"))
        if baseline is None or abs(current_normal - baseline) < 0.05:
            return None
        return baseline, current_normal

    def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
        transition = value_transition(
            history, item, assessment, previous, alert_key, settings
        )
        if transition is None or not callable(base_maybe_alert):
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )

        base_ntfy_send = getattr(tracker_module, "ntfy_send", None)
        if not callable(base_ntfy_send):
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )

        old_value, new_value = transition

        def ntfy_send(title, message, *, priority=3, tags=None):
            return base_ntfy_send(
                title,
                _inject_value_transition(str(message), old_value, new_value),
                priority=priority,
                tags=tags,
            )

        tracker_module.ntfy_send = ntfy_send
        try:
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )
        finally:
            tracker_module.ntfy_send = base_ntfy_send

    tracker_module.candidate_priority = candidate_priority
    if callable(base_maybe_alert):
        tracker_module.maybe_alert = maybe_alert
    tracker_module._PRICE_CHANGE_PRIORITY_GUARD_INSTALLED = True
