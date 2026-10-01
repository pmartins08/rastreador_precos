import json
from pathlib import Path
import unittest

import promotion_budget_guard
import price_guard


class CurrentBudgetTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.settings = json.loads((root / "config/config.json").read_text())["settings"]

    def test_current_config(self):
        self.assertEqual(self.settings["budget_soft"], 1400.0)
        self.assertEqual(self.settings["budget_hard"], 1600.0)

    def test_hard_budget_boundary(self):
        for price, expected in ((1599.99, True), (1600.0, True), (1600.01, False)):
            with self.subTest(price=price):
                view = promotion_budget_guard.budget_view({"preco": price}, self.settings)
                self.assertEqual(view["fits_hard_budget"], expected)
                self.assertEqual(view["checkout_price"], price)

    def test_soft_budget_bonus_uses_updated_anchor(self):
        self.assertEqual(price_guard.exceptional_deal_bonus(1400.0, "HIGH", self.settings), 0.0)
        self.assertEqual(price_guard.exceptional_deal_bonus(1200.0, "HIGH", self.settings), 4.0)
        self.assertEqual(price_guard.exceptional_deal_bonus(1200.0, "UNKNOWN", self.settings), 0.0)
