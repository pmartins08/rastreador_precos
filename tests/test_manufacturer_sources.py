from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

import scraper
import manufacturer_source_guard
import official_store_guard
from price_tracker.sources import asus, hp, lenovo


class LenovoSourceTests(unittest.TestCase):
    def test_exact_psref_url_requires_model_and_family(self):
        item = {
            "titulo": "Portátil Lenovo IdeaPad Slim 3 15ARP10 Ryzen 7",
            "mpn": "83K700U6SP",
        }
        self.assertEqual(
            lenovo.detail_urls(item),
            ["https://psref.lenovo.com/Detail/IdeaPad_Slim_3_15ARP10?M=83K700U6SP"],
        )

    def test_psref_response_must_contain_exact_model(self):
        item = {"titulo": "Lenovo IdeaPad Slim 3 15ARP10", "mpn": "83K700U6SP"}
        good = "Lenovo PSREF Model: 83K700U6SP Processor AMD Ryzen"
        wrong = "Lenovo PSREF Model: 83K7009HCK Processor AMD Ryzen"
        self.assertTrue(lenovo.response_matches(good, item))
        self.assertFalse(lenovo.response_matches(wrong, item))


class HPSourceTests(unittest.TestCase):
    def test_product_number_strips_locale_suffix(self):
        self.assertEqual(hp.normalize_product_number("7W6H7UA#AB9"), "7W6H7UA")

    def test_search_uses_official_typeahead_api(self):
        url = hp.search_url({"mpn": "7W6H7UA", "titulo": "HP Laptop 15"})
        self.assertIsNotNone(url)
        self.assertIn("support.hp.com/typeahead?", url)
        self.assertIn("q=7W6H7UA", url)
        self.assertIn("pm_name_value", url)

    def test_typeahead_builds_exact_specs_url_from_product_number_path(self):
        item = {"mpn": "7W6H7UA#AB9", "titulo": "HP Laptop 15"}
        payload = {
            "matches": [
                {
                    "pmClass": "pm_number_value",
                    "productId": 2102348830,
                    "pmSeriesOid": 2101497656,
                    "seoFriendlyName": "hp-15.6-inch-laptop-pc-15-fc0000",
                    "navigationPath": [
                        "root|2101497656|2101497693|2102348830|"
                    ],
                    "childNodes": "7W6H7UA",
                },
                {
                    "pmClass": "pm_number_value",
                    "productId": 999,
                    "pmSeriesOid": 2101497656,
                    "seoFriendlyName": "wrong-model",
                    "navigationPath": ["root|2101497656|998|999|7W6H8UA|"],
                },
            ]
        }
        matches = hp.typeahead_matches(payload, item)
        self.assertEqual(matches[0]["model_oid"], "2101497693")
        urls = hp.spec_urls(payload, item)
        self.assertEqual(
            urls,
            [
                "https://support.hp.com/us-en/product/product-specs/"
                "hp-15-6-inch-laptop-pc-15-fc0000/model/2101497693?sku=7W6H7UA"
            ],
        )

    def test_hp_response_requires_exact_product_number_and_specs_heading(self):
        item = {"mpn": "7W6H7UA", "titulo": "HP Laptop 15"}
        self.assertTrue(
            hp.response_matches("Product specifications HP Laptop (7W6H7UA)", item)
        )
        self.assertFalse(
            hp.response_matches("Product specifications HP Laptop (7W6H8UA)", item)
        )


class ManufacturerMergeTests(unittest.TestCase):
    def test_official_source_only_fills_missing_fields(self):
        retail = {
            "cpu_modelo": "ryzen 7 7840hs",
            "gpu_tipo": "dedicada",
            "gpu_modelo": "rtx 4060",
            "ram_gb": 16,
            "armazenamento_tb": 1.0,
            "bateria_wh": None,
            "fontes": {},
            "evidencias": {},
        }
        official = dict(retail, bateria_wh=80, peso_kg=2.2)
        merged = manufacturer_source_guard._merge_official(
            scraper, retail, official, "Lenovo PSREF", "https://psref.lenovo.com/x"
        )
        self.assertEqual(merged["bateria_wh"], 80)
        self.assertEqual(merged["peso_kg"], 2.2)
        self.assertEqual(merged["cpu_modelo"], retail["cpu_modelo"])
        self.assertEqual(merged["official_spec_status"], "MERGED")

    def test_core_conflict_rejects_entire_official_merge(self):
        retail = {
            "cpu_modelo": "ryzen 7 7840hs",
            "gpu_tipo": "dedicada",
            "gpu_modelo": "rtx 4060",
            "ram_gb": 16,
            "armazenamento_tb": 1.0,
            "bateria_wh": None,
        }
        official = dict(retail, gpu_modelo="rtx 4050", bateria_wh=80)
        merged = manufacturer_source_guard._merge_official(
            scraper, retail, official, "Lenovo PSREF", "https://psref.lenovo.com/x"
        )
        self.assertIsNone(merged["bateria_wh"])
        self.assertEqual(merged["official_spec_status"], "CONFLICT_REJECTED")
        self.assertEqual(merged["official_source_conflicts"][0]["field"], "gpu_modelo")


class AsusStoreTests(unittest.TestCase):
    def test_store_config_is_strict_and_official(self):
        config = asus.store_config()
        self.assertEqual(config["loja"], "ASUS Store")
        self.assertEqual(config["url"], "https://estore.asus.com/pt/")
        self.assertTrue(config["strict_current_price_context"])

    def test_runtime_config_keeps_experimental_sources_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder) / "config.json"
            module = types.SimpleNamespace()
            module._OFFICIAL_STORE_GUARD_INSTALLED = False
            module.CONFIG_PATH = config_path
            module.load_json = lambda path: {
                "settings": {"alerta_min_tier": "OURO"},
                "category_urls": [{"loja": "Darty", "url": "https://darty.pt"}],
            }
            official_store_guard.install(module)
            loaded = module.load_json(config_path)
            stores = [row["loja"] for row in loaded["category_urls"]]
            self.assertNotIn("ASUS Store", stores)
            self.assertFalse(loaded["settings"]["manufacturer_enrichment_enabled"])
            self.assertEqual(loaded["settings"]["manufacturer_enrichment_max_per_run"], 0)
            self.assertFalse(loaded["settings"]["asus_store_enabled"])

    def test_runtime_config_can_enable_asus_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder) / "config.json"
            module = types.SimpleNamespace()
            module._OFFICIAL_STORE_GUARD_INSTALLED = False
            module.CONFIG_PATH = config_path
            module.load_json = lambda path: {
                "settings": {"asus_store_enabled": True},
                "category_urls": [{"loja": "Darty", "url": "https://darty.pt"}],
            }
            official_store_guard.install(module)
            loaded = module.load_json(config_path)
            stores = [row["loja"] for row in loaded["category_urls"]]
            self.assertIn("ASUS Store", stores)


if __name__ == "__main__":
    unittest.main()
