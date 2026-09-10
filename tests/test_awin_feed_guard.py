from __future__ import annotations

import gzip
import types
import unittest

import awin_feed_guard


class _Scraper:
    @staticmethod
    def norm(value):
        return " ".join(str(value or "").lower().replace("á", "a").replace("é", "e").split())

    @staticmethod
    def eligible(title):
        value = str(title or "").lower()
        return any(brand in value for brand in ("asus", "lenovo", "hp")) and "recondicionado" not in value

    @staticmethod
    def parse_price_value(value):
        raw = str(value or "").replace("€", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(raw)
        except ValueError:
            return None


class AwinFeedGuardTests(unittest.TestCase):
    def _module(self):
        module = types.SimpleNamespace()
        module.scraper = _Scraper()
        module.gtin_valid = lambda value: str(value).isdigit() and len(str(value)) in {8, 12, 13, 14}
        return module

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

    def test_gzip_feed_maps_price_stock_ids_and_direct_merchant_link(self):
        csv_text = (
            "merchant_id,product_name,merchant_category,search_price,merchant_deep_link,in_stock,ean,mpn,merchant_product_id,specifications\n"
            "120908,ASUS TUF Gaming A16,Computadores Portáteis,1.299,99,https://darty.pt/products/asus-tuf-a16,1,5601234567890,FA608UM,sku-1,RTX 5060 32GB 1TB\n"
        )
        # Deliberately use semicolon to preserve PT price comma.
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
                "awin_advertiser_id": 120908,
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
        self.assertEqual(item["sku"], "sku-1")
        self.assertIn("RTX 5060", item["_awin_spec_hint"])
        self.assertNotIn("specs", item)

    def test_wrong_merchant_id_is_ignored(self):
        content = (
            "merchant_id,product_name,merchant_category,search_price,merchant_deep_link\n"
            "999,ASUS TUF Gaming A16,Laptops,1299.99,https://darty.pt/products/asus-tuf-a16\n"
        ).encode()
        items = awin_feed_guard._feed_candidates(
            content,
            {
                "loja": "Darty",
                "url": "https://darty.pt/collections/portateis",
                "awin_advertiser_id": 120908,
            },
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
            {
                "loja": "Darty",
                "url": "https://darty.pt/collections/portateis",
                "awin_advertiser_id": 120908,
            },
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
                "awin_advertiser_id": 20983,
                "awin_category_hints": ["portatil", "laptop", "notebook"],
            },
            self._module(),
        )
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
