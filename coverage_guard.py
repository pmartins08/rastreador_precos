from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def _timestamp_age_hours(value: Any, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - stamp).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def _canonical_url(value: object) -> str:
    """Identidade de URL para cache de cobertura, ignorando tracking/query.

    Não é identidade de produto para matching. Serve apenas para perceber que
    `produto?utm=x` e `produto` são a mesma ficha pública dentro da mesma loja.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.rstrip("/")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}"


def _zero_yield_cooldown(
    stats: dict | None,
    *,
    minimum_attempts: int = 6,
    cooldown_hours: float = 18.0,
    now: datetime | None = None,
) -> bool:
    """Suspende temporariamente uma rota comprovadamente improdutiva.

    O timestamp não é atualizado enquanto a rota está suspensa, por isso ela volta
    automaticamente a ser explorada quando o cooldown termina. Nunca é um ban.
    """
    if not isinstance(stats, dict):
        return False
    if int(stats.get("attempts", 0)) < minimum_attempts:
        return False
    if int(stats.get("new_candidates", 0)) > 0:
        return False
    age = _timestamp_age_hours(stats.get("last_updated"), now=now)
    return age is not None and age < cooldown_hours


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
    - URLs equivalentes que diferem apenas em query/tracking partilham o mesmo cache.
    - URLs novas continuam a receber probes live, mas com limite próprio.
    - Se uma loja conhecida colapsar para zero candidatos, uma pequena amostra do
      histórico pode regressar como lead, mas fica marcada para confirmação live.
    - Leads de fallback que exigem confirmação recebem prioridade nos slots de
      refresh para não ficarem eternamente em cache/rejeição.
    - Um lead marcado para confirmação live nunca pode entrar no ranking usando a
      spec cached se a confirmação não acontecer.
    - Rotas/paginações que provaram repetidamente yield zero entram em cooldown e
      são reabertas automaticamente mais tarde para testar recuperação.

    Esta camada não altera cérebro, Value, tiers, Price Guard, Market Guard ou ntfy.
    """
    if getattr(tracker_module, "_COVERAGE_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    base_discovery_routes = tracker_module.discovery_routes
    base_needs_price_refresh = tracker_module.needs_price_refresh
    base_select_with_cache = tracker_module.select_with_cache
    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_candidate_priority = tracker_module.candidate_priority

    cache_holder: dict[str, dict] = {}
    canonical_holder: dict[str, dict] = {}

    def offer_cache() -> dict[str, dict]:
        if not cache_holder:
            history = tracker_module.compact_history(tracker_module.load_history())
            cache_holder.update(tracker_module.latest_offer_by_url(history))
            for previous in cache_holder.values():
                key = _canonical_url(previous.get("url"))
                if not key:
                    continue
                current = canonical_holder.get(key)
                if current is None or str(previous.get("timestamp") or "") >= str(
                    current.get("timestamp") or ""
                ):
                    canonical_holder[key] = previous
        return cache_holder

    def previous_for_url(url: object) -> dict | None:
        known = offer_cache()
        raw = str(url or "")
        return known.get(raw) or canonical_holder.get(_canonical_url(raw))

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

    def discovery_routes(cat: dict, store: str) -> list[dict]:
        routes = base_discovery_routes(cat, store)
        discovery = tracker_module.bucket(store).get("discovery", {})
        cooldown = float(cat.get("zero_yield_route_cooldown_hours", 18.0))
        minimum = int(cat.get("zero_yield_route_min_attempts", 6))
        return [
            route
            for route in routes
            if not _zero_yield_cooldown(
                discovery.get(route.get("method_key")),
                minimum_attempts=minimum,
                cooldown_hours=cooldown,
            )
        ]

    def scan_store(cat: dict, config: dict, settings: dict):
        store = str(cat["loja"])
        known = offer_cache()
        captured_sitemap_urls: list[str] = []
        current_discover = tracker_module.discover_sitemap_urls
        discovery = tracker_module.bucket(store).get("discovery", {})

        # Paginação com zero yield persistente descansa; após o cooldown, o próprio
        # timestamp antigo permite que seja testada novamente.
        effective_cat = dict(cat)
        cooldown = float(cat.get("zero_yield_route_cooldown_hours", 18.0))
        minimum = int(cat.get("zero_yield_route_min_attempts", 6))
        if _zero_yield_cooldown(
            discovery.get("pagination"),
            minimum_attempts=minimum,
            cooldown_hours=cooldown,
        ):
            effective_cat["max_category_pages"] = 1

        known_for_store = any(
            valid_previous(previous, store, settings) for previous in known.values()
        )
        if (
            not known_for_store
            and _zero_yield_cooldown(
                discovery.get("sitemap"),
                minimum_attempts=minimum,
                cooldown_hours=cooldown,
            )
        ):
            effective_cat["sitemap_enabled"] = False

        # A função base continua a descobrir o sitemap normalmente. Apenas evitamos
        # que volte a abrir, durante a descoberta, todas as URLs que já conhecemos.
        def discover_sitemap_urls(*args, **kwargs):
            urls = list(current_discover(*args, **kwargs))
            captured_sitemap_urls[:] = urls
            novel = [
                url
                for url in urls
                if not valid_previous(previous_for_url(url), store, settings)
            ]
            limit = max(
                0,
                int(
                    effective_cat.get(
                        "sitemap_new_probe_limit",
                        effective_cat.get("sitemap_probe_limit", 6),
                    )
                ),
            )
            return novel[:limit]

        tracker_module.discover_sitemap_urls = discover_sitemap_urls
        try:
            items, stat = base_scan_store(effective_cat, config, settings)
        finally:
            tracker_module.discover_sitemap_urls = current_discover

        urls_in_result = {str(item.get("url")) for item in items if item.get("url")}
        canonical_in_result = {_canonical_url(url) for url in urls_in_result if url}
        stat.setdefault("fontes_descoberta", {}).setdefault("sitemap_cache", 0)
        stat["fontes_descoberta"].setdefault("historico", 0)
        stat["sitemap_urls"] = max(int(stat.get("sitemap_urls", 0)), len(captured_sitemap_urls))

        short_ttl = max(0.0, float(cat.get("sitemap_cache_price_ttl_hours", 7.0)))
        cache_limit = max(0, int(cat.get("sitemap_cache_reuse_limit", 24)))
        reused = 0
        for url in captured_sitemap_urls:
            canonical = _canonical_url(url)
            if reused >= cache_limit or canonical in canonical_in_result:
                continue
            previous = previous_for_url(url)
            if not valid_previous(previous, store, settings):
                continue
            age = _timestamp_age_hours(previous.get("timestamp"))
            force_live = age is None or age > short_ttl
            candidate = _cached_candidate(previous, store, force_live_price=force_live)
            if candidate is None:
                continue
            candidate["discovery_sources"] = ["sitemap_cache"]
            items.append(candidate)
            urls_in_result.add(candidate["url"])
            canonical_in_result.add(_canonical_url(candidate["url"]))
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
                if not url or _canonical_url(url) in canonical_in_result:
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
                canonical_in_result.add(_canonical_url(candidate["url"]))
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

    def candidate_priority(item, weights, settings):
        score = float(base_candidate_priority(item, weights, settings))
        if item.get("_coverage_force_live_price"):
            score += float(settings.get("coverage_force_refresh_priority_bonus", 250.0))
        return score

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

    tracker_module.discovery_routes = discovery_routes
    tracker_module.scan_store = scan_store
    tracker_module.needs_price_refresh = needs_price_refresh
    tracker_module.candidate_priority = candidate_priority
    tracker_module.select_with_cache = select_with_cache
    tracker_module.score_allow_unknown = score_allow_unknown
    tracker_module._COVERAGE_GUARD_INSTALLED = True
