import copy
import unittest
from types import SimpleNamespace

import tracker
import search_index_identity_guard as guard


PCDIGA_URL = (
    "https://www.pcdiga.com/computadores-e-software/computadores-laptop/"
    "computadores-portateis/portatil-asus-tuf-90nr0kv1-m00h70-4711636583923"
)


class SearchIndexIdentityGuardTests(unittest.TestCase):
    def _module(self, items, watch):
        base_items = copy.deepcopy(items)
        base_stat = {
            "search_index": {
                "status": "discovery_available",
                "watchlist": copy.deepcopy(watch),
            }
        }

        def scan_store(cat, config, settings):
            return copy.deepcopy(base_items), copy.deepcopy(base_stat)

        return SimpleNamespace(scan_store=scan_store, url_ean=tracker.url_ean)

    def test_pcdiga_watch_entry_keeps_index_only_and_gains_strong_ean(self):
        module = self._module([], [{
            "url": PCDIGA_URL,
            "title": "ASUS TUF Gaming",
            "price_hint": 1299.99,
            "price_status": "INDEX_ONLY",
            "consensus": False,
        }])
        guard.install(module)

        items, stat = module.scan_store({}, {}, {})
        row = stat["search_index"]["watchlist"][0]
        self.assertEqual(items, [])
        self.assertEqual(row["ean"], "4711636583923")
        self.assertEqual(row["identity_status"], "STRONG_URL_EAN")
        self.assertEqual(row["identity_source"], "product_url")
        self.assertEqual(row["price_hint"], 1299.99)
        self.assertEqual(row["price_status"], "INDEX_ONLY")
        self.assertFalse(row["consensus"])
        self.assertEqual(stat["search_index"]["strong_identity"], 1)

    def test_pccomponentes_slug_does_not_invent_identifier(self):
        url = (
            "https://www.pccomponentes.pt/portatil-lenovo-legion-5-15ahp10-oled-"
            "amd-ryzen-7-260-32gb-1tb-ssd-rtx-5060-151"
        )
        module = self._module([], [{
            "url": url,
            "price_hint": 1299.0,
            "price_status": "INDEX_ONLY",
        }])
        guard.install(module)

        items, stat = module.scan_store({}, {}, {})
        row = stat["search_index"]["watchlist"][0]
        self.assertEqual(items, [])
        self.assertNotIn("ean", row)
        self.assertNotIn("identity_status", row)
        self.assertEqual(stat["search_index"]["strong_identity"], 0)

    def test_existing_history_bridge_can_receive_url_ean_without_price_mutation(self):
        item = {
            "loja": "PCDiga",
            "url": PCDIGA_URL,
            "titulo": "ASUS TUF Gaming",
            "preco": 1249.99,
            "detail_source": "search_index_history_bridge",
        }
        module = self._module([item], [{
            "url": PCDIGA_URL,
            "price_hint": 1249.99,
            "price_status": "INDEX_ONLY",
        }])
        guard.install(module)

        items, stat = module.scan_store({}, {}, {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ean"], "4711636583923")
        self.assertEqual(items[0]["identity_source"], "product_url")
        self.assertEqual(items[0]["preco"], 1249.99)
        self.assertEqual(stat["search_index"]["watchlist"][0]["price_status"], "INDEX_ONLY")

    def test_guard_is_noop_without_search_index_stat(self):
        module = SimpleNamespace(
            scan_store=lambda cat, config, settings: ([{"url": PCDIGA_URL}], {"candidatos": 1}),
            url_ean=tracker.url_ean,
        )
        guard.install(module)
        items, stat = module.scan_store({}, {}, {})
        self.assertEqual(items, [{"url": PCDIGA_URL}])
        self.assertEqual(stat, {"candidatos": 1})


if __name__ == "__main__":
    unittest.main()
