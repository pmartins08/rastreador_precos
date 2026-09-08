from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

import scraper as brain
from pricing import best_product_price, parse_price_value, prices


DEFAULT_CARD_SELECTORS = [
    "article",
    "li[class*='product']",
    "div[class*='product-card']",
    "div[class*='productCard']",
    "div[class*='product-item']",
    "div[class*='ProductItem']",
    "div[data-name='product']",
    "div[class*='item-product']",
    "div[class*='productTile']",
]


def _product_link(card: BeautifulSoup, base_url: str, cat: dict):
    hints = cat.get("product_path_hints", [])
    fallback = None
    for anchor in card.find_all("a", href=True):
        full_url = urljoin(base_url, anchor["href"])
        if fallback is None and brain.same_host(full_url, base_url):
            fallback = (anchor, full_url)
        if brain.same_host(full_url, base_url) and brain.product_path_ok(full_url, hints):
            return anchor, full_url
    return fallback or (None, None)


def _title(card: BeautifulSoup, anchor) -> str:
    title_node = card.select_one("h1,h2,h3,h4,[class*='title'],[class*='name'],a[title]")
    if title_node:
        title = title_node.get("title") or title_node.get_text(" ", strip=True)
        if title and len(title.strip()) >= 6:
            return title.strip()
    if anchor:
        title = anchor.get("title") or anchor.get_text(" ", strip=True)
        if title:
            return title.strip()
    return ""


def _card_prices(card: BeautifulSoup, cat: dict) -> list[float]:
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
            direct = parse_price_value(raw)
            if direct is not None:
                values.append(direct)
            values.extend(prices(str(raw)))
    if not values:
        values.extend(prices(card.get_text(" ", strip=True)))
    return values


def candidate_from_card(card: BeautifulSoup, base_url: str, cat: dict) -> dict | None:
    anchor, url = _product_link(card, base_url, cat)
    title = _title(card, anchor)
    if not url or not title or not brain.eligible(title):
        return None

    price = best_product_price(_card_prices(card, cat))
    if price is None:
        return None

    text = card.get_text(" ", strip=True)
    stock_value = brain.stock(text)
    return {
        "loja": cat["loja"],
        "titulo": title,
        "preco": price,
        "url": url,
        "stock": True if stock_value is None else stock_value,
    }


def _add(out: list[dict], seen: set[str], item: dict, limit: int) -> None:
    url = item.get("url")
    if not url or url in seen or len(out) >= limit:
        return
    seen.add(url)
    out.append(item)


def discover_category(html: str, cat: dict, limit: int) -> list[dict]:
    """Combina JSON-LD, cartões e links em vez de parar na primeira fonte parcial."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()

    for record in brain.jsonld_products(soup):
        if len(out) >= limit:
            break
        title = record.get("titulo") or ""
        price = record.get("preco")
        url = urljoin(cat["url"], record.get("url") or "")
        if (
            brain.eligible(title)
            and price is not None
            and 200 <= float(price) <= 4500
            and brain.same_host(url, cat["url"])
        ):
            _add(
                out,
                seen,
                {
                    "loja": cat["loja"],
                    "titulo": title.strip(),
                    "preco": float(price),
                    "url": url,
                    "stock": True if record.get("stock") is None else record.get("stock"),
                },
                limit,
            )

    selectors = cat.get("card_selectors") or DEFAULT_CARD_SELECTORS
    for card in soup.select(",".join(selectors)):
        if len(out) >= limit:
            break
        item = candidate_from_card(card, cat["url"], cat)
        if item:
            _add(out, seen, item, limit)

    if len(out) < limit:
        hints = cat.get("product_path_hints", [])
        for anchor in soup.find_all("a", href=True):
            if len(out) >= limit:
                break
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            full_url = urljoin(cat["url"], anchor["href"])
            if (
                not title
                or not brain.same_host(full_url, cat["url"])
                or not brain.product_path_ok(full_url, hints)
                or not brain.eligible(title)
                or full_url in seen
            ):
                continue

            parent = anchor
            for _ in range(int(cat.get("parent_climb", 7))):
                parent = parent.parent
                if parent is None:
                    break
                price = best_product_price(prices(parent.get_text(" ", strip=True)))
                if price is None:
                    continue
                _add(
                    out,
                    seen,
                    {
                        "loja": cat["loja"],
                        "titulo": title.strip(),
                        "preco": price,
                        "url": full_url,
                        "stock": brain.stock(parent.get_text(" ", strip=True)),
                    },
                    limit,
                )
                break

    return out[:limit]
