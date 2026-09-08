import unittest

from bs4 import BeautifulSoup

import price_guard
import runner
import scraper


class PriceGuardV88Tests(unittest.TestCase):
    def setUp(self):
        price_guard.install(scraper)
        self.settings = {
            "budget_soft": 1300.0,
            "budget_hard": 1500.0,
            "diamante_value_min": 125.0,
            "ouro_value_min": 110.0,
            "prata_value_min": 90.0,
            "bronze_value_min": 70.0,
            "exceptional_deal_bonus_max": 15.0,
            "price_confirmation_tolerance_eur": 5.0,
            "price_confirmation_tolerance_pct": 1.5,
        }
        self.weights = {
            "gpu_base": {
                "rtx 5090": 100,
                "rtx 5080": 98,
                "rtx 5070": 95,
                "rtx 5060": 85,
            },
            "cpu_base": {"tier_1": 100, "tier_2": 85, "tier_3": 70},
        }

    def tearDown(self):
        price_guard.uninstall(scraper)

    @staticmethod
    def soup_for_price(price: str, *, jsonld=True, meta=True, visible=True):
        parts = ["<html><head>"]
        if jsonld:
            parts.append(
                '<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"ASUS ROG RTX 5090","offers":{"@type":"Offer","price":"'
                + price
                + '"}}'
                "</script>"
            )
        if meta:
            parts.append(f'<meta itemprop="price" content="{price}">')
        parts.append("</head><body>")
        if visible:
            parts.append(f'<span class="current-price">{price} €</span>')
        parts.append("</body></html>")
        return BeautifulSoup("".join(parts), "html.parser")

    def high_end_spec(self, *, confirmed=499.0, confidence="HIGH", sources=None):
        return {
            "fontes": {"ram": "table"},
            "alertas": [],
            "conflitos": [],
            "marca": "asus",
            "submarca": "rog",
            "gpu_tipo": "dedicada",
            "gpu_modelo": "rtx 5090",
            "cpu_modelo": "i9-14900hx",
            "cpu_str_original": "i9-14900hx",
            "cpu_classe": "hx",
            "ram_gb": 32,
            "ram_expansivel": True,
            "armazenamento_tb": 2.0,
            "ssd_expansivel": True,
            "bateria_wh": 90,
            "peso_kg": 2.3,
            "ecra_res": "qhd+",
            "ecra_hz": 240,
            "teclado_pt": "confirmado",
            "price_confirmed": confirmed,
            "price_page_confidence": confidence,
            "price_evidence_sources": sources or ["jsonld", "meta"],
            "price_evidence_count": len(sources or ["jsonld", "meta"]),
        }

    def test_4999_is_parsed_as_4999_not_499(self):
        self.assertEqual(scraper.parse_price_value("4.999 €"), 4999.0)
        self.assertEqual(scraper.parse_price_value("4.999,00 €"), 4999.0)
        self.assertEqual(scraper.prices("Preço 4.999,00 €"), [4999.0])

    def test_product_page_uses_multiple_independent_price_signals(self):
        evidence = scraper.page_price_evidence(self.soup_for_price("499,00"), self.settings)
        self.assertEqual(evidence["price"], 499.0)
        self.assertEqual(evidence["confidence"], "HIGH")
        self.assertGreaterEqual(evidence["source_count"], 2)
        self.assertIn("jsonld", evidence["sources"])
        self.assertIn("meta", evidence["sources"])

    def test_false_499_candidate_conflicts_with_4999_product_page(self):
        soup = self.soup_for_price("4999,00")
        spec = scraper.extract("ASUS ROG i9-14900HX 32GB 2TB RTX 5090", soup)
        spec["teclado_pt"] = "confirmado"
        result = scraper.score(spec, 499.0, self.weights, self.settings)
        self.assertEqual(result["status"], "QUARENTENA")
        self.assertEqual(result["price_status"], "PRICE_CONFLICT")
        self.assertEqual(result["price_confidence"], "LOW")

    def test_rtx5090_at_499_with_only_one_page_signal_is_quarantined(self):
        soup = self.soup_for_price("499,00", jsonld=False, meta=True, visible=False)
        spec = scraper.extract("ASUS ROG i9-14900HX 32GB 2TB RTX 5090", soup)
        spec["teclado_pt"] = "confirmado"
        result = scraper.score(spec, 499.0, self.weights, self.settings)
        self.assertEqual(result["status"], "QUARENTENA")
        self.assertEqual(result["price_status"], "PRICE_UNCONFIRMED")

    def test_verified_rtx5090_at_499_is_allowed_and_becomes_diamond(self):
        spec = self.high_end_spec()
        result = scraper.score(spec, 499.0, self.weights, self.settings)
        self.assertEqual(result["status"], "ACEITE")
        self.assertEqual(result["price_confidence"], "HIGH")
        self.assertEqual(result["exceptional_deal_bonus"], 15.0)
        self.assertGreaterEqual(result["value_score"], 125.0)
        self.assertEqual(scraper.tier_from_value(result["value_score"], self.settings), "DIAMANTE")

    def test_499_and_1299_no_longer_have_same_value_when_price_is_verified(self):
        low_settings = dict(self.settings, _price_confidence="HIGH")
        at_499 = scraper.value_score(75.0, 499.0, low_settings)
        at_1299 = scraper.value_score(75.0, 1299.0, low_settings)
        self.assertGreater(at_499, at_1299)
        self.assertGreaterEqual(at_499 - at_1299, 14.0)

    def test_no_exceptional_bonus_without_high_price_confidence(self):
        unknown = dict(self.settings, _price_confidence="UNKNOWN")
        high = dict(self.settings, _price_confidence="HIGH")
        self.assertEqual(scraper.value_score(75.0, 499.0, unknown), 113.2)
        self.assertEqual(scraper.value_score(75.0, 499.0, high), 128.2)

    def test_old_hard_floor_is_runtime_suspicion_not_rejection(self):
        self.assertTrue(scraper.price_is_plausible_for_title("ASUS ROG RTX 5090", 499.0))
        self.assertTrue(scraper.price_is_suspicious_for_title("ASUS ROG RTX 5090", 499.0))

    def test_pcdiga_text_fallback_prefers_current_price_over_old_and_discount(self):
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Portátil Lenovo LOQ RTX 5070</h1>
              <div class="price-box">
                <span>1.499,99 €</span>
                <span class="old-price">1.699,99 €</span>
                <span>-200,00 €</span>
              </div>
            </body></html>
            """,
            "html.parser",
        )
        self.assertEqual(runner._safe_page_price(soup), 1499.99)

    def test_pcdiga_text_fallback_rejects_pvpr_context(self):
        soup = BeautifulSoup(
            """
            <html><body>
              <div><span>PVPR</span><span class="old-price">1.699,99 €</span></div>
              <div><span>1.299,99 €</span></div>
            </body></html>
            """,
            "html.parser",
        )
        self.assertEqual(runner._safe_page_price(soup), 1299.99)

    def test_merge_preserves_v88_state(self):
        current = {
            "schema_version": 8,
            "tracker_version": "8.7.1",
            "offers": {},
            "alert_state": {},
            "learning": {"runs": [], "stores": {}},
        }
        run_state = {
            "schema_version": 8,
            "tracker_version": "8.8",
            "offers": {
                "https://example.com/tuf": [
                    {
                        "timestamp": "2026-09-08T16:00:00Z",
                        "tracker_version": "8.8",
                        "url": "https://example.com/tuf",
                        "price": 1199.0,
                        "value_score": 117.7,
                        "tier": "OURO",
                        "specs": {"gpu_modelo": "rtx 5060"},
                    }
                ]
            },
            "alert_state": {},
            "learning": {
                "runs": [
                    {
                        "timestamp": "2026-09-08T16:00:00Z",
                        "runner_version": "8.8",
                        "access_requests": 100,
                    }
                ],
                "stores": {},
            },
        }
        merged = runner.tracker.merge_history(current, run_state)
        self.assertIn("https://example.com/tuf", merged["offers"])
        self.assertEqual(merged["offers"]["https://example.com/tuf"][-1]["tracker_version"], "8.8")
        self.assertTrue(any(run.get("runner_version") == "8.8" for run in merged["learning"]["runs"]))


if __name__ == "__main__":
    unittest.main()
