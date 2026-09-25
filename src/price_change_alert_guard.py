from __future__ import annotations

import re

import promotion_value_guard as promotion_value


_TIER_ORDER = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normal_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _latest_equivalent(history: dict, item: dict) -> dict | None:
    """Fallback para URL mudado: procura o mesmo EAN/MPN dentro da mesma loja."""
    store = str(item.get("loja") or "")
    ean = _normal_id(item.get("ean"))
    mpn = _normal_id(item.get("mpn"))
    if not store or not (ean or mpn):
        return None

    best: dict | None = None
    for entries in (history.get("offers", {}) or {}).values():
        if not isinstance(entries, list) or not entries:
            continue
        candidate = entries[-1]
        if not isinstance(candidate, dict) or str(candidate.get("loja") or "") != store:
            continue
        candidate_ean = _normal_id(candidate.get("ean"))
        candidate_mpn = _normal_id(candidate.get("mpn"))
        same = bool(ean and candidate_ean == ean) or bool(mpn and candidate_mpn == mpn)
        if not same:
            continue
        if best is None or str(candidate.get("timestamp") or "") > str(best.get("timestamp") or ""):
            best = candidate
    return best


def _previous_effective_price(previous: dict | None) -> float | None:
    if not isinstance(previous, dict):
        return None
    promo = _number(previous.get("promotion_checkout_price"))
    if promo is not None and promo > 0:
        return promo
    effective = _number(previous.get("effective_price"))
    if effective is not None and effective > 0:
        return effective
    return _number(previous.get("price"))


def current_effective_snapshot(
    tracker_module,
    item: dict,
    assessment: dict,
    tier: str | None,
    settings: dict,
) -> dict:
    raw_price = _number(item.get("preco"))
    base_value = _number(assessment.get("value_score")) if isinstance(assessment, dict) else None
    snapshot = {
        "price": raw_price,
        "value_score": base_value,
        "tier": tier,
        "promotion_applied": False,
        "discount_eur": 0.0,
    }
    if raw_price is None:
        return snapshot

    promotions = promotion_value.dedupe(item.get("promotions") or [])
    if (
        not promotions
        or item.get("promotion_price_live_confirmed") is not True
        or not callable(getattr(tracker_module, "promotion_revalue_assessment", None))
    ):
        return snapshot

    economics = promotion_value.economics(promotions, raw_price)
    discount = float(economics.get("checkout_discount_eur") or 0.0)
    if discount <= 0.0:
        return snapshot

    promo_assessment = tracker_module.promotion_revalue_assessment(
        assessment,
        float(economics["effective_checkout_price"]),
        settings,
    )
    if not isinstance(promo_assessment, dict) or promo_assessment.get("status") != "ACEITE":
        return snapshot

    promo_value = _number(promo_assessment.get("value_score"))
    promo_tier = (
        tracker_module.scraper.tier_from_value(promo_assessment["value_score"], settings)
        if promo_value is not None
        else None
    )
    return {
        "price": float(economics["effective_checkout_price"]),
        "raw_price": raw_price,
        "value_score": promo_value,
        "tier": promo_tier,
        "promotion_applied": True,
        "discount_eur": discount,
        "promotion_value_score": promo_value,
        "promotion_tier": promo_tier,
        "promotion_fingerprint": promotion_value.fingerprint(promotions),
    }


def material_price_change(
    old_price: float | None,
    new_price: float | None,
    threshold_eur: float,
) -> bool:
    return (
        old_price is not None
        and new_price is not None
        and abs(float(new_price) - float(old_price)) + 1e-9 >= max(0.01, float(threshold_eur))
    )


def _tier_can_notify(tier: str | None, settings: dict) -> bool:
    minimum = _TIER_ORDER.get(str(settings.get("alerta_min_tier", "OURO")).upper(), 3)
    return _TIER_ORDER.get(str(tier or "").upper(), 0) >= max(3, minimum)


def install(tracker_module) -> None:
    """Envia uma única notificação para alterações materiais que o alerta base não cobriu."""
    if getattr(tracker_module, "_PRICE_CHANGE_ALERT_GUARD_INSTALLED", False):
        return

    base_maybe_alert = tracker_module.maybe_alert

    def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
        sent, suppressed = base_maybe_alert(
            history,
            item,
            spec,
            assessment,
            tier,
            previous,
            alert_key,
            settings,
        )
        if sent:
            return sent, suppressed

        reference = previous if isinstance(previous, dict) else None
        if reference is None:
            reference = _latest_equivalent(history, item)
        old_price = _previous_effective_price(reference)
        current = current_effective_snapshot(
            tracker_module,
            item,
            assessment,
            tier,
            settings,
        )
        new_price = _number(current.get("price"))
        threshold = float(
            settings.get(
                "alerta_alteracao_preco_eur",
                settings.get("alerta_queda_preco_eur", 5.0),
            )
        )
        if not material_price_change(old_price, new_price, threshold):
            return sent, suppressed

        current_tier = current.get("tier")
        current_value = _number(current.get("value_score"))
        min_value = float(settings.get("min_value_score_alerta", 70.0))
        if (
            item.get("stock") is False
            or current_value is None
            or current_value < min_value
            or not _tier_can_notify(current_tier, settings)
        ):
            return False, True

        delta = float(new_price) - float(old_price)
        direction = "subiu" if delta > 0 else "desceu"
        icon = "📈" if delta > 0 else "📉"
        raw_price = _number(item.get("preco"))
        lines = [
            str(item.get("titulo") or ""),
            f"Loja: {item.get('loja') or '—'}",
            f"Preço efetivo: {old_price:.2f}€ → {new_price:.2f}€ (Δ {delta:+.2f}€)",
        ]
        if current.get("promotion_applied") and raw_price is not None:
            lines.append(
                f"Preço mostrado: {raw_price:.2f}€ | desconto checkout: {float(current.get('discount_eur') or 0.0):.2f}€"
            )
        lines.extend(
            [
                f"Value atual: {current_value:.1f} | Tier: {current_tier}",
                f"Alteração: preço {direction}",
                str(item.get("url") or ""),
            ]
        )
        pushed = tracker_module.ntfy_send(
            f"{icon} PREÇO {current_tier}: {item.get('titulo') or ''}",
            "\n".join(lines),
            priority=4 if current_tier == "DIAMANTE" else 3,
            tags=["computer", "moneybag"],
        )
        if not pushed:
            return False, suppressed

        state = {
            "timestamp": tracker_module.now_iso(),
            "price": item.get("preco"),
            "value_score": assessment.get("value_score"),
            "tier": tier,
            "effective_price": new_price,
            "effective_value_score": current_value,
            "effective_tier": current_tier,
            "last_price_change_from": old_price,
            "last_price_change_to": new_price,
            "last_price_change_delta_eur": round(delta, 2),
        }
        if current.get("promotion_applied"):
            state.update(
                {
                    "promotion_checkout_price": new_price,
                    "promotion_discount_eur": current.get("discount_eur"),
                    "promotion_value_score": current.get("promotion_value_score"),
                    "promotion_tier": current.get("promotion_tier"),
                    "promotion_eligibility_fingerprint": current.get("promotion_fingerprint"),
                }
            )
        history.setdefault("alert_state", {})[alert_key] = state
        tracker_module.LOGGER.info(
            "Alteração preço NTFY | %s | %.2f€ -> %.2f€ | tier=%s | value=%.1f",
            item.get("loja"),
            old_price,
            new_price,
            current_tier,
            current_value,
        )
        return True, False

    tracker_module.maybe_alert = maybe_alert
    tracker_module._PRICE_CHANGE_ALERT_GUARD_INSTALLED = True
