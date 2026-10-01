import json
import unittest
from pathlib import Path
from types import SimpleNamespace
import unicodedata

from store_expansion_guard import fair_selection, laptop_candidate


class StoreExpansionTests(unittest.TestCase):
    def setUp(self):
        self.scraper = SimpleNamespace(norm=lambda value: unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower())

    def test_mixed_catalog_rejects_desktops_accessories_and_consoles(self):
        for title in ('Monitor ASUS 16"', 'Desktop HP OMEN', 'Mochila Lenovo para portátil', 'Lenovo Legion Go 8"', 'Tablet Lenovo Yoga 13"'):
            self.assertFalse(laptop_candidate({"titulo": title}, self.scraper), title)
        for title in ('Portátil Acer Nitro V14', 'Lenovo LEGION 5 15AHP11 (15,3" OLED, 32GB)', 'HP OMEN 16-am0044np (16" 2K, RTX5060)'):
            self.assertTrue(laptop_candidate({"titulo": title}, self.scraper), title)
        self.assertFalse(laptop_candidate({"titulo": "HP OMEN RTX5060"}, self.scraper))

    def test_new_stores_get_slots_without_duplicates_or_exceeding_limit(self):
        cached = [{"loja": "Old", "url": str(i)} for i in range(30)]
        fresh = [{"loja": store, "url": f"{store}{i}"} for store in ("A", "B", "C") for i in range(8)]
        selected = fair_selection(cached + fresh, {row["url"]: {} for row in cached}, 30, 3)
        self.assertEqual(len(selected), 30)
        self.assertEqual(len({row["url"] for row in selected}), 30)
        self.assertEqual([sum(row["loja"] == s for row in selected) for s in ("A", "B", "C")], [3, 3, 3])
        self.assertEqual(len(fair_selection(fresh, {}, 0, 3)), 0)

    def test_all_new_stores_configured_with_bounded_routes(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "config/config.json").read_text())
        stores = {row["loja"]: row for row in config["category_urls"]}
        self.assertEqual(len(stores), 15)
        for name in ("You Get", "Tek4life", "Auchan", "MEO", "Clickfiel", "Novo Atalho"):
            row = stores[name]
            self.assertTrue(row["laptop_only"])
            self.assertLessEqual(row["max_category_pages"], 3)
            self.assertTrue(row["product_path_hints"])
        self.assertTrue(stores["Tek4life"]["catalog_laptop_only"])

    def test_exposure_card_cannot_return_through_radio_popular_fallback(self):
        import runner
        from bs4 import BeautifulSoup
        card = BeautifulSoup('<article>Artigo de Exposição<a href="/produto/legion" title="Lenovo Legion 5">Lenovo Legion 5</a><span class="price" content="1599.99">1599,99€</span></article>', 'html.parser').article
        cat = {"loja": "Radio Popular", "url": "https://www.radiopopular.pt/categoria/portateis", "product_path_hints": ["/produto/"]}
        self.assertIsNone(runner.scraper.candidate_from_card(card, cat["url"], cat))
