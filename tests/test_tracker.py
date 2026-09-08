import copy
import json
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

import scraper
import tracker


class BrainRegressionTests(unittest.TestCase):
    @staticmethod
    def page(rows):
        html = "<table>" + "".join(
            f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in rows
        ) + "</table>"
        return BeautifulSoup(html, "html.parser")

    def test_portuguese_prices_with_thousands(self):
        self.assertEqual(scraper.parse_price_value("1.399 €"), 1399.0)
        self.assertEqual(scraper.parse_price_value("1.399,99 €"), 1399.99)
        self.assertEqual(scraper.parse_price_value("1 399,99 €"), 1399.99)
        self.assertEqual(scraper.prices("Agora 1.399,99 €"), [1399.99])

    def test_subbrand_without_parent_brand(self):
        self.assertEqual(scraper.brand("ROG Zephyrus G16")[0], "asus")
        self.assertEqual(scraper.brand("Legion 5 Gen 10")[0], "lenovo")
        self.assertEqual(scraper.brand("OMEN Gaming 16")[0], "hp")
        self.assertTrue(scraper.eligible("ROG Zephyrus G16 RTX 5070"))
        self.assertFalse(scraper.eligible("ROG Zephyrus G16 recondicionado"))

    def test_cpu_real_world_shorthand(self):
        self.assertEqual(scraper.cpu("Intel Core i7-1255U")[1:], ("tier_2", "u_ultra"))
        self.assertEqual(scraper.cpu("Intel Core 7 240H")[1:], ("tier_2", "h"))
        self.assertEqual(scraper.cpu("Ultra 7 255U")[1:], ("tier_2", "u_ultra"))
        self.assertEqual(scraper.cpu("AMD R7 7445HS")[1:], ("tier_2", "hs"))
        self.assertEqual(scraper.cpu("Intel i9-14900HX")[1:], ("tier_1", "hx"))

    def test_rtx_30_series_is_recognized(self):
        models, gpu_type, model = scraper.gpus("NVIDIA GeForce RTX 3050 Laptop GPU")
        self.assertEqual(gpu_type, "dedicada")
        self.assertEqual(model, "rtx 3050")
        self.assertIn("rtx 3050", models)

    def test_integrated_gpu_stays_integrated(self):
        result = scraper.extract(
            "ASUS Zenbook Ryzen AI 7 445 32GB 1TB AMD Radeon Graphics",
            self.page([("Placa gráfica", "AMD Radeon Graphics")]),
        )
        self.assertIsNone(result["gpu_modelo"])
        self.assertEqual(result["gpu_tipo"], "integrada")

    def test_ram_never_becomes_vram(self):
        spec = scraper.specs("ASUS TUF F16 RTX 5070 32GB DDR5 1TB SSD")
        self.assertIsNone(spec["vram_gb"])
        spec = scraper.specs("ASUS TUF F16 RTX 5070 8 GB GDDR7")
        self.assertEqual(spec["vram_gb"], 8)

    def test_tgp_requires_tgp_context_in_title(self):
        self.assertIsNone(scraper.specs("ASUS TUF 90W charger RTX 5060")["tgp_w"])
        self.assertEqual(scraper.specs("ASUS TUF RTX 5060 TGP 115W")["tgp_w"], 115)

    def test_screen_pair_can_supply_resolution(self):
        result = scraper.extract(
            "Lenovo LOQ 15 R7 7445HS 16GB 512GB RTX 3050 144Hz",
            self.page([("Ecrã", "15.6 Full-HD (1920 x 1080) 144 Hz")]),
        )
        self.assertEqual(result["ecra_res"], "fhd")
        self.assertEqual(result["ecra_hz"], 144)

    def test_m2_does_not_automatically_mean_expandable(self):
        one = scraper.extract("ASUS Vivobook 16GB 1TB", self.page([("M.2", "1 x M.2 2280")]))
        two = scraper.extract("ASUS Vivobook 16GB 1TB", self.page([("Slots M.2", "2 x M.2 2280")]))
        self.assertFalse(one["ssd_expansivel"])
        self.assertTrue(two["ssd_expansivel"])

    def test_jsonld_offer_list(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "ASUS TUF Gaming A16",
            "url": "https://example.com/asus-tuf",
            "offers": [
                {
                    "@type": "Offer",
                    "price": "1.299,99",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }
        soup = BeautifulSoup(
            f'<script type="application/ld+json">{json.dumps(payload)}</script>',
            "html.parser",
        )
        result = scraper.jsonld_products(soup)
        self.assertEqual(result[0]["preco"], 1299.99)
        self.assertTrue(result[0]["stock"])


    def test_jsonld_carries_strong_identifiers(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "ASUS TUF Gaming A16 RTX 5060",
            "url": "https://example.com/tuf",
            "sku": "FA608UM-RV001W",
            "mpn": "90NR0KV1-M00000",
            "gtin13": "4711000000000",
            "offers": {"@type": "Offer", "price": "1499,99"},
        }
        soup = BeautifulSoup(
            f'<script type="application/ld+json">{json.dumps(payload)}</script>',
            "html.parser",
        )
        row = scraper.jsonld_products(soup)[0]
        self.assertEqual(row["sku"], "FA608UM-RV001W")
        self.assertEqual(row["mpn"], "90NR0KV1-M00000")
        self.assertEqual(row["ean"], "4711000000000")

    def test_card_ignores_monthly_installment(self):
        html = """
        <article>
          <h3>ASUS TUF Gaming A16 RTX 5070</h3>
          <a href="/portatil-asus-tuf-a16">Produto</a>
          <span class="price-month">49,99 € / mês</span>
          <span class="price-current">1.299,99 €</span>
        </article>
        """
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(
            card,
            "https://example.com/laptops",
            {"loja": "TEST", "product_path_hints": ["/portatil-asus-"]},
        )
        self.assertEqual(item["preco"], 1299.99)

    def test_value_score_regression(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        self.assertEqual(scraper.value_score(100, 1300, settings), 136.0)
        self.assertEqual(scraper.value_score(75, 1300, settings), 113.2)
        self.assertEqual(scraper.tier_from_value(130, {}), "DIAMANTE")
        self.assertEqual(scraper.tier_from_value(125, {"diamante_value_min": 125}), "DIAMANTE")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.learning = copy.deepcopy(tracker.LEARNING)
        self.requests_used = tracker.REQUESTS_USED
        self.requests_by_store = tracker.REQUESTS_BY_STORE
        self.detail_fetches = tracker.DETAIL_FETCHES_USED
        self.max_requests = tracker.MAX_REQUESTS
        self.max_requests_store = tracker.MAX_REQUESTS_PER_STORE
        self.max_detail = tracker.MAX_DETAIL_FETCHES
        self.deadline = tracker.RUN_DEADLINE
        tracker.LEARNING = {"schema_version": 2, "stores": {}}
        tracker.REQUESTS_USED = 0
        tracker.REQUESTS_BY_STORE = {}
        tracker.DETAIL_FETCHES_USED = 0
        tracker.MAX_REQUESTS = 100
        tracker.MAX_REQUESTS_PER_STORE = 20
        tracker.MAX_DETAIL_FETCHES = 10
        tracker.RUN_DEADLINE = 0

    def tearDown(self):
        tracker.LEARNING = self.learning
        tracker.REQUESTS_USED = self.requests_used
        tracker.REQUESTS_BY_STORE = self.requests_by_store
        tracker.DETAIL_FETCHES_USED = self.detail_fetches
        tracker.MAX_REQUESTS = self.max_requests
        tracker.MAX_REQUESTS_PER_STORE = self.max_requests_store
        tracker.MAX_DETAIL_FETCHES = self.max_detail
        tracker.RUN_DEADLINE = self.deadline

    def test_profile_order_uses_store_history(self):
        b = tracker.bucket("PCDiga")
        b["profiles"] = {
            "chrome131": {"attempts": 10, "successes": 0, "blocks": 10, "errors": 0},
            "safari17_0": {"attempts": 20, "successes": 18, "blocks": 1, "errors": 1},
            "firefox147": {"attempts": 5, "successes": 5, "blocks": 0, "errors": 0},
        }
        order = tracker.profile_order("PCDiga", "category")
        self.assertIn(order[0], {"safari17_0", "firefox147"})
        self.assertNotEqual(order[0], "chrome131")
        self.assertEqual(len(order), len(set(order)))
        self.assertLessEqual(len(order), 3)

    def test_persistent_block_enters_probe_mode(self):
        b = tracker.bucket("BLOCK")
        b["attempts"] = 40
        b["blocks"] = 40
        b["successes"] = 0
        b["contexts"]["category"] = {"chrome131": {"attempts": 12, "successes": 0, "blocks": 12, "errors": 0}}
        for profile in tracker.PROFILES:
            b["profiles"][profile] = {"attempts": 5, "successes": 0, "blocks": 5, "errors": 0}
        self.assertEqual(tracker.access_mode("BLOCK", "category"), "probe")
        self.assertEqual(len(tracker.profile_order("BLOCK", "category")), 1)

    def test_request_and_detail_budgets(self):
        tracker.MAX_REQUESTS_PER_STORE = 2
        self.assertTrue(tracker.consume_request("A"))
        self.assertTrue(tracker.consume_request("A"))
        self.assertFalse(tracker.consume_request("A"))
        tracker.MAX_DETAIL_FETCHES = 2
        self.assertTrue(tracker.reserve_detail_slot())
        self.assertTrue(tracker.reserve_detail_slot())
        self.assertFalse(tracker.reserve_detail_slot())

    def test_network_exception_is_contained(self):
        cfg = {"category_urls": [{"loja": "TEST", "url": "https://example.com/laptops"}]}
        with patch.object(tracker.requests, "get", side_effect=RuntimeError("boom")), patch.object(
            tracker.time, "sleep", return_value=None
        ):
            response, profile, outcome = tracker.adaptive_fetch(
                "https://example.com/laptops", cfg, 0.1, store="TEST", method="category"
            )
        self.assertIsNone(response)
        self.assertIsNotNone(profile)
        self.assertEqual(outcome, "request_error")
        self.assertGreater(tracker.bucket("TEST")["errors"].get("request_error", 0), 0)

    def test_pagination_links_are_discovered(self):
        html = """
        <nav class="pagination">
          <a href="?page=2">2</a>
          <a href="?page=3">3</a>
          <a rel="next" href="?page=2">Seguinte</a>
        </nav>
        """
        urls = tracker.pagination_urls(
            html,
            "https://example.com/laptops",
            "https://example.com/laptops",
            4,
        )
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].endswith("?page=2"))

    def test_sitemap_filter_prioritizes_real_product_url(self):
        cat = {
            "url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop",
            "product_path_hints": ["/portatil-asus-", "/portatil-lenovo-", "/portatil-hp-"],
        }
        self.assertTrue(
            tracker._looks_like_product_url(
                "https://www.pcdiga.com/portatil-lenovo-legion-5-abc", cat
            )
        )
        self.assertFalse(
            tracker._looks_like_product_url(
                "https://www.pcdiga.com/computadores-e-software/computadores-laptop", cat
            )
        )

    def test_selection_is_store_balanced(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        weights = {"gpu_base": {}, "cpu_base": {}}
        items = []
        for store in ("A", "B"):
            for index in range(10):
                items.append(
                    {
                        "loja": store,
                        "url": f"https://{store.lower()}/{index}",
                        "titulo": f"ASUS Vivobook Core i7-13620H 16GB 1TB {index}",
                        "preco": 700 + index,
                    }
                )
        selected = tracker.select_for_evaluation(items, 8, weights, settings)
        counts = {store: sum(row["loja"] == store for row in selected) for store in ("A", "B")}
        self.assertGreaterEqual(counts["A"], 2)
        self.assertGreaterEqual(counts["B"], 2)
        self.assertEqual(len(selected), 8)

    def test_hardware_priority_beats_cheap_integrated(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        weights = {
            "gpu_base": {"rtx 5070": 95},
            "cpu_base": {"tier_1": 100, "tier_2": 85, "tier_3": 70},
        }
        strong = {
            "loja": "A",
            "url": "https://a/1",
            "titulo": "ASUS TUF Core 7 240H 32GB 1TB RTX 5070",
            "preco": 1399,
        }
        cheap = {
            "loja": "A",
            "url": "https://a/2",
            "titulo": "ASUS Vivobook Core i7-1255U 16GB 512GB Intel Graphics",
            "preco": 699,
        }
        self.assertGreater(
            tracker.candidate_priority(strong, weights, settings),
            tracker.candidate_priority(cheap, weights, settings),
        )

    def test_cache_reuses_compatible_v86_entries(self):
        history = {
            "offers": {
                "old": [{"url": "https://x/old", "tracker_version": "8.4", "specs": {"ram_gb": 16}}],
                "new": [{"url": "https://x/new", "tracker_version": "8.6", "specs": {"ram_gb": 32}}],
            }
        }
        cache = tracker.latest_specs_by_url(history)
        self.assertNotIn("https://x/old", cache)
        self.assertEqual(cache["https://x/new"]["ram_gb"], 32)


    def test_configuration_signature_separates_same_family_variants(self):
        base = {
            "loja": "ASUS",
            "url": "https://example.com/tuf-a16",
            "titulo": "ASUS TUF Gaming A16",
        }
        spec_5050 = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 512GB RTX 5050")
        spec_5070 = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5070")
        self.assertNotEqual(
            tracker.configuration_signature(base, spec_5050),
            tracker.configuration_signature(base, spec_5070),
        )

    def test_configuration_signature_prefers_strongest_identifier(self):
        left = {"titulo": "ASUS TUF Gaming A16", "sku": "STORE-1", "mpn": "90NR0KS1-M00730", "ean": "4711636176743"}
        right = {"titulo": "TUF A16 promoção", "sku": "STORE-2", "mpn": "90NR0KS1-M00730", "ean": "4711636176743"}
        self.assertEqual(
            tracker.configuration_signature(left, {}),
            tracker.configuration_signature(right, {}),
        )
        self.assertTrue(tracker.configuration_signature(left, {}).startswith("ean:"))

    def test_compact_history_keeps_compatible_v86(self):
        history = tracker._history_base()
        history["offers"] = {
            "legacy": [{"url": "https://x/old", "tracker_version": "8.4", "timestamp": "2026-01-01T00:00:00Z"}],
            "new": [
                {"url": "https://x/new", "tracker_version": "8.6", "timestamp": "2026-01-01T00:00:00Z"},
                {"url": "https://x/new", "tracker_version": "8.6", "timestamp": "2026-01-02T00:00:00Z"},
            ],
        }
        history["alert_state"] = {
            "https://x/old": {"timestamp": "2026-01-01T00:00:00Z"},
            "https://x/new": {"timestamp": "2026-01-02T00:00:00Z"},
        }
        compact = tracker.compact_history(history, entries_per_url=1)
        self.assertNotIn("https://x/old", compact["offers"])
        self.assertEqual(len(compact["offers"]["https://x/new"]), 1)
        self.assertEqual(set(compact["alert_state"]), {"https://x/new"})

    def test_select_with_cache_keeps_cached_and_prioritizes_new(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        weights = {"gpu_base": {"rtx 5070": 95}, "cpu_base": {"tier_2": 85}}
        items = [
            {"loja": "A", "url": "https://a/cached", "titulo": "ASUS Vivobook Core i7-1255U 16GB 512GB", "preco": 700},
            {"loja": "A", "url": "https://a/strong", "titulo": "ASUS TUF Core 7 240H 32GB 1TB RTX 5070", "preco": 1399},
            {"loja": "A", "url": "https://a/weak", "titulo": "ASUS Vivobook Core i7-1255U 16GB 512GB", "preco": 799},
        ]
        selected = tracker.select_with_cache(
            items, {"https://a/cached": {"ram_gb": 16}}, 2, weights, settings
        )
        self.assertEqual(selected[0]["url"], "https://a/cached")
        self.assertEqual(selected[1]["url"], "https://a/strong")

    def test_unknown_keyboard_wrapper_is_accepted(self):
        spec = scraper.specs("ASUS TUF Core 7 240H 16GB 1TB RTX 5060")
        result = tracker.score_allow_unknown(
            spec,
            1199,
            {"gpu_base": {"rtx 5060": 85}, "cpu_base": {"tier_2": 85}},
            {"budget_soft": 1300, "budget_hard": 1500},
        )
        self.assertEqual(result["status"], "ACEITE")

    def test_heartbeat_is_independent_message(self):
        run = {
            "stores": {"A": {"bloqueada": False}, "B": {"bloqueada": True}},
            "total_candidates": 20,
            "total_evaluated": 15,
            "total_accepted": 12,
            "detail_fetches": 10,
            "cache_reused": 5,
            "access_requests": 30,
            "runtime_seconds": 45.0,
            "tiers": {"DIAMANTE": 0, "OURO": 1, "PRATA": 5, "BRONZE": 6},
        }
        with patch.object(tracker, "ntfy_send", return_value=True) as send:
            self.assertTrue(tracker.send_heartbeat(run))
        args, kwargs = send.call_args
        self.assertIn("Heartbeat", args[0])
        self.assertIn("Descobertos: 20", args[1])
        self.assertEqual(kwargs["priority"], 2)

    def test_merge_history_preserves_two_runs(self):
        left = tracker._history_base()
        right = tracker._history_base()
        left["offers"] = {
            "https://x/1": [{"timestamp": "2026-01-01T00:00:00Z", "tracker_version": "8.6", "url": "https://x/1", "price": 1000}]
        }
        right["offers"] = {
            "https://x/1": [{"timestamp": "2026-01-02T00:00:00Z", "tracker_version": "8.6", "url": "https://x/1", "price": 900}]
        }
        merged = tracker.merge_history(left, right)
        self.assertEqual(len(merged["offers"]["https://x/1"]), 2)
        self.assertEqual(merged["offers"]["https://x/1"][-1]["price"], 900)

    def test_sitemap_parser_handles_index_and_urlset(self):
        index = b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://x/product-sitemap.xml</loc></sitemap></sitemapindex>'
        urls, children = tracker.sitemap_parse(index, index.decode())
        self.assertEqual(urls, [])
        self.assertEqual(children, ["https://x/product-sitemap.xml"])
        urlset = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x/item</loc></url></urlset>'
        urls, children = tracker.sitemap_parse(urlset, urlset.decode())
        self.assertEqual(urls, ["https://x/item"])
        self.assertEqual(children, [])

    def test_discovery_yield_orders_productive_routes_first(self):
        tracker.record_discovery_yield("YIELD", "segment:good", 2, 12)
        tracker.record_discovery_yield("YIELD", "segment:bad", 2, 0)
        routes = tracker.discovery_routes(
            {"extra_discovery_urls": [
                {"label": "bad", "url": "https://x/bad"},
                {"label": "good", "url": "https://x/good"},
            ]},
            "YIELD",
        )
        self.assertEqual(routes[0]["label"], "good")
        self.assertGreater(tracker.discovery_score("YIELD", "segment:good"), tracker.discovery_score("YIELD", "segment:bad"))

    def test_blocked_primary_can_use_public_fallback_route(self):
        blocked = type("Resp", (), {"status_code": 403, "text": "", "headers": {}})()
        html = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"ASUS TUF Gaming A16 RTX 5060 32GB 1TB","url":"https://example.com/asus-tuf-a16","offers":{"@type":"Offer","price":"1199.00","availability":"https://schema.org/InStock"}}</script>'
        ok = type("Resp", (), {"status_code": 200, "text": html, "headers": {"Content-Type": "text/html"}})()

        def fake_fetch(url, *_args, **_kwargs):
            if url.endswith("/primary"):
                return blocked, "chrome131", "http_403"
            return ok, "firefox147", "http_success"

        cat = {
            "loja": "TEST",
            "url": "https://example.com/primary",
            "target_candidates": 10,
            "sitemap_enabled": False,
            "product_path_hints": ["/asus-"],
            "extra_discovery_urls": [{"label": "asus", "url": "https://example.com/asus"}],
        }
        with patch.object(tracker, "adaptive_fetch", side_effect=fake_fetch):
            items, stat = tracker.scan_store(cat, {"category_urls": [cat]}, {"max_category_pages": 1})
        self.assertEqual(len(items), 1)
        self.assertFalse(stat["bloqueada"])

    def test_page_identifiers_validate_ean_and_part_number(self):
        soup = BeautifulSoup("<div>Part-Number: 83JE01KTPG Código EAN: 199276826244</div>", "html.parser")
        ids = tracker.page_identifiers(soup)
        self.assertEqual(ids["mpn"], "83JE01KTPG")
        self.assertEqual(ids["ean"], "199276826244")

    def test_matching_exact_by_ean(self):
        left_item = {"loja": "A", "titulo": "ASUS TUF A16", "ean": "4711636176743"}
        right_item = {"loja": "B", "titulo": "ASUS TUF A16 outra descrição", "ean": "4711636176743"}
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050 165Hz")
        self.assertEqual(tracker.match_configurations(left_item, spec, right_item, spec)["level"], "EXATO")

    def test_matching_never_merges_same_family_with_different_gpu_or_ssd(self):
        left_item = {"loja": "A", "titulo": "ASUS TUF Gaming A16 FA608UH-R72B55CS2"}
        right_item = {"loja": "B", "titulo": "ASUS TUF Gaming A16 FA608UH-R72B55CS2"}
        left_spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 512GB RTX 5050")
        right_spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5070")
        result = tracker.match_configurations(left_item, left_spec, right_item, right_spec)
        self.assertEqual(result["level"], "NAO_FUNDIR")

    def test_matching_strong_requires_model_code_and_core_configuration(self):
        left_item = {"loja": "A", "titulo": "ASUS TUF Gaming A16 FA608UH-R72B55CS2"}
        right_item = {"loja": "B", "titulo": "Portátil ASUS FA608UH-R72B55CS2 promoção"}
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        result = tracker.match_configurations(left_item, spec, right_item, spec)
        self.assertEqual(result["level"], "FORTE")

    def test_cross_store_groups_choose_cheapest_exact_offer(self):
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        records = [
            {"item": {"loja": "A", "url": "https://a/1", "titulo": "ASUS TUF A16", "preco": 1299, "ean": "4711636176743"}, "spec": spec, "assessment": {"value_score": 115}, "tier": "OURO"},
            {"item": {"loja": "B", "url": "https://b/1", "titulo": "ASUS TUF A16", "preco": 1199, "ean": "4711636176743"}, "spec": spec, "assessment": {"value_score": 118}, "tier": "OURO"},
        ]
        summary = tracker.build_cross_store_matches(records)
        self.assertEqual(summary["exact_pairs"], 1)
        self.assertEqual(len(summary["groups"]), 1)
        self.assertEqual(summary["groups"][0]["best_store"], "B")
        self.assertEqual(summary["groups"][0]["spread_eur"], 100.0)


    def test_sitemap_priority_prefers_performance_families(self):
        omen = "https://www.pcdiga.com/portatil-hp-omen-gaming-laptop-16-abc"
        generic = "https://www.pcdiga.com/portatil-hp-15-generic-abc"
        self.assertGreater(tracker._sitemap_product_score(omen), tracker._sitemap_product_score(generic))

    def test_product_fetch_urls_keep_canonical_and_add_public_fallback(self):
        item = {"loja": "PCDiga", "url": "https://www.pcdiga.com/path/produto"}
        cfg = {"category_urls": [{"loja": "PCDiga", "url": "https://www.pcdiga.com/cat", "product_fetch_host_fallbacks": ["publojas.pcdiga.com"]}]}
        urls = tracker._product_fetch_urls(item, cfg)
        self.assertEqual(urls[0][0], item["url"])
        self.assertEqual(urls[1][0], "https://publojas.pcdiga.com/path/produto")

    def test_unrelated_different_eans_are_not_conflicts(self):
        left = {"loja": "A", "titulo": "ASUS TUF A16", "ean": "4711636176743"}
        right = {"loja": "B", "titulo": "Lenovo LOQ 15", "ean": "199271075036"}
        left_spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        right_spec = scraper.specs("Lenovo LOQ i7-14700HX 32GB 1TB RTX 5070")
        self.assertEqual(tracker.match_configurations(left, left_spec, right, right_spec)["level"], "SEM_MATCH")

    def test_same_model_different_strong_id_is_conflict(self):
        left = {"loja": "A", "titulo": "ASUS TUF A16 FA608UH-R72B55CS2", "ean": "4711636176743"}
        right = {"loja": "B", "titulo": "ASUS TUF A16 FA608UH-R72B55CS2", "ean": "4711636338424"}
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        self.assertEqual(tracker.match_configurations(left, spec, right, spec)["level"], "NAO_FUNDIR")

    def test_cross_store_alert_requires_material_gap_and_ouro(self):
        history = {"alert_state": {}}
        group = {
            "configuration_key": "ean:4711636176743",
            "spread_eur": 100.0,
            "offers": [
                {"loja": "A", "url": "https://a/1", "titulo": "ASUS TUF", "price": 1199.0, "tier": "OURO", "value_score": 117.0},
                {"loja": "B", "url": "https://b/1", "titulo": "ASUS TUF", "price": 1299.0, "tier": "OURO", "value_score": 112.0},
            ],
        }
        with patch.object(tracker, "ntfy_send", return_value=True):
            self.assertTrue(tracker.maybe_alert_cross_store(history, group, {"alerta_min_tier": "OURO", "cross_store_alert_min_eur": 50, "cross_store_alert_min_pct": 5}))
            self.assertFalse(tracker.maybe_alert_cross_store(history, group, {"alerta_min_tier": "OURO", "cross_store_alert_min_eur": 50, "cross_store_alert_min_pct": 5}))


    def test_identity_refresh_only_for_unchecked_missing_strong_id(self):
        self.assertTrue(tracker.needs_identity_refresh({"url": "x", "ean": None, "mpn": None}))
        self.assertFalse(tracker.needs_identity_refresh({"url": "x", "ean": "4711636176743"}))
        self.assertFalse(tracker.needs_identity_refresh({"url": "x", "identity_checked_at": "2026-09-08T00:00:00Z"}))

    def test_identity_refresh_ignores_empty_metadata(self):
        self.assertFalse(tracker.needs_identity_refresh({}))
        self.assertFalse(tracker.needs_identity_refresh(None))


class PriceSafetyV871Tests(unittest.TestCase):
    def test_absurd_rtx5090_card_price_is_rejected(self):
        html = """
        <article>
          <h3>ASUS ROG Strix Scar 16 RTX 5090 64GB 2TB</h3>
          <a href="/portatil-asus-rog-rtx5090">Produto</a>
          <span class="price-current">449,90 €</span>
        </article>
        """
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(
            card,
            "https://example.com/laptops",
            {"loja": "TEST", "product_path_hints": ["/portatil-asus-"]},
        )
        self.assertIsNone(item)

    def test_preferred_page_price_ignores_discount_amount(self):
        soup = BeautifulSoup(
            """
            <div>
              <span class="price-current">1.499,99 €</span>
              <span class="old-price">2.299,99 €</span>
              <span class="discount">-800,00 €</span>
            </div>
            """,
            "html.parser",
        )
        self.assertEqual(tracker.preferred_page_price(soup, 800.0), 1499.99)

    def test_url_ean_extracts_pcdiga_identifier(self):
        url = (
            "https://www.pcdiga.com/computadores-e-software/computadores-laptop/"
            "computadores-portateis/portatil-asus-tuf-90nr0kv1-m00h70-4711636583923"
        )
        self.assertEqual(tracker.url_ean(url), "4711636583923")

    def test_price_guardrail_allows_normal_rtx5060_deal(self):
        self.assertTrue(scraper.price_is_plausible_for_title("ASUS TUF RTX 5060", 899.0))
        self.assertFalse(scraper.price_is_plausible_for_title("ASUS ROG RTX 5090", 449.9))


    def test_market_evidence_requires_exact_id_and_two_stores(self):
        records = [
            {"item": {"loja": "A", "ean": "4711636047074", "preco": 1299.0}, "spec": {}},
            {"item": {"loja": "B", "ean": "4711636047074", "preco": 1299.99}, "spec": {}},
            {"item": {"loja": "C", "ean": "4711636047074", "preco": 499.0}, "spec": {}},
        ]
        stats = tracker.apply_exact_market_price_evidence(records, {"price_confirmation_tolerance_eur": 5})
        self.assertEqual(stats["confirmed_groups"], 1)
        self.assertEqual(records[0]["spec"]["market_price_confidence"], "HIGH")
        self.assertFalse(records[0]["spec"]["market_price_conflict"])
        self.assertTrue(records[2]["spec"]["market_price_conflict"])
        self.assertAlmostEqual(records[2]["spec"]["market_price_confirmed"], 1299.495, places=2)

    def test_hardware_cache_discards_stale_price_evidence(self):
        cached = tracker._hardware_cache_copy({
            "gpu_modelo": "rtx 5060",
            "price_confirmed": 1299.0,
            "price_page_confidence": "HIGH",
            "market_price_confirmed": 1299.0,
        })
        self.assertEqual(cached["gpu_modelo"], "rtx 5060")
        self.assertNotIn("price_confirmed", cached)
        self.assertNotIn("market_price_confirmed", cached)



if __name__ == "__main__":
    unittest.main()
