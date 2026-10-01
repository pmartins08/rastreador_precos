"""Availability is an offer gate, never a technical-score bonus."""
import re
import threading
from datetime import datetime, timezone
from bs4 import BeautifulSoup

_LOCAL = threading.local()


def availability(item, html, tracker):
    if item.get('stock') is False:
        return {'status':'OUT_OF_STOCK', 'eligible':False, 'source':'live_stock'}
    soup = BeautifulSoup(html or '', 'html.parser')
    h1 = soup.find('h1')
    scope = h1.find_parent(id=re.compile(r'^ProductInfo-')) if h1 else None
    scope = scope or soup.find('main') or soup
    text = tracker.scraper.norm(scope.get_text(' ', strip=True))
    if item.get('loja') == 'Darty':
        if re.search(r'entrega ao dom[ií]cilio indisponivel', text):
            return {'status':'STORE_ONLY_UNVERIFIED', 'eligible':False, 'source':'product_fulfilment', 'home_delivery':False}
        if re.search(r'entrega ao dom[ií]cilio disponivel|entrega\s+(?:ao domicilio\s+)?(?:(?:em|entre)\s+)?\d', text):
            return {'status':'AVAILABLE', 'eligible':True, 'source':'product_fulfilment', 'home_delivery':True}
        return {'status':'AVAILABILITY_UNCONFIRMED', 'eligible':False, 'source':'product_fulfilment_missing'}
    if item.get('stock') is True:
        return {'status':'AVAILABLE', 'eligible':True, 'source':'live_stock'}
    return {'status':'AVAILABILITY_UNCONFIRMED', 'eligible':False, 'source':'stock_missing'}


def fresh(data, settings):
    if not isinstance(data, dict) or not data.get('checked_at'):
        return False
    try:
        stamp = datetime.fromisoformat(str(data['checked_at']).replace('Z', '+00:00'))
        return 0 <= (datetime.now(timezone.utc) - stamp).total_seconds() < float(settings.get('availability_ttl_hours', 6)) * 3600
    except (TypeError, ValueError):
        return False


def install(tracker):
    if getattr(tracker, '_AVAILABILITY_GUARD_INSTALLED', False):
        return
    fetch, enrich = tracker.adaptive_fetch, tracker.enrich
    select, apply, score = tracker.select_with_cache, tracker.apply_exact_market_price_evidence, tracker.score_allow_unknown
    record, needs = tracker.record_offer, tracker.needs_price_refresh

    def cached(item):
        return tracker.bucket(item.get('loja')).get('availability_by_url', {}).get(item.get('url'))

    def adaptive_fetch(url, config, timeout_s=8, *, store=None, method='page', **kwargs):
        response, profile, outcome = fetch(url, config, timeout_s, store=store, method=method, **kwargs)
        if str(method).startswith('product') and response is not None and outcome == 'http_success':
            _LOCAL.html = str(getattr(response, 'text', '') or '')
        return response, profile, outcome

    def enrich_offer(item, config):
        _LOCAL.html = None
        result, status = enrich(item, config)
        html = getattr(_LOCAL, 'html', None)
        _LOCAL.html = None
        if not status.get('error') and html:
            data = availability(result, html, tracker)
            data['checked_at'] = tracker.now_iso()
            result['offer_availability'] = data
            cache = tracker.bucket(result.get('loja')).setdefault('availability_by_url', {})
            cache[result.get('url')] = data
            while len(cache) > 500:
                cache.pop(next(iter(cache)))
        return result, status

    def select_offers(items, spec_cache, limit, weights, settings):
        selected = select(items, spec_cache, limit, weights, settings)
        reserved = 0
        # Darty's aggregate available=true includes collection in distant stores.
        # Probe before trusting it; preserve a bounded route for cached products.
        for item in selected:
            if item.get('loja') == 'Darty' and not fresh(cached(item), settings) and item.get('url') in spec_cache and reserved < 6:
                spec_cache.pop(item['url'], None)
                item.pop('specs', None)
                reserved += 1
        return selected

    def apply_market(records, settings):
        result = apply(records, settings)
        for row in records:
            item, spec = row.get('item', {}), row.get('spec')
            if not isinstance(spec, dict):
                continue
            data = item.get('offer_availability') or cached(item)
            if not fresh(data, settings):
                data = availability(item, '', tracker)
            if item.get('stock') is False:
                data = {'status':'OUT_OF_STOCK', 'eligible':False, 'source':'live_stock'}
            spec['offer_availability'] = dict(data)
            item['offer_availability'] = dict(data)
        return result

    def score_offer(spec, price, weights, settings):
        data = spec.get('offer_availability')
        if isinstance(data, dict) and data.get('eligible') is not True:
            from rejection_guard import _CURRENT_REJECTION_REASON
            _CURRENT_REJECTION_REASON.set('availability_not_eligible')
            return {'status':'REJEITADO', 'alertas':['Disponibilidade elegível não confirmada: ' + str(data.get('status'))], 'offer_availability':data}
        return score(spec, price, weights, settings)

    def record_offer(history, item, spec, assessment, tier):
        previous, key = record(history, item, spec, assessment, tier)
        entries = history.get('offers', {}).get(key, [])
        if entries:
            entries[-1]['offer_availability'] = item.get('offer_availability')
            entries[-1]['brain_policy'] = assessment.get('brain_policy')
        return previous, key

    def needs_refresh(previous, item, settings, **kwargs):
        return (item.get('loja') == 'Darty' and not fresh(cached(item), settings)) or needs(previous, item, settings, **kwargs)

    tracker.adaptive_fetch, tracker.enrich = adaptive_fetch, enrich_offer
    tracker.select_with_cache, tracker.apply_exact_market_price_evidence = select_offers, apply_market
    tracker.score_allow_unknown, tracker.record_offer = score_offer, record_offer
    tracker.needs_price_refresh = needs_refresh
    tracker._AVAILABILITY_GUARD_INSTALLED = True
