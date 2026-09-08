import unittest
from types import SimpleNamespace

import brain_guard


class BrainGuardV883Tests(unittest.TestCase):
    @staticmethod
    def dummy_module():
        def base_score(spec, price, weights, settings):
            return {
                "status": "ACEITE",
                "score_final": 70.0,
                "score_ranking": 70.0,
                "value_score": 100.0,
                "detalhes": {"Longevidade": 60.0},
            }

        def quality(spec):
            return 1.0, "ALTA"

        def value_score(ranking, price, settings):
            return round(ranking + 30.0, 1)

        return SimpleNamespace(
            score=base_score,
            quality=quality,
            value_score=value_score,
        )

    def test_24gb_no_longer_falls_to_low_longevity_bucket(self):
        module = self.dummy_module()
        brain_guard.install(module)
        result = module.score(
            {"ram_gb": 24, "ram_expansivel": False}, 1099.0, {}, {}
        )
        self.assertEqual(result["brain_corrections"][0]["old_ram_longevity"], 40.0)
        self.assertEqual(result["brain_corrections"][0]["new_ram_longevity"], 85.0)
        self.assertGreater(result["detalhes"]["Longevidade"], 60.0)
        self.assertGreater(result["score_ranking"], 70.0)

    def test_expandable_24gb_receives_same_longevity_class_as_expandable_16gb(self):
        self.assertEqual(brain_guard.ram_longevity_target(24, True), 95.0)
        self.assertEqual(brain_guard.ram_longevity_target(20, True), 95.0)

    def test_non_expandable_intermediate_ram_is_conservative(self):
        self.assertEqual(brain_guard.ram_longevity_target(24, False), 85.0)
        self.assertEqual(brain_guard.ram_longevity_target(28, False), 85.0)

    def test_existing_16gb_and_32gb_policy_is_untouched(self):
        self.assertIsNone(brain_guard.ram_longevity_target(16, False))
        self.assertIsNone(brain_guard.ram_longevity_target(16, True))
        self.assertIsNone(brain_guard.ram_longevity_target(32, False))
        self.assertIsNone(brain_guard.ram_longevity_target(64, True))

    def test_uninstall_restores_original_score(self):
        module = self.dummy_module()
        original = module.score
        brain_guard.install(module)
        self.assertIsNot(module.score, original)
        brain_guard.uninstall(module)
        self.assertIs(module.score, original)


if __name__ == "__main__":
    unittest.main()
