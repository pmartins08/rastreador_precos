from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from bs4 import BeautifulSoup


_ENGINES = {
    "brave": lambda query: f"https://search.brave.com/search?q={quote_plus(query)}&source=web",
    "yahoo": lambda query: f"https://search.yahoo.com/search?p={quote_plus(query)}",
    "duckduckgo": lambda query: f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
}

_BAD_PATH_MARKERS = (
    "/categorias/",
    "/categories/",
    "/marcas/",
    "/blog/",
    "/opinioes/",
    "/opiniones/",
    "/avaliacoes/",
    "/reviews/",
    "/desktops-pcs/",
    "/computadores-desktop/",
    "/placas-graficas/",
    "/monitores/",
    "/loja-",
)

_PRICE_PATTERNS = (
    re.compile(r"pre[cç]o\s*:\s*€\s*([0-9][0-9.\s]*[,.][0-9]{2})", re.I),
    re.compile(r"€\s*([0-9][0-9.\s]*[,.][0-9]{2})"),
    re.compile(r"([0-9][0-9.\s]*[,.][0-9]{2})\s*€"),
)


def _money(value: str) -> float | None:
    raw = re.sub(r"\s+", "", str(value or ""))
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if 100.0 <= price <= 10000.0 else None


def _prices(text: str) -> list[float]:
    out: list[float] = []
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(str(text or "")):
            value = _money(match.group(1))
            if value is not None and value not in out:
                out.append(value)
    return out


def _unwrap_url(href: str) -> str:
    href = str(href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href

    try:
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        for key in ("uddg", "u", "url"):
            values = query.get(key)
            if values:
                candidate = unquote(values[0])
                if candidate.startswith("http"):
                    return candidate
    except Exception:
        pass

    # Yahoo embrulha o destino no próprio path: .../RU=<url>/RK=...
    match = re.search(r"/RU=([^/]+)/R[KSV]=", href, re.I)
    if match:
        candidate = unquote(match.group(1))
        if candidate.startswith("http"):
            return candidate
    return href


def _canonical_target(url: str, domain: str) -> str | None:
    try:
        parsed = urlparse(_unwrap_url(url))
    except Exception:
        return None
    host = parsed.netloc.lower().removeprefix("www.")
    if host != domain.lower().removeprefix("www."):
        return None
    path = parsed.path or "/"
    if any(marker in path.lower() for marker in _BAD_PATH_MARKERS):
        return None
    return parsed._replace(query="", fragment="").geturl()


def _result_context(anchor) -> str:
    title = anchor.get_text(" ", strip=True)
    best = title
    node = anchor
    for _ in range(6):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        # Evita subir até ao documento inteiro. Um resultado individual costuma
        # caber confortavelmente abaixo deste limite.
        if 20 <= len(text) <= 2600:
            best = text
            if _prices(text):
                break
    return best


def _fallback_title(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return re.sub(r"[-_]+", " ", slug).strip()


def _looks_like_laptop(url: str, title: str, tracker_module) -> bool:
    path = urlparse(url).path.lower()
    text = f"{title} {path}".lower()
    if any(marker in text for marker in ("desktop", "monitor", "placa-grafica", "motherboard", "teclado-", "rato-")):
        return False
    explicit = any(marker in text for marker in ("portatil", "laptop", "notebook"))
    family = bool(re.search(r"\b(?:tuf|rog|legion|loq|omen|victus|nitro|predator|cyborg|katana|aero|vivobook|ideapad)\b", text))
    gpu = bool(re.search(r"\brtx[-\s]?(?:50[567]0|40[567]0|30[567]0)\b", text))
    try:
        eligible = bool(tracker_module.scraper.eligible(title or _fallback_title(url)))
    except Exception:
        eligible = True
    return eligible and (explicit or family or gpu)


def _parse_results(html: str, *, engine: str, domain: str, tracker_module) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        target = _canonical_target(anchor.get("href", ""), domain)
        if not target:
            continue
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        context = _result_context(anchor)
        if len(title) < 8:
            # Search engines nem sempre colocam o título no mesmo <a> que contém
            # o destino. O contexto do resultado é melhor que inventar um nome.
            title = context[:260].strip() or _fallback_title(target)
        if not _looks_like_laptop(target, title, tracker_module):
            continue
        row = out.setdefault(target, {
            "url": target,
            "title": title,
            "prices": [],
            "engines": set(),
            "snippets": [],
        })
        if len(title) > len(str(row.get("title") or "")):
            row["title"] = title
        row["engines"].add(engine)
        for price in _prices(context):
            if price not in row["prices"]:
                row["prices"].append(price)
        if context and context not in row["snippets"]:
            row["snippets"].append(context[:700])
    return list(out.values())


def _merge_evidence(target: dict[str, dict], rows: list[dict]) -> None:
    for row in rows:
        url = row["url"]
        current = target.setdefault(url, {
            "url": url,
            "title": row.get("title") or "",
            "prices_by_engine": {},
            "engines": set(),
            "snippets": [],
        })
        if len(str(row.get("title") or "")) > len(str(current.get("title") or "")):
            current["title"] = row["title"]
        for engine in row.get("engines", set()):
            current["engines"].add(engine)
            prices = [float(value) for value in row.get("prices", [])]
            if prices:
                current["prices_by_engine"].setdefault(engine, []).extend(prices)
        for snippet in row.get("snippets", []):
            if snippet not in current["snippets"]:
                current["snippets"].append(snippet)


def _price_hint(evidence: dict, settings: dict) -> tuple[float | None, bool]:
    by_engine = evidence.get("prices_by_engine", {}) or {}
    observations: list[tuple[str, float]] = []
    for engine, values in by_engine.items():
        for value in values:
            observations.append((str(engine), float(value)))
    if not observations:
        return None, False

    hard = float(settings.get("budget_hard", 1500.0))
    # Snippets podem conter PVPR e prestações. Para discovery preferimos preços
    # plausíveis perto do nosso universo, mas nunca os tratamos como live.
    observations = [(engine, value) for engine, value in observations if 250.0 <= value <= hard + 500.0]
    if not observations:
        return None, False

    tolerance_eur = float(settings.get("search_index_consensus_tolerance_eur", 8.0))
    tolerance_pct = float(settings.get("search_index_consensus_tolerance_pct", 1.5)) / 100.0
    for index, (engine, value) in enumerate(observations):
        peers = [(other_engine, other) for other_engine, other in observations[index + 1:] if other_engine != engine]
        for other_engine, other in peers:
            tolerance = max(tolerance_eur, max(value, other) * tolerance_pct)
            if abs(value - other) <= tolerance:
                return round((value + other) / 2.0, 2), True
    # Um único índice continua útil como pista, nunca como confirmação.
    return round(min(value for _engine, value in observations), 2), False


def _fresh_verified_history(previous: dict, hint: float | None, settings: dict) -> bool:
    if not isinstance(previous, dict) or not previous or hint is None:
        return False
    specs = previous.get("specs") if isinstance(previous.get("specs"), dict) else {}
    if str(specs.get("price_page_confidence") or "").upper() != "HIGH":
        return False
    checked = specs.get("price_checked_at")
    confirmed = specs.get("price_confirmed")
    if checked is None or confirmed is None:
        return False
    try:
        stamp = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0
        confirmed_price = float(confirmed)
        previous_price = float(previous.get("price"))
    except (TypeError, ValueError, OverflowError):
        return False
    if age_hours < 0 or age_hours > float(settings.get("price_confirmation_ttl_hours", 24.0)):
        return False
    tolerance = max(
        float(settings.get("price_confirmation_tolerance_eur", 5.0)),
        max(confirmed_price, hint) * float(settings.get("price_confirmation_tolerance_pct", 1.5)) / 100.0,
    )
    return abs(confirmed_price - hint) <= tolerance and abs(previous_price - confirmed_price) <= 0.01


def install(tracker_module) -> None:
    """Descobre lojas bloqueadas através de índices públicos, sem confiar no preço do snippet.

    O search index é uma fonte de *discovery*. Só volta a colocar um produto no
    pipeline normal quando existe uma confirmação HIGH recente no próprio
    histórico do LapIntel e o preço indexado ainda coincide dentro da tolerância.
    Assim, snippets nunca conseguem criar Ouro/Diamante/NTFY por si só.
    """
    if getattr(tracker_module, "_SEARCH_INDEX_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store
    previous_cache: dict[str, dict] = {}
    previous_loaded = False

    def previous_offers() -> dict[str, dict]:
        nonlocal previous_loaded
        if not previous_loaded:
            loader = getattr(tracker_module, "load_history", None)
            latest = getattr(tracker_module, "latest_offer_by_url", None)
            if loader and latest:
                try:
                    previous_cache.update(latest(loader()))
                except Exception:
                    pass
            previous_loaded = True
        return previous_cache

    def fetch_index(store: str, engine: str, query: str, settings: dict):
        if engine not in _ENGINES or not tracker_module.consume_request(store):
            return None, "request_budget_exhausted"
        method = f"search_index:{engine}"
        profile = "chrome131"
        try:
            response = tracker_module.requests.get(
                _ENGINES[engine](query),
                timeout=max(2.0, float(settings.get("search_index_timeout_s", 6.0))),
                impersonate=profile,
                headers=tracker_module.headers(profile),
                allow_redirects=True,
            )
            code = int(getattr(response, "status_code", 0) or 0)
            outcome = "http_success" if 200 <= code < 300 else f"http_{code}" if code else "no_response"
            learning_outcome = "success" if outcome == "http_success" else "blocked" if code in {403, 429} else outcome
            tracker_module.record_learning(store, profile, learning_outcome, method)
            return response, outcome
        except Exception:
            tracker_module.record_learning(store, profile, "request_error", method)
            return None, "request_error"

    def scan_store(cat: dict, config: dict, settings: dict):
        items, stat = base_scan_store(cat, config, settings)
        if not cat.get("search_index_enabled"):
            return items, stat

        threshold = max(0, int(cat.get("search_index_trigger_below", settings.get("search_index_trigger_below", 6))))
        if len(items) >= threshold > 0:
            return items, stat
        if not tracker_module.budget_available(cat.get("loja")):
            return items, stat

        store = str(cat["loja"])
        domain = urlparse(str(cat.get("url") or "")).netloc.lower().removeprefix("www.")
        if not domain:
            return items, stat

        raw_queries = list(cat.get("search_index_queries") or ["portatil RTX 5070", "portatil RTX 5060"])
        max_queries = max(1, int(cat.get("search_index_max_queries", settings.get("search_index_max_queries_per_store", 2))))
        engine_order = list(cat.get("search_index_engines") or ["brave", "yahoo"])
        max_engines = max(1, int(settings.get("search_index_max_engines_per_query", 2)))
        evidence: dict[str, dict] = {}
        engine_stats: dict[str, dict] = {}
        before_requests = int(tracker_module.REQUESTS_BY_STORE.get(store, 0))

        for raw in raw_queries[:max_queries]:
            query = str(raw).strip()
            if not query:
                continue
            if not query.lower().startswith("site:"):
                query = f"site:{domain} {query}"
            for engine in engine_order[:max_engines]:
                if not tracker_module.budget_available(store):
                    break
                response, outcome = fetch_index(store, engine, query, settings)
                rows: list[dict] = []
                if response is not None and outcome == "http_success":
                    rows = _parse_results(response.text, engine=engine, domain=domain, tracker_module=tracker_module)
                    _merge_evidence(evidence, rows)
                info = engine_stats.setdefault(engine, {"requests": 0, "results": 0, "successes": 0})
                info["requests"] += 1
                info["results"] += len(rows)
                info["successes"] += int(outcome == "http_success")

        watch: list[dict] = []
        verified_reused = 0
        known = {str(item.get("url")) for item in items if item.get("url")}
        previous = previous_offers()
        for row in evidence.values():
            hint, consensus = _price_hint(row, settings)
            entry = {
                "title": str(row.get("title") or _fallback_title(row["url"]))[:260],
                "url": row["url"],
                "price_hint": hint,
                "price_status": "INDEX_ONLY",
                "consensus": bool(consensus),
                "engines": sorted(row.get("engines", set())),
                "evidence_count": len(row.get("engines", set())),
            }
            watch.append(entry)

            old = previous.get(row["url"], {})
            if row["url"] in known or not _fresh_verified_history(old, hint, settings):
                continue
            candidate = {
                "loja": store,
                "titulo": str(old.get("titulo") or entry["title"]),
                "preco": float(old["price"]),
                "url": row["url"],
                "stock": old.get("stock"),
                "detail_source": "search_index_history_bridge",
                "discovery_sources": ["search_index", "history_verified"],
                "identity_checked_at": old.get("identity_checked_at"),
            }
            for field in ("ean", "mpn", "sku"):
                if old.get(field):
                    candidate[field] = old[field]
            items.append(candidate)
            known.add(row["url"])
            verified_reused += 1

        watch.sort(key=lambda row: (
            row["price_hint"] is None,
            not row["consensus"],
            float(row["price_hint"] or 99999),
            row["title"],
        ))
        watch_limit = max(1, int(settings.get("search_index_watchlist_limit", 12)))
        spent = max(0, int(tracker_module.REQUESTS_BY_STORE.get(store, 0)) - before_requests)
        tracker_module.record_discovery_yield(store, "search_index", spent, len(evidence))
        stat.setdefault("fontes_descoberta", {})["search_index"] = len(evidence)
        stat.setdefault("rendimento_descoberta", {})["search_index"] = {
            "requests": spent,
            "new_candidates": len(evidence),
            "yield": round(len(evidence) / max(1, spent), 3),
        }
        stat["search_index"] = {
            "status": "discovery_available" if evidence else "no_results",
            "requests": spent,
            "urls": len(evidence),
            "priced": sum(1 for row in watch if row["price_hint"] is not None),
            "consensus_priced": sum(1 for row in watch if row["consensus"]),
            "verified_history_reused": verified_reused,
            "engines": engine_stats,
            "watchlist": watch[:watch_limit],
        }
        stat["candidatos"] = len(items)
        tracker_module.LOGGER.info(
            "Search index | %s | urls=%d | preço=%d | consenso=%d | reutilizados=%d | pedidos=%d",
            store,
            len(evidence),
            stat["search_index"]["priced"],
            stat["search_index"]["consensus_priced"],
            verified_reused,
            spent,
        )
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._SEARCH_INDEX_GUARD_INSTALLED = True
