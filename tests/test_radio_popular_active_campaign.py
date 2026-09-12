from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import promotion_runtime_guard


ROOT = Path(__file__).resolve().parents[1]


class RadioPopularActiveCampaignTests(unittest.TestCase):
    def setUp(self):
        config = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
        self.store = next(row for row in config["category_urls"] if row["loja"] == "Radio Popular")
        self.campaign = next(
            row for row in self.store["campaign_urls"]
            if row.get("label") == "50_por_250_set_2026"
        )

    def test_campaign_dates_and_economics_match_current_official_campaign(self):
        self.assertEqual(self.campaign["active_from"], "2026-09-12")
        self.assertEqual(self.campaign["expires_at"], "2026-09-15")
        promo = self.campaign["promotion"]
        self.assertEqual(promo["kind"], "TIERED_DISCOUNT")
        self.assertEqual(promo["step_discount_eur"], 50.0)
        self.assertEqual(promo["threshold_step_eur"], 250.0)
        self.assertEqual(promo["cap_eur"], 500.0)
        self.assertTrue(promo["applicable"])

    def test_campaign_is_filtered_to_available_laptops_before_pagination(self):
        filtered = promotion_runtime_guard._radio_popular_laptop_campaign(self.campaign["url"])
        parsed = urlsplit(filtered)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/destaque/6a20120dc7e006.23735122")
        self.assertEqual(query["filters[category_n2_name][]"], ["Computadores Portáteis"])
        self.assertEqual(query["filters[disponibilidade][]"], ["Ocultar Produtos Indisponíveis"])


if __name__ == "__main__":
    unittest.main()
