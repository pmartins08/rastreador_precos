from __future__ import annotations

import json
import types
import unittest

import rejection_guard


class RejectionGuardTests(unittest.TestCase):
    def _modules(self):
        scraper = types.SimpleNamespace()
        scraper.price_is_plausible_for_title = lambda title, price: float(price) >= 400

        tracker = types.SimpleNamespace()
        tracker._REJECTION_GUARD_INSTALLED = False
        tracker._empty_store_stats = lambda: {"rejeitados": 0, "aceites": 0}

        def score_allow_unknown(spec, price, weights, settings):
            return dict(spec.get("assessment") or {"status": "ACEITE"})

        tracker.score_allow_unknown = score_allow_unknown
        rejection_guard.install(scraper, tracker)
        return scraper, tracker

    def test_score_rejection_records_stable_reason(self):
        _scraper, tracker = self._modules()
        stats = tracker._empty_store_stats()
        assessment = tracker.score_allow_unknown(
            {
                "assessment": {
                    "status": "REJEITADO",
                    "alertas": ["8GB RAM confirmado - insuficiente."],
                }
            },
            799,
            {},
            {},
        )
        self.assertEqual(assessment["status"], "REJEITADO")
        stats["rejeitados"] += 1
        self.assertEqual(stats["rejeitados"], 1)
        self.assertEqual(stats["rejection_reasons"], {"ram_8gb": 1})

    def test_implausible_price_is_recorded(self):
        scraper, tracker = self._modules()
        stats = tracker._empty_store_stats()
        self.assertFalse(scraper.price_is_plausible_for_title("ASUS RTX 5070", 299))
        stats["rejeitados"] += 1
        self.assertEqual(stats["rejection_reasons"], {"price_implausible": 1})

    def test_direct_increment_without_context_means_price_out_of_range(self):
        _scraper, tracker = self._modules()
        stats = tracker._empty_store_stats()
        stats["rejeitados"] += 1
        self.assertEqual(stats["rejection_reasons"], {"price_out_of_range": 1})

    def test_accepted_score_clears_previous_context(self):
        scraper, tracker = self._modules()
        stats = tracker._empty_store_stats()
        self.assertFalse(scraper.price_is_plausible_for_title("ASUS", 299))
        tracker.score_allow_unknown({"assessment": {"status": "ACEITE"}}, 799, {}, {})
        stats["rejeitados"] += 1
        self.assertEqual(stats["rejection_reasons"], {"price_out_of_range": 1})

    def test_counter_and_reasons_are_json_serializable(self):
        _scraper, tracker = self._modules()
        stats = tracker._empty_store_stats()
        tracker.score_allow_unknown(
            {
                "assessment": {
                    "status": "REJEITADO",
                    "alertas": ["Teclado não é português."],
                }
            },
            999,
            {},
            {},
        )
        stats["rejeitados"] += 1
        encoded = json.dumps(stats, ensure_ascii=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["rejeitados"], 1)
        self.assertEqual(decoded["rejection_reasons"], {"keyboard_non_pt": 1})

    def test_fallback_price_rejection_has_own_bucket(self):
        _scraper, tracker = self._modules()
        stats = tracker._empty_store_stats()
        tracker.score_allow_unknown(
            {
                "assessment": {
                    "status": "REJEITADO",
                    "alertas": ["Preço de fallback histórico requer confirmação live nesta run."],
                }
            },
            1099,
            {},
            {},
        )
        stats["rejeitados"] += 1
        self.assertEqual(
            stats["rejection_reasons"], {"live_price_confirmation_required": 1}
        )


if __name__ == "__main__":
    unittest.main()
