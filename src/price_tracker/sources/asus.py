from __future__ import annotations

STORE_NAME = "ASUS Store"
STORE_URL = "https://estore.asus.com/pt/"


def store_config() -> dict:
    """Configuração de descoberta conservadora para a eShop ASUS Portugal."""
    return {
        "loja": STORE_NAME,
        "url": STORE_URL,
        "timeout_ms": 10000,
        "parent_climb": 8,
        "target_candidates": 35,
        "max_category_pages": 1,
        "sitemap_probe_limit": 6,
        "sitemap_new_probe_limit": 6,
        "sitemap_cache_reuse_limit": 16,
        "sitemap_cache_price_ttl_hours": 7,
        "max_sitemaps": 6,
        "max_sitemap_urls": 100,
        "strict_current_price_context": True,
        "product_path_hints": [
            "/pt/90",
            "portatil-",
            "potatil-",
            "tuf-gaming",
            "rog-",
            "vivobook",
            "zenbook",
            "expertbook",
            "proart",
        ],
        "card_selectors": ["article", "div[class*='product']", "li[class*='product']"],
    }
