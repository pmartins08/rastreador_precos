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
    def _module(self, offers, sitemap_urls=None, base_items=None):
        module = types.SimpleNamespace()
        module.scraper = _Scraper()
        module._offers = offers
        module._sitemap_urls = list(sitemap_urls or [])
        module._base_items = list(base_items or [])

        module.load_history = lambda: {"offers": {}}
        module.compact_history = lambda value: value
        module.latest_offer_by_url = lambda _history: dict(module._offers)
        module.discover_sitemap_urls = lambda *args, **kwargs: list(module._sitemap_urls)

        def base_scan(cat, config, settings):
            # Imita o ponto relevante do scan real: chama a função global já
            # embrulhada pelo guard e devolve apenas os probes live/itens base.
            urls = module.discover_sitemap_urls(cat, config, max_urls=80, max_sitemaps=8)
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

    def test_fresh_live_spec_removes_fallback_gate(self):
        module = self._module({})
        coverage_guard.install(module)
        assessment = module.score_allow_unknown(
            {"gpu_tipo": "dedicada", "gpu_modelo": "rtx 5050"}, 1199.0, {}, {}
        )
        self.assertEqual(assessment["status"], "ACEITE")


if __name__ == "__main__":
    unittest.main()
