from __future__ import annotations

import promotion_value_guard as promotion_value


_GATE_RAW_PRICE = "_promotion_budget_gate_raw_price"
_GATE_CHECKOUT_PRICE = "_promotion_budget_gate_checkout_price"


def budget_view(item: dict, settings: dict) -> dict:
    """Vista económica usada apenas para orçamento/seleção.

    O preço canónico da loja nunca é substituído de forma persistente. Uma
    promoção só pode mudar a vista de orçamento quando a própria run confirmou
    ao vivo a elegibilidade e o preço do produto.
    """
    try:
        raw_price = float(item.get(_GATE_RAW_PRICE, item.get("preco")))
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

    # Quando o proxy do hard-budget já está ativo, o candidate_priority base vê
    # diretamente o checkout. Não somamos a diferença uma segunda vez.
    if _GATE_RAW_PRICE in item:
        try:
            if abs(float(item.get("preco")) - checkout) < 0.01:
                return 0.0
        except (TypeError, ValueError):
            pass

    raw_score = float(tracker_module.scraper.price_score(raw, settings))
    checkout_score = float(tracker_module.scraper.price_score(checkout, settings))
    return 0.35 * max(0.0, checkout_score - raw_score)


def _apply_main_budget_gate(items: list[dict], settings: dict) -> int:
    """Torna visível aos dois hard gates o checkout promocional confirmado."""
    rescued = 0
    for item in items:
        if _GATE_RAW_PRICE in item:
            continue
        view = budget_view(item, settings)
        if not view.get("rescued_by_promotion"):
            continue
        raw = float(view["raw_price"])
        checkout = float(view["checkout_price"])
        item[_GATE_RAW_PRICE] = raw
        item[_GATE_CHECKOUT_PRICE] = checkout
        item["preco"] = checkout
        rescued += 1
    return rescued


def _restore_item_budget_gate(item: dict) -> bool:
    if _GATE_RAW_PRICE not in item:
        return False
    raw = float(item.pop(_GATE_RAW_PRICE))
    checkout = float(item.pop(_GATE_CHECKOUT_PRICE, raw))
    item["preco"] = raw
    item["promotion_budget_gate_checkout_price"] = round(checkout, 2)
    item["promotion_budget_gate_rescued"] = True
    return True


def _restore_main_budget_gate(items: list[dict]) -> int:
    return sum(1 for item in items if _restore_item_budget_gate(item))


def _live_raw_price(result: dict) -> float | None:
    """Preço bruto confirmado pela ficha, nunca o checkout derivado."""
    specs = result.get("specs") if isinstance(result.get("specs"), dict) else {}
    for candidate in (specs.get("price_confirmed"), result.get("preco")):
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _reapply_budget_gate_after_enrich(result: dict, settings: dict) -> tuple[str, dict | None]:
    """Reaplica checkout depois de a ficha live voltar a expor o PVP bruto.

    O runtime promocional limpa temporariamente `preco` antes do fetch para
    obrigar a confirmar o valor atual na ficha. O `enrich` base devolve então o
    PVP bruto. Para candidatos que só cabem no budget graças à campanha, esse
    PVP não pode voltar a chegar ao segundo hard gate. Recalculamos a promoção
    sobre o preço live e só mantemos o proxy se continuar realmente <= hard.
    """
    if _GATE_RAW_PRICE not in result:
        return "not_proxied", None

    live_raw = _live_raw_price(result)
    if live_raw is None:
        return "missing_live_price", None

    probe = dict(result)
    probe.pop(_GATE_RAW_PRICE, None)
    probe.pop(_GATE_CHECKOUT_PRICE, None)
    probe["preco"] = live_raw
    view = budget_view(probe, settings)

    if view.get("rescued_by_promotion"):
        result[_GATE_RAW_PRICE] = float(view["raw_price"])
        result[_GATE_CHECKOUT_PRICE] = float(view["checkout_price"])
        result["preco"] = float(view["checkout_price"])
        result["promotion_budget_gate_live_raw_price"] = round(live_raw, 2)
        return "reapplied", view

    # Se o PVP live já cabe sem promoção, o proxy deixou de ser necessário. Se
    # nem o checkout live cabe, removê-lo faz o segundo gate rejeitar corretamente.
    result.pop(_GATE_RAW_PRICE, None)
    result.pop(_GATE_CHECKOUT_PRICE, None)
    result["preco"] = live_raw
    result["promotion_budget_gate_live_raw_price"] = round(live_raw, 2)
    return "released", view


def _score_price_for_proxy(spec: dict, observed_price: float, active_by_url: dict[str, tuple[float, float]]) -> float:
    """O score normal usa PVP bruto; apenas os hard gates usam checkout."""
    page_url = str(spec.get("page_url") or spec.get("url") or "")
    if page_url in active_by_url:
        return float(active_by_url[page_url][0])

    # Fallback conservador: um checkout só é convertido para bruto se todas as
    # associações compatíveis apontarem para o mesmo PVP.
    matches = {
        float(raw)
        for raw, checkout in active_by_url.values()
        if abs(float(checkout) - float(observed_price)) < 0.01
    }
    if len(matches) == 1:
        return matches.pop()
    return float(observed_price)


def install(tracker_module) -> None:
    """Faz orçamento, seleção, fetch live e ambos hard gates respeitarem promoções."""
    if getattr(tracker_module, "_PROMOTION_BUDGET_GUARD_INSTALLED", False):
        return

    base_candidate_priority = tracker_module.candidate_priority
    base_scan_store = getattr(tracker_module, "scan_store", None)
    base_select_with_cache = getattr(tracker_module, "select_with_cache", None)
    base_enrich = getattr(tracker_module, "enrich", None)
    base_score_allow_unknown = getattr(tracker_module, "score_allow_unknown", None)
    base_record_offer = getattr(tracker_module, "record_offer", None)
    base_main = getattr(tracker_module, "main", None)

    active_items: list[dict] = []
    active_by_url: dict[str, tuple[float, float]] = {}

    def register_active(item: dict) -> None:
        if _GATE_RAW_PRICE not in item:
            return
        raw = float(item[_GATE_RAW_PRICE])
        checkout = float(item[_GATE_CHECKOUT_PRICE])
        keys = {
            str(item.get("url") or ""),
            str((item.get("specs") or {}).get("page_url") or "") if isinstance(item.get("specs"), dict) else "",
        }
        for key in keys:
            if key:
                active_by_url[key] = (raw, checkout)

    def unregister_active(item: dict) -> None:
        keys = {
            str(item.get("url") or ""),
            str((item.get("specs") or {}).get("page_url") or "") if isinstance(item.get("specs"), dict) else "",
        }
        for key in keys:
            if key:
                active_by_url.pop(key, None)

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

            if getattr(tracker_module, "_PROMOTION_BUDGET_MAIN_ACTIVE", False):
                proxied = _apply_main_budget_gate(items, settings)
                if proxied:
                    for item in items:
                        if _GATE_RAW_PRICE not in item:
                            continue
                        active_items.append(item)
                        register_active(item)
                    stat.setdefault("promotion_budget", {})["main_gate_rescued"] = proxied
            return items, stat

        tracker_module.scan_store = scan_store

    if base_select_with_cache is not None:
        def select_with_cache(items, spec_cache, max_items, weights, settings):
            return base_select_with_cache(items, spec_cache, max_items, weights, settings)

        tracker_module.select_with_cache = select_with_cache

    if base_enrich is not None:
        def enrich(item: dict, config: dict):
            result, status = base_enrich(item, config)
            if status.get("error") or _GATE_RAW_PRICE not in result:
                return result, status

            outcome, view = _reapply_budget_gate_after_enrich(
                result, (config or {}).get("settings", {})
            )
            unregister_active(item)
            if outcome == "reapplied":
                register_active(result)
                tracker_module.LOGGER.info(
                    "Gate promocional reaplicado após ficha live | %s | bruto=%.2f€ | checkout=%.2f€",
                    str(result.get("titulo") or result.get("url") or "produto"),
                    float(view["raw_price"]),
                    float(view["checkout_price"]),
                )
            elif outcome == "released":
                tracker_module.LOGGER.info(
                    "Gate promocional revisto após ficha live | %s | bruto=%.2f€ | dentro_hard=%s",
                    str(result.get("titulo") or result.get("url") or "produto"),
                    float(view["raw_price"]),
                    bool(view["fits_hard_budget"]),
                )
            return result, status

        tracker_module.enrich = enrich

    if base_score_allow_unknown is not None:
        def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict):
            score_price = _score_price_for_proxy(spec, float(price), active_by_url)
            return base_score_allow_unknown(spec, score_price, weights, settings)

        tracker_module.score_allow_unknown = score_allow_unknown

    if base_record_offer is not None:
        def record_offer(history, item, spec, assessment, tier):
            if _restore_item_budget_gate(item):
                unregister_active(item)
                tracker_module.LOGGER.info(
                    "Gate promocional restaurado antes do histórico | %s | bruto=%.2f€ | checkout=%.2f€",
                    str(item.get("titulo") or item.get("url") or "produto"),
                    float(item["preco"]),
                    float(item.get("promotion_budget_gate_checkout_price") or item["preco"]),
                )
            return base_record_offer(history, item, spec, assessment, tier)

        tracker_module.record_offer = record_offer

    if base_main is not None:
        def main(*args, **kwargs):
            active_items.clear()
            active_by_url.clear()
            tracker_module._PROMOTION_BUDGET_MAIN_ACTIVE = True
            try:
                return base_main(*args, **kwargs)
            finally:
                leftovers = _restore_main_budget_gate(active_items)
                if leftovers:
                    tracker_module.LOGGER.info(
                        "Gate promocional limpo no fim da run | candidatos=%d | preço bruto preservado",
                        leftovers,
                    )
                active_items.clear()
                active_by_url.clear()
                tracker_module._PROMOTION_BUDGET_MAIN_ACTIVE = False
        tracker_module.main = main

    tracker_module._PROMOTION_BUDGET_GUARD_INSTALLED = True
