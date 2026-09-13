from __future__ import annotations

import unittest

import manufacturer_source_guard
import scraper


class ManufacturerMergeEdgeCaseTests(unittest.TestCase):
    def test_empty_gpu_model_list_is_safe(self):
        retail = {
            "cpu_modelo": "ryzen 7 7840hs",
            "gpu_tipo": "integrada",
            "gpu_modelo": None,
            "gpu_modelos_detectados": [],
            "ram_gb": 16,
            "armazenamento_tb": 1.0,
        }
        official = dict(retail, gpu_modelo="radeon 780m", gpu_modelos_detectados=["radeon 780m"])
        merged = manufacturer_source_guard._merge_official(
            scraper, retail, official, "Lenovo PSREF", "https://psref.lenovo.com/example"
        )
        self.assertEqual(merged["gpu_modelos_detectados"], ["radeon 780m"])

    def test_official_true_can_confirm_expansion(self):
        retail = {
            "cpu_modelo": "ryzen 7 7840hs",
            "gpu_tipo": "integrada",
            "gpu_modelo": None,
            "ram_gb": 16,
            "armazenamento_tb": 1.0,
            "ram_expansivel": False,
            "ssd_expansivel": False,
        }
        official = dict(retail, ram_expansivel=True, ssd_expansivel=True)
        merged = manufacturer_source_guard._merge_official(
            scraper, retail, official, "Lenovo PSREF", "https://psref.lenovo.com/example"
        )
        self.assertTrue(merged["ram_expansivel"])
        self.assertTrue(merged["ssd_expansivel"])


if __name__ == "__main__":
    unittest.main()
