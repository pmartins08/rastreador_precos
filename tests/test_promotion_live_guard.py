import unittest

import promotion_live_guard


class Response:
    status_code = 200

    def __init__(self, text):
        self.text = text


class DummyTracker:
    def __init__(self):
        self._PROMOTION_LIVE_GUARD_INSTALLED = False

    @staticmethod
    def _discover_html(response, route_cat, target, candidates, source, stat):
        candidates["https://example.com/p"] = {
            "discovery_sources": ["promocao"],
            "promotions": [{
                "kind": "TIERED_DISCOUNT",
                "threshold_step_eur": 250,
                "step_discount_eur": 50,
                "eligibility": "campaign_listing",
                "applicable": True,
                "source": "campaign:configured_wrong_dates",
                "valid_from": "2026-09-12",
                "valid_until": "2026-09-15",
            }],
        }
        return 1


class PromotionLiveGuardTests(unittest.TestCase):
    def test_expired_landing_removes_configured_campaign_economics(self):
        tracker = DummyTracker()
        promotion_live_guard.install(tracker)
        candidates = {}
        stat = {}
        tracker._discover_html(
            Response("Promoção válida de 04 a 08 de junho de 2026. Ganha 50€ por cada 250€ em compras."),
            {"url": "https://example.com/promo"}, 10, candidates, "promocao", stat,
        )
        self.assertNotIn("promotions", candidates["https://example.com/p"])
        self.assertEqual(stat["promotion_live_confirmed"], 0)

    def test_live_landing_replaces_configured_rule_with_live_rule(self):
        tracker = DummyTracker()
        promotion_live_guard.install(tracker)
        candidates = {}
        stat = {}
        tracker._discover_html(
            Response("Promoção de 12 a 15 de setembro de 2026. Ganha 25€ por cada 250€ em compras."),
            {"url": "https://example.com/promo"}, 10, candidates, "promocao", stat,
        )
        promo = candidates["https://example.com/p"]["promotions"][0]
        self.assertEqual(promo["step_discount_eur"], 25.0)
        self.assertEqual(promo["source"], "campaign_page_live")
        self.assertEqual(stat["promotion_live_confirmed"], 1)


if __name__ == "__main__":
    unittest.main()
