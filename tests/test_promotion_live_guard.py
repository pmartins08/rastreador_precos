import unittest

import promotion_live_guard


class Response:
    status_code = 200

    def __init__(self, text):
        self.text = text


# Generic campaign economics used by the live-validation tests.  The date
# window itself is tested elsewhere; keeping this fixture undated prevents
# otherwise unrelated tests from expiring as wall-clock time moves on.
CONFIGURED_PROMO = {
    "kind": "TIERED_DISCOUNT",
    "title": "Ganha 50€ por cada 250€ em compras (até 500€)",
    "threshold_step_eur": 250,
    "step_discount_eur": 50,
    "cap_eur": 500,
    "eligibility": "campaign_listing",
    "applicable": True,
    "source": "official_campaign",
}


class DummyTracker:
    def __init__(self):
        self._PROMOTION_LIVE_GUARD_INSTALLED = False
        self.calls = 0

    def _discover_html(self, response, route_cat, target, candidates, source, stat):
        self.calls += 1
        candidates[f"https://example.com/p{self.calls}"] = {
            "discovery_sources": ["promocao"],
            "promotions": [dict(CONFIGURED_PROMO)],
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
        self.assertNotIn("promotions", candidates["https://example.com/p1"])
        self.assertEqual(stat["promotion_live_confirmed"], 0)

    def test_current_landing_confirms_configured_rule_and_preserves_cap(self):
        tracker = DummyTracker()
        promotion_live_guard.install(tracker)
        candidates = {}
        stat = {}
        tracker._discover_html(
            Response("Ganha 50€ por cada 250€ em compras."),
            {"url": "https://example.com/promo"}, 10, candidates, "promocao", stat,
        )
        promo = candidates["https://example.com/p1"]["promotions"][0]
        self.assertEqual(promo["step_discount_eur"], 50)
        self.assertEqual(promo["threshold_step_eur"], 250)
        self.assertEqual(promo["cap_eur"], 500)
        self.assertEqual(promo["source"], "campaign_page_live_verified")
        self.assertTrue(promo["live_verified"])
        self.assertEqual(stat["promotion_live_confirmed"], 1)
        self.assertEqual(stat["promotion_live_rule_replaced"], 0)

    def test_mismatched_live_rule_without_observable_cap_stays_conservative(self):
        tracker = DummyTracker()
        promotion_live_guard.install(tracker)
        candidates = {}
        stat = {}
        tracker._discover_html(
            Response("Ganha 25€ por cada 250€ em compras."),
            {"url": "https://example.com/promo"}, 10, candidates, "promocao", stat,
        )
        self.assertNotIn("promotions", candidates["https://example.com/p1"])
        self.assertEqual(stat["promotion_live_confirmed"], 0)
        self.assertEqual(stat["promotion_live_rule_replaced"], 0)

    def test_changed_live_rule_replaces_stale_config_when_complete(self):
        tracker = DummyTracker()
        promotion_live_guard.install(tracker)
        candidates = {}
        stat = {}
        tracker._discover_html(
            Response("Ganha 75€ por cada 300€ em compras, até 600€."),
            {"url": "https://example.com/promo"}, 10, candidates, "promocao", stat,
        )
        promo = candidates["https://example.com/p1"]["promotions"][0]
        self.assertEqual(promo["step_discount_eur"], 75)
        self.assertEqual(promo["threshold_step_eur"], 300)
        self.assertEqual(promo["cap_eur"], 600)
        self.assertEqual(promo["source"], "campaign_page_live_replaced_config")
        self.assertTrue(promo["live_verified"])
        self.assertTrue(promo["live_rule_replaced_config"])
        self.assertEqual(stat["promotion_live_confirmed"], 1)
        self.assertEqual(stat["promotion_live_rule_replaced"], 1)

    def test_ajax_fragment_reuses_campaign_verified_on_first_page(self):
        tracker = DummyTracker()
        promotion_live_guard.install(tracker)
        candidates = {}
        stat = {}
        route = {"url": "https://example.com/promo"}
        tracker._discover_html(
            Response("Ganha 50€ por cada 250€ em compras."),
            route, 10, candidates, "promocao", stat,
        )
        tracker._discover_html(
            Response("<article><a href='/produto/outro'>Outro produto</a></article>"),
            route, 10, candidates, "promocao", stat,
        )
        promo = candidates["https://example.com/p2"]["promotions"][0]
        self.assertEqual(promo["cap_eur"], 500)
        self.assertTrue(promo["live_verified"])
        self.assertEqual(stat["promotion_live_confirmed"], 1)


if __name__ == "__main__":
    unittest.main()
