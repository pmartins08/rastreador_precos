from __future__ import annotations

import promotion_value_guard as promotion_value


PROMOTION_SOURCE = "promocao"


def _campaign_promotion(promo: dict) -> bool:
    source = str(promo.get("source") or "").lower()
    eligibility = str(promo.get("eligibility") or "").lower()
    return eligibility == "campaign_listing" or source.startswith("campaign:") or source in {
        "official_campaign", "promotion_watch", "campaign_page_live",
        "campaign_page_live_verified",
    }


def _active_live_promotions(html: str) -> list[dict]:
    parsed = promotion_value.parse_promotion_text(
        html or "", source="campaign_page_live", eligibility="campaign_listing"
    )
    return [promo for promo in parsed if promotion_value.is_active(promo)]


def _same_economic_rule(configured: dict, live: dict) -> bool:
    """Confirma a regra pelo núcleo observável sem exigir campos omitidos na landing."""
    kind = str(configured.get("kind") or "").upper()
    if kind != str(live.get("kind") or "").upper():
        return False
    if kind == "TIERED_DISCOUNT":
        return (
            float(configured.get("threshold_step_eur") or 0) == float(live.get("threshold_step_eur") or 0)
            and float(configured.get("step_discount_eur") or 0) == float(live.get("step_discount_eur") or 0)
        )
    if kind in {"DIRECT_DISCOUNT", "COUPON", "STORE_CREDIT", "CASHBACK"}:
        configured_code = str(configured.get("code") or "").upper()
        live_code = str(live.get("code") or "").upper()
        if configured_code and live_code and configured_code != live_code:
            return False
        for field in ("value_eur", "percent"):
            left, right = configured.get(field), live.get(field)
            if left is not None and right is not None and float(left) != float(right):
                return False
        return True
    return True


def _verified_promotions(configured: list[dict], live: list[dict]) -> list[dict]:
    """Mantém condições oficiais configuradas quando a landing confirma a regra."""
    verified: list[dict] = []
    campaign_configured = [promo for promo in configured if _campaign_promotion(promo)]
    non_campaign = [promo for promo in configured if not _campaign_promotion(promo)]
    verified.extend(non_campaign)

    for promo in campaign_configured:
        match = next((candidate for candidate in live if _same_economic_rule(promo, candidate)), None)
        if match is None:
            continue
        merged = dict(promo)
        for field in ("valid_from", "valid_until"):
            if match.get(field):
                merged[field] = match[field]
        merged["source"] = "campaign_page_live_verified"
        merged["live_verified"] = True
        verified.append(merged)

    if not campaign_configured:
        verified.extend(dict(promo, live_verified=True) for promo in live)
    return promotion_value.dedupe(verified)


def install(tracker_module) -> None:
    """Exige confirmação na landing live antes de aplicar economia de campanha."""
    if getattr(tracker_module, "_PROMOTION_LIVE_GUARD_INSTALLED", False):
        return

    base_discover_html = tracker_module._discover_html
    verified_by_route: dict[str, list[dict]] = {}

    def discover_html(response, route_cat, target, candidates, source, stat):
        before = {
            url: PROMOTION_SOURCE in set(row.get("discovery_sources", []))
            for url, row in candidates.items()
        }
        gained = base_discover_html(response, route_cat, target, candidates, source, stat)

        newly_promoted = [
            row
            for url, row in candidates.items()
            if PROMOTION_SOURCE in set(row.get("discovery_sources", []))
            and not before.get(url, False)
        ]
        if not newly_promoted:
            return gained

        route_key = str(route_cat.get("url") or "").rstrip("/").lower()
        html = ""
        if response is not None and getattr(response, "status_code", 200) < 400:
            html = str(getattr(response, "text", "") or "")
        live = _active_live_promotions(html)

        if live:
            sample = promotion_value.dedupe(newly_promoted[0].get("promotions") or [])
            verified = _verified_promotions(sample, live)
            if any(_campaign_promotion(promo) for promo in verified):
                verified_by_route[route_key] = [
                    promo for promo in verified if _campaign_promotion(promo)
                ]
        else:
            cached = verified_by_route.get(route_key, [])
            live = cached

        for row in newly_promoted:
            current = promotion_value.dedupe(row.get("promotions") or [])
            non_campaign = [promo for promo in current if not _campaign_promotion(promo)]
            if live:
                if all(promo.get("live_verified") for promo in live):
                    cleaned = promotion_value.dedupe([*non_campaign, *live])
                else:
                    cleaned = _verified_promotions(current, live)
            else:
                cleaned = non_campaign
            if cleaned:
                row["promotions"] = cleaned
            else:
                row.pop("promotions", None)

            verified_listing = any(
                _campaign_promotion(promo) and promo.get("live_verified")
                for promo in row.get("promotions", [])
            )
            if verified_listing and row.get("preco") is not None:
                # O cartão desta mesma landing é uma observação live oficial do
                # preço corrente e da elegibilidade da promoção. Isto evita
                # reabrir fichas apenas para reconfirmar o mesmo preço.
                row["promotion_listing_live_confirmed"] = True
                row["promotion_price_live_confirmed"] = True
            else:
                row.pop("promotion_listing_live_confirmed", None)
                row.pop("promotion_price_live_confirmed", None)

        # Mantém a semântica deste estado: confirma que a REGRA da campanha foi
        # validada ao vivo, independentemente de um cartão individual ter preço.
        # A confirmação de preço por produto fica no marker separado acima.
        confirmed = any(
            any(
                _campaign_promotion(promo) and promo.get("live_verified")
                for promo in row.get("promotions", [])
            )
            for row in newly_promoted
        )
        stat["promotion_live_confirmed"] = int(bool(confirmed))
        if not confirmed:
            stat["promotion_live_unconfirmed"] = stat.get("promotion_live_unconfirmed", 0) + 1
        return gained

    tracker_module._discover_html = discover_html
    tracker_module._PROMOTION_LIVE_GUARD_INSTALLED = True
