import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matching_guard


class DummyTracker:
    def __init__(self):
        self.LOGGER = logging.getLogger("matching-guard-test")
        self._MATCHING_GUARD_INSTALLED = False
        self._clock = "2026-09-11T19:00:00Z"

    @staticmethod
    def _spec_equal(left, right):
        if isinstance(left, (int, float)) or isinstance(right, (int, float)):
            try:
                return abs(float(left) - float(right)) < 1e-9
            except (TypeError, ValueError):
                pass
        return str(left).strip().lower() == str(right).strip().lower()

    @staticmethod
    def configuration_signature(item, spec):
        return f"url:{item.get('url')}"

    def now_iso(self):
        return self._clock

    @staticmethod
    def match_configurations(left_item, left_spec, right_item, right_spec):
        if left_item.get("ean") and left_item.get("ean") == right_item.get("ean"):
            return {"level": "EXATO", "reason": "EAN/GTIN idêntico"}
        if left_item.get("mpn") and left_item.get("mpn") == right_item.get("mpn"):
            return {"level": "EXATO", "reason": "MPN/part number idêntico"}
        return {"level": "SEM_MATCH", "reason": "evidência insuficiente"}

    @staticmethod
    def apply_exact_market_price_evidence(records, settings):
        groups = {}
        for record in records:
            item = record["item"]
            key = None
            if item.get("ean"):
                key = f"ean:{item['ean']}"
            elif item.get("mpn"):
                key = f"mpn:{item['mpn']}"
            if key:
                groups.setdefault(key, []).append(record)

        confirmed = 0
        for key, members in groups.items():
            stores = {member["item"].get("loja") for member in members}
            if len(stores) < 2:
                continue
            confirmed += 1
            for member in members:
                member["spec"]["market_price_confirmed"] = 999.0
                member["spec"]["market_price_identifier"] = key
        return {"confirmed_groups": confirmed, "outliers": 0}

    def build_cross_store_matches(self, records):
        counts = {"EXATO": 0, "FORTE": 0, "PROVAVEL": 0, "NAO_FUNDIR": 0}
        for left in range(len(records)):
            for right in range(left + 1, len(records)):
                result = self.match_configurations(
                    records[left]["item"],
                    records[left]["spec"],
                    records[right]["item"],
                    records[right]["spec"],
                )
                if result["level"] in counts:
                    counts[result["level"]] += 1
        return {
            "exact_pairs": counts["EXATO"],
            "strong_pairs": counts["FORTE"],
            "probable_pairs": counts["PROVAVEL"],
            "conflicting_pairs": counts["NAO_FUNDIR"],
            "groups": [],
            "probable_review": [],
        }

    def main(self):
        return {"runner_version": "8.8.9"}


class MatchingGuardTests(unittest.TestCase):
    def _tracker(self):
        tracker = DummyTracker()
        matching_guard.install(tracker)
        return tracker

    @staticmethod
    def _conflicting_records():
        return [
            {
                "item": {
                    "ean": "1234567890123",
                    "loja": "A",
                    "url": "https://a/item",
                    "titulo": "Laptop A",
                    "preco": 1000,
                },
                "spec": {
                    "cpu_modelo": "ryzen 7",
                    "gpu_modelo": "rtx 5050",
                    "ram_gb": 32,
                    "armazenamento_tb": 1.0,
                },
            },
            {
                "item": {
                    "ean": "1234567890123",
                    "loja": "B",
                    "url": "https://b/item",
                    "titulo": "Laptop B",
                    "preco": 1050,
                },
                "spec": {
                    "cpu_modelo": "ryzen 7",
                    "gpu_modelo": "rtx 5070",
                    "ram_gb": 32,
                    "armazenamento_tb": 1.0,
                },
            },
        ]

    def test_same_ean_never_overrides_gpu_conflict(self):
        tracker = self._tracker()
        records = self._conflicting_records()

        result = tracker.match_configurations(
            records[0]["item"], records[0]["spec"], records[1]["item"], records[1]["spec"]
        )

        self.assertEqual(result["level"], "NAO_FUNDIR")
        self.assertEqual(result["identifier_type"], "ean")
        self.assertEqual(result["conflicting_fields"], ["gpu_modelo"])

    def test_same_mpn_never_overrides_ram_or_storage_conflict(self):
        tracker = self._tracker()
        left_item = {"mpn": "ABC-123", "loja": "A", "url": "https://a/item"}
        right_item = {"mpn": "ABC-123", "loja": "B", "url": "https://b/item"}
        left_spec = {
            "cpu_modelo": "core ultra 7",
            "gpu_modelo": "arc 140v",
            "ram_gb": 16,
            "armazenamento_tb": 0.5,
        }
        right_spec = {
            "cpu_modelo": "core ultra 7",
            "gpu_modelo": "arc 140v",
            "ram_gb": 32,
            "armazenamento_tb": 1.0,
        }

        result = tracker.match_configurations(left_item, left_spec, right_item, right_spec)

        self.assertEqual(result["level"], "NAO_FUNDIR")
        self.assertEqual(result["identifier_type"], "mpn")
        self.assertEqual(result["conflicting_fields"], ["ram_gb", "armazenamento_tb"])

    def test_missing_spec_does_not_create_false_conflict(self):
        tracker = self._tracker()
        left_item = {"ean": "1234567890123"}
        right_item = {"ean": "1234567890123"}
        left_spec = {"gpu_modelo": "rtx 5050", "ram_gb": 32}
        right_spec = {"gpu_modelo": None, "ram_gb": 32}

        result = tracker.match_configurations(left_item, left_spec, right_item, right_spec)

        self.assertEqual(result["level"], "EXATO")

    def test_reversed_numeric_resolution_is_same_panel(self):
        tracker = self._tracker()
        left_item = {"ean": "0199275936708"}
        right_item = {"ean": "0199275936708"}
        left_spec = {"ecra_res": "2560x1600", "ram_gb": 32, "armazenamento_tb": 1.0}
        right_spec = {"ecra_res": "1600 x 2560 pixels", "ram_gb": 32, "armazenamento_tb": 1.0}

        result = tracker.match_configurations(left_item, left_spec, right_item, right_spec)

        self.assertEqual(result["level"], "EXATO")

    def test_genuinely_different_numeric_resolution_still_conflicts(self):
        tracker = self._tracker()
        left_item = {"ean": "1234567890123"}
        right_item = {"ean": "1234567890123"}
        left_spec = {"ecra_res": "1920x1080"}
        right_spec = {"ecra_res": "2560x1600"}

        result = tracker.match_configurations(left_item, left_spec, right_item, right_spec)

        self.assertEqual(result["level"], "NAO_FUNDIR")
        self.assertEqual(result["conflicting_fields"], ["ecra_res"])

    def test_resolution_orientation_does_not_block_market_evidence(self):
        tracker = self._tracker()
        records = [
            {
                "item": {"ean": "0199275936715", "loja": "A"},
                "spec": {"ecra_res": "2560 × 1600", "ram_gb": 16, "armazenamento_tb": 1.0},
            },
            {
                "item": {"ean": "0199275936715", "loja": "B"},
                "spec": {"ecra_res": "1600 x 2560 pixels", "ram_gb": 16, "armazenamento_tb": 1.0},
            },
        ]

        summary = tracker.apply_exact_market_price_evidence(records, {})

        self.assertEqual(summary["confirmed_groups"], 1)
        self.assertNotIn("identity_conflicts", summary)

    def test_market_evidence_is_blocked_for_ambiguous_ean(self):
        tracker = self._tracker()
        records = self._conflicting_records()

        summary = tracker.apply_exact_market_price_evidence(records, {})

        self.assertEqual(summary["confirmed_groups"], 0)
        self.assertEqual(summary["identity_conflicts"], 1)
        self.assertEqual(summary["identity_conflict_offers"], 2)
        for record in records:
            self.assertNotIn("market_price_confirmed", record["spec"])
            self.assertTrue(record["spec"]["market_identity_conflict"])
            self.assertEqual(
                record["spec"]["market_identity_conflict_fields"], ["gpu_modelo"]
            )
            self.assertEqual(record["item"]["ean"], "1234567890123")

    def test_market_evidence_remains_available_when_specs_are_compatible(self):
        tracker = self._tracker()
        records = self._conflicting_records()
        records[1]["spec"]["gpu_modelo"] = "rtx 5050"

        summary = tracker.apply_exact_market_price_evidence(records, {})

        self.assertEqual(summary["confirmed_groups"], 1)
        self.assertNotIn("identity_conflicts", summary)
        for record in records:
            self.assertEqual(record["spec"]["market_price_confirmed"], 999.0)
            self.assertNotIn("market_identity_conflict", record["spec"])

    def test_build_cross_store_matching_counts_identifier_conflict(self):
        tracker = self._tracker()
        records = self._conflicting_records()

        result = tracker.build_cross_store_matches(records)

        self.assertEqual(result["exact_pairs"], 0)
        self.assertEqual(result["conflicting_pairs"], 1)

    def test_matching_state_is_derived_and_json_serializable(self):
        tracker = DummyTracker()
        records = [
            {
                "item": {
                    "ean": "1234567890123",
                    "loja": "A",
                    "url": "https://a/item",
                    "titulo": "Laptop A",
                    "preco": 999.9,
                },
                "spec": {
                    "cpu_modelo": "ryzen 7 260",
                    "gpu_modelo": "rtx 5050",
                    "ram_gb": 32,
                    "armazenamento_tb": 1.0,
                    "ecra_res": "2560x1600",
                    "ecra_hz": 165,
                },
            }
        ]
        matching = {
            "exact_pairs": 0,
            "strong_pairs": 0,
            "probable_pairs": 0,
            "conflicting_pairs": 0,
            "groups": [],
            "probable_review": [],
        }
        state = matching_guard.build_matching_state(tracker, records, matching, [])

        self.assertEqual(state["source"], "current_run_records")
        self.assertEqual(state["records_considered"], 1)
        self.assertEqual(state["identity_count"], 1)
        self.assertEqual(state["identities"][0]["identity"], "ean:1234567890123")
        offer = state["identities"][0]["offers"][0]
        self.assertEqual(offer["resolution"], "2560x1600")
        self.assertEqual(offer["refresh_hz"], 165)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matching_state.json"
            matching_guard._save(path, state)
            self.assertIn('"schema_version": 1', path.read_text(encoding="utf-8"))

    def test_main_writes_only_derived_matching_state(self):
        records = self._conflicting_records()

        tracker = DummyTracker()

        def run_with_matching():
            tracker.build_cross_store_matches(records)
            return {"runner_version": "8.8.9"}

        tracker.main = run_with_matching
        matching_guard.install(tracker)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matching_state.json"
            with patch.object(matching_guard, "MATCHING_STATE_PATH", path):
                run = tracker.main()
            self.assertTrue(path.exists())
            self.assertEqual(run["matching_state_conflicts"], 1)


if __name__ == "__main__":
    unittest.main()
