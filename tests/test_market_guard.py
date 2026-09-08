import unittest

import market_guard
import runner
import scraper
import tracker


class MarketGuardV882Tests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "budget_soft": 1300.0,
            "budget_hard": 1500.0,
            "diamante_value_min": 125.0,
            "ouro_value_min": 110.0,
            "prata_value_min": 90.0,
            "bronze_value_min": 70.0,
            "market_disagreement_min_eur": 150.0,
            "market_disagreement_min_pct": 20.0,
            "price_confirmation_tolerance_eur": 5.0,
            "price_confirmation_tolerance_pct": 1.5,
        }
        self.weights = {
            "gpu_base": {"rtx 5060": 85},
            "cpu_base": {"tier_1": 100, "tier_2": 85, "tier_3": 70},
        }

    @staticmethod
    def record(store, price, ean="0199276824165"):
        spec = scraper.specs(
            "Lenovo IdeaPad 5 Ryzen 5 230 16GB 512GB Radeon Graphics FHD 60Hz"
        )
        spec["teclado_pt"] = "confirmado"
        return {
            "item": {
                "loja": store,
                "url": f"https://{store.lower().replace(' ', '')}.example/produto",
                "titulo": "Lenovo IdeaPad 5 2IN1 14AHP11-165",
                "preco": float(price),
                "ean": ean,
            },
            "spec": spec,
        }

    def test_two_exact_stores_with_extreme_gap_are_quarantined(self):
        records = [self.record("Radio Popular", 325.0), self.record("Globaldata", 999.0)]
        summary = market_guard.mark_unresolved_market_disagreements(records, self.settings)
        self.assertEqual(summary["groups"], 1)
        self.assertEqual(summary["offers"], 2)
        for record in records:
            self.assertTrue(record["spec"]["market_price_disagreement"])
            result = tracker.score_allow_unknown(
                record["spec"], record["item"]["preco"], self.weights, self.settings
            )
            self.assertEqual(result["status"], "QUARENTENA")
            self.assertEqual(result["price_status"], "MARKET_DISAGREEMENT")

    def test_high_page_confirmation_can_resolve_two_store_disagreement(self):
        records = [self.record("Darty", 1229.98), self.record("Outra", 1499.99)]
        summary = market_guard.mark_unresolved_market_disagreements(records, self.settings)
        self.assertEqual(summary["groups"], 1)
        cheap = records[0]
        cheap["spec"].update(
            {
                "price_confirmed": 1229.98,
                "price_page_confidence": "HIGH",
                "price_evidence_sources": ["jsonld", "visible"],
                "price_evidence_count": 2,
            }
        )
        result = tracker.score_allow_unknown(
            cheap["spec"], cheap["item"]["preco"], self.weights, self.settings
        )
        self.assertEqual(result["status"], "ACEITE")
        self.assertTrue(result.get("market_outlier_verified"))

    def test_normal_cross_store_difference_is_not_quarantined(self):
        records = [self.record("A", 1199.0), self.record("B", 1299.0)]
        summary = market_guard.mark_unresolved_market_disagreements(records, self.settings)
        self.assertEqual(summary["groups"], 0)
        self.assertFalse(any(r["spec"].get("market_price_disagreement") for r in records))

    def test_existing_exact_market_cluster_resolves_disagreement(self):
        records = [
            self.record("A", 999.0),
            self.record("B", 1004.0),
            self.record("C", 325.0),
        ]
        summary = tracker.apply_exact_market_price_evidence(records, self.settings)
        self.assertGreaterEqual(summary["confirmed_groups"], 1)
        self.assertGreaterEqual(summary["outliers"], 1)
        self.assertEqual(summary.get("disagreements", 0), 0)
        cheap = records[2]
        result = tracker.score_allow_unknown(
            cheap["spec"], cheap["item"]["preco"], self.weights, self.settings
        )
        self.assertEqual(result["status"], "QUARENTENA")
        self.assertEqual(result["price_status"], "PRICE_CONFLICT")

    def test_high_page_confirmation_beats_exact_market_cluster_outlier(self):
        records = [
            self.record("A", 1499.0),
            self.record("B", 1499.99),
            self.record("Darty", 1229.98),
        ]
        summary = tracker.apply_exact_market_price_evidence(records, self.settings)
        self.assertGreaterEqual(summary["confirmed_groups"], 1)
        self.assertGreaterEqual(summary["outliers"], 1)
        cheap = records[2]
        self.assertTrue(cheap["spec"].get("market_price_conflict"))
        cheap["spec"].update(
            {
                "price_confirmed": 1229.98,
                "price_page_confidence": "HIGH",
                "price_evidence_sources": ["jsonld", "meta", "visible"],
                "price_evidence_count": 3,
            }
        )
        result = tracker.score_allow_unknown(
            cheap["spec"], cheap["item"]["preco"], self.weights, self.settings
        )
        self.assertEqual(result["status"], "ACEITE")
        self.assertTrue(result.get("market_outlier_verified"))
        self.assertEqual(result.get("market_reference_price"), 1499.5)

    def test_different_eans_never_create_market_disagreement(self):
        records = [
            self.record("A", 325.0, "0199276824165"),
            self.record("B", 999.0, "0199276824999"),
        ]
        summary = market_guard.mark_unresolved_market_disagreements(records, self.settings)
        self.assertEqual(summary["groups"], 0)


if __name__ == "__main__":
    unittest.main()
