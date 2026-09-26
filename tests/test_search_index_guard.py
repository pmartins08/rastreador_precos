from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock
import types
import unittest
from urllib.parse import quote

import search_index_guard


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _Scraper:
    @staticmethod
    def eligible(title):
        text = str(title or "").lower()
        return any(word in text for word in ("asus", "lenovo", "hp", "acer", "msi", "gigabyte"))


class SearchIndexGuardTests(unittest.TestCase):
    def _module(self, responses=None, base_items=None):
        module = types.SimpleNamespace()
        module._SEARCH_INDEX_GUARD_INSTALLED = False
        module.scraper = _Scraper()
        module.REQUESTS_BY_STORE = {}
        module.LOGGER = types.SimpleNamespace(info=lambda *args, **kwargs: None)
        module._learning = []
        module._yields = []
        base_items = list(base_items or [])

        module.scan_store = Mock(return_value=(
            base_items,
            {
                "candidatos": len(base_items),
                "bloqueada": not bool(base_items),
                "fontes_descoberta": {},
                "rendimento_descoberta": {},
            },
        ))
        module.headers = lambda profile: {"User-Agent": profile}
        module.budget_available = lambda store=None: True

        def consume(store):
            module.REQUESTS_BY_STORE[store] = module.REQUESTS_BY_STORE.get(store, 0) + 1
            return True

        module.consume_request = consume
        response_list = list(responses or [])
        module.requests = types.SimpleNamespace(get=Mock(side_effect=response_list))
        module.record_learning = lambda *args: module._learning.append(args)
        module.record_discovery_yield = lambda *args: module._yields.append(args)
        module.load_history = lambda: {}
        module.latest_offer_by_url = lambda history: {}
        return module

    def test_parse_brave_result_extracts_product_and_portuguese_price(self):
        html = """
        <html><body>
          <div class='snippet'>
            <a href='https://www.pccomponentes.pt/hp-omen-16-am0046np-intel-core-ultra-7-255h-24gb-1tb-ssd-rtx5070-16-pt'>
              HP OMEN 16-am0046np Intel Core Ultra 7 255H/24GB/1TB SSD/RTX5070/16 PT
            </a>
            <p>Gaming de alto nível. Preço: € 1.499,00</p>
          </div>
          <div><a href='https://www.pccomponentes.pt/categorias/portateis/gaming'>Portáteis gaming</a></div>
        </body></html>
        """
        module = self._module()
        rows = search_index_guard._parse_results(
            html, engine="brave", domain="pccomponentes.pt", tracker_module=module
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prices"], [1499.0])
        self.assertIn("am0046np", rows[0]["url"])

    def test_unwraps_yahoo_ru_destination(self):
        target = "https://www.pccomponentes.pt/lenovo-loq-15irx10-540-intel-core-i7-13650hx-24gb-1tb-ssd-rtx5070-156-pt"
        wrapped = f"https://r.search.yahoo.com/x/RU={quote(target, safe='')}/RK=2/RS=test"
        self.assertEqual(search_index_guard._unwrap_url(wrapped), target)

    def test_price_hint_requires_independent_engines_for_consensus(self):
        settings = {"budget_hard": 1500}
        evidence = {
            "prices_by_engine": {"brave": [1429.0], "yahoo": [1430.0]},
        }
        price, consensus = search_index_guard._price_hint(evidence, settings)
        self.assertTrue(consensus)
        self.assertEqual(price, 1429.5)

        price, consensus = search_index_guard._price_hint(
            {"prices_by_engine": {"brave": [1429.0]}}, settings
        )
        self.assertFalse(consensus)
        self.assertEqual(price, 1429.0)

    def test_blocked_store_gets_watchlist_but_unverified_result_never_enters_scoring(self):
        product = "https://www.pccomponentes.pt/hp-omen-16-am0046np-intel-core-ultra-7-255h-24gb-1tb-ssd-rtx5070-16-pt"
        brave = _Response(f"<div><a href='{product}'>HP OMEN 16-am0046np RTX5070 24GB 1TB portátil</a><p>Preço: € 1.499,00</p></div>")
        yahoo = _Response(f"<div><a href='{product}'>HP OMEN 16-am0046np RTX5070 24GB 1TB portátil</a><p>€ 1.499,00</p></div>")
        module = self._module([brave, yahoo])
        search_index_guard.install(module)

        items, stat = module.scan_store(
            {
                "loja": "PcComponentes",
                "url": "https://www.pccomponentes.pt/categorias/computadores-portateis",
                "search_index_enabled": True,
                "search_index_queries": ["portatil RTX 5070"],
            },
            {},
            {
                "budget_hard": 1500,
                "search_index_max_queries_per_store": 1,
                "search_index_max_engines_per_query": 2,
            },
        )
        self.assertEqual(items, [])
        self.assertEqual(stat["search_index"]["status"], "discovery_available")
        self.assertEqual(stat["search_index"]["urls"], 1)
        self.assertEqual(stat["search_index"]["priced"], 1)
        self.assertEqual(stat["search_index"]["consensus_priced"], 1)
        self.assertEqual(stat["search_index"]["verified_history_reused"], 0)
        self.assertEqual(stat["fontes_descoberta"]["search_index"], 1)
        self.assertEqual(module.REQUESTS_BY_STORE["PcComponentes"], 2)

    def test_recent_high_confidence_history_can_bridge_index_discovery(self):
        product = "https://www.pccomponentes.pt/lenovo-loq-15irx10-540-intel-core-i7-13650hx-24gb-1tb-ssd-rtx5070-156-pt"
        response = _Response(
            f"<div><a href='{product}'>Lenovo LOQ 15IRX10-540 portátil RTX 5070 24GB 1TB</a>"
            "<span>Preço: € 1.429,00</span></div>"
        )
        module = self._module([response])
        previous = {
            "loja": "PcComponentes",
            "titulo": "Lenovo LOQ 15IRX10-540 RTX 5070 24GB 1TB",
            "price": 1429.0,
            "stock": True,
            "url": product,
            "ean": "1234567890123",
            "specs": {
                "price_confirmed": 1429.0,
                "price_page_confidence": "HIGH",
                "price_checked_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        module.latest_offer_by_url = lambda history: {product: previous}
        search_index_guard.install(module)

        items, stat = module.scan_store(
            {
                "loja": "PcComponentes",
                "url": "https://www.pccomponentes.pt/categorias/computadores-portateis",
                "search_index_enabled": True,
                "search_index_queries": ["Lenovo LOQ RTX 5070"],
                "search_index_engines": ["brave"],
            },
            {},
            {
                "budget_hard": 1500,
                "search_index_max_queries_per_store": 1,
                "search_index_max_engines_per_query": 1,
                "price_confirmation_ttl_hours": 24,
            },
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["preco"], 1429.0)
        self.assertEqual(items[0]["detail_source"], "search_index_history_bridge")
        self.assertEqual(items[0]["ean"], "1234567890123")
        self.assertEqual(stat["search_index"]["verified_history_reused"], 1)

    def test_search_index_is_skipped_when_direct_coverage_is_sufficient(self):
        existing = [
            {"loja": "PCDiga", "titulo": "Portátil ASUS TUF A16", "preco": 1200, "url": f"https://pcdiga.com/p/{i}"}
            for i in range(6)
        ]
        module = self._module([], base_items=existing)
        search_index_guard.install(module)
        items, stat = module.scan_store(
            {"loja": "PCDiga", "url": "https://www.pcdiga.com/computadores/portateis", "search_index_enabled": True},
            {},
            {"search_index_trigger_below": 6},
        )
        self.assertEqual(items, existing)
        self.assertNotIn("search_index", stat)
        module.requests.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
