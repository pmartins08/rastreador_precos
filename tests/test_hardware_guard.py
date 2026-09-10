from __future__ import annotations

import unittest

import hardware_guard
import scraper
from hardware_catalog import gpu_capability


class HardwareGuardTests(unittest.TestCase):
    def test_core_ultra_x9_series_3_is_recognized(self):
        result = hardware_guard.identify_cpu(
            "Intel® Core™ Ultra X9 Processor 388H", scraper
        )
        self.assertEqual(result, ("core ultra x9 388h", "tier_1", "h"))

    def test_core_ultra_200hx_plus_keeps_variant(self):
        result = hardware_guard.identify_cpu(
            "Intel Core Ultra 9 290HX Plus", scraper
        )
        self.assertEqual(result, ("core ultra 9 290hx plus", "tier_1", "hx"))

    def test_ryzen_ai_400_hx_is_recognized(self):
        result = hardware_guard.identify_cpu("AMD Ryzen AI 9 HX 475", scraper)
        self.assertEqual(result, ("ryzen ai 9 hx 475", "tier_1", "hx"))

    def test_ryzen_ai_max_is_identified_without_invented_cpu_tier(self):
        result = hardware_guard.identify_cpu("AMD Ryzen AI Max+ 395", scraper)
        self.assertEqual(result, ("ryzen ai max+ 395", None, None))

    def test_cpu_can_infer_published_integrated_gpu(self):
        spec = {
            "fontes": {},
            "evidencias": {},
            "gpu_tipo": "desconhecida",
            "gpu_modelo": None,
            "gpu_modelos_detectados": [],
            "cpu_modelo": None,
            "cpu_str_original": None,
            "cpu_classe": None,
        }
        hardware_guard.upgrade_spec(
            spec,
            scraper,
            "HP OmniBook com AMD Ryzen AI 9 HX 475",
        )
        self.assertEqual(spec["cpu_modelo"], "ryzen ai 9 hx 475")
        self.assertEqual(spec["gpu_tipo"], "integrada")
        self.assertEqual(spec["gpu_modelo"], "radeon 890m")
        self.assertEqual(spec["fontes"]["gpu_modelo"], "hardware_catalog_cpu_map")
        self.assertEqual(spec["gpu_capability"]["compute_units"], 16)

    def test_core_ultra_x9_infers_arc_b390_without_performance_score(self):
        spec = {
            "fontes": {},
            "evidencias": {},
            "gpu_tipo": "integrada",
            "gpu_modelo": None,
            "gpu_modelos_detectados": [],
            "cpu_modelo": "core ultra x9 388h",
            "cpu_str_original": "core ultra x9 388h",
            "cpu_classe": "h",
        }
        hardware_guard.upgrade_spec(spec, scraper)
        self.assertEqual(spec["gpu_modelo"], "intel arc b390")
        self.assertEqual(spec["gpu_capability"]["compute_units"], 12)
        self.assertIsNone(spec["gpu_capability"]["performance_score"])
        self.assertIsNone(spec["gpu_capability"]["vram_gb"])
        self.assertIsNone(spec["gpu_capability"]["memory_bus_bits"])

    def test_explicit_new_igpu_is_recognized(self):
        self.assertEqual(
            hardware_guard.identify_catalog_igpu(
                "AMD Radeon 8060S Graphics", scraper
            ),
            "radeon 8060s",
        )
        capability = gpu_capability("radeon 8060s")
        self.assertEqual(capability["family"], "rdna3.5")
        self.assertEqual(capability["compute_units"], 40)
        self.assertIsNone(capability["performance_score"])

    def test_dedicated_gpu_is_never_overwritten_by_cpu_mapping(self):
        spec = {
            "fontes": {},
            "evidencias": {},
            "gpu_tipo": "dedicada",
            "gpu_modelo": "rtx 5070",
            "gpu_modelos_detectados": ["rtx 5070"],
            "cpu_modelo": "ryzen ai 9 hx 475",
            "cpu_str_original": "ryzen ai 9 hx 475",
            "cpu_classe": "hx",
        }
        hardware_guard.upgrade_spec(spec, scraper)
        self.assertEqual(spec["gpu_tipo"], "dedicada")
        self.assertEqual(spec["gpu_modelo"], "rtx 5070")
        self.assertNotIn("gpu_capability", spec)

    def test_ryzen_200_mapping_is_identity_only(self):
        spec = {
            "fontes": {},
            "evidencias": {},
            "gpu_tipo": "desconhecida",
            "gpu_modelo": None,
            "gpu_modelos_detectados": [],
            "cpu_modelo": None,
            "cpu_str_original": None,
            "cpu_classe": None,
        }
        hardware_guard.upgrade_spec(spec, scraper, "Lenovo Ryzen 5 220")
        self.assertEqual(spec["cpu_modelo"], "ryzen 5 220")
        self.assertEqual(spec["gpu_modelo"], "radeon 740m")
        self.assertIsNone(spec["gpu_capability"]["performance_score"])


if __name__ == "__main__":
    unittest.main()
