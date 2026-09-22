import unittest
from copy import deepcopy

from decision_truth import decision_truth, force_diamond_for_value, tier_meets_minimum


class _RuntimeScore(float):
    """Mimetiza um score runtime que não pode ser reconstruído por deepcopy."""

    def __new__(cls, value, *, metadata):
        obj = super().__new__(cls, value)
        obj.metadata = metadata
        return obj


class DecisionTruthTests(unittest.TestCase):
    def test_value_strictly_above_120_is_always_diamond(self):
        self.assertEqual(force_diamond_for_value(120.1, "OURO"), "DIAMANTE")
        self.assertEqual(force_diamond_for_value(135.0, "PRATA"), "DIAMANTE")

    def test_value_equal_to_120_preserves_existing_tier_logic(self):
        self.assertEqual(force_diamond_for_value(120.0, "OURO"), "OURO")

    def test_unconfirmed_promotion_never_replaces_base_decision(self):
        view = decision_truth(
            base_value_score=115.0,
            base_tier="OURO",
            promotion_value_score=124.0,
            promotion_tier="DIAMANTE",
            promotion_confirmed=False,
            promotion_discount_eur=250.0,
        )
        self.assertFalse(view["promotion_applied"])
        self.assertEqual(view["effective_value_score"], 115.0)
        self.assertEqual(view["effective_tier"], "OURO")

    def test_zero_discount_promotion_never_replaces_base_decision(self):
        view = decision_truth(
            base_value_score=115.0,
            base_tier="OURO",
            promotion_value_score=124.0,
            promotion_tier="DIAMANTE",
            promotion_confirmed=True,
            promotion_discount_eur=0.0,
        )
        self.assertFalse(view["promotion_applied"])
        self.assertEqual(view["effective_tier"], "OURO")

    def test_confirmed_promotion_becomes_effective_decision(self):
        view = decision_truth(
            base_value_score=112.0,
            base_tier="OURO",
            promotion_value_score=123.6,
            promotion_tier="OURO",
            promotion_confirmed=True,
            promotion_discount_eur=300.0,
        )
        self.assertTrue(view["promotion_applied"])
        self.assertEqual(view["base_tier"], "OURO")
        self.assertEqual(view["promotion_tier"], "DIAMANTE")
        self.assertEqual(view["effective_value_score"], 123.6)
        self.assertEqual(view["effective_tier"], "DIAMANTE")

    def test_base_value_above_120_is_diamond_even_without_promotion(self):
        view = decision_truth(base_value_score=121.0, base_tier="OURO")
        self.assertFalse(view["promotion_applied"])
        self.assertEqual(view["effective_tier"], "DIAMANTE")

    def test_specialized_runtime_score_becomes_plain_float_and_is_copy_safe(self):
        score = _RuntimeScore(118.2, metadata={"gaming": 5.0})
        view = decision_truth(base_value_score=score, base_tier="DIAMANTE")

        self.assertIs(type(view["base_value_score"]), float)
        self.assertIs(type(view["effective_value_score"]), float)
        self.assertEqual(view["effective_value_score"], 118.2)
        self.assertEqual(deepcopy(view)["effective_value_score"], 118.2)

    def test_effective_alert_floor_can_be_checked_from_same_tier(self):
        self.assertTrue(tier_meets_minimum("OURO", "OURO"))
        self.assertTrue(tier_meets_minimum("DIAMANTE", "OURO"))
        self.assertFalse(tier_meets_minimum("PRATA", "OURO"))


if __name__ == "__main__":
    unittest.main()
