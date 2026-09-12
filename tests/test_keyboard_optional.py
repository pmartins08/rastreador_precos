import unittest
import scraper

class KeyboardOptionalTests(unittest.TestCase):
    def test_layout_does_not_change_score_or_evidence(self):
        base = {"ram_gb": 16, "armazenamento_tb": 0.512}
        results = []
        for keyboard in ("confirmado", "nao_pt", "desconhecido"):
            spec = dict(base, teclado_pt=keyboard)
            result = scraper.score(spec, 900, {}, {})
            self.assertEqual(result["status"], "ACEITE")
            self.assertEqual(spec["teclado_pt"], keyboard)
            results.append(float(result["value_score"]))
        self.assertEqual(len(set(results)), 1)

    def test_other_hardware_rejections_still_apply(self):
        for keyboard in ("confirmado", "nao_pt", "desconhecido"):
            self.assertEqual(scraper.score({"ram_gb": 8, "teclado_pt": keyboard}, 900, {}, {})["status"], "REJEITADO")
