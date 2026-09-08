from __future__ import annotations

import scraper
from price_guard import BAD_PRICE_CONTEXT, VERSION, install, page_price_evidence


install(scraper)

import tracker


tracker.VERSION = VERSION
tracker.COMPATIBLE_STATE_VERSIONS.add(VERSION)


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


# O tracker continua responsável por toda a operação; a V8.8 apenas substitui
# o seletor de preço da ficha por uma versão que preserva promoções reais sem
# voltar ao antigo erro de usar descontos/mensalidades como preço do portátil.
tracker.preferred_page_price = _safe_page_price

main = tracker.main


if __name__ == "__main__":
    main()
