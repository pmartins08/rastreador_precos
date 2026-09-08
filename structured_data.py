from __future__ import annotations

import json

from pricing import parse_price_value


def _types(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(x).lower() for x in value}
    if value is None:
        return set()
    return {str(value).lower()}


def _offer_candidates(offers: object) -> list[dict]:
    if isinstance(offers, dict):
        if "@graph" in offers and isinstance(offers["@graph"], list):
            return [x for x in offers["@graph"] if isinstance(x, dict)]
        return [offers]
    if isinstance(offers, list):
        return [x for x in offers if isinstance(x, dict)]
    return []


def _availability(value: object) -> bool | None:
    text = str(value or "").lower()
    if not text:
        return None
    if "outofstock" in text or "soldout" in text or "discontinued" in text:
        return False
    if "instock" in text or "limitedavailability" in text or "preorder" in text:
        return True
    return None


def jsonld_products(soup) -> list[dict]:
    """Extrai Product/Offer de JSON-LD, incluindo offers em lista e @graph."""
    out: list[dict] = []
    seen: set[tuple[str, str, float | None]] = set()

    for node in soup.find_all("script", type="application/ld+json"):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_types = _types(item.get("@type"))
            is_product = "product" in item_types or "offers" in item
            is_offer = "offer" in item_types
            if is_product or is_offer:
                name = item.get("name")
                item_url = item.get("url")
                price = parse_price_value(item.get("price"))
                stock = _availability(item.get("availability"))
                offers = _offer_candidates(item.get("offers"))

                for offer in offers:
                    offer_price = parse_price_value(
                        offer.get("price")
                        or offer.get("lowPrice")
                        or offer.get("highPrice")
                    )
                    if offer_price is not None:
                        price = offer_price
                    if not item_url and offer.get("url"):
                        item_url = offer.get("url")
                    offer_stock = _availability(offer.get("availability"))
                    if offer_stock is not None:
                        stock = offer_stock
                    if not name and offer.get("name"):
                        name = offer.get("name")
                    if price is not None:
                        break

                if name and item_url:
                    record = {
                        "titulo": str(name).strip(),
                        "url": str(item_url).strip(),
                        "preco": price,
                        "stock": stock,
                    }
                    key = (record["titulo"], record["url"], record["preco"])
                    if key not in seen:
                        seen.add(key)
                        out.append(record)

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            for key, value in item.items():
                if key == "@graph":
                    continue
                if isinstance(value, (dict, list)):
                    stack.append(value)

    return out
