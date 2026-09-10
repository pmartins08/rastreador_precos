from __future__ import annotations

import types
import unittest

import sitemap_route_guard


class SitemapRouteGuardTests(unittest.TestCase):
    def _module(self):
        module = types.SimpleNamespace()
        module._SITEMAP_ROUTE_GUARD_INSTALLED = False
        children = [
            "https://shop.test/_/sitemap/aa.xml",
            "https://shop.test/_/sitemap/blog.xml",
            "https://shop.test/_/sitemap/informatica-2026.xml",
            "https://shop.test/_/sitemap/zz.xml",
        ]

        def base_parse(_content, _text, max_children=10):
            return [], sorted(children)[:max_children]

        module.sitemap_parse = base_parse

        def base_discover(cat, config, **kwargs):
            _urls, selected = module.sitemap_parse(b"", "", kwargs.get("max_sitemaps", 2))
            return selected

        module.discover_sitemap_urls = base_discover
        return module

    def test_configured_hint_can_promote_child_outside_original_cutoff(self):
        module = self._module()
        sitemap_route_guard.install(module)
        selected = module.discover_sitemap_urls(
            {
                "loja": "Worten",
                "url": "https://shop.test/laptops",
                "sitemap_child_hints": ["informatica", "portatil"],
                "sitemap_index_scan_limit": 20,
            },
            {},
            max_sitemaps=2,
        )
        self.assertEqual(selected[0], "https://shop.test/_/sitemap/informatica-2026.xml")
        self.assertEqual(len(selected), 2)

    def test_without_hints_preserves_base_parser_behavior(self):
        module = self._module()
        sitemap_route_guard.install(module)
        selected = module.discover_sitemap_urls(
            {"loja": "TEST", "url": "https://shop.test/laptops"},
            {},
            max_sitemaps=2,
        )
        self.assertEqual(
            selected,
            [
                "https://shop.test/_/sitemap/aa.xml",
                "https://shop.test/_/sitemap/blog.xml",
            ],
        )


if __name__ == "__main__":
    unittest.main()
