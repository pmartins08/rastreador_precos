import unittest

import gpu_guard


class DummyScraper:
    def __init__(self):
        self.tier_from_value = self._tier
        self.gpus = self._gpus
        self.value_score = self._value_score
        self._PRICE_GUARD_ORIGINALS = {"value_score": self._value_score}

    @staticmethod
    def norm(value):
        return " ".join(str(value or "").lower().split())

    @staticmethod
    def quality(_spec):
        return 1.0, "ALTA"

    @staticmethod
    def _value_score(ranking, _price, settings):
        return round(float(settings.get("test_value", 120.0)) + (float(ranking) - 74.0) * 0.5, 1)

    @staticmethod
    def _gpus(text):
        value = str(text or "").lower()
        if "rtx 5070" in value:
            return ["rtx 5070"], "dedicada", "rtx 5070"
        if "radeon" in value or "arc" in value or "integrated" in value:
            return [], "integrada", None
        return [], "desconhecida", None

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
        self.select_with_cache = self._select_with_cache

    @staticmethod
    def _select_with_cache(items, _spec_cache, max_items, _weights, _settings):
        return items[:max_items]

    @staticmethod
    def _score(spec, price, weights, settings):
        return {
            "status": "ACEITE",
            "value_score": float(settings.get("test_value", 120.0)),
            "value_score_sem_bonus": float(settings.get("test_value", 120.0)),
            "exceptional_deal_bonus": 0.0,
            "score_final": 75.0,
            "score_ranking": 74.0,
            "detalhes": {"Gaming": 50.0},
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

    def test_generic_integrated_gpu_remains_capped(self):
        scraper, tracker = self._modules()
        spec = {"gpu_tipo": "integrada", "gpu_modelo": None}
        assessment = tracker.score_allow_unknown(spec, 700, self.weights, self.settings)
        self.assertEqual(assessment["gpu_tier_guard"]["status"], "INTEGRADA_NAO_MAPEADA")
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], self.settings), "PRATA")

    def test_known_arc_140v_is_identified_and_confirmed(self):
        scraper, tracker = self._modules()
        models, kind, model = scraper.gpus("Intel® Arc™ de 140 V | Core Ultra 7")
        self.assertEqual(kind, "integrada")
        self.assertEqual(model, "intel arc graphics 140v")
        self.assertEqual(models, ["intel arc graphics 140v"])

        spec = {"gpu_tipo": kind, "gpu_modelo": model}
        assessment = tracker.score_allow_unknown(spec, 1299, self.weights, self.settings)
        self.assertTrue(assessment["gpu_tier_guard"]["confirmed"])
        self.assertEqual(assessment["gpu_tier_guard"]["performance_class"], 33.0)
        self.assertGreater(float(assessment["value_score"]), 120.0)
        self.assertEqual(scraper.tier_from_value(assessment["value_score"], self.settings), "OURO")

    def test_known_radeon_890m_is_identified(self):
        scraper, _tracker = self._modules()
        models, kind, model = scraper.gpus("AMD Radeon 890M Graphics")
        self.assertEqual((kind, model), ("integrada", "radeon 890m"))
        self.assertEqual(models, ["radeon 890m"])
        self.assertEqual(gpu_guard.igpu_score(model), 31.0)

    def test_cache_is_upgraded_from_current_title_without_refetch(self):
        _scraper, tracker = self._modules()
        items = [
            {
                "url": "https://example.test/hp-omnibook",
                "titulo": "HP OmniBook X Flip | Intel Arc 140V | 32GB",
            }
        ]
        spec_cache = {
            items[0]["url"]: {
                "gpu_tipo": "integrada",
                "gpu_modelo": None,
                "evidencias": {},
                "fontes": {},
            }
        }
        selected = tracker.select_with_cache(
            items, spec_cache, 1, self.weights, self.settings
        )
        self.assertEqual(len(selected), 1)
        cached = spec_cache[items[0]["url"]]
        self.assertEqual(cached["gpu_modelo"], "intel arc graphics 140v")
        self.assertEqual(cached["fontes"]["gpu_modelo"], "gpu_guard_v887")

    def test_existing_evidence_can_upgrade_cached_igpu(self):
        scraper, tracker = self._modules()
        spec = {
            "gpu_tipo": "integrada",
            "gpu_modelo": None,
            "evidencias": {"gpu": "Intel Arc Graphics 130V"},
            "fontes": {},
        }
        assessment = tracker.score_allow_unknown(spec, 1000, self.weights, self.settings)
        self.assertEqual(spec["gpu_modelo"], "intel arc graphics 130v")
        self.assertTrue(assessment["gpu_tier_guard"]["confirmed"])
        self.assertEqual(assessment["gpu_tier_guard"]["performance_class"], 28.0)

    def test_igpu_scale_stays_below_rtx_3050_class(self):
        self.assertLess(max(gpu_guard.IGPU_BASE.values()), 38.0)
        self.assertGreater(gpu_guard.IGPU_BASE["intel arc graphics 140v"], 30.0)
        self.assertLess(gpu_guard.IGPU_BASE["radeon 780m"], 30.0)

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
        scraper, _tracker = self._modules()
        self.assertEqual(scraper.tier_from_value(130.0, self.settings), "DIAMANTE")
        self.assertEqual(scraper.tier_from_value(115.0, self.settings), "OURO")


if __name__ == "__main__":
    unittest.main()
