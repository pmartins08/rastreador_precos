from __future__ import annotations


def _strong_url_identity(url: str, tracker_module) -> dict:
    """Extrai apenas identificadores que o próprio runtime já valida pela URL."""
    extractor = getattr(tracker_module, "url_ean", None)
    if not callable(extractor):
        return {}
    try:
        ean = extractor(str(url or ""))
    except Exception:
        return {}
    if not ean:
        return {}
    return {
        "ean": str(ean),
        "identity_status": "STRONG_URL_EAN",
        "identity_source": "product_url",
    }


def _annotate_search_index(items: list[dict], stat: dict, tracker_module) -> None:
    """Enriquece identidade sem promover price hints a preço live/scoring."""
    search = stat.get("search_index") if isinstance(stat, dict) else None
    if not isinstance(search, dict):
        return

    watch = search.get("watchlist")
    if not isinstance(watch, list):
        return

    identities_by_url: dict[str, dict] = {}
    strong = 0
    for row in watch:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        identity = _strong_url_identity(url, tracker_module)
        if not identity:
            continue
        # A identidade é independente do price hint. O estado INDEX_ONLY não é
        # alterado e esta camada nunca cria candidatos nem confirma preços.
        for key, value in identity.items():
            row.setdefault(key, value)
        identities_by_url[url] = identity
        strong += 1

    # Se o search_index_guard já recuperou uma oferta através de histórico HIGH,
    # podemos completar o EAN a partir da URL. Nunca adicionamos uma oferta nova.
    for item in items:
        if not isinstance(item, dict) or item.get("ean"):
            continue
        identity = identities_by_url.get(str(item.get("url") or ""))
        if identity and identity.get("ean"):
            item["ean"] = identity["ean"]
            item.setdefault("identity_source", identity["identity_source"])

    search["strong_identity"] = strong


def install(tracker_module) -> None:
    """Preserva identidade forte das watchlists INDEX_ONLY de lojas bloqueadas."""
    if getattr(tracker_module, "_SEARCH_INDEX_IDENTITY_GUARD_INSTALLED", False):
        return

    base_scan_store = tracker_module.scan_store

    def scan_store(cat: dict, config: dict, settings: dict):
        items, stat = base_scan_store(cat, config, settings)
        _annotate_search_index(items, stat, tracker_module)
        return items, stat

    tracker_module.scan_store = scan_store
    tracker_module._SEARCH_INDEX_IDENTITY_GUARD_INSTALLED = True
