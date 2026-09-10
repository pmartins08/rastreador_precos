from __future__ import annotations

import types
import unittest

import sitemap_strategy_epoch_guard


class SitemapStrategyEpochGuardTests(unittest.TestCase):
    def _module(self):
        module = types.SimpleNamespace()
        module._SITEMAP_STRATEGY_EPOCH_GUARD_INSTALLED = False
        module._bucket = {
            "discovery": {
                "sitemap": {
                    "attempts": 8,
                    "requests": 8,
                    "new_candidates": 0,
                    "last_yield": 0.0,
                    "ema_yield": 0.0,
                    "last_updated": "2026-09-10T18:00:00Z",
                }
            }
        }
        module.bucket = lambda store: module._bucket

        def scan_store(cat, config, settings):
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
        self.assertEqual(active["strategy_version"], "worten-index-hints-v2")
        self.assertEqual(archived["attempts"], 8)
        self.assertTrue(stat["sitemap_strategy_reset"])

    def test_same_strategy_keeps_learning(self):
        module = self._module()
        module._bucket["discovery"]["sitemap"]["strategy_version"] = "v2"
        sitemap_strategy_epoch_guard.install(module)
        module.scan_store({"loja": "Worten", "sitemap_strategy_version": "v2"}, {}, {})
        self.assertEqual(module._bucket["discovery"]["sitemap"]["attempts"], 9)
        self.assertNotIn("discovery_history", module._bucket)

    def test_unconfigured_store_is_noop(self):
        module = self._module()
        sitemap_strategy_epoch_guard.install(module)
        module.scan_store({"loja": "Darty"}, {}, {})
        self.assertEqual(module._bucket["discovery"]["sitemap"]["attempts"], 9)
        self.assertNotIn("discovery_history", module._bucket)


if __name__ == "__main__":
    unittest.main()
