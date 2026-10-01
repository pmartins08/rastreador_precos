import subprocess
import sys
import unittest
from pathlib import Path

import scraper
from technical_context_guard import enrich, summary, technical_context


class TechnicalContextTests(unittest.TestCase):
    def test_new_brands_and_subbrands_are_eligible(self):
        for title in ("Acer Nitro V14", "Predator Helios", "Gigabyte AERO X16", "AORUS 16X"):
            self.assertTrue(scraper.eligible(title), title)
        for title in ("Apple MacBook", "Acer Nitro recondicionado", "Gigabyte AERO usado"):
            self.assertFalse(scraper.eligible(title), title)

    def test_graphics_power_label_and_panel_fields(self):
        rows = [("tgp", "Potência gráfica máxima", "Até 60 W", "table"),
                ("screen", "Ecrã", '14.5 IPS 400 nits 100% sRGB', "table")]
        spec = enrich({}, rows, scraper)
        self.assertEqual(spec["tgp_w"], 60)
        self.assertEqual(spec["tgp_evidence_status"], "explicit")
        self.assertEqual(spec["ecra_brightness_nits"], 400)
        self.assertEqual(spec["ecra_srgb_percent"], 100)

    def test_conflicting_asus_power_is_not_maximum_or_sum(self):
        spec = enrich({"tgp_w": 55}, [("gpu", "Graphics", "1737 MHz at 55W (up to 115W Dynamic Boost)", "table")], scraper)
        self.assertIsNone(spec["tgp_w"])
        self.assertEqual(spec["tgp_candidates_w"], [55, 115])
        self.assertEqual(spec["tgp_evidence_status"], "ambiguous")

    def test_adapter_and_battery_are_not_gpu_power(self):
        spec = enrich({}, [("battery", "Battery", "76 Wh", "table"),
                           ("power", "AC adapter", "135 W", "table")], scraper)
        self.assertNotIn("tgp_w", spec)

    def test_hdr_peak_is_not_sdr_brightness(self):
        spec = enrich({"ecra_brightness_nits": 1000}, [("screen", "Display", "OLED 500nits typical / 1000nits HDR peak", "table")], scraper)
        self.assertIsNone(spec["ecra_brightness_nits"])
        self.assertEqual(spec["ecra_brightness_nits_evidence_status"], "peak_or_combined")

    def test_conflicting_brightness_stays_unknown(self):
        spec = enrich({}, [("screen", "Display", "300 nits / 400 nits", "table")], scraper)
        self.assertIsNone(spec["ecra_brightness_nits"])

    def test_family_tgp_is_not_confirmed_sku_tgp(self):
        context = technical_context({"gpu_tipo": "dedicada", "tgp_w": 85, "tgp_evidence_status": "family_only"})
        self.assertIsNone(context["tgp_w"])
        self.assertIn("por confirmar", summary({"tgp_w": 85, "tgp_evidence_status": "family_only"}))

    def test_gamut_not_inferred_from_ntsc(self):
        spec = enrich({}, [("screen", "Display", "300 nits 45% NTSC", "table")], scraper)
        self.assertNotIn("ecra_srgb_percent", spec)

    def test_invalid_numbers_remain_unknown(self):
        context = technical_context({"tgp_w": float('nan'), "ecra_brightness_nits": float('inf'), "ecra_srgb_percent": 140})
        self.assertIsNone(context["tgp_w"])
        self.assertIsNone(context["brightness_nits"])
        self.assertIsNone(context["srgb_percent"])

    def test_real_runtime_preserves_value_and_exposes_caveats(self):
        code = '''
import json, runner
from bs4 import BeautifulSoup
config = json.load(open('config/config.json'))
s = runner.scraper.specs('ASUS Ryzen 7 260 RTX 5060')
s.update(ram_gb=32, armazenamento_tb=.5, ecra_res='fhd+', ecra_hz=144,
         bateria_wh=70, peso_kg=2.2, ram_expansivel=True, ssd_expansivel=True,
         fontes={'ram':'table'}, ecra_brightness_nits=300, ecra_srgb_percent=100)
a = runner.tracker.score_allow_unknown(s, 1424.99, config['weights'], config['settings'])
assert float(a['value_score']) == 106.9, a
assert a['technical_context']['value_basis'] == 'legacy_nominal_not_benchmark'
assert a['technical_context']['warnings']
assert s['technical_context'] == a['technical_context']
from gpu_guard import TierAwareValue
assert runner.scraper.tier_from_value(TierAwareValue(120, gaming_score=10), config['settings']) == 'DIAMANTE'
assert runner.scraper.eligible('Gigabyte AERO X16 RTX5060')
assert runner.scraper.eligible('Acer Nitro V14 RTX5060')
soup = BeautifulSoup('<table><tr><th>Potência gráfica máxima</th><td>Até 60 W</td></tr><tr><th>Ecrã</th><td>IPS 400 nits 100% sRGB</td></tr></table>', 'html.parser')
p = runner.scraper.extract('Acer Nitro V14 Ryzen AI 7 350 RTX 5060 32GB', soup)
assert p['tgp_w'] == 60, p
assert p['ecra_srgb_percent'] == 100, p
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
