import unittest

import gpu_guard
import market_guard


class DummyScraper:
    def __init__(self):
        self.gpus = self._gpus
        self.tier_from_value = self._tier
        self.value_score = self._value_score
        self._PRICE_GUARD_ORIGINALS = {"value_score": self._value_score}

    @staticmethod
    def norm(value):
        return " ".join(str(value or "").lower().split())

    @staticmethod
    def quality(_spec):
        return 1.0, "ALTA"

    @staticmethod
    def _gpus(_text):
        return [], "integrada", None

    @staticmethod
    def _value_score(_ranking, _price, _settings):
        return 120.0

    @staticmethod
    def _tier(value, settings):
        if value >= settings.get("diamante_value_min", 125):
            return "DIAMANTE"
        if value >= settings.get("ouro_value_min", 110):
            return "OURO"
        if value >= settings.get("prata_value_min", 90):
            return "PRATA"
        return None


class DummyLogger:
    @staticmethod
    def warning(*_args, **_kwargs):
        return None


class DummyTracker:
    def __init__(self):
        self._GPU_GUARD_INSTALLED = False
        self._MARKET_GUARD_INSTALLED = False
        self.select_with_cache = self._select
        self.apply_exact_market_price_evidence = self._market_evidence
        self.score_allow_unknown = self._score
        self.LOGGER = DummyLogger()

    @staticmethod
    def _select(items, _spec_cache, _max_items, _weights, _settings):
        return items

    @staticmethod
    def _market_evidence(_records, _settings):
        return {"confirmed_groups": 0, "outliers": 0}

    @staticmethod
    def _score(_spec, _price, _weights, _settings):
        return {
            "status": "ACEITE",
            "score_final": 75.0,
            "score_ranking": 74.0,
            "value_score": 120.0,
            "value_score_sem_bonus": 120.0,
            "exceptional_deal_bonus": 0.0,
            "detalhes": {"Gaming": 50.0},
        }


TITLE = "HP OmniBook X Flip | Intel® Arc™ de 140 V | Core Ultra 7"


def unknown_spec():
    return {
        "gpu_tipo": "desconhecida",
        "gpu_modelo": None,
        "gpu_modelos_detectados": [],
        "evidencias": {},
        "fontes": {},
    }


class InlineSpecMigrationTests(unittest.TestCase):
    def test_embedded_arc_140v_specs_are_upgraded_from_current_title(self):
        scraper = DummyScraper()
        tracker = DummyTracker()
        gpu_guard.install(scraper, tracker)

        item = {
            "url": "https://example.test/hp-omnibook-arc",
            "titulo": TITLE,
            "specs": unknown_spec(),
        }

        selected = tracker.select_with_cache([item], {}, 1, {}, {})
        spec = selected[0]["specs"]

        self.assertEqual(spec["gpu_tipo"], "integrada")
        self.assertEqual(spec["gpu_modelo"], "intel arc graphics 140v")

    def test_authoritative_record_stage_upgrades_history_cache_before_scoring(self):
        scraper = DummyScraper()
        tracker = DummyTracker()
        gpu_guard.install(scraper, tracker)
        # Mesma ordem do runner real: Market Guard é instalado depois do GPU Guard.
        market_guard.install(scraper, tracker)

        spec = unknown_spec()
        record = {
            "item": {
                "url": "https://example.test/hp-omnibook-arc",
                "titulo": TITLE,
                "preco": 1299.99,
                "loja": "FNAC",
            },
            "spec": spec,
        }

        tracker.apply_exact_market_price_evidence([record], {})

        self.assertEqual(spec["gpu_tipo"], "integrada")
        self.assertEqual(spec["gpu_modelo"], "intel arc graphics 140v")

        settings = {
            "ouro_value_min": 110,
            "diamante_value_min": 125,
            "prata_value_min": 90,
        }
        assessment = tracker.score_allow_unknown(spec, 1299.99, {}, settings)

        self.assertTrue(assessment["gpu_tier_guard"]["confirmed"])
        self.assertEqual(assessment["gpu_tier_guard"]["status"], "INTEGRADA_MAPEADA")
        self.assertEqual(assessment["gpu_tier_guard"]["model"], "intel arc graphics 140v")
        self.assertEqual(
            scraper.tier_from_value(assessment["value_score"], settings),
            "OURO",
        )


if __name__ == "__main__":
    unittest.main()
