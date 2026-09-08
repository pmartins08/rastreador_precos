from __future__ import annotations

import scraper as brain
from brands import BRANDS, EXCLUDE, brand, eligible
from catalog import candidate_from_card, discover_category
from hardware import cpu as classify_cpu
from pricing import parse_price_value, prices
from structured_data import jsonld_products


def apply() -> None:
    """Aplica correções de parsing ao V8 sem alterar os pesos nem a fórmula de scoring."""
    brain.BRANDS = BRANDS
    brain.EXCLUDE = sorted(EXCLUDE)
    brain.brand = brand
    brain.eligible = eligible
    brain.parse_price_value = parse_price_value
    brain.prices = prices
    brain.cpu = lambda text: classify_cpu(text, brain.norm)
    brain.jsonld_products = jsonld_products
    brain.candidate_from_card = candidate_from_card
    brain.discover_category = discover_category
