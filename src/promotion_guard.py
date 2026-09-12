from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import promotion_value_guard as promotion_value


PROMOTION_SOURCE = "promocao"


def _parse_day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def route_is_active(route: dict, today: date | None = None) -> bool:
    day = today or datetime.now(timezone.utc).date()
    start = _parse_day(route.get("active_from") or route.get("valid_from"))
    end = _parse_day(route.get("expires_at") or route.get("valid_until"))
    return (not start or day >= start) and (not end or day <= end)


def _route(raw: Any, index: int, kind: str) -> dict | None:
    if isinstance(raw, str):
        route = {"url": raw, "label": f"{kind}_{index + 1}"}
    elif isinstance(raw, dict) and raw.get("url"):
        route = dict(raw)
        route["url"] = str(raw["url"])
        route["label"] = str(raw.get("label") or f"{kind}_{index + 1}")
    else:
        return None
    if not route_is_active(route):
        return None
    route["kind"] = kind
    prefix = "campaign" if kind == "promotion" else "segment"
    route["method_key"] = f"{prefix}:{route['label']}"
    route["priority"] = int(route.get("priority", 100 if kind == "promotion" else 0))
    route["yield_score"] = 0.0
    route["priority_band"] = 0
    return route


def _campaigns_for(cat: dict, dynamic: list[dict] | None = None) -> list[Any]:
    configured = [*list(cat.get("campaign_urls", [])), *(dynamic or [])]
    seen, out = set(), []
    for raw in configured:
        url = raw if isinstance(raw, str) else raw.get("url") if isinstance(raw, dict) else None
        marker = str(url or "").rstrip("/").lower()
        if marker and marker not in seen:
            seen.add(marker)
            out.append(raw)
    return out


def _active_campaign_urls(cat: dict, dynamic: list[dict] | None = None) -> set[str]:
    urls = set()
    for index, raw in enumerate(_campaigns_for(cat, dynamic)):
        route = _route(raw, index, "promotion")
        if route is not None:
            urls.add(str(route["url"]).rstrip("/").lower())
    return urls


def promotion_priority_band(attempts: int, yield_score: float) -> int:
    attempts = max(0, int(attempts))
    yield_score = max(0.0, float(yield_score))
    if attempts < 2:
        return 2
    if yield_score >= 2.0:
        return 1
    return 0


def _discovery_attempts(tracker_module, store: str, method_key: str) -> int:
    try:
        stats = tracker_module.bucket(store).get("discovery", {}).get(method_key, {})
        return int(stats.get("attempts", 0))
    except Exception:
        return 0


def _campaign_routes_from_html(html: str, base_url: str) -> list[dict]:
    """Descobre cards públicos de promoção que apontam para uma listagem."""
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    base_host = urlparse(base_url).netloc.lower()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, str(anchor.get("href") or ""))
        if urlparse(href).netloc.lower() != base_host:
            continue
        node, context = anchor, anchor.get_text(" ", strip=True)
        for _ in range(5):
            parent = getattr(node, "parent", None)
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            if len(text) <= 3500:
                context = text
            if any(token in text.lower() for token in ("desconto", "ganha", "cupão", "cupao", "oferta", "cashback", "talão", "talao", "sem juros")):
                context = text
                break
            node = parent
        promotions = promotion_value.parse_promotion_text(
            context, source="promotion_watch", eligibility="campaign_listing"
        )
        if not promotions:
            continue
        marker = href.rstrip("/").lower()
        if marker in seen:
            continue
        seen.add(marker)
        primary = promotions[0]
        route = {
            "label": f"auto_{hashlib.sha1(marker.encode('utf-8')).hexdigest()[:8]}",
            "url": href,
            "priority": 125,
            "promotion": primary,
            "auto_detected": True,
        }
        if primary.get("valid_from"):
            route["active_from"] = primary["valid_from"]
        if primary.get("valid_until"):
            route["expires_at"] = primary["valid_until"]
        if route_is_active(route):
            out.append(route)
    return out[:12]


def _promo_for_url(cat: dict, url: str, dynamic: list[dict] | None = None) -> dict | None:
    marker = str(url or "").rstrip("/").lower()
    for index, raw in enumerate(_campaigns_for(cat, dynamic)):
        route = _route(raw, index, "promotion")
        if route is None or str(route["url"]).rstrip("/").lower() != marker:
            continue
        promo = route.get("promotion")
        if isinstance(promo, dict):
            value = dict(promo)
            value.setdefault("source", f"campaign:{route['label']}")
            value.setdefault("eligibility", "campaign_listing")
            value.setdefault("applicable", True)
            if route.get("active_from"):
                value.setdefault("valid_from", route["active_from"])
            if route.get("expires_at"):
                value.setdefault("valid_until", route["expires_at"])
            return value
    return None


def _promo_assessment(tracker_module, item: dict, spec: dict, weights: dict, settings: dict):
    price = item.get("preco")
    if price is None:
        return None, None
    econ = promotion_value.economics(item.get("promotions"), float(price))
    item["promotion_economics"] = econ
    effective = float(econ["effective_checkout_price"])
    if effective >= float(price) - 0.01:
        return None, None
    assessment = tracker_module.score_allow_unknown(spec, effective, weights, settings)
    if assessment.get("status") != "ACEITE":
        return None, None
    tier = tracker_module.scraper.tier_from_value(assessment["value_score"], settings)
    item["promotion_value_score"] = assessment["value_score"]
    item["promotion_score_ranking"] = assessment["score_ranking"]
    item["promotion_tier"] = tier
    return assessment, tier


def install(tracker_module) -> None:
    """Promo Intelligence V2 sem alterar preço, Value ou tier canónicos."""
    if getattr(tracker_module, "_PROMOTION_GUARD_INSTALLED", False):
        return

    base_discover_html = tracker_module._discover_html
    base_candidate_priority = tracker_module.candidate_priority
    base_adaptive_fetch = getattr(tracker_module, "adaptive_fetch", None)
    base_scan_store = getattr(tracker_module, "scan_store", None)
    base_enrich = getattr(tracker_module, "enrich", None)
    base_record_offer = getattr(tracker_module, "record_offer", None)
    base_maybe_alert = getattr(tracker_module, "maybe_alert", None)

    dynamic_by_store: dict[str, list[dict]] = {}
    page_html: dict[str, str] = {}
    promo_alerts_sent = 0

    def dynamic_for(store: str) -> list[dict]:
        return dynamic_by_store.get(str(store), [])

    def discovery_routes(cat: dict, store: str) -> list[dict]:
        routes: list[dict] = []
        for index, raw in enumerate(_campaigns_for(cat, dynamic_for(store))):
            route = _route(raw, index, "promotion")
            if route is not None:
                route["yield_score"] = tracker_module.discovery_score(store, route["method_key"])
                attempts = _discovery_attempts(tracker_module, store, route["method_key"])
                route["attempts"] = attempts
                route["priority_band"] = promotion_priority_band(attempts, route["yield_score"])
                routes.append(route)
        for index, raw in enumerate(cat.get("extra_discovery_urls", [])):
            route = _route(raw, index, "segment")
            if route is not None:
                route["yield_score"] = tracker_module.discovery_score(store, route["method_key"])
                route["attempts"] = _discovery_attempts(tracker_module, store, route["method_key"])
                route["priority_band"] = 0
                routes.append(route)
        return sorted(
            routes,
            key=lambda route: (
                -int(route.get("priority_band", 0)),
                -float(route.get("yield_score", 0.0)),
                -int(route.get("priority", 0)),
                route["label"],
            ),
        )

    def discover_html(response, route_cat, target, candidates, source, stat):
        current = str(route_cat.get("url") or "").rstrip("/").lower()
        store = str(route_cat.get("loja") or "")
        effective_source = source
        before = {
            url: PROMOTION_SOURCE in set(row.get("discovery_sources", []))
            for url, row in candidates.items()
        }
        if current and current in _active_campaign_urls(route_cat, dynamic_for(store)):
            effective_source = PROMOTION_SOURCE
            stat.setdefault("fontes_descoberta", {}).setdefault(PROMOTION_SOURCE, 0)
        gained = base_discover_html(response, route_cat, target, candidates, effective_source, stat)
        if effective_source == PROMOTION_SOURCE:
            promo = _promo_for_url(route_cat, current, dynamic_for(store))
            if promo:
                for url, row in candidates.items():
                    now_promoted = PROMOTION_SOURCE in set(row.get("discovery_sources", []))
                    if now_promoted and not before.get(url, False):
                        row["promotions"] = promotion_value.dedupe([*(row.get("promotions") or []), promo])
        return gained

    def candidate_priority(item: dict, weights: dict, settings: dict) -> float:
        base = float(base_candidate_priority(item, weights, settings))
        if PROMOTION_SOURCE in set(item.get("discovery_sources", [])):
            base += max(0.0, min(15.0, float(settings.get("promotion_candidate_priority_bonus", 6.0))))
        try:
            price = float(item.get("preco"))
            econ = promotion_value.economics(item.get("promotions"), price)
            pct = 100.0 * float(econ["checkout_discount_eur"]) / max(1.0, price)
            base += min(float(settings.get("promotion_economic_priority_bonus_max", 18.0)), pct)
        except (TypeError, ValueError, KeyError):
            pass
        return round(base, 3)

    if base_adaptive_fetch is not None:
        def adaptive_fetch(url, config, timeout_s=8.0, *, store=None, method="page", **_ignored):
            response, profile, outcome = base_adaptive_fetch(
                url, config, timeout_s, store=store, method=method
            )
            if response is not None and response.status_code < 400 and str(method).startswith("product"):
                for key in {str(url), str(getattr(response, "url", url))}:
                    page_html[key] = response.text
            return response, profile, outcome
        tracker_module.adaptive_fetch = adaptive_fetch

    if base_scan_store is not None and base_adaptive_fetch is not None:
        def scan_store(cat: dict, config: dict, settings: dict):
            store = str(cat.get("loja") or "")
            detected: list[dict] = []
            for index, watch in enumerate(cat.get("promotion_watch_urls", [])):
                watch_url = str(watch.get("url") if isinstance(watch, dict) else watch)
                if not watch_url or not tracker_module.budget_available(store):
                    continue
                response, _profile, _outcome = tracker_module.adaptive_fetch(
                    watch_url, config, 7, store=store, method=f"promotion_watch:{index + 1}"
                )
                if response is not None and response.status_code < 400:
                    detected.extend(_campaign_routes_from_html(response.text, watch_url))
            dynamic_by_store[store] = _campaigns_for({}, detected)
            items, stat = base_scan_store(cat, config, settings)
            stat["promotion_watch_detected"] = len(dynamic_by_store.get(store, []))
            return items, stat
        tracker_module.scan_store = scan_store

    if base_enrich is not None:
        def enrich(item: dict, config: dict):
            result, status = base_enrich(item, config)
            if status.get("error"):
                return result, status
            promotions = [*(item.get("promotions") or []), *(result.get("promotions") or [])]
            page_url = str((result.get("specs") or {}).get("page_url") or result.get("url") or item.get("url") or "")
            html = page_html.pop(page_url, None) or page_html.pop(str(item.get("url") or ""), None)
            if html:
                promotions.extend(
                    promotion_value.extract_product_promotions(
                        html,
                        store=str(result.get("loja") or item.get("loja") or ""),
                        title=str(result.get("titulo") or ""),
                    )
                )
            store_cat = next(
                (row for row in config.get("category_urls", []) if row.get("loja") == result.get("loja")), {}
            )
            for promo in store_cat.get("store_promotions", []):
                if isinstance(promo, dict) and promotion_value.is_active(promo):
                    promotions.append(promo)
            promotions = promotion_value.dedupe(promotions)
            if promotions:
                result["promotions"] = promotions
                if result.get("preco") is not None:
                    result["promotion_economics"] = promotion_value.economics(promotions, float(result["preco"]))
            return result, status
        tracker_module.enrich = enrich

    if base_record_offer is not None:
        def record_offer(history, item, spec, assessment, tier):
            previous, key = base_record_offer(history, item, spec, assessment, tier)
            if item.get("promotions"):
                config = tracker_module.load_json(tracker_module.CONFIG_PATH)
                econ = promotion_value.economics(item.get("promotions"), float(item["preco"]))
                promo_assessment, promo_tier = _promo_assessment(
                    tracker_module, item, spec, config.get("weights", {}), config.get("settings", {})
                )
                entries = history.get("offers", {}).get(key, [])
                if entries:
                    entries[-1]["promotions"] = promotion_value.dedupe(item.get("promotions"))
                    entries[-1]["promotion_economics"] = econ
                    entries[-1]["promotion_fingerprint"] = promotion_value.fingerprint(item.get("promotions"), float(item["preco"]))
                    if promo_assessment:
                        entries[-1]["promotion_value_score"] = promo_assessment["value_score"]
                        entries[-1]["promotion_score_ranking"] = promo_assessment["score_ranking"]
                        entries[-1]["promotion_tier"] = promo_tier
            return previous, key
        tracker_module.record_offer = record_offer

    if base_maybe_alert is not None:
        def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
            nonlocal promo_alerts_sent
            promotions = promotion_value.dedupe(item.get("promotions"))
            if not promotions:
                return base_maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings)

            econ = promotion_value.economics(promotions, float(item["preco"]))
            config = tracker_module.load_json(tracker_module.CONFIG_PATH)
            promo_assessment, promo_tier = _promo_assessment(
                tracker_module, item, spec, config.get("weights", {}), settings
            )
            order = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}
            effective_tier = promo_tier if order.get(promo_tier or "", 0) > order.get(tier or "", 0) else tier
            min_notify = str(settings.get("alerta_min_tier", "OURO")).upper()
            if order.get(effective_tier or "", 0) < order.get(min_notify, 3):
                return base_maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings)

            prior = history["alert_state"].get(alert_key) or {}
            promo_fp = promotion_value.fingerprint(promotions, float(item["preco"]))
            changed = prior.get("promotion_fingerprint") != promo_fp
            material = float(econ["checkout_discount_eur"]) >= float(settings.get("promotion_alert_min_eur", 25.0))
            if changed and material and promo_alerts_sent < int(settings.get("max_promotion_alerts_per_run", 5)):
                labels = [str(p.get("title") or p.get("kind")) for p in promotions if promotion_value.is_active(p)]
                message = (
                    f"{item['titulo']}\n"
                    f"Loja: {item['loja']} | Preço anunciado: {float(item['preco']):.2f}€\n"
                    f"Promo: {'; '.join(labels[:3])}\n"
                    f"Desconto confirmado: {float(econ['checkout_discount_eur']):.2f}€ | Checkout estimado: {float(econ['effective_checkout_price']):.2f}€\n"
                    f"Value normal: {assessment['value_score']:.1f} | Value promo: {(promo_assessment or assessment)['value_score']:.1f}\n"
                    f"Tier normal/promo: {tier or '—'} / {promo_tier or tier or '—'}\n"
                    f"{item['url']}"
                )
                sent = tracker_module.ntfy_send(
                    f"🏷️ PROMO {effective_tier}: {item['titulo']}", message,
                    priority=4, tags=["computer", "moneybag"]
                )
                if sent:
                    promo_alerts_sent += 1
                    history["alert_state"][alert_key] = {
                        "timestamp": tracker_module.now_iso(),
                        "price": item["preco"],
                        "value_score": assessment["value_score"],
                        "tier": tier,
                        "promotion_fingerprint": promo_fp,
                        "promotion_checkout_price": econ["effective_checkout_price"],
                        "promotion_tier": promo_tier,
                    }
                    return True, False
            return base_maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings)
        tracker_module.maybe_alert = maybe_alert

    tracker_module.discovery_routes = discovery_routes
    tracker_module._discover_html = discover_html
    tracker_module.candidate_priority = candidate_priority
    tracker_module.promotion_economics = promotion_value.economics
    tracker_module.promotion_fingerprint = promotion_value.fingerprint
    tracker_module._PROMOTION_GUARD_INSTALLED = True
