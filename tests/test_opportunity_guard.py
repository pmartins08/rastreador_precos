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
            118.2,
            30.0,
            {"available": True, "at_or_near_low": True},
        )
        self.assertEqual(loq["value"], 109.8)
        self.assertEqual(ultrabook["value"], 118.2)
        self.assertGreater(loq["score"], ultrabook["score"])

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
