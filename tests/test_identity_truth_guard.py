import unittest
from types import SimpleNamespace

from identity_utils import canonical_gtin, canonical_identity_key
import identity_truth_guard


UPC = "199271076309"
EAN = "0199271076309"
CANONICAL = "00199271076309"


class IdentityUtilsTests(unittest.TestCase):
    def test_upc_and_zero_prefixed_ean_share_gtin14(self):
        self.assertEqual(canonical_gtin(UPC), CANONICAL)
        self.assertEqual(canonical_gtin(EAN), CANONICAL)
        self.assertEqual(canonical_identity_key({"ean": UPC}), f"ean:{CANONICAL}")
        self.assertEqual(canonical_identity_key({"ean": EAN}), f"ean:{CANONICAL}")

    def test_invalid_gtin_is_never_rewritten(self):
        self.assertIsNone(canonical_gtin("1234567890123"))


class IdentityTruthGuardTests(unittest.TestCase):
    def _tracker(self):
        def signature(item, spec):
            if item.get("ean"):
                return f"ean:{item['ean']}"
            return "fallback"

        def match(left_item, left_spec, right_item, right_spec):
            return {
                "level": "EXATO" if left_item.get("ean") == right_item.get("ean") else "SEM_MATCH"
            }

        def market(records, settings):
            keys = {record["item"].get("ean") for record in records}
            return {"confirmed_groups": 1 if len(keys) == 1 else 0, "outliers": 0}

        return SimpleNamespace(
            configuration_signature=signature,
            match_configurations=match,
            apply_exact_market_price_evidence=market,
            _IDENTITY_TRUTH_GUARD_INSTALLED=False,
        )

    def test_runtime_matching_uses_canonical_gtin_without_mutating_items(self):
        tracker = self._tracker()
        identity_truth_guard.install(tracker)
        left = {"ean": UPC}
        right = {"ean": EAN}
        self.assertEqual(tracker.configuration_signature(left, {}), f"ean:{CANONICAL}")
        self.assertEqual(tracker.configuration_signature(right, {}), f"ean:{CANONICAL}")
        self.assertEqual(tracker.match_configurations(left, {}, right, {})["level"], "EXATO")
        summary = tracker.apply_exact_market_price_evidence(
            [{"item": left, "spec": {}}, {"item": right, "spec": {}}], {}
        )
        self.assertEqual(summary["confirmed_groups"], 1)
        self.assertEqual(left["ean"], UPC)
        self.assertEqual(right["ean"], EAN)


if __name__ == "__main__":
    unittest.main()
