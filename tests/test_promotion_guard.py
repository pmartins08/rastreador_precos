import unittest
from datetime import date

import promotion_guard


class DummyTracker:
    def __init__(self):
        self._PROMOTION_GUARD_INSTALLED = False
        self.last_source = None
        self.discovery = {}

    def discovery_score(self, store, method):
        stats = self.discovery.get(method, {})
        if stats:
            return float(stats.get("yield", 0.0))
        return 3.0 if method.startswith("segment:") else 0.5

    def bucket(self, store):
        return {"discovery": self.discovery}

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

    def test_new_campaign_gets_short_exploration_priority(self):
        self.assertEqual(promotion_guard.promotion_priority_band(0, 0.0), 2)
        self.assertEqual(promotion_guard.promotion_priority_band(1, 0.0), 2)

    def test_proven_productive_campaign_keeps_priority(self):
        self.assertEqual(promotion_guard.promotion_priority_band(2, 2.0), 1)
        self.assertEqual(promotion_guard.promotion_priority_band(8, 5.0), 1)

    def test_weak_campaign_returns_to_normal_yield_competition(self):
        self.assertEqual(promotion_guard.promotion_priority_band(2, 0.0), 0)
        self.assertEqual(promotion_guard.promotion_priority_band(5, 1.99), 0)

    def test_new_promotion_beats_high_yield_normal_segment_temporarily(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        cat = {
            "campaign_urls": [
                {"label": "promo", "url": "https://example.com/promo", "priority": 100}
            ],
            "extra_discovery_urls": [
                {"label": "normal", "url": "https://example.com/normal"}
            ],
        }
        routes = tracker.discovery_routes(cat, "TEST")
        self.assertEqual(routes[0]["kind"], "promotion")
        self.assertEqual(routes[0]["priority_band"], 2)
        self.assertEqual(routes[1]["kind"], "segment")

    def test_weak_campaign_is_overtaken_by_productive_segment_after_learning(self):
        tracker = DummyTracker()
        tracker.discovery = {
            "campaign:promo": {"attempts": 3, "yield": 0.5},
            "segment:normal": {"attempts": 5, "yield": 4.0},
        }
        promotion_guard.install(tracker)
        cat = {
            "campaign_urls": [
                {"label": "promo", "url": "https://example.com/promo", "priority": 120}
            ],
            "extra_discovery_urls": [
                {"label": "normal", "url": "https://example.com/normal"}
            ],
        }
        routes = tracker.discovery_routes(cat, "TEST")
        self.assertEqual(routes[0]["kind"], "segment")
        self.assertEqual(routes[0]["yield_score"], 4.0)
        self.assertEqual(routes[1]["kind"], "promotion")
        self.assertEqual(routes[1]["priority_band"], 0)

    def test_no_campaign_is_invented_when_config_is_empty(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        self.assertEqual(tracker.discovery_routes({}, "FNAC"), [])

    def test_configured_campaign_is_available(self):
        tracker = DummyTracker()
        promotion_guard.install(tracker)
        cat = {
            "campaign_urls": [
                {
                    "label": "regresso_aulas_2026",
                    "url": "https://example.com/regresso-aulas",
                    "priority": 115,
                }
            ]
        }
        routes = tracker.discovery_routes(cat, "TEST")
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["method_key"], "campaign:regresso_aulas_2026")

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
        promoted = {"discovery_sources": [promotion_guard.PROMOTION_SOURCE]}
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
