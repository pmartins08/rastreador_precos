from __future__ import annotations

import unittest

from scripts.history_audit import audit


class HistoryAuditTests(unittest.TestCase):
    def test_top_value_is_deduplicated_by_identity(self):
        history = {
            "offers": {
                "u1": [
                    {
                        "timestamp": "2026-09-01T00:00:00Z",
                        "loja": "A",
                        "titulo": "Laptop A",
                        "price": 1300,
                        "value_score": 118,
                        "tier": "OURO",
                        "ean": "111",
                        "url": "u1",
                        "specs": {},
                    },
                    {
                        "timestamp": "2026-09-02T00:00:00Z",
                        "loja": "A",
                        "titulo": "Laptop A",
                        "price": 1200,
                        "value_score": 123,
                        "tier": "OURO",
                        "ean": "111",
                        "url": "u1",
                        "specs": {},
                    },
                ],
                "u2": [
                    {
                        "loja": "B",
                        "titulo": "Laptop B",
                        "price": 999,
                        "value_score": 121,
                        "tier": "OURO",
                        "ean": "222",
                        "url": "u2",
                        "specs": {},
                    }
                ],
            }
        }
        report = audit(history)
        self.assertEqual(report["history_observations"], 3)
        self.assertEqual(report["unique_identities"], 2)
        self.assertEqual(report["top10_unique_by_value"][0]["value"], 123)
        self.assertEqual(report["value_distribution_unique_best"]["threshold_counts"]["120"], 2)
        self.assertEqual(report["value_distribution_unique_best"]["threshold_counts"]["125"], 0)

    def test_detects_known_rtx5060_vram_leak_from_system_ram(self):
        history = {
            "offers": {
                "u": [
                    {
                        "loja": "UPTECHBOX",
                        "titulo": "ASUS TUF RTX 5060 8GB | 32GB DDR5",
                        "price": 1299.99,
                        "value_score": 120,
                        "url": "u",
                        "specs": {
                            "gpu_tipo": "dedicada",
                            "gpu_modelo": "rtx 5060",
                            "ram_gb": 32,
                            "vram_gb": 32,
                        },
                    }
                ]
            }
        }
        report = audit(history)
        self.assertGreaterEqual(report["suspect_counts"].get("known_gpu_vram_mismatch", 0), 1)
        self.assertGreaterEqual(report["suspect_counts"].get("ram_vram_equal_suspicious", 0), 1)
        self.assertNotIn("ram_title_mismatch", report["suspect_counts"])

    def test_detects_title_ram_mismatch(self):
        history = {
            "offers": {
                "u": [
                    {
                        "loja": "UPTECHBOX",
                        "titulo": "RTX 5060 8GB GDDR7 | 32GB DDR5",
                        "price": 1299,
                        "value_score": 110,
                        "url": "u",
                        "specs": {
                            "gpu_tipo": "dedicada",
                            "gpu_modelo": "rtx 5060",
                            "ram_gb": 8,
                            "vram_gb": 8,
                        },
                    }
                ]
            }
        }
        report = audit(history)
        self.assertEqual(report["suspect_counts"].get("ram_title_mismatch"), 1)


if __name__ == "__main__":
    unittest.main()
