import unittest

import spec_truth_guard


UPC = "199271076309"
EAN = "0199271076309"


class SpecTruthGuardTests(unittest.TestCase):
    def _history(self, *, gpu="rtx 5060"):
        return {
            "offers": {
                "https://globaldata.test/loq": [
                    {
                        "loja": "Globaldata",
                        "ean": EAN,
                        "specs": {
                            "cpu_modelo": "i7-13650hx",
                            "cpu_classe": "hx",
                            "gpu_tipo": "dedicada",
                            "gpu_modelo": gpu,
                            "ram_gb": 32,
                            "ram_type": "DDR5",
                            "armazenamento_tb": 1.0,
                            "ecra_res": "1920x1080",
                            "ecra_hz": 144,
                            "bateria_wh": 60,
                            "peso_kg": 2.4,
                            "ram_expansivel": False,
                            "ssd_expansivel": False,
                        },
                    }
                ]
            }
        }

    def _current(self):
        return [
            {
                "item": {
                    "loja": "UPTECHBOX",
                    "ean": UPC,
                    "url": "https://uptechbox.test/loq",
                },
                "spec": {
                    "cpu_modelo": "i7-13650hx",
                    "cpu_classe": "hx",
                    "gpu_tipo": "dedicada",
                    "gpu_modelo": "rtx 5060",
                    "ram_gb": 32,
                    "ram_type": "DDR5",
                    "armazenamento_tb": 1.0,
                    "ecra_hz": 144,
                    "ecra_res": None,
                    "bateria_wh": None,
                    "peso_kg": None,
                    "fontes": {},
                },
            }
        ]

    def test_same_gtin_fills_only_missing_fields_from_history(self):
        records = self._current()
        summary = spec_truth_guard.enrich_exact_specs(records, self._history())
        spec = records[0]["spec"]
        self.assertEqual(summary["groups_used"], 1)
        self.assertGreaterEqual(summary["fields_filled"], 3)
        self.assertEqual(spec["ecra_res"], "1920x1080")
        self.assertEqual(spec["bateria_wh"], 60)
        self.assertEqual(spec["peso_kg"], 2.4)
        self.assertEqual(
            spec["cross_store_spec_truth"]["peso_kg"]["confidence"],
            "EXACT_IDENTITY",
        )
        self.assertEqual(spec["fontes"]["weight"], "cross_store_exact")

    def test_existing_current_values_are_never_overwritten(self):
        records = self._current()
        records[0]["spec"]["peso_kg"] = 2.35
        spec_truth_guard.enrich_exact_specs(records, self._history())
        self.assertEqual(records[0]["spec"]["peso_kg"], 2.35)

    def test_critical_conflict_quarantines_whole_identity_group(self):
        records = self._current()
        summary = spec_truth_guard.enrich_exact_specs(records, self._history(gpu="rtx 5050"))
        spec = records[0]["spec"]
        self.assertEqual(summary["groups_used"], 0)
        self.assertEqual(summary["groups_skipped_conflict"], 1)
        self.assertIsNone(spec["peso_kg"])
        self.assertIsNone(spec["bateria_wh"])
        self.assertNotIn("cross_store_spec_truth", spec)

    def test_no_strong_identity_means_no_cross_store_fill(self):
        records = self._current()
        records[0]["item"]["ean"] = None
        summary = spec_truth_guard.enrich_exact_specs(records, self._history())
        self.assertEqual(summary["fields_filled"], 0)
        self.assertIsNone(records[0]["spec"]["peso_kg"])


if __name__ == "__main__":
    unittest.main()
