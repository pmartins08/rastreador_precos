from __future__ import annotations

import re


_GTIN_LENGTHS = {8, 12, 13, 14}


def digits_only(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def gtin_valid(value: object) -> bool:
    """Valida o dígito de controlo GS1 de GTIN-8/12/13/14."""
    digits = digits_only(value)
    if len(digits) not in _GTIN_LENGTHS:
        return False
    body = [int(char) for char in digits[:-1]]
    expected = int(digits[-1])
    weighted = sum(
        digit * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(body))
    )
    return (10 - weighted % 10) % 10 == expected


def canonical_gtin(value: object) -> str | None:
    """Representação interna GTIN-14 sem alterar a identidade comercial.

    UPC-A/GTIN-12 e o mesmo EAN-13 com zero à esquerda passam a ter exatamente
    a mesma chave. GTIN-8/13 também são zero-padded conforme a representação
    canónica GS1 em 14 dígitos. Valores inválidos nunca são 'corrigidos'.
    """
    digits = digits_only(value)
    if not gtin_valid(digits):
        return None
    return digits.zfill(14)


def normal_text_id(value: object) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def canonical_strong_identity(item: dict) -> tuple[str | None, str | None]:
    """Devolve apenas identidade forte explícita: GTIN válido ou MPN textual."""
    ean = canonical_gtin(item.get("ean"))
    if ean:
        return "ean", ean
    mpn = normal_text_id(item.get("mpn"))
    if mpn:
        return "mpn", mpn
    return None, None


def canonical_identity_key(item: dict) -> str | None:
    kind, value = canonical_strong_identity(item)
    return f"{kind}:{value}" if kind and value else None
