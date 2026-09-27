import unittest

import opportunity_guard


class OpportunityGuardTests(unittest.TestCase):
    def test_loq_gaming_profile_can_outrank_ultrabook_without_changing_value(self):
        loq = opportunity_guard.calculate_opportunity(
            109.8,
            86.0,
            {"available": True, "at_or_near_low": True},
        )
        ultrabook = opportunity_guard.calculate_opportunity(
            108.8,
            39.8,
            {"available": True, "at_or_near_low": True},
        )
        self.assertEqual(loq["value"], 109.8)
        self.assertEqual(ultrabook["value"], 108.8)
        self.assertGreater(loq["score"], ultrabook["score"])

    def test_low_price_bonus_is_removed_from_value_truth(self):
        assessment = {
            "status": "ACEITE",
            "value_score": 118.2,
            "value_score_sem_bonus": 108.7,
            "exceptional_deal_bonus": 9.5,
            "detalhes": {"Gaming": 39.8},
        }
        result = opportunity_guard.normalize_value_truth(assessment)
        self.assertAlmostEqual(float(result["value_score"]), 108.7)
        self.assertEqual(result["value_score_sem_bonus"], 108.7)
        self.assertEqual(result["legacy_exceptional_deal_bonus"], 9.5)
        self.assertEqual(result["exceptional_deal_bonus"], 0.0)
        self.assertEqual(result["value_truth_schema"], 1)

    def test_exact_configuration_is_deduplicated(self):
        rows = [
            {
                "configuration_key": "ean:00000000000001",
                "url": "https://a.example/product",
                "store": "A",
                "price": 799.99,
                "value": 108.8,
                "score": 101.0,
            },
            {
                "configuration_key": "ean:00000000000001",
                "url": "https://b.example/product",
                "store": "B",
                "price": 799.99,
                "value": 108.6,
                "score": 100.8,
            },
        ]
        result = opportunity_guard.deduplicate_observations(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["store"], "A")

    def test_different_configurations_remain_separate(self):
        rows = [
            {
                "configuration_key": "ean:00000000000001",
                "url": "https://a.example/product",
                "price": 800,
                "value": 109,
                "score": 101,
            },
            {
                "configuration_key": "ean:00000000000002",
                "url": "https://b.example/product",
                "price": 800,
                "value": 109,
                "score": 101,
            },
        ]
        self.assertEqual(len(opportunity_guard.deduplicate_observations(rows)), 2)

    def test_new_historical_low_gets_small_bounded_bonus(self):
        normal = opportunity_guard.calculate_opportunity(110, 80, None)
        low = opportunity_guard.calculate_opportunity(
            110, 80, {"available": True, "new_low": True}
        )
        self.assertEqual(low["history_component"], 5.0)
        self.assertEqual(low["score"] - normal["score"], 5.0)

    def test_below_average_history_bonus_is_bounded(self):
        result = opportunity_guard.calculate_opportunity(
            110,
            80,
            {"available": True, "delta_vs_average_pct": -30.0},
        )
        self.assertEqual(result["history_component"], 4.0)

    def test_score_is_capped_at_150(self):
        result = opportunity_guard.calculate_opportunity(
            150,
            100,
            {"available": True, "new_low": True},
        )
        self.assertEqual(result["score"], 150.0)


if __name__ == "__main__":
    unittest.main()
