from __future__ import annotations

import re


_GROUPED_DOT = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_GROUPED_COMMA = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def parse_price_value(value: object) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not raw:
        return None
    try:
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                return float(raw.replace(".", "").replace(",", "."))
            return float(raw.replace(",", ""))
        if _GROUPED_DOT.fullmatch(raw):
            return float(raw.replace(".", ""))
        if _GROUPED_COMMA.fullmatch(raw):
            return float(raw.replace(",", ""))
        if "," in raw:
            return float(raw.replace(".", "").replace(",", "."))
        return float(raw)
    except ValueError:
        return None


def prices(text: str) -> list[float]:
    """Extrai preços em euros, incluindo 1.399,99 €, 1.399 € e 1 399,99 €."""
    pattern = re.compile(
        r"(?<!\d)(\d{1,3}(?:[.\s\u00a0]\d{3})+(?:,\d{2})?|\d{1,4}(?:[.,]\d{2})?)\s*€"
    )
    out: list[float] = []
    for raw in pattern.findall(text or ""):
        value = parse_price_value(raw)
        if value is not None and 50 <= value <= 10000:
            out.append(value)
    return out


def best_product_price(values: list[float], minimum: float = 200.0, maximum: float = 4500.0) -> float | None:
    """Ignora prestações/portes quando o mesmo bloco também contém um preço de portátil plausível."""
    valid = [float(value) for value in values if minimum <= float(value) <= maximum]
    return min(valid) if valid else None
