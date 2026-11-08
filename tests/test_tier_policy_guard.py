from __future__ import annotations

import unittest
from types import SimpleNamespace

from tier_policy_guard import install


class AdjustedValue(float):
    def __new__(cls, value: float, tier_score: float):
        obj = float.__new__(cls, value)
        obj.tier_score = tier_score
        return obj


class TierPolicyGuardTests(unittest.TestCase):
    def test_tier_policy_uses_raw_value_not_auxiliary_score(self):
        def tier_from_value(value, settings):
            score = getattr(value, "tier_score", float(value))
            if score > float(settings["diamante_value_min"]):
                return "DIAMANTE"
            return "OURO"

        scraper = SimpleNamespace(tier_from_value=tier_from_value)
        tracker = SimpleNamespace(scraper=scraper)

        # Simula o caso real: Value 123.3, mas GPU tier_score abaixo de 120.
        self.assertEqual(
            scraper.tier_from_value(AdjustedValue(123.3, 116.0), {"diamante_value_min": 120}),
            "OURO",
        )

        install(tracker)

        self.assertEqual(
            scraper.tier_from_value(AdjustedValue(123.3, 116.0), {"diamante_value_min": 120}),
            "DIAMANTE",
        )


if __name__ == "__main__":
    unittest.main()
