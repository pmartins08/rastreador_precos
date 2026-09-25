from __future__ import annotations

import types
import unittest

import sitemap_strategy_epoch_guard


class SitemapStrategyEpochGuardTests(unittest.TestCase):
    def _module(self):
        module = types.SimpleNamespace()
        module._SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED = False
        module.last_cat = None
        module._bucket = {
            "methods": {"sitemap": 11, "category": 20},
            "contexts": {
                "sitemap": {
                    "chrome131": {
                        "attempts": 6,
                        "successes": 0,
                        "blocks": 6,
                        "errors": 0,
                        "results": {},
                    }
                },
                "category": {
                    "chrome131": {
                        "attempts": 20,
                        "successes": 0,
                        "blocks": 20,
                        "errors": 0,
                        "results": {},
                    }
                },
            },
            "discovery": {
                "sitemap": {
                    "attempts": 8,
                    "requests": 8,
                    "new_candidates": 0,
                    "last_yield": 0.0,
                    "ema_yield": 0.0,
                    "last_updated": "2026-09-10T18:00:00Z",
                }
            },
        }
        module.bucket = lambda store: module._bucket

        def scan_store(cat, config, settings):
            module.last_cat = cat
            stats = module._bucket.setdefault("discovery", {}).setdefault("sitemap", {})
            stats["attempts"] = int(stats.get("attempts", 0)) + 1
            stats["new_candidates"] = int(stats.get("new_candidates", 0)) + 3
            return ([{"url": "https://example.test/p"}], {"candidatos": 1})

        module.scan_store = scan_store
        return module

    def test_new_strategy_archives_old_stats_and_starts_fresh(self):
        module = self._module()
        sitemap_strategy_epoch_guard.install(module)
        _items, stat = module.scan_store(
            {"loja": "Worten", "sitemap_strategy_version": "worten-index-hints-v2"}, {}, {}
        )
        active = module._bucket["discovery"]["sitemap"]
        archived = module._bucket["discovery_history"]["sitemap"]["legacy"]
        self.assertEqual(active["attempts"], 1)
        self.assertEqual(active["new_candidates"], 3)
        self.assertEqual(active["strategy_version"], "worten-index-hints-v3-reopen")
        self.assertEqual(archived["attempts"], 8)
        self.assertTrue(stat["sitemap_strategy_reset"])
        self.assertTrue(stat["sitemap_recovery_policy"])

    def test_new_strategy_reopens_blocked_sitemap_context_only(self):
        module = self._module()
        old_category_context = module._bucket["contexts"]["category"]
        sitemap_strategy_epoch_guard.install(module)

        module.scan_store({"loja": "PCDiga"}, {}, {})

        self.assertNotIn("sitemap", module._bucket["contexts"])
        self.assertNotIn("sitemap", module._bucket["methods"])
        self.assertIs(module._bucket["contexts"]["category"], old_category_context)
        archived = module._bucket["access_context_history"]["sitemap"]["legacy"]
        self.assertEqual(archived["method_attempts"], 11)
        self.assertEqual(archived["contexts"]["chrome131"]["blocks"], 6)

    def test_recovery_enables_pccomponentes_sitemap_and_public_route(self):
        module = self._module()
        sitemap_strategy_epoch_guard.install(module)
        module.scan_store(
            {
                "loja": "PcComponentes",
                "sitemap_enabled": False,
                "extra_discovery_urls": [],
            },
            {},
            {},
        )
        self.assertTrue(module.last_cat["sitemap_enabled"])
        self.assertEqual(
            module.last_cat["sitemap_strategy_version"],
            "pccomponentes-public-sitemap-v1",
        )
        self.assertGreaterEqual(module.last_cat["sitemap_probe_limit"], 6)
        urls = [route["url"] for route in module.last_cat["extra_discovery_urls"]]
        self.assertIn("https://www.pccomponentes.pt/categorias/portateis", urls)

    def test_recovery_adds_chip7_public_landing_without_duplicates(self):
        module = self._module()
        sitemap_strategy_epoch_guard.install(module)
        route = {
            "label": "landing_portateis_public",
            "url": "https://chip7.pt/landing/portateis",
        }
        module.scan_store(
            {"loja": "CHIP7", "extra_discovery_urls": [route]},
            {},
            {},
        )
        urls = [entry["url"] for entry in module.last_cat["extra_discovery_urls"]]
        self.assertEqual(urls.count("https://chip7.pt/landing/portateis"), 1)
        self.assertTrue(module.last_cat["sitemap_enabled"])

    def test_same_strategy_keeps_learning_and_access_context(self):
        module = self._module()
        version = "worten-index-hints-v3-reopen"
        module._bucket["discovery"]["sitemap"]["strategy_version"] = version
        sitemap_strategy_epoch_guard.install(module)
        module.scan_store({"loja": "Worten", "sitemap_strategy_version": version}, {}, {})
        self.assertEqual(module._bucket["discovery"]["sitemap"]["attempts"], 9)
        self.assertIn("sitemap", module._bucket["contexts"])
        self.assertEqual(module._bucket["methods"]["sitemap"], 11)
        self.assertNotIn("discovery_history", module._bucket)
        self.assertNotIn("access_context_history", module._bucket)

    def test_unconfigured_store_is_noop(self):
        module = self._module()
        sitemap_strategy_epoch_guard.install(module)
        module.scan_store({"loja": "Darty"}, {}, {})
        self.assertEqual(module._bucket["discovery"]["sitemap"]["attempts"], 9)
        self.assertIn("sitemap", module._bucket["contexts"])
        self.assertEqual(module._bucket["methods"]["sitemap"], 11)
        self.assertNotIn("discovery_history", module._bucket)
        self.assertNotIn("access_context_history", module._bucket)
        self.assertIs(module.last_cat["loja"], "Darty")


if __name__ == "__main__":
    unittest.main()
