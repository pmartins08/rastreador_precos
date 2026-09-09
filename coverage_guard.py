from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _timestamp_age_hours(value: Any, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - stamp).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def _cached_candidate(previous: dict, store: str, *, force_live_price: bool) -> dict | None:
    if not isinstance(previous, dict):
        return None
    url = previous.get("url")
    title = previous.get("titulo")
    price = previous.get("price")
    if not url or not title or price is None or previous.get("stock") is False:
        return None
    try:
        price_value = float(price)
    except (TypeError, ValueError):
        return None

    out = {
        "loja": store,
        "titulo": str(title),
        "preco": price_value,
        "url": str(url),
        "stock": previous.get("stock"),
        "detail_source": "coverage_cache_seed",
        "_coverage_force_live_price": bool(force_live_price),
    }
    for field in ("ean", "mpn", "sku", "identity_checked_at"):
        if previous.get(field):
            out[field] = previous[field]
    return out


def install(tracker_module) -> None:
    """Reduz I/O repetido e dá fallback seguro a lojas instáveis.

    Regras:
    - URLs que continuam presentes no sitemap e já são conhecidas podem reutilizar
      o último preço por uma janela curta, evitando reabrir dezenas de fichas.
    - URLs novas continuam a receber probes live, mas com limite próprio.
    - Se uma loja conhecida colapsar para zero candidatos, uma pequena amostra do
      histórico pode regressar como lead, mas fica marcada para confirmação live.
    - Um lead marcado para confirmação live nunca pode entrar no ranking usando a
      spec cached se a confirmação não acontecer.

    Esta camada não altera cérebro, Value, tiers, Price Guard, Market Guard ou ntfy.
    """
    if getattr(tracker_module, "_COVERAGE_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    base_discover_sitemap_urls = tracker_module.discover_sitemap_urls
    base_needs_price_refresh = tracker_module.needs_price_refresh
    base_select_with_cache = tracker_module.select_with_cache
    base_score_allow_unknown = tracker_module.score_allow_unknown

    cache_holder: dict[str, dict] = {}

    def offer_cache() -> dict[str, dict]:
        if not cache_holder:
            history = tracker_module.compact_history(tracker_module.load_history())
            cache_holder.update(tracker_module.latest_offer_by_url(history))
        return cache_holder

    def valid_previous(previous: dict | None, store: str, settings: dict) -> bool:
        if not isinstance(previous, dict) or previous.get("loja") != store:
            return False
        if previous.get("stock") is False:
            return False
        try:
            price = float(previous.get("price"))
        except (TypeError, ValueError):
            return False
        minimum = float(settings.get("preco_minimo_global", 250.0))
        hard = float(settings.get("budget_hard", 1500.0))
        return minimum <= price <= hard and tracker_module.scraper.eligible(previous.get("titulo", ""))

    def scan_store(cat: dict, config: dict, settings: dict):
        store = str(cat["loja"])
        known = offer_cache()
        captured_sitemap_urls: list[str] = []
        current_discover = tracker_module.discover_sitemap_urls

        # A função base continua a descobrir o sitemap normalmente. Apenas evitamos
        # que volte a abrir, durante a descoberta, todas as URLs que já conhecemos.
        def discover_sitemap_urls(*args, **kwargs):
            urls = list(current_discover(*args, **kwargs))
            captured_sitemap_urls[:] = urls
            novel = [url for url in urls if not valid_previous(known.get(url), store, settings)]
            limit = max(0, int(cat.get("sitemap_new_probe_limit", cat.get("sitemap_probe_limit", 6))))
            return novel[:limit]

        tracker_module.discover_sitemap_urls = discover_sitemap_urls
        try:
            items, stat = base_scan_store(cat, config, settings)
        finally:
            tracker_module.discover_sitemap_urls = current_discover

        urls_in_result = {str(item.get("url")) for item in items if item.get("url")}
        stat.setdefault("fontes_descoberta", {}).setdefault("sitemap_cache", 0)
        stat["fontes_descoberta"].setdefault("historico", 0)
        stat["sitemap_urls"] = max(int(stat.get("sitemap_urls", 0)), len(captured_sitemap_urls))

        short_ttl = max(0.0, float(cat.get("sitemap_cache_price_ttl_hours", 7.0)))
        cache_limit = max(0, int(cat.get("sitemap_cache_reuse_limit", 24)))
        reused = 0
        for url in captured_sitemap_urls:
            if reused >= cache_limit or url in urls_in_result:
                continue
            previous = known.get(url)
            if not valid_previous(previous, store, settings):
                continue
            age = _timestamp_age_hours(previous.get("timestamp"))
            force_live = age is None or age > short_ttl
            candidate = _cached_candidate(previous, store, force_live_price=force_live)
            if candidate is None:
                continue
            candidate["discovery_sources"] = ["sitemap_cache"]
            items.append(candidate)
            urls_in_result.add(url)
            reused += 1
            stat["fontes_descoberta"]["sitemap_cache"] += 1

        # Resiliência a falhas transitórias (ex.: PCDiga): se a descoberta caiu
        # abaixo do mínimo, reintroduzimos apenas leads recentes e obrigamos refresh.
        fallback_below = max(0, int(cat.get("history_fallback_below", 0)))
        fallback_limit = max(0, int(cat.get("history_fallback_limit", 0)))
        fallback_max_age = max(1.0, float(cat.get("history_fallback_max_age_hours", 36.0)))
        if fallback_limit and len(items) < fallback_below:
            choices = []
            for previous in known.values():
                if not valid_previous(previous, store, settings):
                    continue
                url = str(previous.get("url") or "")
                if not url or url in urls_in_result:
                    continue
                age = _timestamp_age_hours(previous.get("timestamp"))
                if age is None or age > fallback_max_age:
                    continue
                choices.append((age, -float(previous.get("value_score") or 0.0), previous))
            for _age, _negative_value, previous in sorted(choices)[:fallback_limit]:
                candidate = _cached_candidate(previous, store, force_live_price=True)
                if candidate is None:
                    continue
                candidate["discovery_sources"] = ["historico"]
                items.append(candidate)
                urls_in_result.add(candidate["url"])
                stat["fontes_descoberta"]["historico"] += 1

        stat["coverage_cache_reused"] = reused
        stat["candidatos"] = len(items)
        if items:
            stat["bloqueada"] = False
        return items, stat

    def needs_price_refresh(previous_meta, item, settings, **kwargs):
        if item.get("_coverage_force_live_price"):
            return True
        return base_needs_price_refresh(previous_meta, item, settings, **kwargs)

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        # Se um lead só existe por fallback histórico, a spec cached recebe um
        # marcador transitório. Um refresh live substitui essa spec; sem refresh,
        # score_allow_unknown rejeita-a e impede ranking/alerta com preço stale.
        for item in items:
            if not item.get("_coverage_force_live_price"):
                continue
            url = item.get("url")
            cached = spec_cache.get(url) if url else None
            if isinstance(cached, dict):
                safe = dict(cached)
                safe["_coverage_force_live_price"] = True
                spec_cache[url] = safe
        return base_select_with_cache(items, spec_cache, max_items, weights, settings)

    def score_allow_unknown(spec, price, weights, settings):
        if isinstance(spec, dict) and spec.get("_coverage_force_live_price"):
            return {
                "status": "REJEITADO",
                "alertas": ["Preço de fallback histórico requer confirmação live nesta run."],
            }
        return base_score_allow_unknown(spec, price, weights, settings)

    tracker_module.scan_store = scan_store
    tracker_module.needs_price_refresh = needs_price_refresh
    tracker_module.select_with_cache = select_with_cache
    tracker_module.score_allow_unknown = score_allow_unknown
    tracker_module._COVERAGE_GUARD_INSTALLED = True
