from __future__ import annotations

import json
import re
from urllib.parse import urlencode

SOURCE_NAME = "HP Support"
SOURCE_HOST = "support.hp.com"
_TYPEAHEAD_FILTERS = (
    "class:(pm_series_value^1.1 OR pm_name_value OR pm_number_value) "
    "AND (hiddenproduct:no OR (!_exists_:hiddenproduct))"
)
_TYPEAHEAD_FIELDS = (
    "tmspmseriesvalue,tmspmnamevalue,tmspmnumbervalue,class,productid,"
    "seofriendlyname,activewebsupportflag,navigationpath,childnodes"
)


def normalize_product_number(value: object) -> str | None:
    raw = str(value or "").upper().strip()
    raw = raw.split("#", 1)[0]
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    if not 6 <= len(raw) <= 12:
        return None
    if not re.search(r"[A-Z]", raw) or not re.search(r"\d", raw):
        return None
    return raw


def product_number(item: dict) -> str | None:
    for field in ("mpn", "sku"):
        code = normalize_product_number(item.get(field))
        if code:
            return code
    title = str(item.get("titulo") or "").upper()
    labelled = re.search(
        r"(?:SKU|P\s*/?\s*N|PRODUCT\s*(?:NO\.?|NUMBER)|N[UÚ]MERO\s+DO\s+PRODUTO)\s*[:#-]?\s*([A-Z0-9]{6,12}(?:#[A-Z0-9]{2,5})?)",
        title,
        re.I,
    )
    return normalize_product_number(labelled.group(1)) if labelled else None


def search_url(item: dict) -> str | None:
    """Endpoint oficial usado pela SPA HP para resolver SKU -> modelo/OID."""
    code = product_number(item)
    if not code:
        return None
    params = {
        "q": code,
        "resultLimit": 10,
        "store": "tmsstore",
        "languageCode": "en",
        "filters": _TYPEAHEAD_FILTERS,
        "printFields": _TYPEAHEAD_FIELDS,
    }
    return f"https://{SOURCE_HOST}/typeahead?{urlencode(params)}"


def _pick(row: dict, *names: str):
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name in row:
            return row[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _normalized_contains(value: object, code: str) -> bool:
    return code in re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _navigation_paths(value: object) -> list[list[str]]:
    raw_paths = value if isinstance(value, list) else [value]
    out: list[list[str]] = []
    for raw in raw_paths:
        parts = [part.strip() for part in str(raw or "").split("|") if part.strip()]
        if parts:
            out.append(parts)
    return out


def _model_oid(pm_class: str, product_id: object, series_oid: object, navigation: object) -> str | None:
    product = str(product_id or "").strip()
    series = str(series_oid or "").strip()
    paths = _navigation_paths(navigation)

    # Para pm_number_value, productId é o OID do número de produto/SKU. O OID
    # do modelo é o nó imediatamente anterior no navigationPath da HP.
    if product and pm_class == "pm_number_value":
        for parts in paths:
            try:
                index = parts.index(product)
            except ValueError:
                continue
            if index > 0:
                candidate = parts[index - 1]
                if candidate and candidate != series:
                    return candidate

    # Em pm_name_value, productId normalmente já identifica o modelo exato.
    if product and pm_class == "pm_name_value":
        return product

    # Fallback conservador: se a path tiver série -> modelo -> produto, usa o
    # primeiro nó após a série, nunca o terminal de SKU sem contexto.
    if series:
        for parts in paths:
            try:
                index = parts.index(series)
            except ValueError:
                continue
            if index + 1 < len(parts):
                candidate = parts[index + 1]
                if candidate != product or pm_class != "pm_number_value":
                    return candidate
                if index + 2 < len(parts):
                    return candidate
    return None


def typeahead_matches(payload: object, item: dict) -> list[dict]:
    code = product_number(item)
    if not code:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("matches") or payload.get("Matches") or []
    if not isinstance(rows, list):
        return []

    ranked: list[tuple[int, dict]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pm_class = str(_pick(row, "pmClass", "class") or "").lower()
        product_id = _pick(row, "productId", "productid")
        series_oid = _pick(row, "pmSeriesOid", "pmseriesoid", "tmspmseriesvalue")
        seo_name = _pick(row, "seoFriendlyName", "seofriendlyname")
        name = _pick(row, "name", "tmspmnamevalue")
        number = _pick(row, "pmNumber", "pmnumber", "tmspmnumbervalue")
        navigation = _pick(row, "navigationPath", "navigationpath")

        haystacks = (name, number, navigation, row)
        exact_evidence = any(_normalized_contains(value, code) for value in haystacks)
        if not exact_evidence:
            continue
        model_oid = _model_oid(pm_class, product_id, series_oid, navigation)
        if not model_oid:
            continue

        score = 0
        if pm_class == "pm_name_value":
            score += 100
        elif pm_class == "pm_number_value":
            score += 40
        elif pm_class == "pm_series_value":
            score += 10
        if model_oid:
            score += 30
        if series_oid:
            score += 10
        if seo_name:
            score += 5
        ranked.append(
            (
                score,
                {
                    "pm_class": pm_class,
                    "product_id": str(product_id) if product_id is not None else None,
                    "model_oid": str(model_oid),
                    "series_oid": str(series_oid) if series_oid is not None else None,
                    "seo_name": str(seo_name or "").strip() or None,
                    "name": str(name or "").strip() or None,
                    "number": str(number or "").strip() or None,
                    "navigation_path": navigation,
                },
            )
        )
    return [row for _score, row in sorted(ranked, key=lambda value: -value[0])]


def _slug(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or None


def spec_urls(payload: object, item: dict) -> list[str]:
    """Constrói fichas oficiais de specs a partir do resultado typeahead."""
    code = product_number(item)
    if not code:
        return []
    out: list[str] = []
    seen = set()
    for row in typeahead_matches(payload, item):
        model_oid = row.get("model_oid")
        seo_name = _slug(row.get("seo_name") or row.get("name"))
        if not model_oid or not seo_name:
            continue
        url = (
            f"https://{SOURCE_HOST}/us-en/product/product-specs/"
            f"{seo_name}/model/{model_oid}?sku={code}"
        )
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def response_matches(text: object, item: dict) -> bool:
    code = product_number(item)
    if not code:
        return False
    raw = str(text or "")
    normalized = re.sub(r"[^A-Z0-9]", "", raw.upper())
    has_heading = "PRODUCTSPECIFICATIONS" in normalized or "ESPECIFICACOESDOPRODUTO" in normalized
    return has_heading and code in normalized
