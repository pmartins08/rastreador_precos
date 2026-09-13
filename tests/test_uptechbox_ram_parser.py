from __future__ import annotations

import types
import unittest

import scraper
from hardware_guard import identify_system_ram, install


class UptechboxRamParserTests(unittest.TestCase):
    def test_mixed_gpu_vram_and_system_ram_prefers_ddr_memory(self):
        title = (
            "Portátil Gaming Asus TUF A16 FA608UM — Ryzen 7 260 + RTX 5060 8GB | "
            "32GB DDR5 | WUXGA 165Hz | Sem OS"
        )
        self.assertEqual(identify_system_ram(title, scraper), 32)

    def test_explicit_ram_before_gpu_is_preserved(self):
        title = "ASUS TUF A16 16GB RAM | RTX 5060 8GB GDDR7 | 1TB SSD"
        self.assertEqual(identify_system_ram(title, scraper), 16)

    def test_gpu_memory_alone_is_not_system_ram(self):
        title = "ASUS TUF A16 RTX 5060 8GB GDDR7 1TB SSD"
        self.assertIsNone(identify_system_ram(title, scraper))

    def test_installed_wrapper_fixes_real_uptechbox_title(self):
        class FakeScraper:
            @staticmethod
            def norm(value):
                return scraper.norm(value)

            @staticmethod
            def gp(value):
                return scraper.gp(value)

            @staticmethod
            def cpu(_text):
                return None, None, None

            @staticmethod
            def gpus(_text):
                return [], "desconhecida", None

            @staticmethod
            def nram(text):
                return scraper.nram(text)

            @staticmethod
            def pairs(_soup):
                return []

        fake = FakeScraper()
        tracker = types.SimpleNamespace(
            score_allow_unknown=lambda spec, price, weights, settings: {"status": "ACEITE"},
            select_with_cache=lambda items, cache, max_items, weights, settings: items,
            _HARDWARE_GUARD_INSTALLED=False,
        )
        install(fake, tracker)
        title = (
            "Portátil Gaming Asus TUF A16 FA608UM — Ryzen 7 260 + RTX 5060 8GB | "
            "32GB DDR5 | WUXGA 165Hz | Sem OS"
        )
        self.assertEqual(fake.nram(title), 32)


if __name__ == "__main__":
    unittest.main()
