"""Regressões do preço acessível e da separação Value/Opportunity."""

import unittest

import runner  # noqa: F401 - instala os guards da beta.9 sem executar a run
import scraper
import tracker
from opportunity_guard import calculate_opportunity


class PriceContinuityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = tracker.load_json(tracker.CONFIG_PATH)
        cls.history = tracker.load_json(tracker.HISTORY_PATH)

    def test_discount_within_soft_budget_changes_value_once(self):
        settings = self.config["settings"]
        self.assertEqual(scraper.price_score(1299.99, settings), 150.0008)
        self.assertGreater(scraper.price_score(1079.07, settings), 150.0)
        self.assertGreater(scraper.value_score(80.5, 1079.07, settings),
                           scraper.value_score(80.5, 1299.99, settings))
        self.assertEqual(scraper.price_score(1049.99, settings), 170.0)
        self.assertEqual(scraper.price_score(700.0, settings), 170.0)

    def test_above_soft_budget_is_continuous_and_unchanged(self):
        settings = self.config["settings"]
        self.assertAlmostEqual(scraper.price_score(1300.0, settings), 150.0)
        self.assertAlmostEqual(scraper.price_score(1300.01, settings), 149.9975)
        self.assertAlmostEqual(scraper.price_score(1500.0, settings), 100.0)

    def test_exact_asus_at_worten_price_becomes_diamond_without_legacy_bonus(self):
        history = self.history["offers"]
        url = "https://www.radiopopular.pt/produto/pc-portatil-asus-fa608uh-r72a55cb2"
        spec = dict(history[url][-1]["specs"])
        assessment = tracker.score_allow_unknown(
            spec, 1079.07, self.config["weights"], self.config["settings"]
        )
        self.assertEqual(assessment["status"], "ACEITE")
        self.assertEqual(assessment["value_score"], 123.6)
        self.assertEqual(assessment["exceptional_deal_bonus"], 0.0)
        self.assertEqual(
            scraper.tier_from_value(assessment["value_score"], self.config["settings"]),
            "DIAMANTE",
        )
        opportunity = calculate_opportunity(
            assessment["value_score"], assessment["detalhes"]["Gaming"],
            {"available": True, "new_low": True},
        )
        self.assertEqual(opportunity["score"], 125.2)


if __name__ == "__main__":
    unittest.main()
