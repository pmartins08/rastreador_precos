from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

import promotion_engine_v3 as engine


class FakeResponse:
    def __init__(self, text="", payload=None, status_code=200):
        self.text = text
        self._payload = payload
        self.status_code = status_code
        self.url = "https://darty.pt/"

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class PromotionEngineV3Tests(unittest.TestCase):
    def test_detects_campaign_even_without_numeric_discount(self):
        html = """
        <section>
          <h2>Lenovo Week</h2>
          <p>de 7 a 13 de setembro</p>
          <a href="/collections/campanha-lenovo">ver tudo</a>
        </section>
        """
        routes = engine.detect_campaign_routes(
            html,
            "https://darty.pt/pages/oportunidades",
            today=date(2026, 9, 13),
        )
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["url"], "https://darty.pt/collections/campanha-lenovo")
        self.assertEqual(routes[0]["active_from"], "2026-09-07")
        self.assertEqual(routes[0]["expires_at"], "2026-09-13")
        self.assertNotIn("promotion", routes[0])

    def test_expired_banner_is_not_returned(self):
        html = """
        <section>
          <h2>Lenovo Week</h2><p>de 7 a 13 de setembro</p>
          <a href="/collections/campanha-lenovo">ver tudo</a>
        </section>
        """
        routes = engine.detect_campaign_routes(
            html,
            "https://darty.pt/",
            today=date(2026, 9, 14),
        )
        self.assertEqual(routes, [])

    def test_numeric_rule_keeps_economics_and_inferred_dates(self):
        html = """
        <div>
          <strong>Ganha 50€ por cada 250€ em compras</strong>
          <span>de 12 a 15 de setembro</span>
          <a href="/collections/promocao-portateis">aproveitar promoção</a>
        </div>
        """
        route = engine.detect_campaign_routes(
            html,
            "https://loja.pt/",
            today=date(2026, 9, 13),
        )[0]
        promo = route["promotion"]
        self.assertEqual(promo["kind"], "TIERED_DISCOUNT")
        self.assertEqual(promo["step_discount_eur"], 50.0)
        self.assertEqual(promo["threshold_step_eur"], 250.0)
        self.assertEqual(promo["valid_from"], "2026-09-12")
        self.assertEqual(promo["valid_until"], "2026-09-15")

    def test_shopify_collection_json_url_is_generic(self):
        self.assertEqual(
            engine.shopify_collection_json_url("https://darty.pt/collections/campanha-lenovo"),
            "https://darty.pt/collections/campanha-lenovo/products.json?limit=250",
        )
        self.assertIsNone(engine.shopify_collection_json_url("https://darty.pt/pages/oportunidades"))

    def test_collection_membership_merges_without_weakening_price_confirmation(self):
        existing = [{
            "loja": "Darty",
            "titulo": "Portátil Lenovo",
            "preco": 999.99,
            "url": "https://darty.pt/products/portatil-lenovo",
            "discovery_sources": ["catalog_json"],
        }]
        rows = [{
            "loja": "Darty",
            "titulo": "Portátil Lenovo",
            "preco": 999.99,
            "url": "https://darty.pt/products/portatil-lenovo",
            "ean": "123",
            "discovery_sources": ["catalog_json"],
        }]
        verified = [{
            "kind": "DIRECT_DISCOUNT",
            "title": "100€ extra no carrinho",
            "value_eur": 100.0,
            "eligibility": "campaign_listing",
            "applicable": True,
            "live_verified": True,
        }]
        added = engine._merge_promoted_rows(
            existing,
            rows,
            {"url": "https://darty.pt/collections/campanha-lenovo", "label": "lenovo"},
            verified,
        )
        self.assertEqual(added, 0)
        self.assertEqual(len(existing), 1)
        self.assertIn("promocao", existing[0]["discovery_sources"])
        self.assertTrue(existing[0]["promotion_listing_live_confirmed"])
        self.assertNotIn("promotion_price_live_confirmed", existing[0])
        self.assertEqual(existing[0]["ean"], "123")

    def test_engine_hands_dynamic_routes_to_v2_without_duplicate_watch(self):
        watch_html = """
        <section><h2>Lenovo Week</h2><p>de 7 a 13 de setembro</p>
        <a href="/collections/campanha-lenovo">ver tudo</a></section>
        """
        calls = []
        received_cat = {}

        class Tracker:
            pass

        tracker = Tracker()
        tracker._PROMOTION_ENGINE_V3_INSTALLED = False
        tracker.scraper = SimpleNamespace(eligible=lambda title: True, parse_price_value=lambda value: float(value))
        tracker.gtin_valid = lambda value: True
        tracker.budget_available = lambda store: True

        def adaptive_fetch(url, config, timeout_s=8.0, *, store=None, method="page", **kwargs):
            calls.append((url, method))
            return FakeResponse(watch_html), "p", "http_success"

        def base_scan(cat, config, settings):
            received_cat.update(cat)
            return [], {"candidatos": 0}

        tracker.adaptive_fetch = adaptive_fetch
        tracker.scan_store = base_scan
        engine.install(tracker)
        cat = {
            "loja": "Darty",
            "url": "https://darty.pt/collections/portateis",
            "promotion_watch_urls": ["https://darty.pt/pages/oportunidades"],
        }
        tracker.scan_store(cat, {}, {})

        self.assertEqual(len(calls), 1)
        self.assertEqual(received_cat["promotion_watch_urls"], [])
        self.assertEqual(len(received_cat["campaign_urls"]), 1)
        self.assertEqual(
            received_cat["campaign_urls"][0]["url"],
            "https://darty.pt/collections/campanha-lenovo",
        )

    def test_real_runtime_keeps_promo_engine_and_historical_price_guard(self):
        import runner

        self.assertTrue(getattr(runner.tracker, "_PROMOTION_ENGINE_V3_INSTALLED", False))
        self.assertTrue(getattr(runner.tracker, "_PRICE_CHANGE_PRIORITY_GUARD_INSTALLED", False))


if __name__ == "__main__":
    unittest.main()
