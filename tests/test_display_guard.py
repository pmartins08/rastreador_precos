import re
import unittest

import display_guard


class DummyScraper:
    @staticmethod
    def norm(value):
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    @staticmethod
    def _resolution(text):
        value = DummyScraper.norm(text)
        if "2560 x 1600" in value or "qhd+" in value:
            return "qhd+"
        if "1920 x 1080" in value or "fhd" in value:
            return "fhd"
        return None


class DummyTracker:
    def __init__(self):
        self._DISPLAY_GUARD_INSTALLED = False

    @staticmethod
    def score_allow_unknown(spec, price, weights, settings):
        return {"value_score": 100.0, "spec": spec}

    @staticmethod
    def select_with_cache(items, spec_cache, max_items, weights, settings):
        return items[:max_items]


class DisplayGuardTests(unittest.TestCase):
    def _runtime(self):
        scraper = type("Scraper", (), {})()
        scraper.norm = DummyScraper.norm
        scraper._resolution = DummyScraper._resolution
        tracker = DummyTracker()
        display_guard.install(scraper, tracker)
        return scraper, tracker

    def test_wqxga_beats_secondary_fhd_marker(self):
        scraper, _tracker = self._runtime()

        result = scraper._resolution(
            "Painel WQXGA OLED 165Hz; webcam FHD com obturador de privacidade"
        )

        self.assertEqual(result, "qhd+")

    def test_plain_fhd_keeps_base_behavior(self):
        scraper, _tracker = self._runtime()

        self.assertEqual(scraper._resolution("Ecrã FHD 1920 x 1080"), "fhd")

    def test_cached_wrong_fhd_is_upgraded_from_explicit_title(self):
        _scraper, tracker = self._runtime()
        url = "https://example.test/83RL000UPG"
        cached = {
            "ecra_res": "fhd",
            "ecra_hz": 165,
            "fontes": {"ecra_res": "history_cache"},
        }
        items = [
            {
                "url": url,
                "titulo": "Lenovo IdeaPad Slim 5x 15Q8Y11 WQXGA OLED 165Hz",
            }
        ]

        tracker.select_with_cache(items, {url: cached}, 10, {}, {})

        self.assertEqual(cached["ecra_res"], "qhd+")
        self.assertEqual(cached["fontes"]["ecra_res"], "display_guard_title")
        self.assertEqual(cached["display_resolution_guard"]["previous"], "fhd")

    def test_explicit_wqxga_in_evidence_upgrades_before_scoring(self):
        _scraper, tracker = self._runtime()
        spec = {
            "ecra_res": "fhd",
            "evidencias": {"screen": "15.3 WQXGA OLED 165Hz"},
        }

        tracker.score_allow_unknown(spec, 999.0, {}, {})

        self.assertEqual(spec["ecra_res"], "qhd+")
        self.assertEqual(spec["display_resolution_guard"]["source"], "evidence")

    def test_unrelated_resolution_is_not_overwritten(self):
        _scraper, tracker = self._runtime()
        spec = {"ecra_res": "qhd"}
        items = [{"url": "u", "titulo": "Laptop QHD OLED"}]

        tracker.select_with_cache(items, {"u": spec}, 10, {}, {})

        self.assertEqual(spec["ecra_res"], "qhd")
        self.assertNotIn("display_resolution_guard", spec)


if __name__ == "__main__":
    unittest.main()
