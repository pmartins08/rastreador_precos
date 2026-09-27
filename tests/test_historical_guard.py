import unittest
from datetime import date

import historical_guard


class HistoricalGuardTests(unittest.TestCase):
    def test_exact_identity_is_shared_across_stores(self):
        left = {"ean": "4711636047258", "url": "https://a/item", "loja": "A"}
        right = {"ean": "4711636047258", "url": "https://b/item", "loja": "B"}
        self.assertEqual(historical_guard.identity_key(left), historical_guard.identity_key(right))
        self.assertEqual(historical_guard.identity_key(left)[1], "EXATO")

    def test_upc_and_zero_prefixed_ean_share_canonical_history_identity(self):
        upc = {"ean": "199271076309", "url": "https://pcdiga/item", "loja": "PCDiga"}
        ean = {"ean": "0199271076309", "url": "https://globaldata/item", "loja": "Globaldata"}
        self.assertEqual(
            historical_guard.identity_key(upc),
            ("ean:00199271076309", "EXATO"),
        )
        self.assertEqual(historical_guard.identity_key(upc), historical_guard.identity_key(ean))

    def test_compact_migrates_legacy_gtin_aliases_without_losing_observations(self):
        state = {
            "schema_version": 1,
            "updated_at": "2026-09-27T00:00:00Z",
            "identities": {
                "ean:199271076309": {
                    "confidence": "EXATO",
                    "ean": "199271076309",
                    "mpn": "83JE00C6PG",
                    "url": None,
                    "title": "LOQ PCDiga",
                    "first_seen": "2026-09-23T10:00:00Z",
                    "last_seen": "2026-09-23T10:00:00Z",
                    "days": {
                        "2026-09-23": {
                            "min": 1299.99,
                            "max": 1299.99,
                            "last": 1299.99,
                            "sum": 1299.99,
                            "samples": 1,
                            "stores": ["PCDiga"],
                        }
                    },
                },
                "ean:0199271076309": {
                    "confidence": "EXATO",
                    "ean": "0199271076309",
                    "mpn": "83JE00C6PG",
                    "url": None,
                    "title": "LOQ Globaldata",
                    "first_seen": "2026-09-23T09:00:00Z",
                    "last_seen": "2026-09-24T18:00:00Z",
                    "days": {
                        "2026-09-23": {
                            "min": 1299.0,
                            "max": 1299.0,
                            "last": 1299.0,
                            "sum": 1299.0,
                            "samples": 1,
                            "stores": ["Globaldata"],
                        },
                        "2026-09-24": {
                            "min": 1299.0,
                            "max": 1299.0,
                            "last": 1299.0,
                            "sum": 1299.0,
                            "samples": 1,
                            "stores": ["Globaldata"],
                        },
                    },
                },
            },
        }
        compacted = historical_guard.compact(state, today=date(2026, 9, 27))
        identities = compacted["identities"]
        self.assertEqual(list(identities), ["ean:00199271076309"])
        entry = identities["ean:00199271076309"]
        self.assertEqual(entry["gtin14"], "00199271076309")
        self.assertEqual(entry["first_seen"], "2026-09-23T09:00:00Z")
        self.assertEqual(entry["last_seen"], "2026-09-24T18:00:00Z")
        day = entry["days"]["2026-09-23"]
        self.assertEqual(day["min"], 1299.0)
        self.assertEqual(day["max"], 1299.99)
        self.assertEqual(day["samples"], 2)
        self.assertEqual(day["sum"], 2598.99)
        self.assertEqual(day["stores"], ["Globaldata", "PCDiga"])

    def test_compact_does_not_double_count_overlapping_alias_store(self):
        state = {
            "schema_version": 1,
            "identities": {
                "ean:199271076309": {
                    "confidence": "EXATO",
                    "ean": "199271076309",
                    "days": {
                        "2026-09-23": {
                            "min": 1299.99,
                            "max": 1299.99,
                            "last": 1299.99,
                            "sum": 1299.99,
                            "samples": 1,
                            "stores": ["PCDiga"],
                        }
                    },
                },
                "ean:0199271076309": {
                    "confidence": "EXATO",
                    "ean": "0199271076309",
                    "days": {
                        "2026-09-23": {
                            "min": 1299.99,
                            "max": 1299.99,
                            "last": 1299.99,
                            "sum": 1299.99,
                            "samples": 1,
                            "stores": ["PCDiga"],
                        }
                    },
                },
            },
        }
        compacted = historical_guard.compact(state, today=date(2026, 9, 27))
        day = compacted["identities"]["ean:00199271076309"]["days"]["2026-09-23"]
        self.assertEqual(day["samples"], 1)
        self.assertEqual(day["sum"], 1299.99)

    def test_observe_preserves_original_first_seen_when_rebuilding(self):
        state = {"schema_version": 1, "identities": {}}
        item = {"ean": "0199271076309", "loja": "Globaldata", "titulo": "LOQ"}
        historical_guard.observe(
            state, item, 1299.0, observed_at="2026-09-23T06:23:21Z"
        )
        historical_guard.observe(
            state, item, 1299.0, observed_at="2026-09-24T06:22:16Z"
        )
        key = historical_guard.identity_key(item)[0]
        entry = state["identities"][key]
        self.assertEqual(entry["first_seen"], "2026-09-23T06:23:21Z")
        self.assertEqual(entry["last_seen"], "2026-09-24T06:22:16Z")

    def test_url_fallback_is_local(self):
        first = {"url": "https://a/item"}
        second = {"url": "https://b/item"}
        self.assertNotEqual(historical_guard.identity_key(first)[0], historical_guard.identity_key(second)[0])
        self.assertEqual(historical_guard.identity_key(first)[1], "LOCAL")

    def test_context_detects_new_90_day_low(self):
        state = {"schema_version": 1, "identities": {}}
        item_a = {
            "ean": "4711636047258",
            "url": "https://a/item",
            "loja": "A",
            "titulo": "ASUS TUF",
        }
        item_b = dict(item_a, loja="B", url="https://b/item")
        historical_guard.observe(state, item_a, 1499.0, observed_at="2026-09-01T10:00:00Z")
        historical_guard.observe(state, item_b, 1399.0, observed_at="2026-09-05T10:00:00Z")

        context = historical_guard.historical_context(
            state, item_a, 1299.0, today=date(2026, 9, 8)
        )
        self.assertTrue(context["available"])
        self.assertEqual(context["confidence"], "EXATO")
        self.assertEqual(context["min"], 1399.0)
        self.assertEqual(context["days_observed"], 2)
        self.assertEqual(context["samples"], 2)
        self.assertEqual(context["stores"], ["A", "B"])
        self.assertTrue(context["new_low"])
        self.assertLess(context["delta_vs_average_pct"], 0)

    def test_same_day_is_compacted(self):
        state = {"schema_version": 1, "identities": {}}
        item = {"mpn": "90NR0NB1-M00560", "url": "https://a/item", "loja": "A"}
        historical_guard.observe(state, item, 1499.0, observed_at="2026-09-08T08:00:00Z")
        historical_guard.observe(state, item, 1399.0, observed_at="2026-09-08T14:00:00Z")
        key = historical_guard.identity_key(item)[0]
        day = state["identities"][key]["days"]["2026-09-08"]
        self.assertEqual(day["min"], 1399.0)
        self.assertEqual(day["max"], 1499.0)
        self.assertEqual(day["last"], 1399.0)
        self.assertEqual(day["samples"], 2)
        self.assertEqual(day["sum"], 2898.0)

    def test_compact_removes_days_outside_window(self):
        state = {"schema_version": 1, "identities": {}}
        item = {"ean": "4711636047258", "url": "https://a/item", "loja": "A"}
        historical_guard.observe(state, item, 1600.0, observed_at="2026-05-01T10:00:00Z")
        historical_guard.observe(state, item, 1400.0, observed_at="2026-09-01T10:00:00Z")
        compacted = historical_guard.compact(state, today=date(2026, 9, 8))
        key = historical_guard.identity_key(item)[0]
        self.assertNotIn("2026-05-01", compacted["identities"][key]["days"])
        self.assertIn("2026-09-01", compacted["identities"][key]["days"])

    def test_merge_is_idempotent_for_same_run_state(self):
        current = {"schema_version": 1, "identities": {}}
        run_state = {"schema_version": 1, "identities": {}}
        item = {"ean": "4711636047258", "url": "https://a/item", "loja": "A"}
        historical_guard.observe(run_state, item, 1299.0, observed_at="2026-09-08T10:00:00Z")
        once = historical_guard.merge_price_history(current, run_state)
        twice = historical_guard.merge_price_history(once, run_state)
        key = historical_guard.identity_key(item)[0]
        self.assertEqual(
            once["identities"][key]["days"]["2026-09-08"]["samples"],
            twice["identities"][key]["days"]["2026-09-08"]["samples"],
        )
        self.assertEqual(
            once["identities"][key]["days"]["2026-09-08"]["sum"],
            twice["identities"][key]["days"]["2026-09-08"]["sum"],
        )


if __name__ == "__main__":
    unittest.main()
