from __future__ import annotations

import types
import unittest

import catalog_guard


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Scraper:
    @staticmethod
    def eligible(title):
        return any(brand in str(title).lower() for brand in ("asus", "lenovo", "hp"))

    @staticmethod
    def parse_price_value(value):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None


class CatalogGuardTests(unittest.TestCase):
    def _module(self, payload):
        module = types.SimpleNamespace()
        module._CATALOG_GUARD_INSTALLED = False
        module.scraper = _Scraper()
        module.REQUESTS_BY_STORE = {}
        module.BLOCK_OUTCOMES = {"http_403", "challenge"}
        module._payload = payload
        module._discovery = {}
        module._learning = []

        def base_scan(cat, config, settings):
            return [], {
                "candidatos": 0,
                "bloqueada": True,
                "fontes_descoberta": {},
                "rendimento_descoberta": {},
            }

        module.scan_store = base_scan
        module.profile_order = lambda store, method: ["chrome131"]
        module.headers = lambda profile: {"User-Agent": profile}
        module.budget_available = lambda store=None: True

        def consume(store):
            module.REQUESTS_BY_STORE[store] = module.REQUESTS_BY_STORE.get(store, 0) + 1
            return True

        module.consume_request = consume
        module.requests = types.SimpleNamespace(
            get=lambda *args, **kwargs: _Response(module._payload)
        )
        module.classify = lambda response: ("http_success", False)
        module.record_learning = lambda *args: module._learning.append(args)

        def record_yield(store, method, spent, added):
            module._discovery[method] = {"requests": spent, "new_candidates": added}

        module.record_discovery_yield = record_yield
        module.gtin_valid = lambda value: str(value).isdigit() and len(str(value)) in {8, 12, 13, 14}
        return module

    def test_public_shopify_collection_json_adds_brand_candidates(self):
        payload = {
            "products": [
                {
                    "title": "ASUS TUF Gaming A16 RTX 5060",
                    "handle": "portatil-asus-tuf-a16",
                    "variants": [
                        {
                            "price": "1299.99",
                            "available": True,
                            "sku": "FA608UM",
                            "barcode": "1234567890123",
                        }
                    ],
                },
                {
                    "title": "Samsung TV",
                    "handle": "tv-samsung",
                    "variants": [{"price": "499.99", "available": True}],
                },
            ]
        }
        module = self._module(payload)
        catalog_guard.install(module)
        items, stat = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://darty.pt/collections/portateis",
                "target_candidates": 80,
                "public_catalog_json_url": "https://darty.pt/collections/portateis/products.json?limit=250",
                "catalog_json_below": 20,
            },
            {},
            {},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://darty.pt/products/portatil-asus-tuf-a16")
        self.assertEqual(items[0]["preco"], 1299.99)
        self.assertEqual(items[0]["sku"], "FA608UM")
        self.assertEqual(items[0]["ean"], "1234567890123")
        self.assertFalse(stat["bloqueada"])
        self.assertEqual(stat["fontes_descoberta"]["catalog_json"], 1)
        self.assertEqual(module.REQUESTS_BY_STORE["Darty"], 1)

    def test_catalog_probe_is_skipped_when_base_coverage_is_sufficient(self):
        module = self._module({"products": []})

        def enough(cat, config, settings):
            items = [
                {"loja": "Darty", "titulo": "ASUS X", "preco": 999, "url": f"https://darty.pt/p/{i}"}
                for i in range(20)
            ]
            return items, {"candidatos": 20, "bloqueada": False, "fontes_descoberta": {}, "rendimento_descoberta": {}}

        module.scan_store = enough
        catalog_guard.install(module)
        items, _stat = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://darty.pt/collections/portateis",
                "public_catalog_json_url": "https://darty.pt/collections/portateis/products.json?limit=250",
                "catalog_json_below": 20,
            },
            {},
            {},
        )
        self.assertEqual(len(items), 20)
        self.assertNotIn("Darty", module.REQUESTS_BY_STORE)


if __name__ == "__main__":
    unittest.main()
