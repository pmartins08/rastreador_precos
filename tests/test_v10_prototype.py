"""Unit tests for the LapIntel V10 autonomous agent prototype."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import v10_agent_prototype as v10


class V10AgentPrototypeTests(unittest.TestCase):
    def test_evaluate_laptop_deal_eligible_deal(self):
        raw = v10.evaluate_laptop_deal_v10(
            store="Globaldata",
            sku_or_mpn="83DH003KPG",
            brand="Lenovo",
            model_name="Legion Slim 5 16AHP9",
            listed_price_eur=1249.0,
            gpu_model="RTX 4070",
            ram_gb=32,
            storage_gb=1000,
            promo_discount_eur=50.0,
            gpu_tgp_watts=140,
            display_nits=350,
            color_gamut_srgb_pct=100,
            battery_wh=80.0,
            weight_kg=2.3,
            os_status="none_or_freedos",
            keyboard_layout="PT",
            is_new_condition=True,
            in_stock_confirmed=True,
            historical_bonus_pts=4.0,
        )
        data = json.loads(raw)
        self.assertTrue(data["eligible"])
        self.assertIsNone(data["ineligibility_reason"])
        self.assertEqual(data["effective_price_eur"], 1309.0)  # (1249 - 50) + 110 surcharge
        self.assertEqual(data["os_install_surcharge_eur"], 110.0)
        self.assertGreaterEqual(data["value_score"], 115.0)
        self.assertIn(data["tier"], {"Diamante", "Ouro"})

    def test_evaluate_laptop_deal_rejects_spanish_keyboard(self):
        raw = v10.evaluate_laptop_deal_v10(
            store="TestStore",
            sku_or_mpn="SKU-ES",
            brand="ASUS",
            model_name="TUF Gaming",
            listed_price_eur=1199.0,
            gpu_model="RTX 4060",
            ram_gb=16,
            storage_gb=512,
            keyboard_layout="ES",
            is_new_condition=True,
            in_stock_confirmed=True,
        )
        data = json.loads(raw)
        self.assertFalse(data["eligible"])
        self.assertIn("Teclado espanhol", data["ineligibility_reason"])

    def test_evaluate_laptop_deal_rejects_refurbished(self):
        raw = v10.evaluate_laptop_deal_v10(
            store="TestStore",
            sku_or_mpn="SKU-REFURB",
            brand="Lenovo",
            model_name="IdeaPad",
            listed_price_eur=800.0,
            gpu_model="RTX 4050",
            ram_gb=16,
            storage_gb=512,
            is_new_condition=False,
            in_stock_confirmed=True,
        )
        data = json.loads(raw)
        self.assertFalse(data["eligible"])
        self.assertIn("recondicionado", data["ineligibility_reason"])

    def test_evaluate_laptop_deal_rejects_out_of_stock(self):
        raw = v10.evaluate_laptop_deal_v10(
            store="TestStore",
            sku_or_mpn="SKU-OOS",
            brand="HP",
            model_name="Victus",
            listed_price_eur=999.0,
            gpu_model="RTX 4060",
            ram_gb=16,
            storage_gb=512,
            is_new_condition=True,
            in_stock_confirmed=False,
        )
        data = json.loads(raw)
        self.assertFalse(data["eligible"])
        self.assertIn("Sem stock", data["ineligibility_reason"])

    def test_evaluate_laptop_deal_rejects_budget_exceeded(self):
        raw = v10.evaluate_laptop_deal_v10(
            store="TestStore",
            sku_or_mpn="SKU-EXPENSIVE",
            brand="ASUS",
            model_name="ROG Strix",
            listed_price_eur=1700.0,
            gpu_model="RTX 4080",
            ram_gb=32,
            storage_gb=1000,
            is_new_condition=True,
            in_stock_confirmed=True,
        )
        data = json.loads(raw)
        self.assertFalse(data["eligible"])
        self.assertIn("excede o máximo", data["ineligibility_reason"])

    def test_dry_run_demo_executes_cleanly(self):
        result = v10.run_dry_run_demo()
        self.assertTrue(result["eligible"])
        self.assertGreaterEqual(result["value_score"], 115.0)
        self.assertEqual(result["effective_price_eur"], 1309.0)
        self.assertIn("spec", result)
        self.assertEqual(result["spec"]["brand"], "Lenovo")


if __name__ == "__main__":
    unittest.main()
