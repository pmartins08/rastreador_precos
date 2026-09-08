from __future__ import annotations

import re
import unicodedata


BRANDS = {
    "asus": {"rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"},
    "lenovo": {"legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"},
    "hp": {"omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"},
}

EXCLUDE = {
    "recondicionado",
    "refurbished",
    "usado",
    "outlet",
    "grade a",
    "grade b",
    "grade c",
    "seminovo",
    "open box",
}


def norm(value: object) -> str:
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", text).lower().strip()


def brand(text: str) -> tuple[str | None, str | None]:
    """Reconhece tanto a marca mãe como submarcas usadas sozinhas em títulos comerciais."""
    value = norm(text)
    for parent, children in BRANDS.items():
        if re.search(rf"\b{re.escape(parent)}\b", value):
            for child in sorted(children, key=len, reverse=True):
                if re.search(rf"\b{re.escape(child)}\b", value):
                    return parent, child
            return parent, None

    for parent, children in BRANDS.items():
        for child in sorted(children, key=len, reverse=True):
            if re.search(rf"\b{re.escape(child)}\b", value):
                return parent, child
    return None, None


def eligible(text: str) -> bool:
    value = norm(text)
    return not any(marker in value for marker in EXCLUDE) and brand(value)[0] in BRANDS
