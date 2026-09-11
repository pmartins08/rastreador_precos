from __future__ import annotations

import re


_WQXGA = re.compile(r"\bwqxga\b", re.I)


def identify_explicit_resolution(text: object, scraper_module) -> str | None:
    """Reconhece apenas nomenclatura de resolução inequívoca ausente no parser base."""
    value = scraper_module.norm(text or "")
    if _WQXGA.search(value):
        return "qhd+"
    return None


def upgrade_spec(spec: dict, scraper_module, title: object = None) -> dict:
    """Corrige cache/evidência quando o próprio produto diz explicitamente WQXGA.

    O objetivo é impedir que um `FHD` secundário da página (por exemplo webcam ou
    conteúdo editorial) substitua o painel WQXGA do portátil. Não inferimos uma
    resolução a partir de família/modelo nem relaxamos valores desconhecidos.
    """
    if not isinstance(spec, dict):
        return spec

    evidence = spec.get("evidencias") if isinstance(spec.get("evidencias"), dict) else {}
    sources = (
        ("title", title),
        ("evidence", " ".join(str(value or "") for value in evidence.values())),
    )
    for source, text in sources:
        mapped = identify_explicit_resolution(text, scraper_module)
        if not mapped:
            continue
        previous = spec.get("ecra_res")
        if previous != mapped:
            spec["ecra_res"] = mapped
            spec.setdefault("fontes", {})["ecra_res"] = f"display_guard_{source}"
            spec["display_resolution_guard"] = {
                "status": "WQXGA_EXPLICITO",
                "source": source,
                "previous": previous,
                "resolution": mapped,
            }
        return spec
    return spec


def install(scraper_module, tracker_module) -> None:
    """Instala reconhecimento WQXGA no parser live e na cache histórica."""
    if getattr(tracker_module, "_DISPLAY_GUARD_INSTALLED", False):
        return

    base_resolution = scraper_module._resolution
    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_select_with_cache = tracker_module.select_with_cache

    def resolution(text: str):
        mapped = identify_explicit_resolution(text, scraper_module)
        return mapped if mapped is not None else base_resolution(text)

    scraper_module._resolution = resolution

    def score_allow_unknown(spec, price, weights, settings):
        upgrade_spec(spec, scraper_module)
        return base_score_allow_unknown(spec, price, weights, settings)

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        for item in items:
            title = item.get("titulo")
            inline = item.get("specs")
            if isinstance(inline, dict):
                upgrade_spec(inline, scraper_module, title)
            cached = spec_cache.get(item.get("url")) if isinstance(spec_cache, dict) else None
            if isinstance(cached, dict):
                upgrade_spec(cached, scraper_module, title)
        return base_select_with_cache(items, spec_cache, max_items, weights, settings)

    tracker_module.score_allow_unknown = score_allow_unknown
    tracker_module.select_with_cache = select_with_cache
    tracker_module._DISPLAY_GUARD_INSTALLED = True
