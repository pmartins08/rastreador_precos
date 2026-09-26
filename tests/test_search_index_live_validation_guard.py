import copy
import unittest
from types import SimpleNamespace

import scraper
import search_index_live_validation_guard as guard


EAN = "4711636583923"
URL = f"https://www.pcdiga.com/portatil-asus-tuf-{EAN}"
MPN = "83JE00C6PG"
MPN_URL = f"https://chip7.pt/computadores/portateis/portateis-gaming/lenovo/{MPN.lower()}"


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _Requests:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


class SearchIndexLiveValidationGuardTests(unittest.TestCase):
    def _module(self, *, html, page_ean=EAN, status_code=200, hint=1299.99, identity="ean"):
        if identity == "mpn":
            watch = [{
                "url": MPN_URL,
                "title": "Lenovo LOQ RTX 5060 32GB",
                "price_hint": hint,
                "price_status": "INDEX_ONLY",
                "consensus": True,
                "mpn": MPN,
                "identity_status": "STRONG_URL_MPN",
                "identity_source": "product_url",
            }]
            page_ids = {"mpn": MPN}
        else:
            watch = [{
                "url": URL,
                "title": "ASUS TUF Gaming RTX 5070 32GB",
                "price_hint": hint,
                "price_status": "INDEX_ONLY",
                "consensus": True,
                "ean": EAN,
                "identity_status": "STRONG_URL_EAN",
                "identity_source": "product_url",
            }]
            page_ids = {"ean": page_ean} if page_ean else {}

        def scan_store(cat, config, settings):
            return [], {
                "candidatos": 0,
                "search_index": {"status": "discovery_available", "watchlist": copy.deepcopy(watch)},
            }

        learning = []
        module = SimpleNamespace(
            scan_store=scan_store,
            scraper=scraper,
            requests=_Requests(_Response(html, status_code)),
            budget_available=lambda store: True,
            consume_request=lambda store: True,
            headers=lambda profile: {},
            record_learning=lambda *args: learning.append(args),
            page_identifiers=lambda soup: dict(page_ids),
            now_iso=lambda: "2026-09-26T19:00:00Z",
            LOGGER=SimpleNamespace(info=lambda *args, **kwargs: None),
        )
        module.learning = learning
        return module

    def _high_html(self, price="1299.99"):
        return f"""
        <html><head>
          <meta property="product:price:amount" content="{price}">
          <script type="application/ld+json">
            {{"@type":"Product","offers":{{"@type":"Offer","price":"{price}"}}}}
          </script>
        </head><body><h1>Gaming laptop</h1></body></html>
        """

    def test_strong_ean_and_high_live_price_promotes_candidate(self):
        module = self._module(html=self._high_html())
        guard.install(module)
        items, stat = module.scan_store({"loja": "PCDiga"}, {}, {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ean"], EAN)
        self.assertEqual(items[0]["preco"], 1299.99)
        self.assertEqual(items[0]["price_page_confidence"], "HIGH")
        self.assertEqual(stat["search_index"]["live_validation"]["validated"], 1)

    def test_strong_mpn_and_high_live_price_promotes_candidate(self):
        module = self._module(html=self._high_html(), identity="mpn")
        guard.install(module)
        items, stat = module.scan_store({"loja": "CHIP7"}, {}, {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["mpn"], MPN)
        self.assertEqual(items[0]["preco"], 1299.99)
        self.assertEqual(stat["search_index"]["watchlist"][0]["price_status"], "LIVE_HIGH")

    def test_identity_mismatch_never_creates_candidate(self):
        module = self._module(html=self._high_html(), page_ean="1234567890123")
        guard.install(module)
        items, stat = module.scan_store({"loja": "PCDiga"}, {}, {})
        self.assertEqual(items, [])
        self.assertEqual(stat["search_index"]["watchlist"][0]["live_validation_status"], "identity_mismatch")

    def test_single_price_family_stays_index_only(self):
        html = '<html><head><meta property="product:price:amount" content="1299.99"></head></html>'
        module = self._module(html=html)
        guard.install(module)
        items, stat = module.scan_store({"loja": "PCDiga"}, {}, {})
        self.assertEqual(items, [])
        self.assertEqual(stat["search_index"]["watchlist"][0]["live_validation_status"], "price_not_high")

    def test_live_price_conflicting_with_index_hint_is_quarantined(self):
        module = self._module(html=self._high_html("1399.99"), hint=1299.99)
        guard.install(module)
        items, stat = module.scan_store({"loja": "PCDiga"}, {}, {})
        self.assertEqual(items, [])
        self.assertEqual(stat["search_index"]["watchlist"][0]["live_validation_status"], "index_hint_conflict")

    def test_blocked_page_does_not_promote(self):
        module = self._module(html="blocked", status_code=403)
        guard.install(module)
        items, stat = module.scan_store({"loja": "PCDiga"}, {}, {})
        self.assertEqual(items, [])
        self.assertEqual(stat["search_index"]["watchlist"][0]["live_validation_status"], "http_403")
        self.assertTrue(any(row[2] == "blocked" for row in module.learning))


if __name__ == "__main__":
    unittest.main()
