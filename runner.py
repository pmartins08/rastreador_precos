from __future__ import annotations

import logging
import re
import sys

import scraper
from brain_guard import VERSION, install as install_brain_guard
from market_guard import install as install_market_guard
from price_guard import BAD_PRICE_CONTEXT, install as install_price_guard, page_price_evidence


# ---------------------------------------------------------------------------
# Fallback genérico label -> valor
# ---------------------------------------------------------------------------

# Algumas lojas (nomeadamente Darty) apresentam especificações como uma sequência
# visual de rótulo/valor sem <table>, <dl> ou classes semânticas previsvisíveis.
# Esta camada tem confiança 0.90: qualquer tabela/dl/label_value estruturado do
# scraper base continua a ganhar no algoritmo best().
_BASE_PAIRS = scraper.pairs

_LINEAR_LABELS = {
    "refresh rate": "refresh",
    "processador": "cpu",
    "memoria ram": "ram",
    "tipo memoria": "ram_type",
    "placa(s) grafica(s)": "gpu",
    "placa grafica": "gpu",
    "memoria grafica": "vram",
    "disco ssd": "storage",
    "dimensao ecra": "screen",
    "resolucao": "resolution",
    "tipo de ecra": "screen",
    "bateria": "battery",
    "peso": "weight",
}


def _linear_spec_pairs(soup) -> list[tuple]:
    strings = [str(value).strip() for value in soup.stripped_strings if str(value).strip()]
    out: list[tuple] = []
    for index, label in enumerate(strings[:-1]):
        key = _LINEAR_LABELS.get(scraper.norm(label))
        if not key:
            continue
        value = strings[index + 1].strip()
        normalized = scraper.norm(value)

        # Darty apresenta alguns números sem unidade; normalizamos apenas quando
        # o rótulo torna a unidade inequívoca.
        if key == "refresh" and re.fullmatch(r"\d{2,3}", normalized):
            value = f"{value} Hz"
        elif key == "weight" and re.fullmatch(r"\d(?:[.,]\d{1,2})?", normalized):
            value = f"{value} kg"
        elif key == "screen" and scraper.norm(label) == "dimensao ecra" and re.fullmatch(
            r"\d{1,2}(?:[.,]\d)?", normalized
        ):
            value = f'{value}"'

        out.append((key, label, value, "linear_label", 0.90))

        # "Tipo de Ecrã" pode transportar também painel e brilho. Guardamos
        # essas evidências separadamente para o cérebro não perder informação.
        if scraper.norm(label) == "tipo de ecra":
            if re.search(r"\b(?:oled|ips|va|tn|mini[- ]?led)\b", normalized):
                out.append(("panel", label, value, "linear_label", 0.90))
            if re.search(r"\b\d{2,4}\s*(?:nits|cd/m2)\b", normalized):
                out.append(("brightness", label, value, "linear_label", 0.90))
    return out


def _pairs_with_linear_fallback(soup) -> list[tuple]:
    return [*_BASE_PAIRS(soup), *_linear_spec_pairs(soup)]


scraper.pairs = _pairs_with_linear_fallback


# Ordem intencional: correções técnicas entram primeiro; price_guard envolve o
# cérebro já corrigido e acrescenta confiança/bónus de preço; market_guard atua
# depois sobre a decisão operacional cross-store.
install_brain_guard(scraper)
install_price_guard(scraper)

import tracker


# ---------------------------------------------------------------------------
# Identidade pública adicional
# ---------------------------------------------------------------------------

_BASE_PAGE_IDENTIFIERS = tracker.page_identifiers


def _enhanced_page_identifiers(soup) -> dict:
    out = dict(_BASE_PAGE_IDENTIFIERS(soup))
    if out.get("ean"):
        return out

    text = " ".join(soup.stripped_strings)
    # Padrão público usado pela Darty:
    # ID PRODUTO: T00166546 | 0199271125540 | Lenovo
    match = re.search(
        r"ID\s+PRODUTO\s*:\s*[^|]{1,60}\|\s*(\d{8}|\d{12,14})\s*\|",
        text,
        re.I,
    )
    if match and tracker.gtin_valid(match.group(1)):
        out["ean"] = match.group(1)
    return out


tracker.page_identifiers = _enhanced_page_identifiers
install_market_guard(scraper, tracker)
tracker.VERSION = VERSION
tracker.COMPATIBLE_STATE_VERSIONS.add(VERSION)


class _VersionLogFilter(logging.Filter):
    """Compatibilidade enquanto mensagens antigas do tracker não são dinâmicas."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = record.msg.replace("V8.8.1", f"V{VERSION}")
        return True


tracker.LOGGER.addFilter(_VersionLogFilter())


def _safe_page_price(soup, structured_price: float | None = None) -> float | None:
    """Preço da ficha por evidência forte ou, em último caso, primeiro preço visível seguro.

    O fallback existe sobretudo para lojas como a PCDiga, onde o preço atual pode
    estar num nó de texto sem uma classe semântica. Nunca escolhe o menor valor da
    página e rejeita contextos de PVPR, preço antigo, desconto e financiamento.
    """
    evidence = page_price_evidence(soup, scraper)
    if evidence.get("price") is not None:
        return float(evidence["price"])

    if structured_price is not None and 200 <= float(structured_price) <= 10000:
        return float(structured_price)

    bad = tuple(BAD_PRICE_CONTEXT) + ("pvpr", "preco recomendado", "preço recomendado")
    for text_node in soup.find_all(string=lambda value: value and "€" in str(value)):
        raw = str(text_node).strip()
        if not raw or raw.lstrip().startswith("-"):
            continue
        parent = getattr(text_node, "parent", None)
        class_text = " ".join(parent.get("class", [])) if parent is not None else ""
        id_text = str(parent.get("id") or "") if parent is not None else ""
        previous = str(text_node.previous_sibling or "")[-60:]
        context = scraper.norm(f"{class_text} {id_text} {previous} {raw}")
        if any(marker in context for marker in bad):
            continue
        for value in scraper.prices(raw):
            if 200 <= float(value) <= 10000:
                return float(value)
    return None


# O tracker continua responsável por toda a operação; as camadas são instaladas
# aqui num único composition root.
tracker.preferred_page_price = _safe_page_price

main = tracker.main
merge_cli = tracker.merge_cli


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "merge-state":
        merge_cli(sys.argv[2:])
    else:
        main()
