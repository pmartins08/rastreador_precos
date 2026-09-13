from __future__ import annotations

import promotion_value_guard as promotion_value


def budget_view(item: dict, settings: dict) -> dict:
    """Vista económica usada apenas para seleção/pré-ranking.

    O preço canónico da loja nunca é alterado. Uma promoção só pode mudar a
    vista de orçamento quando a própria run confirmou ao vivo a elegibilidade e
    o preço do produto (landing/listagem ou ficha).
    """
    try:
        raw_price = float(item.get("preco"))
    except (TypeError, ValueError):
        return {
            "confirmed": False,
            "raw_price": None,
            "checkout_price": None,
            "discount_eur": 0.0,
            "hard_budget": float(settings.get("budget_hard", 1500.0)),
            "fits_hard_budget": False,
            "rescued_by_promotion": False,
        }

    hard = float(settings.get("budget_hard", 1500.0))
    live_confirmed = bool(
        item.get("promotion_listing_live_confirmed")
        or item.get("promotion_price_live_confirmed")
    )
    promotions = promotion_value.dedupe(item.get("promotions") or [])
    economics = promotion_value.economics(promotions, raw_price) if promotions else {}
    discount = float(economics.get("checkout_discount_eur") or 0.0)
    confirmed = bool(live_confirmed and discount > 0.0)
    checkout = (
        float(economics.get("effective_checkout_price"))
        if confirmed and economics.get("effective_checkout_price") is not None
        else raw_price
    )
    fits = checkout <= hard + 1e-9
    rescued = raw_price > hard + 1e-9 and fits and confirmed
    return {
        "confirmed": confirmed,
        "raw_price": round(raw_price, 2),
        "checkout_price": round(checkout, 2),
        "discount_eur": round(discount if confirmed else 0.0, 2),
        "hard_budget": round(hard, 2),
        "fits_hard_budget": bool(fits),
        "rescued_by_promotion": bool(rescued),
    }


def _effective_price_priority_delta(tracker_module, item: dict, settings: dict) -> float:
    """Corrige apenas a parcela preço do candidate_priority base (35%)."""
    view = budget_view(item, settings)
    if not view["confirmed"]:
        return 0.0
    raw = float(view["raw_price"])
    checkout = float(view["checkout_price"])
    if checkout >= raw - 0.01:
        return 0.0
    raw_score = float(tracker_module.scraper.price_score(raw, settings))
    checkout_score = float(tracker_module.scraper.price_score(checkout, settings))
    return 0.35 * max(0.0, checkout_score - raw_score)


def install(tracker_module) -> None:
    """Faz o pré-ranking respeitar o preço realmente pago após promoção live.

    Não altera score técnico, Value canónico, preço histórico nem tier normal.
    A camada de runtime continua responsável por recalcular Value/tier promocional
    e por decidir alertas OURO/DIAMANTE.
    """
    if getattr(tracker_module, "_PROMOTION_BUDGET_GUARD_INSTALLED", False):
        return

    base_candidate_priority = tracker_module.candidate_priority
    base_scan_store = getattr(tracker_module, "scan_store", None)

    def candidate_priority(item: dict, weights: dict, settings: dict) -> float:
        base = float(base_candidate_priority(item, weights, settings))
        delta = _effective_price_priority_delta(tracker_module, item, settings)
        return round(base + delta, 3)

    tracker_module.candidate_priority = candidate_priority

    if base_scan_store is not None:
        def scan_store(cat: dict, config: dict, settings: dict):
            items, stat = base_scan_store(cat, config, settings)
            views = [
                (item, budget_view(item, settings))
                for item in items
                if item.get("promotions")
            ]
            confirmed = [(item, view) for item, view in views if view["confirmed"]]
            rescued = [(item, view) for item, view in confirmed if view["rescued_by_promotion"]]
            fits = [(item, view) for item, view in confirmed if view["fits_hard_budget"]]
            if confirmed:
                promo_stats = {
                    "confirmed_candidates": len(confirmed),
                    "fits_hard_budget": len(fits),
                    "rescued_above_hard_budget": len(rescued),
                    "max_gross_price": round(max(float(view["raw_price"]) for _item, view in confirmed), 2),
                    "max_checkout_price": round(max(float(view["checkout_price"]) for _item, view in confirmed), 2),
                }
                if rescued:
                    promo_stats["max_rescued_gross_price"] = round(
                        max(float(view["raw_price"]) for _item, view in rescued), 2
                    )
                    promo_stats["max_rescued_checkout_price"] = round(
                        max(float(view["checkout_price"]) for _item, view in rescued), 2
                    )
                stat["promotion_budget"] = promo_stats
                tracker_module.LOGGER.info(
                    "Orçamento promocional | %s | confirmados=%d | dentro_hard=%d | "
                    "resgatados_acima_hard=%d | bruto_max=%.2f€",
                    str(cat.get("loja") or ""),
                    len(confirmed),
                    len(fits),
                    len(rescued),
                    promo_stats["max_gross_price"],
                )
            return items, stat

        tracker_module.scan_store = scan_store

    tracker_module._PROMOTION_BUDGET_GUARD_INSTALLED = True
