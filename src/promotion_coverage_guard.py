from __future__ import annotations

from urllib.parse import urlsplit

import promotion_value_guard as promotion_value
from promotion_live_guard import _active_live_promotions, _verified_promotions


PROMOTION_SOURCE = "promocao"
_RP_CAMPAIGN_PATH = "/destaque/6a20120dc7e006.23735122"


def _listing_promotion(item: dict) -> bool:
    return bool(
        item.get("promotion_listing_live_confirmed")
        and item.get("promotions")
        and item.get("preco") is not None
    )


def _item_key(item: dict) -> tuple[str, str]:
    return str(item.get("loja") or ""), str(item.get("url") or "")


def _route_path(url: object) -> str:
    return urlsplit(str(url or "")).path.rstrip("/").lower()


def _configured_rp_promotion(route_cat: dict) -> dict | None:
    if str(route_cat.get("loja") or "") != "Radio Popular":
        return None
    if _route_path(route_cat.get("url")) != _RP_CAMPAIGN_PATH:
        return None
    for raw in route_cat.get("campaign_urls", []):
        if not isinstance(raw, dict) or _route_path(raw.get("url")) != _RP_CAMPAIGN_PATH:
            continue
        promo = raw.get("promotion")
        if not isinstance(promo, dict):
            continue
        value = dict(promo)
        value.setdefault("source", "official_campaign")
        value.setdefault("eligibility", "campaign_listing")
        value.setdefault("applicable", True)
        if raw.get("active_from"):
            value.setdefault("valid_from", raw["active_from"])
        if raw.get("expires_at"):
            value.setdefault("valid_until", raw["expires_at"])
        if promotion_value.is_active(value):
            return value
    return None


def _mark_verified_listing(item: dict, verified: list[dict]) -> None:
    if PROMOTION_SOURCE not in set(item.get("discovery_sources", [])):
        return
    if item.get("preco") is None:
        return
    item["promotions"] = promotion_value.dedupe(
        [*(item.get("promotions") or []), *verified]
    )
    item["promotion_listing_live_confirmed"] = True
    item["promotion_price_live_confirmed"] = True


def install(tracker_module) -> None:
    """Evita detail fetch redundante e garante cobertura completa da campanha live.

    A listagem oficial já confirma duas coisas voláteis: pertença à campanha e
    preço corrente do cartão. A ficha de produto continua necessária para
    hardware novo, mas hardware conhecido pode vir da cache sem desperdiçar o
    orçamento HTTP da loja.

    Produtos de uma campanha live confirmada também têm cobertura prioritária:
    nunca são os primeiros candidatos cortados pelo limite global de avaliação.
    Isto é especialmente importante quando a campanha contém quase tantos
    portáteis como o orçamento total da run.
    """
    if getattr(tracker_module, "_PROMOTION_COVERAGE_GUARD_INSTALLED", False):
        return

    base_discover_html = tracker_module._discover_html
    base_scan_store = tracker_module.scan_store
    base_needs_price_refresh = tracker_module.needs_price_refresh
    base_adaptive_fetch = tracker_module.adaptive_fetch
    verified_rp: list[dict] = []

    def discover_html(response, route_cat, target, candidates, source, stat):
        nonlocal verified_rp
        configured = _configured_rp_promotion(route_cat)
        if configured and response is not None and getattr(response, "status_code", 200) < 400:
            live = _active_live_promotions(str(getattr(response, "text", "") or ""))
            verified = _verified_promotions([configured], live) if live else []
            verified = [promo for promo in verified if promo.get("live_verified")]
            if verified:
                verified_rp = verified

        gained = base_discover_html(response, route_cat, target, candidates, source, stat)

        # Última camada de segurança: algumas wrappers internas trocam o URL
        # filtrado pelo URL canónico durante a descoberta. Se a landing desta run
        # confirmou a regra, todos os candidatos realmente descobertos pela fonte
        # promocional herdam a mesma promoção; candidatos só de categoria não.
        if verified_rp and str(route_cat.get("loja") or "") == "Radio Popular":
            for row in candidates.values():
                _mark_verified_listing(row, verified_rp)
            stat["promotion_live_confirmed"] = 1
        return gained

    def scan_store(cat: dict, config: dict, settings: dict):
        nonlocal verified_rp
        if str(cat.get("loja") or "") == "Radio Popular":
            verified_rp = []
        items, stat = base_scan_store(cat, config, settings)
        if verified_rp and str(cat.get("loja") or "") == "Radio Popular":
            for item in items:
                _mark_verified_listing(item, verified_rp)
            stat["promotion_live_confirmed"] = 1
        return items, stat

    def _select_regular(items, spec_cache, max_items, weights, settings):
        if max_items <= 0:
            return []
        cached = [
            item for item in items
            if item.get("specs") or (item.get("url") and item["url"] in spec_cache)
        ]
        cached_selected = tracker_module.select_for_evaluation(
            cached, min(max_items, len(cached)), weights, settings
        ) if cached else []
        cached_keys = {_item_key(item) for item in cached_selected}
        remaining_slots = max(0, max_items - len(cached_selected))
        if remaining_slots == 0:
            return cached_selected
        uncached = [
            item for item in items
            if _item_key(item) not in cached_keys
            and not item.get("specs")
            and item.get("url") not in spec_cache
        ]
        return cached_selected + tracker_module.select_for_evaluation(
            uncached, min(remaining_slots, len(uncached)), weights, settings
        )

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        if max_items <= 0:
            return []

        # Uma campanha confirmada live é um universo explicitamente pedido pelo
        # utilizador e observado na loja nesta run. Reserva esses candidatos antes
        # do corte global; dentro da própria campanha continua a valer o seletor
        # normal caso, excecionalmente, a campanha ultrapasse todo o orçamento.
        promoted = [item for item in items if _listing_promotion(item)]
        promoted_selected = tracker_module.select_for_evaluation(
            promoted, min(max_items, len(promoted)), weights, settings
        ) if promoted else []
        promoted_keys = {_item_key(item) for item in promoted_selected}

        remaining_slots = max(0, max_items - len(promoted_selected))
        if remaining_slots == 0:
            return promoted_selected

        regular = [item for item in items if _item_key(item) not in promoted_keys]
        return promoted_selected + _select_regular(
            regular, spec_cache, remaining_slots, weights, settings
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

    tracker_module._discover_html = discover_html
    tracker_module.scan_store = scan_store
    tracker_module.select_with_cache = select_with_cache
    tracker_module.needs_price_refresh = needs_price_refresh
    tracker_module.adaptive_fetch = adaptive_fetch
    tracker_module._PROMOTION_COVERAGE_GUARD_INSTALLED = True
