from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
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

        module.scan_store = Mock(side_effect=base_scan)
        module._empty_store_stats = lambda: {"candidatos": 0, "bloqueada": False, "fontes_descoberta": {}, "rendimento_descoberta": {}}
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

    def _cat(self, **overrides):
        return {
            "loja": "Darty", "url": "https://darty.pt/collections/portateis",
            "public_catalog_json_url": "https://darty.pt/collections/portateis/products.json?limit=2",
            "catalog_json_first": True, "catalog_json_below": 2,
            "catalog_json_candidate_limit": 10, "catalog_json_max_pages": 3,
            **overrides,
        }

    def _product(self, number, price="999", available=True):
        return {"id": number, "handle": f"asus-{number}", "title": f"Portátil ASUS {number}",
                "variants": [{"price": price, "available": available}]}

    def test_primary_catalog_skips_expensive_discovery_and_keeps_live_seeds(self):
        module = self._module({"products": [self._product(1), self._product(2)]})
        base = module.scan_store
        catalog_guard.install(module)
        items, stats = module.scan_store(self._cat(catalog_json_max_pages=1), {}, {})
        base.assert_not_called()
        self.assertEqual(len(items), 2)
        self.assertEqual(module.REQUESTS_BY_STORE["Darty"], 1)
        self.assertFalse(stats["catalog_json_fallback"])
        self.assertTrue(all("specs" not in item for item in items))
        self.assertTrue(all(item["detail_source"] == "catalog_json_seed" for item in items))

    def test_primary_catalog_paginates_and_deduplicates(self):
        module = self._module({})
        module.requests.get = Mock(side_effect=[
            _Response({"products": [self._product(1), self._product(2)]}),
            _Response({"products": [self._product(2), self._product(3)]}),
            _Response({"products": [self._product(4)]}),
        ])
        catalog_guard.install(module)
        items, stats = module.scan_store(self._cat(), {}, {})
        self.assertEqual(len(items), 4)
        self.assertEqual(stats["catalog_json_pages"], 3)
        self.assertTrue(stats["catalog_json_exhausted"])
        self.assertIn("page=2", module.requests.get.call_args_list[1].args[0])

    def test_repeated_catalog_page_stops_without_duplicate_candidates(self):
        module = self._module({"products": [self._product(1), self._product(2)]})
        catalog_guard.install(module)
        items, stats = module.scan_store(self._cat(), {}, {})
        self.assertEqual(len(items), 2)
        self.assertEqual(module.REQUESTS_BY_STORE["Darty"], 2)
        self.assertEqual(stats["catalog_json_outcome"], "repeated_page")
        self.assertFalse(stats["catalog_json_exhausted"])

    def test_only_usable_stock_and_prices_count_towards_primary_coverage(self):
        module = self._module({"products": [
            self._product(1, "999", False), self._product(2, "2000"),
            self._product(3, "NaN"), self._product(4, "99"), self._product(5),
        ]})
        base = module.scan_store
        catalog_guard.install(module)
        items, stats = module.scan_store(self._cat(catalog_json_max_pages=1), {}, {})
        base.assert_called_once()
        self.assertEqual(len(items), 1)
        self.assertTrue(stats["catalog_json_fallback"])

    def test_malformed_or_blocked_catalog_uses_existing_discovery_once(self):
        for payload, outcome in [({"error": "maintenance"}, "http_success"), ({}, "http_403")]:
            with self.subTest(outcome=outcome):
                module = self._module(payload)
                module.classify = lambda response: (outcome, False)
                base = module.scan_store
                catalog_guard.install(module)
                items, stats = module.scan_store(self._cat(), {}, {})
                base.assert_called_once()
                self.assertTrue(stats["catalog_json_fallback"])
                self.assertEqual(module.REQUESTS_BY_STORE["Darty"], 1)

    def test_partial_catalog_survives_later_page_error(self):
        module = self._module({})
        module.requests.get = Mock(side_effect=[
            _Response({"products": [self._product(1), self._product(2)]}),
            ValueError("failed"),
        ])
        catalog_guard.install(module)
        items, stats = module.scan_store(self._cat(), {}, {})
        self.assertEqual(len(items), 2)
        self.assertEqual(stats["catalog_json_outcome"], "request_error")

    def test_exhausted_request_budget_does_not_fetch_catalog(self):
        module = self._module({})
        module.consume_request = lambda store: False
        module.requests.get = Mock()
        catalog_guard.install(module)
        _, stats = module.scan_store(self._cat(), {}, {})
        module.requests.get.assert_not_called()
        self.assertEqual(stats["catalog_json_outcome"], "request_budget_exhausted")

    def test_laptop_catalog_excludes_consoles_desktops_and_accessories(self):
        module = self._module({})
        payload = {"products": [
            {**self._product(1), "title": "Consola Portátil Asus ROG Xbox Ally"},
            {**self._product(2), "title": "Desktop Lenovo IdeaCentre"},
            {**self._product(3), "title": "Monitor HP para portátil"},
            {**self._product(4), "title": "Portátil ASUS TUF A16"},
            {**self._product(5), "title": "HP", "product_type": "Computadores Portáteis"},
        ]}
        rows = catalog_guard._shopify_candidates(payload, self._cat(catalog_laptop_only=True), module)
        self.assertEqual([r["url"].rsplit("-", 1)[-1] for r in rows], ["4", "5"])

    def test_catalog_hint_does_not_override_live_promotional_price(self):
        module = self._module({})
        module.enrich = Mock(return_value=(
            {"preco": 699.99, "specs": {"price_confirmed": 699.99, "price_page_confidence": "MEDIUM"}},
            {"error": None, "access": "http_success"},
        ))
        base = module.enrich
        catalog_guard.install(module)
        seed = {"preco": 899.99, "_catalog_price_hint": 899.99}
        item, status = module.enrich(seed, {})
        self.assertIsNone(base.call_args.args[0]["preco"])
        self.assertEqual(seed["preco"], 899.99)
        self.assertEqual(item["preco"], 699.99)
        self.assertEqual(item["specs"]["catalog_price_hint"], 899.99)
        self.assertEqual(item["specs"]["price_page_confidence"], "MEDIUM")
        self.assertIsNone(status["error"])

    def test_catalog_missing_live_price_cannot_be_scored_as_confirmed(self):
        module = self._module({})
        module.enrich = Mock(return_value=({"preco": 899.99, "specs": {}}, {"error": None}))
        catalog_guard.install(module)
        _, status = module.enrich({"preco": 899.99, "_catalog_price_hint": 899.99}, {})
        self.assertEqual(status["error"], "catalog_live_price_unconfirmed")

    def test_failed_catalog_product_keeps_access_failure(self):
        module = self._module({})
        module.enrich = Mock(return_value=({}, {"error": "access_failed", "access": "http_403"}))
        catalog_guard.install(module)
        _, status = module.enrich({"preco": 899.99, "_catalog_price_hint": 899.99}, {})
        self.assertEqual(status["access"], "http_403")
        self.assertEqual(status["error"], "access_failed")

    def test_regular_store_seed_is_unchanged(self):
        module = self._module({})
        module.enrich = Mock(return_value=({}, {"error": None}))
        base = module.enrich
        catalog_guard.install(module)
        seed = {"preco": 899.99}
        module.enrich(seed, {})
        self.assertIs(base.call_args.args[0], seed)

    def test_live_catalog_price_cache_requires_same_hint_and_fresh_confirmation(self):
        now = datetime(2026, 9, 11, 23, tzinfo=timezone.utc)
        previous = {"price": 699.99, "specs": {
            "catalog_price_hint": 899.99, "price_confirmed": 699.99,
            "price_page_confidence": "MEDIUM",
            "price_checked_at": (now - timedelta(hours=1)).isoformat(),
        }}
        self.assertEqual(catalog_guard._reusable_live_catalog_price(previous, 899.99, now=now), 699.99)
        self.assertIsNone(catalog_guard._reusable_live_catalog_price(previous, 999.99, now=now))
        self.assertIsNone(catalog_guard._reusable_live_catalog_price(previous, 899.99, now=now + timedelta(hours=5)))
        self.assertIsNone(catalog_guard._reusable_live_catalog_price(previous, 899.99, now=now - timedelta(hours=2)))
        previous["specs"]["price_page_confidence"] = "UNKNOWN"
        self.assertIsNone(catalog_guard._reusable_live_catalog_price(previous, 899.99, now=now))

    def test_catalog_promotion_still_uses_real_price_guard_for_suspicious_prices(self):
        import price_guard
        validation = price_guard.validate_price({
            "gpu_tipo": "dedicada", "gpu_modelo": "rtx 5070",
            "price_confirmed": 399.99, "price_page_confidence": "MEDIUM",
        }, 399.99, {})
        self.assertEqual(validation["status"], "PRICE_UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()
