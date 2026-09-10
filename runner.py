from __future__ import annotations

import re
import sys

import price_guard as price_guard_module
import scraper
from awin_feed_guard import install as install_awin_feed_guard
from brain_guard import install as install_brain_guard
from catalog_guard import install as install_catalog_guard
from coverage_guard import install as install_coverage_guard
from gpu_guard import install as install_gpu_guard
from hardware_guard import install as install_hardware_guard
from historical_guard import install as install_historical_guard
from market_guard import install as install_market_guard
from price_guard import BAD_PRICE_CONTEXT, install as install_price_guard, page_price_evidence
from promotion_guard import install as install_promotion_guard
from rejection_guard import install as install_rejection_guard
from sitemap_route_guard import install as install_sitemap_route_guard
from sitemap_strategy_epoch_guard import install as install_sitemap_strategy_epoch_guard
from state_refresh_guard import install as install_state_refresh_guard
from top5_guard import install as install_top5_guard
from version import VERSION
from version_guard import install as install_version_guard


# ---------------------------------------------------------------------------
# Fallback genérico label -> valor
# ---------------------------------------------------------------------------

_BASE_PAIRS = scraper.pairs
_BASE_CARD_PRICES = scraper._card_prices

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

# Algumas lojas oficiais mostram, por obrigação legal, o mínimo dos 30 dias
# anteriores junto do preço atual. É contexto histórico, nunca preço corrente.
_OLD_PRICE_MARKERS = (
    "preco mais baixo praticado nos 30 dias anteriores",
    "preço mais baixo praticado nos 30 dias anteriores",
)
_CARD_BAD_PRICE_MARKERS = (
    "old-price",
    "oldprice",
    "regular price",
    "preco anterior",
    "preço anterior",
    "pvpr",
    *_OLD_PRICE_MARKERS,
)
price_guard_module.BAD_PRICE_CONTEXT = tuple(
    dict.fromkeys((*price_guard_module.BAD_PRICE_CONTEXT, *_OLD_PRICE_MARKERS))
)


def _linear_spec_pairs(soup) -> list[tuple]:
    strings = [str(value).strip() for value in soup.stripped_strings if str(value).strip()]
    out: list[tuple] = []
    for index, label in enumerate(strings[:-1]):
        key = _LINEAR_LABELS.get(scraper.norm(label))
        if not key:
            continue
        value = strings[index + 1].strip()
        normalized = scraper.norm(value)

        if key == "refresh" and re.fullmatch(r"\d{2,3}", normalized):
            value = f"{value} Hz"
        elif key == "weight" and re.fullmatch(r"\d(?:[.,]\d{1,2})?", normalized):
            value = f"{value} kg"
        elif key == "screen" and scraper.norm(label) == "dimensao ecra" and re.fullmatch(
            r"\d{1,2}(?:[.,]\d)?", normalized
        ):
            value = f'{value}"'

        out.append((key, label, value, "linear_label", 0.90))

        if scraper.norm(label) == "tipo de ecra":
            if re.search(r"\b(?:oled|ips|va|tn|mini[- ]?led)\b", normalized):
                out.append(("panel", label, value, "linear_label", 0.90))
            if re.search(r"\b\d{2,4}\s*(?:nits|cd/m2)\b", normalized):
                out.append(("brightness", label, value, "linear_label", 0.90))
    return out


def _pairs_with_linear_fallback(soup) -> list[tuple]:
    return [*_BASE_PAIRS(soup), *_linear_spec_pairs(soup)]


def _contextual_card_prices(card, cat: dict) -> list[float]:
    """Em lojas oficiais estritas, ignora preço antigo/histórico no cartão.

    Nas restantes lojas preserva exatamente o parser V8 existente.
    """
    strict = bool(cat.get("strict_current_price_context")) or cat.get("loja") == "ASUS Store"
    if not strict:
        return _BASE_CARD_PRICES(card, cat)

    values: list[float] = []
    selectors = cat.get("price_selectors", []) + [
        "[itemprop='price']",
        "[data-price]",
        "[class*='price']",
        "[class*='Price']",
    ]
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in card.select(selector):
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            previous = str(node.previous_sibling or "")[-140:]
            parent = getattr(node, "parent", None)
            parent_class = " ".join(parent.get("class", [])) if parent is not None else ""
            context = scraper.norm(
                f"{' '.join(node.get('class', []))} {node.get('id') or ''} "
                f"{parent_class} {previous} {raw}"
            )
            if any(
                marker in context
                for marker in (
                    "month",
                    "mensal",
                    "prestacao",
                    "/ mes",
                    "/mes",
                    "por mes",
                    *_CARD_BAD_PRICE_MARKERS,
                )
            ):
                continue
            direct = scraper.parse_price_value(raw)
            if direct is not None:
                values.append(float(direct))
            values.extend(float(value) for value in scraper.prices(str(raw)))
    # No modo estrito não fazemos fallback ao texto integral do cartão: se a
    # estrutura atual não for identificável, a ficha/sitemap confirma o preço.
    return values


scraper.pairs = _pairs_with_linear_fallback
scraper._card_prices = _contextual_card_prices

# O cérebro base é deliberadamente preservado. As correções entram por camadas
# pequenas, testáveis e independentes.
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
    match = re.search(
        r"ID\s+PRODUTO\s*:\s*[^|]{1,60}\|\s*(\d{8}|\d{12,14})\s*\|",
        text,
        re.I,
    )
    if match and tracker.gtin_valid(match.group(1)):
        out["ean"] = match.group(1)
    return out


tracker.page_identifiers = _enhanced_page_identifiers

# As camadas de acesso apenas alteram descoberta/cache; não mexem no cérebro.
# Awin fica antes da Coverage Guard para que candidatos autorizados recebam as
# mesmas regras de cache/fallback/live confirmation das restantes fontes.
install_version_guard(tracker)
install_promotion_guard(tracker)
install_gpu_guard(scraper, tracker)
install_hardware_guard(scraper, tracker)
install_market_guard(scraper, tracker)
install_historical_guard(tracker)
install_state_refresh_guard(tracker)
install_sitemap_route_guard(tracker)
install_catalog_guard(tracker)
install_awin_feed_guard(tracker)
install_coverage_guard(tracker)
install_sitemap_strategy_epoch_guard(tracker)
install_rejection_guard(scraper, tracker)
install_top5_guard(tracker)


def _safe_page_price(soup, structured_price: float | None = None) -> float | None:
    """Preço da ficha por evidência forte ou primeiro preço visível seguro."""
    evidence = page_price_evidence(soup, scraper)
    if evidence.get("price") is not None:
        return float(evidence["price"])

    if structured_price is not None and 200 <= float(structured_price) <= 10000:
        return float(structured_price)

    bad = tuple(BAD_PRICE_CONTEXT) + (
        "pvpr",
        "preco recomendado",
        "preço recomendado",
        *_OLD_PRICE_MARKERS,
    )
    for text_node in soup.find_all(string=lambda value: value and "€" in str(value)):
        raw = str(text_node).strip()
        if not raw or raw.lstrip().startswith("-"):
            continue
        parent = getattr(text_node, "parent", None)
        class_text = " ".join(parent.get("class", [])) if parent is not None else ""
        id_text = str(parent.get("id") or "") if parent is not None else ""
        previous = str(text_node.previous_sibling or "")[-100:]
        context = scraper.norm(f"{class_text} {id_text} {previous} {raw}")
        if any(marker in context for marker in bad):
            continue
        for value in scraper.prices(raw):
            if 200 <= float(value) <= 10000:
                return float(value)
    return None


tracker.preferred_page_price = _safe_page_price

main = tracker.main
merge_cli = tracker.merge_cli


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "merge-state":
        merge_cli(sys.argv[2:])
    else:
        main()