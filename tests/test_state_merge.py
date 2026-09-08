import unittest

from state_merge import merge_access_learning, merge_history


class StateMergeTests(unittest.TestCase):
    def test_history_merge_preserves_both_runs_and_entries(self):
        current = {
            "schema_version": 8,
            "offers": {
                "A": [
                    {"timestamp": "2026-09-08T01:00:00Z", "url": "https://x/a", "price": 1000, "value_score": 100, "tier": "PRATA"}
                ]
            },
            "alert_state": {
                "A": {"timestamp": "2026-09-08T01:00:00Z", "price": 1000, "tier": "PRATA"}
            },
            "learning": {"runs": [{"timestamp": "2026-09-08T01:00:00Z", "access_requests": 50}], "stores": {}},
        }
        run = {
            "schema_version": 8,
            "offers": {
                "A": [
                    {"timestamp": "2026-09-08T01:00:00Z", "url": "https://x/a", "price": 1000, "value_score": 100, "tier": "PRATA"},
                    {"timestamp": "2026-09-08T02:00:00Z", "url": "https://x/a", "price": 950, "value_score": 110, "tier": "OURO"},
                ],
                "B": [
                    {"timestamp": "2026-09-08T02:00:01Z", "url": "https://x/b", "price": 900, "value_score": 95, "tier": "PRATA"}
                ],
            },
            "alert_state": {
                "A": {"timestamp": "2026-09-08T02:00:00Z", "price": 950, "tier": "OURO"}
            },
            "learning": {"runs": [{"timestamp": "2026-09-08T02:00:00Z", "runner_version": "8.4", "access_requests": 40}], "stores": {}},
        }
        merged = merge_history(current, run)
        self.assertEqual(len(merged["offers"]["A"]), 2)
        self.assertIn("B", merged["offers"])
        self.assertEqual(merged["alert_state"]["A"]["price"], 950)
        self.assertEqual(len(merged["learning"]["runs"]), 2)

    def test_access_learning_never_rolls_back_counters(self):
        current = {
            "schema_version": 2,
            "updated_at": "2026-09-08T02:00:00Z",
            "stores": {
                "PCDiga": {
                    "attempts": 20,
                    "successes": 15,
                    "blocks": 3,
                    "methods": {"product": 10},
                }
            },
        }
        run = {
            "schema_version": 2,
            "updated_at": "2026-09-08T01:59:00Z",
            "stores": {
                "PCDiga": {
                    "attempts": 19,
                    "successes": 16,
                    "blocks": 4,
                    "methods": {"product": 12, "category": 1},
                },
                "FNAC": {"attempts": 2, "successes": 2, "blocks": 0},
            },
        }
        merged = merge_access_learning(current, run)
        pcdiga = merged["stores"]["PCDiga"]
        self.assertEqual(pcdiga["attempts"], 20)
        self.assertEqual(pcdiga["successes"], 16)
        self.assertEqual(pcdiga["blocks"], 4)
        self.assertEqual(pcdiga["methods"]["product"], 12)
        self.assertEqual(pcdiga["methods"]["category"], 1)
        self.assertIn("FNAC", merged["stores"])
        self.assertEqual(merged["updated_at"], "2026-09-08T02:00:00Z")


if __name__ == "__main__":
    unittest.main()
