from __future__ import annotations

from bs4 import BeautifulSoup

from price_guard import page_price_evidence


def _close(left: float, right: float, settings: dict) -> bool:
    abs_tol = float(settings.get("price_confirmation_tolerance_eur", 5.0))
    pct_tol = float(settings.get("price_confirmation_tolerance_pct", 1.5)) / 100.0
    return abs(float(left) - float(right)) <= max(
        abs_tol,
        max(float(left), float(right)) * pct_tol,
    )


def _validate_row(row: dict, *, store: str, tracker_module, settings: dict) -> tuple[dict | None, str]:
    """Confirma identidade + preço diretamente na ficha do produto.

    Search-index nunca é autoridade de preço. Esta função só promove uma entrada
    quando a própria ficha live confirma o mesmo EAN e o price_guard obtém preço
    HIGH (>= 2 famílias independentes de sinais).
    """
    url = str(row.get("url") or "").strip()
    expected_ean = str(row.get("ean") or "").strip()
    if not url or not expected_ean or str(row.get("identity_status") or "") != "STRONG_URL_EAN":
        return None, "identity_not_strong"
    if not tracker_module.budget_available(store) or not tracker_module.consume_request(store):
        return None, "request_budget_exhausted"

    profile = "chrome131"
    method = "search_index:live_validation"
    try:
        response = tracker_module.requests.get(
            url,
            timeout=max(2.0, float(settings.get("search_index_live_timeout_s", 7.0))),
            impersonate=profile,
            headers=tracker_module.headers(profile),
            allow_redirects=True,
        )
    except Exception:
        tracker_module.record_learning(store, profile, "request_error", method)
        return None, "request_error"

    code = int(getattr(response, "status_code", 0) or 0)
    if not 200 <= code < 300:
        tracker_module.record_learning(
            store,
            profile,
            "blocked" if code in {403, 429} else f"http_{code}" if code else "no_response",
            method,
        )
        return None, f"http_{code}" if code else "no_response"

    tracker_module.record_learning(store, profile, "success", method)
    soup = BeautifulSoup(getattr(response, "text", "") or "", "html.parser")
    try:
        identifiers = tracker_module.page_identifiers(soup) or {}
    except Exception:
        identifiers = {}
    live_ean = str(identifiers.get("ean") or "").strip()
    if not live_ean or live_ean != expected_ean:
        return None, "identity_mismatch"

    evidence = page_price_evidence(soup, tracker_module.scraper, settings)
    if str(evidence.get("confidence") or "").upper() != "HIGH" or evidence.get("price") is None:
        return None, "price_not_high"

    live_price = float(evidence["price"])
    hint = row.get("price_hint")
    if hint is not None:
        try:
            if not _close(live_price, float(hint), settings):
                return None, "index_hint_conflict"
        except (TypeError, ValueError):
            return None, "invalid_hint"

    return {
        "loja": store,
        "titulo": str(row.get("title") or "")[:260],
        "preco": live_price,
        "url": url,
        "ean": expected_ean,
        "detail_source": "search_index_live_validation",
        "discovery_sources": ["search_index", "live_product_page"],
        "identity_source": "product_url+live_page",
        "identity_checked_at": tracker_module.now_iso() if hasattr(tracker_module, "now_iso") else None,
        "price_validation_sources": list(evidence.get("sources") or []),
        "price_page_confidence": "HIGH",
    }, "validated"


def install(tracker_module) -> None:
    """Promove apenas search-index com EAN forte + ficha live HIGH confirmada."""
    if getattr(tracker_module, "_SEARCH_INDEX_LIVE_VALIDATION_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store

    def scan_store(cat: dict, config: dict, settings: dict):
        items, stat = base_scan_store(cat, config, settings)
        search = stat.get("search_index") if isinstance(stat, dict) else None
        watch = search.get("watchlist") if isinstance(search, dict) else None
        if not isinstance(watch, list) or not watch:
            return items, stat

        store = str(cat.get("loja") or "")
        if not store:
            return items, stat

        known = {str(item.get("url") or "") for item in items if isinstance(item, dict)}
        limit = max(0, int(settings.get("search_index_live_validation_limit", 3)))
        attempts = 0
        validated = 0
        outcomes: dict[str, int] = {}

        ordered = sorted(
            [row for row in watch if isinstance(row, dict)],
            key=lambda row: (
                str(row.get("identity_status") or "") != "STRONG_URL_EAN",
                not bool(row.get("consensus")),
                row.get("price_hint") is None,
                float(row.get("price_hint") or 99999),
            ),
        )
        for row in ordered:
            if attempts >= limit:
                break
            url = str(row.get("url") or "")
            if not url or url in known or str(row.get("identity_status") or "") != "STRONG_URL_EAN":
                continue
            attempts += 1
            candidate, outcome = _validate_row(
                row,
                store=store,
                tracker_module=tracker_module,
                settings=settings,
            )
            outcomes[outcome] = int(outcomes.get(outcome, 0)) + 1
            row["live_validation_status"] = outcome
            if not candidate:
                continue
            row["price_status"] = "LIVE_HIGH"
            row["live_price"] = candidate["preco"]
            row["price_validation_sources"] = candidate["price_validation_sources"]
            items.append(candidate)
            known.add(url)
            validated += 1

        search["live_validation"] = {
            "attempts": attempts,
            "validated": validated,
            "outcomes": outcomes,
        }
        stat["candidatos"] = len(items)
        if hasattr(tracker_module, "LOGGER"):
            tracker_module.LOGGER.info(
                "Search index live | %s | tentativas=%d | validados=%d | outcomes=%s",
                store,
                attempts,
                validated,
                outcomes,
            )
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._SEARCH_INDEX_LIVE_VALIDATION_GUARD_INSTALLED = True
