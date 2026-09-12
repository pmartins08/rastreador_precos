from __future__ import annotations

import promotion_value_guard as promotion_value


PROMOTION_SOURCE = "promocao"


def _campaign_promotion(promo: dict) -> bool:
    source = str(promo.get("source") or "").lower()
    eligibility = str(promo.get("eligibility") or "").lower()
    return eligibility == "campaign_listing" or source.startswith("campaign:") or source in {
        "official_campaign", "promotion_watch", "campaign_page_live"
    }


def _active_live_promotions(html: str) -> list[dict]:
    parsed = promotion_value.parse_promotion_text(
        html or "", source="campaign_page_live", eligibility="campaign_listing"
    )
    return [promo for promo in parsed if promotion_value.is_active(promo)]


def install(tracker_module) -> None:
    """Exige confirmação na landing live antes de aplicar economia de campanha.

    Uma rota configurada pode continuar a servir para descoberta, mas datas ou
    regras antigas no JSON nunca são suficientes para baixar checkout/Value.
    """
    if getattr(tracker_module, "_PROMOTION_LIVE_GUARD_INSTALLED", False):
        return

    base_discover_html = tracker_module._discover_html

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

        html = ""
        if response is not None and getattr(response, "status_code", 200) < 400:
            html = str(getattr(response, "text", "") or "")
        live = _active_live_promotions(html)

        for row in newly_promoted:
            existing = [
                promo
                for promo in promotion_value.dedupe(row.get("promotions") or [])
                if not _campaign_promotion(promo)
            ]
            if live:
                existing.extend(live)
            cleaned = promotion_value.dedupe(existing)
            if cleaned:
                row["promotions"] = cleaned
            else:
                row.pop("promotions", None)

        stat["promotion_live_confirmed"] = int(bool(live))
        if not live:
            stat["promotion_live_unconfirmed"] = stat.get("promotion_live_unconfirmed", 0) + 1
        return gained

    tracker_module._discover_html = discover_html
    tracker_module._PROMOTION_LIVE_GUARD_INSTALLED = True
