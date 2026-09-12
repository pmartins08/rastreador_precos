from __future__ import annotations

from urllib.parse import urljoin


def _current_card_price(scraper_module, card) -> float | None:
    """Lê primeiro o preço corrente explícito do cartão RP, nunca o PVPR."""
    values: list[float] = []
    for node in card.select(".price[content], [data-price]"):
        classes = {str(value).lower() for value in (node.get("class") or [])}
        if "old-price" in classes or "oldprice" in classes:
            continue
        raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
        value = scraper_module.parse_price_value(raw)
        if value is not None and 200 <= float(value) <= 4500:
            values.append(float(value))
    return min(values) if values else None


def _radio_popular_fallback(scraper_module, card, base_url: str, cat: dict) -> dict | None:
    hints = cat.get("product_path_hints", [])
    for anchor in card.find_all("a", href=True):
        full_url = urljoin(base_url, str(anchor.get("href") or ""))
        if not scraper_module.same_host(full_url, base_url):
            continue
        if not scraper_module.product_path_ok(full_url, hints):
            continue
        title = (anchor.get("title") or anchor.get_text(" ", strip=True) or "").strip()
        if not title or not scraper_module.eligible(title):
            continue

        price = _current_card_price(scraper_module, card)
        if price is None:
            price = scraper_module.best_product_price(scraper_module._card_prices(card, cat))
        if price is None or not scraper_module.price_is_plausible_for_title(title, float(price)):
            continue

        text = card.get_text(" ", strip=True)
        return {
            "loja": cat["loja"],
            "titulo": title,
            "preco": float(price),
            "url": full_url,
            "stock": scraper_module.stock(text),
        }
    return None


def install(scraper_module) -> None:
    """Evita que etiquetas de oferta sejam confundidas com o título do portátil.

    A Radio Popular pode colocar um bloco como ``OFERTA: Norton`` antes da
    designação do produto. O parser genérico procura classes que contenham
    ``title`` e pode escolher esse texto promocional, descartando depois um
    cartão perfeitamente válido. Mantemos o parser genérico para todas as lojas
    e usamos um fallback estreito, apenas para a RP, baseado no próprio link
    ``/produto/`` e no preço corrente explícito ``.price[content]``.
    """
    if getattr(scraper_module, "_RADIO_POPULAR_CARD_GUARD_INSTALLED", False):
        return

    base_candidate_from_card = scraper_module.candidate_from_card

    def candidate_from_card(card, base_url: str, cat: dict):
        result = base_candidate_from_card(card, base_url, cat)
        if result is not None or str(cat.get("loja") or "") != "Radio Popular":
            return result
        return _radio_popular_fallback(scraper_module, card, base_url, cat)

    scraper_module.candidate_from_card = candidate_from_card
    scraper_module._RADIO_POPULAR_CARD_GUARD_INSTALLED = True
