from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from gpu_guard import TierAwareValue
import promotion_value_guard as promotion_value


_RP_CAMPAIGN_PATH = "/destaque/6a20120dc7e006.23735122"
_RP_FILTER_LABEL = "50_por_250_set_2026_portateis"


def _confirmed_checkout_promotion(item: dict) -> bool:
    price = item.get("preco")
    if price is None:
        return False
    promotions = promotion_value.dedupe(item.get("promotions") or [])
    if not promotions:
        return False
    economics = promotion_value.economics(promotions, float(price))
    return float(economics.get("checkout_discount_eur") or 0.0) > 0.0


def _assessment_copy(assessment: dict) -> dict:
    """Copia um assessment sem tentar reconstruir subclasses de float.

    TierAwareValue é intencionalmente um float enriquecido e não suporta
    deepcopy sem o gaming_score. Aqui só precisamos de uma cópia isolada das
    estruturas mutáveis que podemos alterar no resultado promocional.
    """
    result = dict(assessment)
    for key in ("detalhes", "gpu_tier_influence", "gpu_tier_guard"):
        value = result.get(key)
        if isinstance(value, dict):
            result[key] = dict(value)
    for key in ("alertas", "brain_corrections"):
        value = result.get(key)
        if isinstance(value, list):
            result[key] = list(value)
    return result


def _revalue_from_accepted(tracker_module, assessment: dict, checkout_price: float, settings: dict) -> dict:
    """Recalcula apenas o efeito de preço após uma promoção já confirmada.

    A evidência da ficha continua a validar o preço observado. O checkout
    promocional não volta a passar pelo Price Guard como se fosse um segundo
    preço anunciado; reutiliza o ranking técnico já aceite e recalcula apenas
    Value. Não atribui exceptional-deal bonus porque esse bónus exige preço HIGH
    visível/confirmado na ficha.
    """
    if not isinstance(assessment, dict) or assessment.get("status") != "ACEITE":
        return _assessment_copy(assessment) if isinstance(assessment, dict) else {"status": "REJEITADO"}

    ranking = assessment.get("score_ranking")
    if ranking is None:
        return {"status": "REJEITADO", "alertas": ["Ranking técnico ausente para Value promocional."]}

    originals = getattr(tracker_module.scraper, "_PRICE_GUARD_ORIGINALS", {})
    base_value_score = originals.get("value_score")
    if not callable(base_value_score):
        # Fallback compatível: UNKNOWN impede o Price Guard de somar o bónus
        # extraordinário caso a instalação futura deixe de expor originals.
        def base_value_score(rank, price, cfg):
            safe = dict(cfg)
            safe["_price_confidence"] = "UNKNOWN"
            return tracker_module.scraper.value_score(rank, price, safe)

    raw_value = float(base_value_score(float(ranking), float(checkout_price), settings))
    details = assessment.get("detalhes") if isinstance(assessment.get("detalhes"), dict) else {}
    gaming = float(details.get("Gaming", 0.0) or 0.0)
    wrapped = TierAwareValue(raw_value, gaming_score=gaming)

    result = _assessment_copy(assessment)
    result["value_score"] = wrapped
    result["value_score_sem_bonus"] = round(raw_value, 1)
    result["exceptional_deal_bonus"] = 0.0
    result["promotion_checkout_price"] = round(float(checkout_price), 2)
    result["promotion_revalue_basis"] = "ranking_tecnico_aceite+checkout_promocional_confirmado"
    result["gpu_tier_influence"] = {
        "raw_value": round(raw_value, 3),
        "gaming_score": round(wrapped.gaming_score, 3),
        "multiplier": round(wrapped.tier_multiplier, 6),
        "tier_score": round(wrapped.tier_score, 3),
    }
    return result


def _radio_popular_laptop_campaign(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    if parsed.netloc.lower().removeprefix("www.") != "radiopopular.pt":
        return str(url)
    if parsed.path.rstrip("/") != _RP_CAMPAIGN_PATH:
        return str(url)
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"filters[category_n2_name][]", "filters[disponibilidade][]"}
    ]
    pairs.extend(
        [
            ("filters[category_n2_name][]", "Computadores Portáteis"),
            ("filters[disponibilidade][]", "Ocultar Produtos Indisponíveis"),
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), parsed.fragment))


def _original_campaign_url(cat: dict, current_url: str) -> str | None:
    parsed = urlsplit(str(current_url or ""))
    if parsed.netloc.lower().removeprefix("www.") != "radiopopular.pt":
        return None
    if parsed.path.rstrip("/") != _RP_CAMPAIGN_PATH:
        return None
    for raw in cat.get("campaign_urls", []):
        if not isinstance(raw, dict) or not raw.get("url"):
            continue
        candidate = urlsplit(str(raw["url"]))
        if candidate.path.rstrip("/") == _RP_CAMPAIGN_PATH:
            return str(raw["url"])
    return None


def install(tracker_module) -> None:
    """Fecha a lacuna entre descoberta promocional e preço/alerta operacional.

    A landing promocional pode conter preços auxiliares plausíveis. Qualquer
    candidato com desconto de checkout confirmado perde a cache apenas nesta
    run e é reaberto na ficha do produto antes de entrar no histórico.
    """
    if getattr(tracker_module, "_PROMOTION_RUNTIME_GUARD_INSTALLED", False):
        return

    base_discovery_routes = tracker_module.discovery_routes
    base_discover_html = tracker_module._discover_html
    base_candidate_priority = tracker_module.candidate_priority
    base_select_with_cache = tracker_module.select_with_cache
    base_enrich = tracker_module.enrich
    base_needs_price_refresh = tracker_module.needs_price_refresh
    base_record_offer = tracker_module.record_offer
    base_maybe_alert = tracker_module.maybe_alert

    eligibility_alerts_sent = 0

    def discovery_routes(cat: dict, store: str) -> list[dict]:
        routes = base_discovery_routes(cat, store)
        if str(store) != "Radio Popular":
            return routes
        for route in routes:
            if str(route.get("label")) != "50_por_250_set_2026":
                continue
            route["url"] = _radio_popular_laptop_campaign(str(route["url"]))
            route["label"] = _RP_FILTER_LABEL
            # Novo método = nova aprendizagem; não herda o yield zero da landing
            # não filtrada que só mostrava eletrodomésticos na primeira página.
            route["method_key"] = f"campaign:{_RP_FILTER_LABEL}"
            route["priority"] = max(180, int(route.get("priority", 0)))
            route["priority_band"] = max(3, int(route.get("priority_band", 0)))
        return sorted(
            routes,
            key=lambda route: (
                -int(route.get("priority_band", 0)),
                -float(route.get("yield_score", 0.0)),
                -int(route.get("priority", 0)),
                str(route.get("label") or ""),
            ),
        )

    def discover_html(response, route_cat, target, candidates, source, stat):
        original = _original_campaign_url(route_cat, str(route_cat.get("url") or ""))
        if original:
            proxy = dict(route_cat)
            proxy["url"] = original
            return base_discover_html(response, proxy, target, candidates, source, stat)
        return base_discover_html(response, route_cat, target, candidates, source, stat)

    def candidate_priority(item: dict, weights: dict, settings: dict) -> float:
        base = float(base_candidate_priority(item, weights, settings))
        if _confirmed_checkout_promotion(item):
            # Só pré-ranking. Garante que uma campanha curta não perde os seus
            # produtos para a cauda do catálogo; não toca em Value/tier.
            base += float(settings.get("promotion_confirmed_selection_bonus", 120.0))
        return round(base, 3)

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        # A cache de hardware permanece no history.json; só é retirada do mapa
        # em memória para forçar uma ficha live nesta run promocional.
        for item in items:
            if _confirmed_checkout_promotion(item) and item.get("url"):
                spec_cache.pop(item["url"], None)
        return base_select_with_cache(items, spec_cache, max_items, weights, settings)

    def enrich(item: dict, config: dict):
        probe = item
        if _confirmed_checkout_promotion(item):
            probe = dict(item)
            # Nunca deixa um preço auxiliar da landing sobreviver à ficha live.
            probe["preco"] = None
            probe["promotion_price_requires_live"] = True
        result, status = base_enrich(probe, config)
        if not status.get("error") and _confirmed_checkout_promotion(item):
            result["promotion_price_live_confirmed"] = True
        return result, status

    def needs_price_refresh(previous_meta, item, settings, *, current_time=None):
        if _confirmed_checkout_promotion(item):
            return True
        return base_needs_price_refresh(
            previous_meta, item, settings, current_time=current_time
        )

    def record_offer(history, item, spec, assessment, tier):
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        promotions = promotion_value.dedupe(item.get("promotions") or [])
        if promotions and item.get("preco") is not None:
            economics = promotion_value.economics(promotions, float(item["preco"]))
            config = tracker_module.load_json(tracker_module.CONFIG_PATH)
            promo_assessment = _revalue_from_accepted(
                tracker_module,
                assessment,
                float(economics["effective_checkout_price"]),
                config.get("settings", {}),
            )
            promo_tier = (
                tracker_module.scraper.tier_from_value(
                    promo_assessment["value_score"], config.get("settings", {})
                )
                if promo_assessment.get("status") == "ACEITE"
                else None
            )
            entries = history.get("offers", {}).get(key, [])
            if entries and isinstance(entries[-1], dict):
                entries[-1]["promotion_discount_eur"] = economics["checkout_discount_eur"]
                entries[-1]["promotion_checkout_price"] = economics["effective_checkout_price"]
                entries[-1]["promotion_economic_price"] = economics["effective_economic_price"]
                entries[-1]["promotion_eligibility_fingerprint"] = promotion_value.fingerprint(promotions)
                entries[-1]["promotion_price_live_confirmed"] = bool(
                    item.get("promotion_price_live_confirmed")
                )
                if promo_assessment.get("status") == "ACEITE":
                    entries[-1]["promotion_value_score"] = float(promo_assessment["value_score"])
                    entries[-1]["promotion_tier_score"] = round(
                        float(
                            getattr(
                                promo_assessment["value_score"],
                                "tier_score",
                                promo_assessment["value_score"],
                            )
                        ),
                        1,
                    )
                    entries[-1]["promotion_tier"] = promo_tier
                    entries[-1]["promotion_score_ranking"] = promo_assessment.get("score_ranking")
        return previous, key

    def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
        nonlocal eligibility_alerts_sent
        promotions = promotion_value.dedupe(item.get("promotions") or [])
        price = item.get("preco")
        if not promotions or price is None:
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )

        economics = promotion_value.economics(promotions, float(price))
        discount = float(economics.get("checkout_discount_eur") or 0.0)
        if discount <= 0.0:
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )

        promo_assessment = _revalue_from_accepted(
            tracker_module, assessment, float(economics["effective_checkout_price"]), settings
        )
        promo_tier = None
        if promo_assessment.get("status") == "ACEITE":
            promo_tier = tracker_module.scraper.tier_from_value(
                promo_assessment["value_score"], settings
            )

        prior = history.get("alert_state", {}).get(alert_key) or {}
        eligibility_fp = promotion_value.fingerprint(promotions)
        newly_eligible = prior.get("promotion_eligibility_fingerprint") != eligibility_fp
        prior_checkout = prior.get("promotion_checkout_price")
        checkout_improved = (
            prior_checkout is not None
            and float(economics["effective_checkout_price"])
            <= float(prior_checkout) - float(settings.get("alerta_queda_preco_eur", 5.0))
        )
        material = discount >= float(settings.get("promotion_alert_min_eur", 25.0))
        cap = int(settings.get("max_promotion_eligibility_alerts_per_run", 20))

        if (
            promo_assessment.get("status") == "ACEITE"
            and material
            and (newly_eligible or checkout_improved)
            and eligibility_alerts_sent < cap
        ):
            labels = [
                str(promo.get("title") or promo.get("kind"))
                for promo in promotions
                if promotion_value.is_active(promo)
            ]
            message = (
                f"{item['titulo']}\n"
                f"Loja: {item['loja']} | Preço confirmado: {float(price):.2f}€\n"
                f"Promo: {'; '.join(labels[:3])}\n"
                f"Desconto: {discount:.2f}€ | Checkout: {float(economics['effective_checkout_price']):.2f}€\n"
                f"Value normal: {assessment['value_score']:.1f} | Value promo: {promo_assessment['value_score']:.1f}\n"
                f"Tier normal/promo: {tier or '—'} / {promo_tier or '—'}\n"
                f"{item['url']}"
            )
            sent = tracker_module.ntfy_send(
                f"🏷️ NOVA PROMO: {item['titulo']}",
                message,
                priority=4,
                tags=["computer", "moneybag"],
            )
            if sent:
                eligibility_alerts_sent += 1
                history.setdefault("alert_state", {})[alert_key] = {
                    "timestamp": tracker_module.now_iso(),
                    "price": price,
                    "value_score": assessment["value_score"],
                    "tier": tier,
                    "promotion_eligibility_fingerprint": eligibility_fp,
                    "promotion_checkout_price": economics["effective_checkout_price"],
                    "promotion_discount_eur": discount,
                    "promotion_value_score": float(promo_assessment["value_score"]),
                    "promotion_tier_score": round(
                        float(
                            getattr(
                                promo_assessment["value_score"],
                                "tier_score",
                                promo_assessment["value_score"],
                            )
                        ),
                        1,
                    ),
                    "promotion_tier": promo_tier,
                }
                tracker_module.LOGGER.info(
                    "Promo nova | %s | %.2f€ -> %.2f€ | Value %.1f -> %.1f | tier %s -> %s",
                    item.get("loja"),
                    float(price),
                    float(economics["effective_checkout_price"]),
                    float(assessment["value_score"]),
                    float(promo_assessment["value_score"]),
                    tier or "—",
                    promo_tier or "—",
                )
                return True, False

        # A Promo Guard anterior também tem um alerta promocional baseado em
        # tier. Removemos as promoções apenas nesta chamada para cair diretamente
        # no alerta normal e evitar duplicados depois da nova elegibilidade.
        normal_item = dict(item)
        normal_item.pop("promotions", None)
        normal_item.pop("promotion_economics", None)
        return base_maybe_alert(
            history, normal_item, spec, assessment, tier, previous, alert_key, settings
        )

    tracker_module.discovery_routes = discovery_routes
    tracker_module._discover_html = discover_html
    tracker_module.candidate_priority = candidate_priority
    tracker_module.select_with_cache = select_with_cache
    tracker_module.enrich = enrich
    tracker_module.needs_price_refresh = needs_price_refresh
    tracker_module.record_offer = record_offer
    tracker_module.maybe_alert = maybe_alert
    tracker_module.promotion_revalue_assessment = lambda assessment, checkout_price, settings: _revalue_from_accepted(
        tracker_module, assessment, checkout_price, settings
    )
    tracker_module._PROMOTION_RUNTIME_GUARD_INSTALLED = True
