from __future__ import annotations

import gzip
import os
import types
import unittest
from unittest.mock import patch

import awin_feed_guard


class _Scraper:
    @staticmethod
    def norm(value):
        return (
            " ".join(
                str(value or "")
                .lower()
                .replace("á", "a")
                .replace("é", "e")
                .replace("í", "i")
                .replace("ó", "o")
                .replace("ú", "u")
                .split()
            )
        )

    @staticmethod
    def eligible(title):
        value = str(title or "").lower()
        return any(brand in value for brand in ("asus", "lenovo", "hp")) and "recondicionado" not in value

    @staticmethod
    def parse_price_value(value):
        raw = str(value or "").replace("€", "").replace(" ", "").strip()
        if not raw:
            return None
        try:
            if "," in raw and "." in raw:
                if raw.rfind(",") > raw.rfind("."):
                    return float(raw.replace(".", "").replace(",", "."))
                return float(raw.replace(",", ""))
            if "," in raw:
                return float(raw.replace(",", "."))
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def specs(text):
        value = str(text or "").lower()
        return {
            "fontes": {},
            "evidencias": {},
            "conflitos": [],
            "alertas": [],
            "marca": "asus" if "asus" in value else "lenovo" if "lenovo" in value else "hp" if "hp" in value else None,
            "submarca": None,
            "gpu_tipo": "dedicada" if "rtx" in value else "desconhecida",
            "gpu_modelo": "rtx 5060" if "rtx 5060" in value else None,
            "gpu_modelos_detectados": ["rtx 5060"] if "rtx 5060" in value else [],
            "cpu_modelo": None,
            "cpu_str_original": None,
            "cpu_classe": None,
            "ram_gb": 32 if "32gb" in value or "32 gb" in value else None,
            "ram_type": None,
            "ram_expansivel": False,
            "armazenamento_tb": 1.0 if "1tb" in value or "1 tb" in value else None,
            "ssd_expansivel": False,
            "vram_gb": None,
            "tgp_w": None,
            "bateria_wh": None,
            "peso_kg": None,
            "ecra_tamanho": None,
            "ecra_res": None,
            "ecra_painel": None,
            "ecra_hz": None,
            "ecra_brightness_nits": None,
            "teclado_pt": "desconhecido",
        }


class _Response:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


class AwinFeedGuardTests(unittest.TestCase):
    def _module(self):
        module = types.SimpleNamespace()
        module.scraper = _Scraper()
        module.gtin_valid = lambda value: str(value).isdigit() and len(str(value)) in {8, 12, 13, 14}
        return module

    def test_default_advertiser_ids_are_known(self):
        self.assertEqual(awin_feed_guard._advertiser_id({"loja": "Darty"}), "120908")
        self.assertEqual(awin_feed_guard._advertiser_id({"loja": "PcComponentes"}), "20983")
        self.assertEqual(awin_feed_guard._advertiser_id({"loja": "Worten"}), "99897")
        self.assertEqual(awin_feed_guard._advertiser_id({"loja": "CHIP7"}), "")

    def test_feed_list_selects_download_url_by_advertiser(self):
        payload = (
            "Advertiser ID,Advertiser Name,Membership Status,Feed ID,URL\n"
            "120908,Darty PT,Joined,1,https://datafeed.test/darty.csv.gz\n"
            "20983,PcComponentes PT,Joined,2,https://datafeed.test/pccomp.csv.gz\n"
        ).encode()
        self.assertEqual(
            awin_feed_guard._feed_urls_from_list(payload)["120908"],
            "https://datafeed.test/darty.csv.gz",
        )
        self.assertEqual(
            awin_feed_guard._feed_urls_from_list(payload)["20983"],
            "https://datafeed.test/pccomp.csv.gz",
        )

    def test_feed_list_prefers_joined_portuguese_feed(self):
        payload = (
            "Advertiser ID,Membership Status,Feed Name,Language,Vertical,URL\n"
            "120908,Not Joined,Default,English,General,https://datafeed.test/en.csv.gz\n"
            "120908,Joined,Produtos,Portuguese,General,https://datafeed.test/pt.csv.gz\n"
        ).encode()
        self.assertEqual(
            awin_feed_guard._feed_urls_from_list(payload)["120908"],
            "https://datafeed.test/pt.csv.gz",
        )

    def test_gzip_feed_maps_price_stock_ids_and_medium_price_evidence(self):
        csv_text = (
            "merchant_id;product_name;merchant_category;search_price;merchant_deep_link;in_stock;ean;mpn;merchant_product_id;specifications\n"
            "120908;ASUS TUF Gaming A16;Computadores Portáteis;1299,99;https://darty.pt/products/asus-tuf-a16;1;5601234567890;FA608UM;sku-1;RTX 5060 32GB 1TB\n"
        )
        content = gzip.compress(csv_text.encode("utf-8"))
        items = awin_feed_guard._feed_candidates(
            content,
            {
                "loja": "Darty",
                "url": "https://darty.pt/collections/portateis",
                "awin_category_hints": ["portatil", "laptop"],
                "awin_feed_candidate_limit": 20,
            },
            self._module(),
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["preco"], 1299.99)
        self.assertEqual(item["url"], "https://darty.pt/products/asus-tuf-a16")
        self.assertTrue(item["stock"])
        self.assertEqual(item["ean"], "5601234567890")
        self.assertEqual(item["mpn"], "FA608UM")
        self.assertEqual(item["_awin_product_id"], "sku-1")
        self.assertNotIn("sku", item)
        self.assertIn("RTX 5060", item["_awin_spec_hint"])
        self.assertEqual(item["detail_source"], "awin_feed")
        self.assertEqual(item["specs"]["gpu_modelo"], "rtx 5060")
        self.assertEqual(item["specs"]["ram_gb"], 32)
        self.assertEqual(item["specs"]["armazenamento_tb"], 1.0)
        self.assertEqual(item["specs"]["price_confirmed"], 1299.99)
        self.assertEqual(item["specs"]["price_page_confidence"], "MEDIUM")
        self.assertEqual(item["specs"]["price_evidence_sources"], ["awin_feed"])
        self.assertTrue(item["specs"]["awin_feed_authoritative"])

    def test_weak_feed_specs_remain_seed_for_live_enrichment(self):
        content = (
            "merchant_id,product_name,merchant_category,search_price,merchant_deep_link,specifications\n"
            "120908,ASUS Vivobook,Laptops,899.99,https://darty.pt/products/asus-vivobook,OLED\n"
        ).encode()
        items = awin_feed_guard._feed_candidates(
            content,
            {"loja": "Darty", "url": "https://darty.pt/collections/portateis"},
            self._module(),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["detail_source"], "awin_feed_seed")
        self.assertNotIn("specs", items[0])

    def test_wrong_merchant_id_is_ignored(self):
        content = (
            "merchant_id,product_name,merchant_category,search_price,merchant_deep_link\n"
            "999,ASUS TUF Gaming A16,Laptops,1299.99,https://darty.pt/products/asus-tuf-a16\n"
        ).encode()
        items = awin_feed_guard._feed_candidates(
            content,
            {"loja": "Darty", "url": "https://darty.pt/collections/portateis"},
            self._module(),
        )
        self.assertEqual(items, [])

    def test_awin_tracking_link_is_not_used_as_product_url(self):
        content = (
            "merchant_id,product_name,merchant_category,search_price,merchant_deep_link,aw_deep_link\n"
            "120908,ASUS TUF Gaming A16,Laptops,1299.99,,https://www.awin1.com/cread.php?awinmid=120908\n"
        ).encode()
        items = awin_feed_guard._feed_candidates(
            content,
            {"loja": "Darty", "url": "https://darty.pt/collections/portateis"},
            self._module(),
        )
        self.assertEqual(items, [])

    def test_non_laptop_and_refurbished_rows_are_filtered(self):
        content = (
            "merchant_id,product_name,merchant_category,search_price,merchant_deep_link,condition\n"
            "20983,ASUS Monitor,Monitores,299.99,https://www.pccomponentes.pt/asus-monitor,new\n"
            "20983,Lenovo ThinkPad,Laptops,699.99,https://www.pccomponentes.pt/lenovo-thinkpad,recondicionado\n"
        ).encode()
        items = awin_feed_guard._feed_candidates(
            content,
            {
                "loja": "PcComponentes",
                "url": "https://www.pccomponentes.pt/categorias/computadores-portateis",
                "awin_category_hints": ["portatil", "laptop", "notebook"],
            },
            self._module(),
        )
        self.assertEqual(items, [])

    def test_install_is_noop_without_secret(self):
        module = types.SimpleNamespace()
        module._AWIN_FEED_GUARD_INSTALLED = False
        module.scraper = _Scraper()
        module.gtin_valid = lambda value: True
        module.scan_store = lambda cat, config, settings: (
            [],
            {"candidatos": 0, "bloqueada": True, "fontes_descoberta": {}, "rendimento_descoberta": {}},
        )
        module.candidate_priority = lambda item, weights, settings: 1.0
        module.budget_available = lambda store=None: True
        module.REQUESTS_BY_STORE = {}
        module.consume_request = lambda store: (_ for _ in ()).throw(AssertionError("não devia fazer pedidos"))
        module.requests = types.SimpleNamespace()
        module.record_discovery_yield = lambda *args: None

        with patch.dict(os.environ, {}, clear=True):
            awin_feed_guard.install(module)
            items, stat = module.scan_store(
                {"loja": "Darty", "url": "https://darty.pt/collections/portateis"},
                {},
                {},
            )
        self.assertEqual(items, [])
        self.assertEqual(stat["awin_feed_outcome"], "not_configured")

    def test_install_loads_feed_list_then_authorized_feed(self):
        feed_list = (
            "Advertiser ID,Membership Status,Language,URL\n"
            "120908,Joined,Portuguese,https://datafeed.test/darty.csv.gz\n"
        ).encode()
        feed = gzip.compress(
            (
                "merchant_id;product_name;merchant_category;search_price;merchant_deep_link;in_stock;specifications\n"
                "120908;ASUS TUF A16;Portáteis;1199,99;https://darty.pt/products/asus-tuf-a16;1;RTX 5060 32GB 1TB\n"
            ).encode()
        )
        calls = []

        module = types.SimpleNamespace()
        module._AWIN_FEED_GUARD_INSTALLED = False
        module.scraper = _Scraper()
        module.gtin_valid = lambda value: True
        module.scan_store = lambda cat, config, settings: (
            [],
            {"candidatos": 0, "bloqueada": True, "fontes_descoberta": {}, "rendimento_descoberta": {}},
        )
        module.candidate_priority = lambda item, weights, settings: 1.0
        module.budget_available = lambda store=None: True
        module.REQUESTS_BY_STORE = {}

        def consume(store):
            module.REQUESTS_BY_STORE[store] = module.REQUESTS_BY_STORE.get(store, 0) + 1
            return True

        module.consume_request = consume

        def get(url, **kwargs):
            calls.append(url)
            return _Response(feed_list if "datafeed/list/apikey/" in url else feed)

        module.requests = types.SimpleNamespace(get=get)
        module.record_discovery_yield = lambda *args: None

        with patch.dict(os.environ, {"AWIN_DATAFEED_API_KEY": "secret-test-key"}, clear=True):
            awin_feed_guard.install(module)
            items, stat = module.scan_store(
                {"loja": "Darty", "url": "https://darty.pt/collections/portateis"},
                {},
                {},
            )

        self.assertEqual(len(calls), 2)
        self.assertNotIn("secret-test-key", str(stat))
        self.assertEqual(len(items), 1)
        self.assertEqual(stat["awin_feed_outcome"], "http_success")
        self.assertEqual(stat["fontes_descoberta"]["awin_feed"], 1)
        self.assertFalse(stat["bloqueada"])


if __name__ == "__main__":
    unittest.main()
