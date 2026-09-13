from __future__ import annotations

import re
from urllib.parse import quote

SOURCE_NAME = "Lenovo PSREF"
SOURCE_HOST = "psref.lenovo.com"

# Machine Type Model / MTM Lenovo usado nas páginas PSREF. Mantemos a deteção
# conservadora: 10 caracteres alfanuméricos, com letras e algarismos.
_MODEL_CODE = re.compile(r"^[A-Z0-9]{10}$")
_FAMILY_CODE = re.compile(
    r"\b((?:IdeaPad|LOQ|Legion|Yoga|ThinkBook)\b.{0,45}?\b\d{2}[A-Z]{2,5}\d{1,2})\b",
    re.I,
)


def normalize_model_code(value: object) -> str | None:
    raw = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not _MODEL_CODE.fullmatch(raw):
        return None
    if not re.search(r"[A-Z]", raw) or not re.search(r"\d", raw):
        return None
    return raw


def model_code(item: dict) -> str | None:
    for field in ("mpn", "sku"):
        code = normalize_model_code(item.get(field))
        if code:
            return code
    # Alguns retalhistas colocam o MTM apenas no título.
    for token in re.findall(r"\b[A-Z0-9]{10}\b", str(item.get("titulo") or "").upper()):
        code = normalize_model_code(token)
        if code:
            return code
    return None


def family_slug(title: object) -> str | None:
    text = " ".join(str(title or "").split())
    match = _FAMILY_CODE.search(text)
    if not match:
        return None
    family = match.group(1)
    family = re.sub(r"[^A-Za-z0-9]+", "_", family).strip("_")
    return family or None


def detail_urls(item: dict) -> list[str]:
    code = model_code(item)
    family = family_slug(item.get("titulo"))
    if not code or not family:
        return []
    return [f"https://{SOURCE_HOST}/Detail/{quote(family)}?M={quote(code)}"]


def response_matches(text: object, item: dict) -> bool:
    code = model_code(item)
    if not code:
        return False
    normalized = re.sub(r"[^A-Z0-9]", "", str(text or "").upper())
    return code in normalized and "PSREF" in str(text or "").upper()
