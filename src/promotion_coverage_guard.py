from __future__ import annotations


def _listing_promotion(item: dict) -> bool:
    return bool(
        item.get("promotion_listing_live_confirmed")
        and item.get("promotions")
        and item.get("preco") is not None
    )


def install(tracker_module) -> None:
    """Evita que uma campanha live transforme toda a loja em detail fetch.

    A listagem oficial já confirma duas coisas voláteis: pertença à campanha e
    preço corrente do cartão. A ficha de produto continua necessária para
    hardware novo, mas hardware conhecido pode vir da cache sem desperdiçar o
    orçamento HTTP da loja.
    """
    if getattr(tracker_module, "_PROMOTION_COVERAGE_GUARD_INSTALLED", False):
        return

    base_needs_price_refresh = tracker_module.needs_price_refresh
    base_adaptive_fetch = tracker_module.adaptive_fetch

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        if max_items <= 0:
            return []
        cached = [
            item for item in items
            if item.get("specs") or (item.get("url") and item["url"] in spec_cache)
        ]
        cached_selected = tracker_module.select_for_evaluation(
            cached, min(max_items, len(cached)), weights, settings
        ) if cached else []
        cached_keys = {(item["loja"], item["url"]) for item in cached_selected}
        remaining_slots = max(0, max_items - len(cached_selected))
        if remaining_slots == 0:
            return cached_selected
        uncached = [
            item for item in items
            if (item["loja"], item["url"]) not in cached_keys
            and not item.get("specs")
            and item.get("url") not in spec_cache
        ]
        return cached_selected + tracker_module.select_for_evaluation(
            uncached, min(remaining_slots, len(uncached)), weights, settings
        )

    def needs_price_refresh(previous_meta, item, settings, *, current_time=None):
        # O preço/elegibilidade já foram observados na landing oficial nesta run.
        # A alteração de preço continua a ser avaliada pelo cérebro e alertas;
        # apenas evitamos um segundo pedido HTTP redundante à ficha.
        if _listing_promotion(item):
            return False
        return base_needs_price_refresh(
            previous_meta, item, settings, current_time=current_time
        )

    def adaptive_fetch(url, config, timeout_s=8.0, *, store=None, method="page", **kwargs):
        effective_timeout = float(timeout_s)
        if str(store or "") == "Radio Popular" and str(method).startswith("product"):
            effective_timeout = max(effective_timeout, 14.0)
        return base_adaptive_fetch(
            url, config, effective_timeout, store=store, method=method, **kwargs
        )

    tracker_module.select_with_cache = select_with_cache
    tracker_module.needs_price_refresh = needs_price_refresh
    tracker_module.adaptive_fetch = adaptive_fetch
    tracker_module._PROMOTION_COVERAGE_GUARD_INSTALLED = True
