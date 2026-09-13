from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from price_tracker.sources import hp, lenovo

_CORE_FIELDS = (
    "cpu_modelo",
    "gpu_modelo",
    "gpu_tipo",
    "ram_gb",
    "armazenamento_tb",
)
_MERGE_FIELDS = (
    "cpu_modelo",
    "cpu_str_original",
    "cpu_classe",
    "gpu_modelo",
    "gpu_tipo",
    "gpu_modelos_detectados",
    "ram_gb",
    "ram_type",
    "ram_expansivel",
    "armazenamento_tb",
    "ssd_expansivel",
    "vram_gb",
    "tgp_w",
    "bateria_wh",
    "peso_kg",
    "ecra_tamanho",
    "ecra_res",
    "ecra_painel",
    "ecra_hz",
    "ecra_brightness_nits",
    "teclado_pt",
)
_SUPPLEMENTAL_FIELDS = (
    "bateria_wh",
    "peso_kg",
    "ecra_res",
    "ecra_hz",
    "ecra_brightness_nits",
)
_BOOLEAN_CONFIRM_FIELDS = {"ram_expansivel", "ssd_expansivel"}


def _missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value in {"", "desconhecida", "desconhecido"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _same(scraper, field: str, left: object, right: object) -> bool:
    if _missing(left) or _missing(right):
        return True
    if field in {"ram_gb", "bateria_wh", "ecra_hz"}:
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return False
    if field in {"armazenamento_tb", "peso_kg", "ecra_tamanho"}:
        try:
            return abs(float(left) - float(right)) <= 0.02
        except (TypeError, ValueError):
            return False
    return scraper.norm(left) == scraper.norm(right)


def _needs_enrichment(spec: dict) -> bool:
    core_missing = sum(_missing(spec.get(field)) for field in _CORE_FIELDS)
    supplemental_missing = sum(_missing(spec.get(field)) for field in _SUPPLEMENTAL_FIELDS)
    return core_missing >= 1 or supplemental_missing >= 3


def _brand(scraper, item: dict, spec: dict) -> str | None:
    raw = scraper.norm(spec.get("marca") or item.get("titulo") or "")
    if "lenovo" in raw:
        return "lenovo"
    if raw == "hp" or raw.startswith("hp ") or " hp " in f" {raw} ":
        return "hp"
    return None


def _fetch(tracker_module, url: str, config: dict, source_store: str, method: str):
    response, profile, access = tracker_module.adaptive_fetch(
        url,
        config,
        7,
        store=source_store,
        method=method,
    )
    if not response or response.status_code >= 400:
        return None, {"error": "access_failed", "profile": profile, "access": access}
    return response, {"error": None, "profile": profile, "access": access}


def _lenovo_document(tracker_module, item: dict, config: dict):
    for url in lenovo.detail_urls(item):
        response, status = _fetch(
            tracker_module, url, config, lenovo.SOURCE_NAME, "manufacturer_specs:psref"
        )
        if response is None:
            continue
        if urlparse(str(response.url)).netloc.lower() != lenovo.SOURCE_HOST:
            continue
        if not lenovo.response_matches(response.text, item):
            continue
        return response, lenovo.SOURCE_NAME, status
    return None, lenovo.SOURCE_NAME, {"error": "identity_unresolved"}


def _hp_document(tracker_module, item: dict, config: dict):
    search = hp.search_url(item)
    if not search:
        return None, hp.SOURCE_NAME, {"error": "identity_unresolved"}
    response, status = _fetch(
        tracker_module, search, config, hp.SOURCE_NAME, "manufacturer_search"
    )
    if response is None:
        return None, hp.SOURCE_NAME, status
    for url in hp.spec_links(response.text, str(response.url), item)[:3]:
        detail, detail_status = _fetch(
            tracker_module, url, config, hp.SOURCE_NAME, "manufacturer_specs:product"
        )
        if detail is None:
            continue
        if urlparse(str(detail.url)).netloc.lower() != hp.SOURCE_HOST:
            continue
        if hp.response_matches(detail.text, item):
            return detail, hp.SOURCE_NAME, detail_status
    return None, hp.SOURCE_NAME, {"error": "identity_unresolved"}


def _merge_official(scraper, spec: dict, official: dict, source_name: str, source_url: str) -> dict:
    result = dict(spec)
    conflicts = []
    for field in _CORE_FIELDS:
        left = result.get(field)
        right = official.get(field)
        if not _missing(left) and not _missing(right) and not _same(scraper, field, left, right):
            conflicts.append({"field": field, "retailer": left, "official": right})

    # Uma contradição de configuração é tratada como possível variante errada:
    # guardamos o diagnóstico, mas não deixamos a fonte oficial contaminar specs.
    if conflicts:
        result["official_source_conflicts"] = conflicts
        result["official_spec_source"] = source_name
        result["official_spec_url"] = source_url
        result["official_spec_status"] = "CONFLICT_REJECTED"
        return result

    merged = []
    for field in _MERGE_FIELDS:
        current = result.get(field)
        candidate = official.get(field)
        confirmed_true = field in _BOOLEAN_CONFIRM_FIELDS and candidate is True and current is not True
        if (_missing(current) and not _missing(candidate)) or confirmed_true:
            result[field] = candidate
            merged.append(field)

    sources = dict(result.get("fontes") or {})
    evidence = dict(result.get("evidencias") or {})
    for field in merged:
        sources[field] = f"official:{source_name}"
        if field in (official.get("evidencias") or {}):
            evidence[field] = official["evidencias"][field]
    result["fontes"] = sources
    result["evidencias"] = evidence
    result["official_spec_source"] = source_name
    result["official_spec_url"] = source_url
    result["official_spec_fields"] = merged
    result["official_spec_status"] = "MERGED" if merged else "CONFIRMED_NO_CHANGE"
    return result


def install(tracker_module) -> None:
    """Enriquece Lenovo/HP sem usar fabricante como fonte de preço."""
    if getattr(tracker_module, "_MANUFACTURER_SOURCE_GUARD_INSTALLED", False):
        return

    base_enrich = tracker_module.enrich
    attempts = 0
    attempts_by_brand = defaultdict(int)

    def enrich(item: dict, config: dict):
        nonlocal attempts
        result, status = base_enrich(item, config)
        if status.get("error"):
            return result, status

        settings = config.get("settings", {})
        if not bool(settings.get("manufacturer_enrichment_enabled", True)):
            return result, status
        spec = result.get("specs") if isinstance(result.get("specs"), dict) else {}
        brand = _brand(tracker_module.scraper, result, spec)
        if brand not in {"lenovo", "hp"} or not _needs_enrichment(spec):
            return result, status

        max_total = int(settings.get("manufacturer_enrichment_max_per_run", 6))
        max_brand = int(settings.get("manufacturer_enrichment_max_per_brand", 3))
        if attempts >= max_total or attempts_by_brand[brand] >= max_brand:
            return result, status

        # Só consumimos quota quando existe identidade suficiente para uma
        # pesquisa exata. Não fazemos pesquisa fuzzy por nome comercial.
        if brand == "lenovo" and not lenovo.detail_urls(result):
            return result, status
        if brand == "hp" and not hp.search_url(result):
            return result, status

        attempts += 1
        attempts_by_brand[brand] += 1
        if brand == "lenovo":
            response, source_name, official_status = _lenovo_document(
                tracker_module, result, config
            )
        else:
            response, source_name, official_status = _hp_document(
                tracker_module, result, config
            )

        result["official_spec_lookup"] = {
            "source": source_name,
            "status": official_status.get("error") or "ok",
        }
        if response is None:
            return result, status

        soup = BeautifulSoup(response.text, "html.parser")
        official = tracker_module.scraper.extract(result.get("titulo", ""), soup)
        result["specs"] = _merge_official(
            tracker_module.scraper,
            spec,
            official,
            source_name,
            str(response.url),
        )
        return result, status

    tracker_module.enrich = enrich
    tracker_module._MANUFACTURER_SOURCE_GUARD_INSTALLED = True
