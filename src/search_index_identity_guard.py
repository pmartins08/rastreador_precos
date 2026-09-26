from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


def _strong_url_identity(url: str, tracker_module) -> dict:
    """Extrai apenas identificadores fortes que podem ser confirmados na ficha live."""
    raw_url = str(url or "")
    extractor = getattr(tracker_module, "url_ean", None)
    if callable(extractor):
        try:
            ean = extractor(raw_url)
        except Exception:
            ean = None
        if ean:
            return {
                "ean": str(ean),
                "identity_status": "STRONG_URL_EAN",
                "identity_source": "product_url",
            }

    # A CHIP7 usa frequentemente a referência do fabricante como último segmento
    # (ex.: /83je00c6pg). Aceitamos apenas formatos muito restritos de P/N de
    # portáteis Lenovo/ASUS; slugs descritivos genéricos nunca viram identidade.
    try:
        parsed = urlparse(raw_url)
        host = parsed.netloc.lower().removeprefix("www.")
        slug = unquote(parsed.path.rstrip("/").split("/")[-1]).upper()
    except Exception:
        return {}
    if host != "chip7.pt":
        return {}
    strong_mpn = bool(
        re.fullmatch(r"8[23][A-Z0-9]{8}", slug)
        or re.fullmatch(r"90NR[A-Z0-9]{3,10}-[A-Z0-9]{4,10}", slug)
    )
    if not strong_mpn:
        return {}
    return {
        "mpn": slug,
        "identity_status": "STRONG_URL_MPN",
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
        for key, value in identity.items():
            row.setdefault(key, value)
        identities_by_url[url] = identity
        strong += 1

    # Só completa ofertas que já existem; esta camada nunca cria candidatos.
    for item in items:
        if not isinstance(item, dict):
            continue
        identity = identities_by_url.get(str(item.get("url") or ""))
        if not identity:
            continue
        for field in ("ean", "mpn"):
            if identity.get(field) and not item.get(field):
                item[field] = identity[field]
        if identity.get("identity_source"):
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
