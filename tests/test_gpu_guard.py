import unittest

import gpu_guard


class DummyScraper:
    def __init__(self):
        self.tier_from_value = self._tier

    @staticmethod
    def _tier(value, settings):
        if value >= settings.get("diamante_value_min", 125):
            return "DIAMANTE"
        if value >= settings.get("ouro_value_min", 110):
            return "OURO"
        if value >= settings.get("prata_value_min", 90):
            return "PRATA"
        if value >= settings.get("bronze_value_min", 70):
            return "BRONZE"
        return None


class DummyTracker:
    def __init__(self):
        self._GPU_GUARD_INSTALLED = False
        self.score_allow_unknown = self._score

    @staticmethod
    def _score(spec, price, weights, settings):
        return {
            "status": "ACEITE",
            "value_score": float(settings.get("test_value", 120.0)),
            "score_final": 75.0,
            "score_ranking": 74.0,
        }


class GpuGuardTests(unittest.TestCase):
    def setUp(self):
        self.weights = {"gpu_base": {"rtx 5070": 95, "rtx 4060": 65}}
        self.settings = {
            "bronze_value_min": 70,
            "prata_value_min": 90,
            "ouro_value_min": 110,
            "diamante_value_min": 125,
            "test_value": 120,
        }

    def _modules(self):
        scraper = DummyScraper()
        tracker = DummyTracker()
        gpu_guard.install(scraper, tracker)
        return scraper, tracker

    def test_mapped_dedicated_gpu_can_be_gold(self):
        scraper, tracker = self._modules()
        spec = {"gpu_tipo": "dedicada", "gpu_modelo": "rtx 5070"}
        assessment = tracker.score_allow_unknown(spec, 1200, self.weights, self.settings)
        self.assertEqual(assessment["value_score"], 120.0)
        self.assertTrue(assessment["gpu_tier_guard"]["confirmed"])
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], self.settings), "OURO")

    def test_unknown_gpu_is_capped_at_silver_without_changing_value(self):
        scraper, tracker = self._modules()
        spec = {"gpu_tipo": "desconhecida", "gpu_modelo": None}
        assessment = tracker.score_allow_unknown(spec, 800, self.weights, self.settings)
        self.assertEqual(assessment["value_score"], 120.0)
        self.assertFalse(assessment["gpu_tier_guard"]["confirmed"])
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], self.settings), "PRATA")

    def test_unmapped_dedicated_gpu_is_capped_at_silver(self):
        scraper, tracker = self._modules()
        spec = {"gpu_tipo": "dedicada", "gpu_modelo": None}
        assessment = tracker.score_allow_unknown(spec, 900, self.weights, self.settings)
        self.assertEqual(assessment["gpu_tier_guard"]["status"], "DEDICADA_NAO_MAPEADA")
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], self.settings), "PRATA")

    def test_integrated_gpu_is_capped_until_explicitly_classified(self):
        scraper, tracker = self._modules()
        spec = {"gpu_tipo": "integrada", "gpu_modelo": None}
        assessment = tracker.score_allow_unknown(spec, 700, self.weights, self.settings)
        self.assertEqual(assessment["gpu_tier_guard"]["status"], "INTEGRADA_SEM_CLASSE_PREMIUM")
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], self.settings), "PRATA")

    def test_diamond_also_requires_mapped_gpu(self):
        scraper, tracker = self._modules()
        settings = dict(self.settings, test_value=135)
        unknown = {"gpu_tipo": "desconhecida", "gpu_modelo": None}
        assessment = tracker.score_allow_unknown(unknown, 600, self.weights, settings)
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], settings), "PRATA")

        mapped = {"gpu_tipo": "dedicada", "gpu_modelo": "rtx 5070"}
        assessment = tracker.score_allow_unknown(mapped, 600, self.weights, settings)
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], settings), "DIAMANTE")

    def test_plain_value_calls_keep_original_tier_logic(self):
        scraper, tracker = self._modules()
        self.assertEqual(scraper.tier_from_value(130.0, self.settings), "DIAMANTE")
        self.assertEqual(scraper.tier_from_value(115.0, self.settings), "OURO")


if __name__ == "__main__":
    unittest.main()
