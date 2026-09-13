from __future__ import annotations

import unittest

import history_integrity_guard


class HistoryIntegrityGuardTests(unittest.TestCase):
    def test_large_page_price_conflict_is_removed(self):
        record = {
            "timestamp": "2026-09-13T16:22:04Z",
            "loja": "Radio Popular",
            "titulo": "Asus VivoBook 15",
            "price": 295.0,
            "ean": "4711636091879",
            "specs": {"conflitos": ["Sinais de preço divergentes na ficha: 749.99€, 799.99€"]},
        }
        reason = history_integrity_guard.corruption_reason("https://example.com/vivobook", record)
        self.assertTrue(reason.startswith("price_conflict:"))

    def test_normal_old_price_difference_is_preserved(self):
        record = {
            "price": 1599.99,
            "specs": {"conflitos": ["Sinais de preço divergentes na ficha: 1699.99€"]},
        }
        self.assertIsNone(history_integrity_guard.corruption_reason("https://example.com/tuf", record))

    def test_legitimate_299_campaign_laptop_is_not_removed_without_conflict(self):
        record = {"price": 299.99, "specs": {"conflitos": []}}
        self.assertIsNone(history_integrity_guard.corruption_reason("https://example.com/hp", record))

    def test_known_wrong_rp_technical_offer_is_removed(self):
        url = "https://www.radiopopular.pt/produto/pc-portatil-lenovo-ideapad-s3-15iwc11-169"
        record = {
            "ean": "0199276826169",
            "price": 999.99,
            "specs": {"cpu_modelo": "ryzen ai 7 350", "gpu_modelo": "radeon 860m"},
        }
        reason = history_integrity_guard.corruption_reason(url, record)
        self.assertTrue(reason.startswith("known_technical_conflict:"))

    def test_repair_keeps_clean_records_and_removes_only_corrupt_ones(self):
        bad_url = "https://www.radiopopular.pt/produto/bad"
        good_url = "https://example.com/good"
        history = {
            "offers": {
                bad_url: [{
                    "timestamp": "2026-09-13T12:00:00Z",
                    "loja": "Radio Popular",
                    "titulo": "HP x360",
                    "price": 295.0,
                    "ean": "0198415352668",
                    "specs": {"conflitos": ["Sinais de preço divergentes na ficha: 899.99€"]},
                }],
                good_url: [{
                    "timestamp": "2026-09-13T12:00:00Z",
                    "loja": "Globaldata",
                    "titulo": "ASUS TUF",
                    "price": 1199.0,
                    "ean": "4711636154796",
                    "specs": {},
                }],
            }
        }
        repaired, removed = history_integrity_guard.repair_history_data(history)
        self.assertNotIn(bad_url, repaired["offers"])
        self.assertIn(good_url, repaired["offers"])
        self.assertEqual(len(removed), 1)

    def test_rebuilt_price_history_cannot_keep_removed_false_minimum(self):
        history = {
            "offers": {
                "https://example.com/good": [
                    {
                        "timestamp": "2026-09-12T12:00:00Z",
                        "loja": "Radio Popular",
                        "titulo": "ASUS VivoBook",
                        "price": 699.99,
                        "ean": "4711636091879",
                    },
                    {
                        "timestamp": "2026-09-13T12:00:00Z",
                        "loja": "Radio Popular",
                        "titulo": "ASUS VivoBook",
                        "price": 699.99,
                        "ean": "4711636091879",
                    },
                ]
            }
        }
        state = history_integrity_guard.rebuild_price_history(history)
        entry = state["identities"]["ean:4711636091879"]
        minima = [row["min"] for row in entry["days"].values()]
        self.assertEqual(min(minima), 699.99)


if __name__ == "__main__":
    unittest.main()
