from __future__ import annotations

import unittest

import ranking_history_guard


class RankingHistoryGuardTests(unittest.TestCase):
    def test_global_and_store_positions_are_stable(self):
        rows = [
            {
                "url": "a",
                "store": "Darty",
                "effective_value_score": 120.0,
                "effective_price": 1200.0,
                "previous_ranking_position": 3,
            },
            {
                "url": "b",
                "store": "FNAC",
                "effective_value_score": 125.0,
                "effective_price": 1300.0,
                "previous_ranking_position": 1,
            },
            {
                "url": "c",
                "store": "Darty",
                "effective_value_score": 120.0,
                "effective_price": 1100.0,
                "previous_ranking_position": 2,
            },
        ]
        ranked = ranking_history_guard.rank_observations(rows)
        self.assertEqual([row["url"] for row in ranked], ["b", "c", "a"])
        self.assertEqual([row["ranking_position"] for row in ranked], [1, 2, 3])
        self.assertEqual(ranked[1]["store_ranking_position"], 1)
        self.assertEqual(ranked[2]["store_ranking_position"], 2)
        self.assertEqual(ranked[2]["ranking_position_delta"], 0)

    def test_positive_delta_means_rank_improved(self):
        ranked = ranking_history_guard.rank_observations(
            [
                {
                    "url": "x",
                    "store": "Globaldata",
                    "effective_value_score": 130.0,
                    "effective_price": 1299.0,
                    "previous_ranking_position": 4,
                }
            ]
        )
        self.assertEqual(ranked[0]["ranking_position"], 1)
        self.assertEqual(ranked[0]["ranking_position_delta"], 3)

    def test_effective_decision_truth_is_never_replaced_by_raw_tier(self):
        value, price, tier = ranking_history_guard._effective_fields(
            {
                "price": 999.0,
                "value_score": 112.0,
                "tier": "PRATA",
                "effective_price": 999.0,
                "effective_value_score": 108.5,
                "effective_tier": "BRONZE",
            }
        )
        self.assertEqual(value, 108.5)
        self.assertEqual(price, 999.0)
        self.assertEqual(tier, "BRONZE")


if __name__ == "__main__":
    unittest.main()
