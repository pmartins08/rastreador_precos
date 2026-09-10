from __future__ import annotations

import types
import unittest
from datetime import datetime, timedelta, timezone

import coverage_guard


class _Scraper:
    @staticmethod
    def eligible(title):
        return "asus" in str(title).lower() or "lenovo" in str(title).lower() or "hp" in str(title).lower()


class CoverageGuardTests(unittest.TestCase):
    def _module(self, offers, sitemap_urls=None, base_items=None, discovery=None, routes=None):
        module = types.SimpleNamespace()
        module.scraper = _Scraper()
        module._offers = offers
        module._sitemap_urls = list(sitemap_urls or [])
        module._base_items = list(base_items or [])
        module._discovery = dict(discovery or {})
        module._routes = list(routes or [])
        module._last_scan_cat = None

        module.load_history = lambda: {"offers": {}}
        module.compact_history = lambda value: value
        module.latest_offer_by_url = lambda _history: dict(module._offers)
        module.discover_sitemap_urls = lambda *args, **kwargs: list(module._sitemap_urls)
        module.discovery_routes = lambda cat, store: [dict(route) for route in module._routes]
        module.bucket = lambda store: {"discovery": module._discovery}
        module.candidate_priority = lambda item, weights, settings: 50.0

        def base_scan(cat, config, settings):
            module._last_scan_cat = dict(cat)
            urls = (
                module.discover_sitemap_urls(cat, config, max_urls=80, max_sitemaps=8)
                if cat.get("sitemap_enabled", True)
                else []
            )
            items = list(module._base_items)
            for url in urls:
                items.append(
                    {
                        "loja": cat["loja"],
                        "titulo": "ASUS produto novo",
                        "preco": 999.0,
                        "url": url,
                        "stock": True,
                    }
                )
            return items, {
                "candidatos": len(items),
                "bloqueada": not bool(items),
                "sitemap_urls": len(urls),
                "fontes_descoberta": {"sitemap": len(urls)},
            }

        module.scan_store = base_scan
        module.needs_price_refresh = lambda previous, item, settings, **kwargs: False
        module.select_with_cache = lambda items, spec_cache, max_items, weights, settings: list(items)[:max_items]
        module.score_allow_unknown = lambda spec, price, weights, settings: {"status": "ACEITE"}
        return module

    def test_known_sitemap_url_is_reused_without_becoming_live_probe(self):
        now = datetime.now(timezone.utc)
        known_url = "https://shop.test/asus-known.html"
        new_url = "https://shop.test/asus-new.html"
        offers = {
            known_url: {
                "timestamp": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                "loja": "Darty",
                "titulo": "ASUS TUF conhecido",
                "price": 1099.0,
                "stock": True,
                "url": known_url,
                "ean": "12345678",
            }
        }
        module = self._module(offers, [known_url, new_url])
        coverage_guard.install(module)

        items, stat = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://shop.test/laptops",
                "sitemap_new_probe_limit": 3,
                "sitemap_cache_reuse_limit": 10,
                "sitemap_cache_price_ttl_hours": 7,
            },
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )

        by_url = {item["url"]: item for item in items}
        self.assertEqual(set(by_url), {known_url, new_url})
        self.assertEqual(by_url[known_url]["detail_source"], "coverage_cache_seed")
        self.assertFalse(by_url[known_url]["_coverage_force_live_price"])
        self.assertEqual(stat["fontes_descoberta"]["sitemap_cache"], 1)
        self.assertEqual(stat["sitemap_urls"], 2)

    def test_sitemap_cache_matches_equivalent_url_without_query(self):
        now = datetime.now(timezone.utc)
        historical_url = "https://darty.pt/products/portatil-asus-tuf?variant=123&utm_source=x"
        sitemap_url = "https://www.darty.pt/products/portatil-asus-tuf"
        offers = {
            historical_url: {
                "timestamp": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                "loja": "Darty",
                "titulo": "ASUS TUF conhecido",
                "price": 1099.0,
                "stock": True,
                "url": historical_url,
            }
        }
        module = self._module(offers, [sitemap_url])
        coverage_guard.install(module)
        items, stat = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://darty.pt/collections/portateis",
                "sitemap_new_probe_limit": 5,
                "sitemap_cache_reuse_limit": 10,
                "sitemap_cache_price_ttl_hours": 7,
            },
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["detail_source"], "coverage_cache_seed")
        self.assertEqual(stat["fontes_descoberta"]["sitemap"], 0)
        self.assertEqual(stat["fontes_descoberta"]["sitemap_cache"], 1)

    def test_stale_sitemap_cache_requires_live_confirmation(self):
        now = datetime.now(timezone.utc)
        url = "https://shop.test/asus-stale.html"
        offers = {
            url: {
                "timestamp": (now - timedelta(hours=12)).isoformat().replace("+00:00", "Z"),
                "loja": "Darty",
                "titulo": "ASUS TUF stale",
                "price": 999.0,
                "stock": True,
                "url": url,
            }
        }
        module = self._module(offers, [url])
        coverage_guard.install(module)
        items, _ = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://shop.test/laptops",
                "sitemap_new_probe_limit": 0,
                "sitemap_cache_price_ttl_hours": 7,
            },
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )
        self.assertTrue(items[0]["_coverage_force_live_price"])
        self.assertTrue(module.needs_price_refresh({}, items[0], {}))

    def test_history_fallback_is_never_ranked_without_live_refresh(self):
        now = datetime.now(timezone.utc)
        url = "https://shop.test/asus-history.html"
        offers = {
            url: {
                "timestamp": (now - timedelta(hours=6)).isoformat().replace("+00:00", "Z"),
                "loja": "PCDiga",
                "titulo": "ASUS TUF histórico",
                "price": 1199.0,
                "value_score": 116.0,
                "stock": True,
                "url": url,
            }
        }
        module = self._module(offers, [])
        coverage_guard.install(module)
        items, stat = module.scan_store(
            {
                "loja": "PCDiga",
                "url": "https://shop.test/laptops",
                "history_fallback_below": 4,
                "history_fallback_limit": 2,
                "history_fallback_max_age_hours": 36,
            },
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["_coverage_force_live_price"])
        self.assertEqual(stat["fontes_descoberta"]["historico"], 1)

        spec_cache = {url: {"gpu_tipo": "dedicada", "gpu_modelo": "rtx 5050"}}
        module.select_with_cache(items, spec_cache, 10, {}, {})
        self.assertTrue(spec_cache[url]["_coverage_force_live_price"])
        assessment = module.score_allow_unknown(spec_cache[url], 1199.0, {}, {})
        self.assertEqual(assessment["status"], "REJEITADO")

    def test_forced_history_refresh_gets_priority_bonus(self):
        module = self._module({})
        coverage_guard.install(module)
        regular = module.candidate_priority({"preco": 999.0}, {}, {})
        forced = module.candidate_priority(
            {"preco": 999.0, "_coverage_force_live_price": True}, {}, {}
        )
        self.assertEqual(regular, 50.0)
        self.assertEqual(forced, 300.0)

    def test_fresh_live_spec_removes_fallback_gate(self):
        module = self._module({})
        coverage_guard.install(module)
        assessment = module.score_allow_unknown(
            {"gpu_tipo": "dedicada", "gpu_modelo": "rtx 5050"}, 1199.0, {}, {}
        )
        self.assertEqual(assessment["status"], "ACEITE")

    def test_zero_yield_route_enters_temporary_cooldown(self):
        now = datetime.now(timezone.utc)
        discovery = {
            "segment:dead": {
                "attempts": 10,
                "new_candidates": 0,
                "last_updated": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            },
            "segment:good": {
                "attempts": 10,
                "new_candidates": 20,
                "last_updated": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            },
        }
        routes = [
            {"label": "dead", "method_key": "segment:dead", "url": "https://dead"},
            {"label": "good", "method_key": "segment:good", "url": "https://good"},
        ]
        module = self._module({}, discovery=discovery, routes=routes)
        coverage_guard.install(module)
        filtered = module.discovery_routes({}, "TEST")
        self.assertEqual([route["label"] for route in filtered], ["good"])

    def test_zero_yield_route_returns_after_cooldown(self):
        now = datetime.now(timezone.utc)
        discovery = {
            "segment:dead": {
                "attempts": 10,
                "new_candidates": 0,
                "last_updated": (now - timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
            }
        }
        routes = [{"label": "dead", "method_key": "segment:dead", "url": "https://dead"}]
        module = self._module({}, discovery=discovery, routes=routes)
        coverage_guard.install(module)
        self.assertEqual(len(module.discovery_routes({}, "TEST")), 1)

    def test_zero_yield_pagination_is_temporarily_reduced_to_first_page(self):
        now = datetime.now(timezone.utc)
        discovery = {
            "pagination": {
                "attempts": 20,
                "new_candidates": 0,
                "last_updated": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        }
        module = self._module({}, discovery=discovery)
        coverage_guard.install(module)
        module.scan_store(
            {"loja": "CHIP7", "url": "https://shop.test/laptops", "max_category_pages": 4},
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )
        self.assertEqual(module._last_scan_cat["max_category_pages"], 1)

    def test_adaptive_sitemap_probe_rises_from_5_to_10_on_high_yield(self):
        discovery = {
            "sitemap": {
                "attempts": 13,
                "new_candidates": 340,
                "last_yield": 0.7692,
                "ema_yield": 0.7692,
            }
        }
        urls = [f"https://darty.test/products/asus-{index}" for index in range(20)]
        module = self._module({}, sitemap_urls=urls, discovery=discovery)
        coverage_guard.install(module)
        items, stat = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://darty.test/collections/portateis",
                "sitemap_new_probe_limit": 5,
                "sitemap_probe_steps": [5, 10, 15],
                "sitemap_probe_yield_threshold": 0.60,
            },
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )
        self.assertEqual(module._last_scan_cat["sitemap_new_probe_limit"], 10)
        self.assertEqual(len(items), 10)
        self.assertEqual(stat["sitemap_probe_limit_used"], 10)
        self.assertEqual(module._discovery["sitemap"]["adaptive_probe_limit"], 10)

    def test_adaptive_sitemap_probe_requires_recent_and_ema_yield(self):
        discovery = {
            "sitemap": {
                "attempts": 8,
                "new_candidates": 30,
                "last_yield": 0.55,
                "ema_yield": 0.72,
            }
        }
        urls = [f"https://darty.test/products/asus-{index}" for index in range(20)]
        module = self._module({}, sitemap_urls=urls, discovery=discovery)
        coverage_guard.install(module)
        items, stat = module.scan_store(
            {
                "loja": "Darty",
                "url": "https://darty.test/collections/portateis",
                "sitemap_new_probe_limit": 5,
                "sitemap_probe_steps": [5, 10, 15],
                "sitemap_probe_yield_threshold": 0.60,
            },
            {},
            {"preco_minimo_global": 250, "budget_hard": 1500},
        )
        self.assertEqual(module._last_scan_cat["sitemap_new_probe_limit"], 5)
        self.assertEqual(len(items), 5)
        self.assertEqual(stat["sitemap_probe_limit_used"], 5)

    def test_adaptive_sitemap_probe_rises_only_one_step_per_run(self):
        discovery = {
            "sitemap": {
                "attempts": 14,
                "new_candidates": 350,
                "last_yield": 0.80,
                "ema_yield": 0.75,
                "adaptive_probe_limit": 10,
            }
        }
        self.assertEqual(
            coverage_guard._adaptive_sitemap_probe_limit(
                {
                    "sitemap_new_probe_limit": 5,
                    "sitemap_probe_steps": [5, 10, 15],
                    "sitemap_probe_yield_threshold": 0.60,
                },
                discovery["sitemap"],
            ),
            15,
        )


if __name__ == "__main__":
    unittest.main()
