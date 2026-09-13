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
        for item in items:
            if item.get("promotions") and item.get("url"):
                spec_cache.pop(item["url"], None)
        return list(items)[:max_items]

    def needs_price_refresh(self, previous_meta, item, settings, *, current_time=None):
        self.refresh_calls += 1
        if not previous_meta:
            return False
        spec = previous_meta.get("specs", {}) if isinstance(previous_meta, dict) else {}
        confirmed = spec.get("price_confirmed")
        if confirmed is None:
            return True
        try:
            return abs(float(confirmed) - float(item.get("preco"))) >= 35.0
        except (TypeError, ValueError):
            return True

    def adaptive_fetch(self, url, config, timeout_s=8.0, *, store=None, method="page", **kwargs):
        self.fetch_calls.append((url, timeout_s, store, method))
        return DummyResponse(), "chrome", "http_success"


class PromotionCoverageGuardTests(unittest.TestCase):
    def setUp(self):
        self.tracker = DummyTracker()
        promotion_coverage_guard.install(self.tracker)

    @staticmethod
    def promo_item(url="https://www.radiopopular.pt/produto/test", price=1299.99):
        return {
            "loja": "Radio Popular",
            "url": url,
            "preco": price,
            "promotions": [{
                "kind": "TIERED_DISCOUNT",
                "threshold_step_eur": 250.0,
                "step_discount_eur": 50.0,
                "cap_eur": 500.0,
                "applicable": True,
            }],
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

    def test_confirmed_campaign_item_is_not_cut_by_global_limit(self):
        normal_a = {"loja": "FNAC", "url": "https://example.com/a", "preco": 700.0}
        normal_b = {"loja": "Darty", "url": "https://example.com/b", "preco": 800.0}
        promo = self.promo_item("https://www.radiopopular.pt/produto/cb2")
        selected = self.tracker.select_with_cache([normal_a, normal_b, promo], {}, 2, {}, {})
        self.assertIn(promo, selected)
        self.assertEqual(len(selected), 2)

    def test_all_confirmed_campaign_items_are_reserved_before_regular_candidates(self):
        promos = [self.promo_item(f"https://www.radiopopular.pt/produto/promo-{index}") for index in range(3)]
        normals = [
            {"loja": "FNAC", "url": f"https://example.com/{index}", "preco": 700.0 + index}
            for index in range(3)
        ]
        selected = self.tracker.select_with_cache([*normals, *promos], {}, 4, {}, {})
        self.assertEqual(selected[:3], promos)
        self.assertEqual(len(selected), 4)

    def test_new_normal_campaign_listing_does_not_require_second_price_fetch(self):
        item = self.promo_item()
        self.assertFalse(self.tracker.needs_price_refresh({}, item, {"preco_minimo_global": 250}))
        self.assertEqual(self.tracker.refresh_calls, 0)

    def test_campaign_material_price_change_requires_product_refresh(self):
        item = self.promo_item(price=699.99)
        previous = {"specs": {"price_confirmed": 899.99}}
        self.assertTrue(self.tracker.needs_price_refresh(previous, item, {"preco_minimo_global": 250}))
        self.assertEqual(self.tracker.refresh_calls, 1)

    def test_campaign_missing_cached_price_confirmation_requires_refresh(self):
        item = self.promo_item(price=699.99)
        previous = {"specs": {"ram_gb": 16}}
        self.assertTrue(self.tracker.needs_price_refresh(previous, item, {"preco_minimo_global": 250}))

    def test_campaign_checkout_below_global_floor_requires_refresh_even_when_new(self):
        item = self.promo_item(price=295.0)
        self.assertTrue(self.tracker.needs_price_refresh({}, item, {"preco_minimo_global": 250}))
        self.assertEqual(self.tracker.refresh_calls, 0)

    def test_legitimate_299_campaign_price_is_verified_because_checkout_is_249(self):
        item = self.promo_item(price=299.99)
        self.assertTrue(self.tracker.needs_price_refresh({}, item, {"preco_minimo_global": 250}))

    def test_non_campaign_item_keeps_existing_refresh_logic(self):
        item = {"loja": "Radio Popular", "url": "https://example.com", "preco": 999.0}
        self.assertFalse(self.tracker.needs_price_refresh({}, item, {}))
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
