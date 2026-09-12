import unittest

import promotion_coverage_guard


class DummyResponse:
    status_code = 200


class DummyTracker:
    def __init__(self):
        self._PROMOTION_COVERAGE_GUARD_INSTALLED = False
        self.fetch_calls = []
        self.refresh_calls = 0

    @staticmethod
    def select_for_evaluation(items, limit, weights, settings):
        return list(items)[:limit]

    @staticmethod
    def select_with_cache(items, spec_cache, max_items, weights, settings):
        # Simula o wrapper antigo que destruía a cache promocional.
        for item in items:
            if item.get("promotions") and item.get("url"):
                spec_cache.pop(item["url"], None)
        return list(items)[:max_items]

    def needs_price_refresh(self, previous_meta, item, settings, *, current_time=None):
        self.refresh_calls += 1
        return True

    def adaptive_fetch(self, url, config, timeout_s=8.0, *, store=None, method="page", **kwargs):
        self.fetch_calls.append((url, timeout_s, store, method))
        return DummyResponse(), "chrome", "http_success"


class PromotionCoverageGuardTests(unittest.TestCase):
    def setUp(self):
        self.tracker = DummyTracker()
        promotion_coverage_guard.install(self.tracker)

    @staticmethod
    def promo_item(url="https://www.radiopopular.pt/produto/test"):
        return {
            "loja": "Radio Popular",
            "url": url,
            "preco": 1299.99,
            "promotions": [{"kind": "TIERED_DISCOUNT"}],
            "promotion_listing_live_confirmed": True,
            "promotion_price_live_confirmed": True,
        }

    def test_live_campaign_does_not_delete_hardware_cache(self):
        item = self.promo_item()
        cache = {item["url"]: {"ram_gb": 32, "gpu": "RTX 5050"}}
        selected = self.tracker.select_with_cache([item], cache, 10, {}, {})
        self.assertEqual(selected, [item])
        self.assertIn(item["url"], cache)
        self.assertEqual(cache[item["url"]]["ram_gb"], 32)

    def test_live_campaign_listing_does_not_require_second_price_fetch(self):
        item = self.promo_item()
        self.assertFalse(self.tracker.needs_price_refresh({}, item, {}))
        self.assertEqual(self.tracker.refresh_calls, 0)

    def test_non_campaign_item_keeps_existing_refresh_logic(self):
        item = {"loja": "Radio Popular", "url": "https://example.com", "preco": 999.0}
        self.assertTrue(self.tracker.needs_price_refresh({}, item, {}))
        self.assertEqual(self.tracker.refresh_calls, 1)

    def test_radio_popular_product_fetch_gets_longer_timeout(self):
        self.tracker.adaptive_fetch(
            "https://www.radiopopular.pt/produto/test", {}, 8,
            store="Radio Popular", method="product"
        )
        self.assertEqual(self.tracker.fetch_calls[-1][1], 14.0)

    def test_other_store_timeout_is_untouched(self):
        self.tracker.adaptive_fetch(
            "https://example.com/product", {}, 8,
            store="FNAC", method="product"
        )
        self.assertEqual(self.tracker.fetch_calls[-1][1], 8.0)


if __name__ == "__main__":
    unittest.main()
