import unittest
from datetime import date

import promotion_guard


class DummyTracker:
    def __init__(self):
        self._PROMOTION_GUARD_INSTALLED = False
        self.last_source = None

    @staticmethod
    def discovery_score(store, method):
        return 3.0 if method.startswith("segment:") else 0.5

    def _discover_html(self, response, route_cat, target, candidates, source, stat):
        self.last_source = source
        return 0

    @staticmethod
    def candidate_priority(item, weights, settings):
        return 50.0


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

    def test_default_campaign_is_added_by_store_without_date_fragility(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        routes = tracker.discovery_routes({}, "FNAC")
        self.assertTrue(any(route["kind"] == "promotion" for route in routes))
        self.assertTrue(any("regresso_aulas_2026" in route["method_key"] for route in routes))

    def test_campaign_source_is_recorded_separately(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        cat = {
            "loja": "TEST",
            "url": "https://example.com/promo",
            "campaign_urls": [
                {"label": "promo", "url": "https://example.com/promo"}
            ],
        }
        stat = {"fontes_descoberta": {}}
        tracker._discover_html(None, cat, 10, {}, "segmento", stat)
        self.assertEqual(tracker.last_source, promotion_guard.PROMOTION_SOURCE)
        self.assertIn(promotion_guard.PROMOTION_SOURCE, stat["fontes_descoberta"])

    def test_campaign_bonus_only_affects_pre_ranking(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        promoted = {
            "discovery_sources": [promotion_guard.PROMOTION_SOURCE]
        }
        normal = {"discovery_sources": ["categoria"]}
        self.assertEqual(tracker.candidate_priority(normal, {}, {}), 50.0)
        self.assertEqual(tracker.candidate_priority(promoted, {}, {}), 56.0)
        self.assertEqual(
            tracker.candidate_priority(
                promoted, {}, {"promotion_candidate_priority_bonus": 9.5}
            ),
            59.5,
        )


if __name__ == "__main__":
    unittest.main()
