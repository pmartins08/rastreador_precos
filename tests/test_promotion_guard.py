import unittest
from datetime import date

import promotion_guard


class DummyTracker:
    def __init__(self):
        self._PROMOTION_GUARD_INSTALLED = False

    @staticmethod
    def discovery_score(store, method):
        return 3.0 if method.startswith("segment:") else 0.5


class PromotionGuardTests(unittest.TestCase):
    def test_expired_campaign_is_inactive(self):
        route = {"expires_at": "2026-09-13"}
        self.assertTrue(promotion_guard.route_is_active(route, date(2026, 9, 13)))
        self.assertFalse(promotion_guard.route_is_active(route, date(2026, 9, 14)))

    def test_future_campaign_is_inactive(self):
        route = {"active_from": "2026-09-20"}
        self.assertFalse(promotion_guard.route_is_active(route, date(2026, 9, 19)))
        self.assertTrue(promotion_guard.route_is_active(route, date(2026, 9, 20)))

    def test_promotions_beat_high_yield_normal_segments(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        cat = {
            "campaign_urls": [
                {
                    "label": "promo",
                    "url": "https://example.com/promo",
                    "priority": 100,
                }
            ],
            "extra_discovery_urls": [
                {"label": "normal", "url": "https://example.com/normal"}
            ],
        }
        routes = tracker.discovery_routes(cat, "TEST")
        self.assertEqual(routes[0]["kind"], "promotion")
        self.assertEqual(routes[0]["method_key"], "campaign:promo")
        self.assertEqual(routes[1]["kind"], "segment")

    def test_default_campaign_is_added_by_store(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        routes = tracker.discovery_routes({}, "PcComponentes")
        self.assertTrue(any(route["kind"] == "promotion" for route in routes))
        self.assertTrue(any("regresso_aulas_2026" in route["method_key"] for route in routes))


if __name__ == "__main__":
    unittest.main()
