import copy
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

import runner_v84 as runner
import scraper


class RunnerV84Tests(unittest.TestCase):
    def setUp(self):
        self.learning = copy.deepcopy(runner.LEARNING)
        self.requests_used = runner.REQUESTS_USED
        self.requests_by_store = runner.REQUESTS_BY_STORE
        self.max_requests = runner.MAX_REQUESTS
        self.max_requests_store = runner.MAX_REQUESTS_PER_STORE
        self.deadline = runner.RUN_DEADLINE

    def tearDown(self):
        runner.LEARNING = self.learning
        runner.REQUESTS_USED = self.requests_used
        runner.REQUESTS_BY_STORE = self.requests_by_store
        runner.MAX_REQUESTS = self.max_requests
        runner.MAX_REQUESTS_PER_STORE = self.max_requests_store
        runner.RUN_DEADLINE = self.deadline

    def reset_learning(self):
        runner.LEARNING = {"schema_version": 2, "stores": {}}

    def test_subbrands_infer_parent_brand(self):
        self.assertEqual(runner.infer_brand("ROG Zephyrus G16")[0], "asus")
        self.assertEqual(runner.infer_brand("Legion 5 Gen 10")[0], "lenovo")
        self.assertEqual(runner.infer_brand("OMEN Gaming Laptop 16")[0], "hp")
        self.assertTrue(runner.eligible("ROG Zephyrus G16 RTX 5070"))
        self.assertFalse(runner.eligible("ROG Zephyrus G16 recondicionado"))

    def test_method_classification(self):
        cfg = {
            "category_urls": [
                {
                    "loja": "TESTE",
                    "url": "https://example.com/laptops",
                    "product_path_hints": ["/produto/"],
                }
            ]
        }
        self.assertEqual(runner.method_for_url("https://example.com/laptops", cfg), "category")
        self.assertEqual(runner.method_for_url("https://example.com/produto/abc", cfg), "product")
        self.assertEqual(runner.method_for_url("https://example.com/robots.txt", cfg), "robots")

    def test_profile_order_uses_store_wide_history(self):
        self.reset_learning()
        b = runner.bucket("PCDiga")
        b["profiles"] = {
            "chrome131": {"attempts": 10, "successes": 0, "blocks": 10, "errors": 0},
            "safari17_0": {"attempts": 20, "successes": 18, "blocks": 1, "errors": 1},
            "firefox147": {"attempts": 5, "successes": 5, "blocks": 0, "errors": 0},
        }
        order = runner.profile_order("PCDiga", "category")
        self.assertEqual(order[0], "safari17_0")
        self.assertIn("firefox147", order)
        self.assertEqual(len(order), len(set(order)))
        self.assertLessEqual(len(order), 3)

    def test_persistently_blocked_store_enters_probe_mode(self):
        self.reset_learning()
        b = runner.bucket("BLOQUEADA")
        b["attempts"] = 40
        b["blocks"] = 40
        b["successes"] = 0
        for p in runner.PROFILES:
            b["profiles"][p] = {"attempts": 5, "successes": 0, "blocks": 5, "errors": 0}
        self.assertEqual(runner.access_mode("BLOQUEADA", "category"), "probe")
        self.assertEqual(len(runner.profile_order("BLOQUEADA", "category")), 1)

    def test_candidate_priority_prefers_strong_hardware(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        weights = {
            "gpu_base": {"rtx 5070": 95},
            "cpu_base": {"tier_1": 100, "tier_2": 85, "tier_3": 70},
        }
        strong = {
            "loja": "A",
            "url": "https://a/1",
            "titulo": "ASUS Gaming V16 Core 7 240H 32GB 1TB RTX 5070",
            "preco": 1399,
        }
        cheap = {
            "loja": "A",
            "url": "https://a/2",
            "titulo": "ASUS Vivobook Core 7 150U 16GB 512GB Intel Graphics",
            "preco": 699,
        }
        self.assertGreater(
            runner.candidate_priority(strong, weights, settings),
            runner.candidate_priority(cheap, weights, settings),
        )

    def test_enrichment_selection_is_store_balanced(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        weights = {"gpu_base": {}, "cpu_base": {}}
        items = []
        for store in ("A", "B"):
            for i in range(10):
                items.append(
                    {
                        "loja": store,
                        "url": f"https://{store.lower()}/{i}",
                        "titulo": f"ASUS Vivobook Core i7-13620H 16GB 1TB {i}",
                        "preco": 700 + i,
                    }
                )
        selected = runner.select_for_enrichment(items, 6, weights, settings)
        counts = {s: sum(x["loja"] == s for x in selected) for s in ("A", "B")}
        self.assertEqual(counts, {"A": 3, "B": 3})

    def test_per_store_request_budget(self):
        self.reset_learning()
        runner.REQUESTS_USED = 0
        runner.REQUESTS_BY_STORE = {}
        runner.MAX_REQUESTS = 10
        runner.MAX_REQUESTS_PER_STORE = 2
        runner.RUN_DEADLINE = 0
        self.assertTrue(runner.consume_request("A"))
        self.assertTrue(runner.consume_request("A"))
        self.assertFalse(runner.consume_request("A"))
        self.assertTrue(runner.consume_request("B"))

    def test_network_exception_is_contained(self):
        self.reset_learning()
        runner.REQUESTS_USED = 0
        runner.REQUESTS_BY_STORE = {}
        runner.MAX_REQUESTS = 20
        runner.MAX_REQUESTS_PER_STORE = 20
        runner.RUN_DEADLINE = 0
        cfg = {"category_urls": [{"loja": "TESTE", "url": "https://example.com/laptops"}]}
        with patch.object(runner.requests, "get", side_effect=RuntimeError("boom")), patch.object(
            runner.time, "sleep", return_value=None
        ):
            response, profile, outcome = runner.adaptive_fetch(
                "https://example.com/laptops", cfg, 0.1
            )
        self.assertIsNone(response)
        self.assertIsNone(profile)
        self.assertEqual(outcome, "no_response")
        self.assertGreater(runner.bucket("TESTE")["errors"].get("request_error", 0), 0)

    def test_loose_catalog_handles_subbrand_only_title(self):
        html = """
        <div class="card">
          <h3>ROG Zephyrus G16 RTX 5070</h3>
          <span>1.399,99 €</span>
          <a href="/pt/laptops/rog-zephyrus-g16/">Saber mais</a>
        </div>
        """
        cat = {
            "loja": "ASUS",
            "url": "https://www.asus.com/pt/store/laptops/",
            "product_path_hints": ["/pt/laptops/"],
            "parent_climb": 4,
        }
        out = runner.loose_catalog_candidates(html, cat, 5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["preco"], 1399.99)


class ScraperV8RegressionTests(unittest.TestCase):
    @staticmethod
    def page(rows):
        html = "<table>" + "".join(
            f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows
        ) + "</table>"
        return BeautifulSoup(html, "html.parser")

    def test_integrated_gpu_does_not_become_unknown(self):
        x = scraper.extract(
            "Portátil ASUS Zenbook Ryzen AI 7 445 32GB 1TB AMD Graphics",
            self.page([("Placa gráfica", "AMD Radeon Graphics")]),
        )
        self.assertIsNone(x["gpu_modelo"])
        self.assertEqual(x["gpu_tipo"], "integrada")

    def test_explicit_vram_and_tgp(self):
        x = scraper.extract(
            "Portátil ASUS TUF 16 Ryzen 7 260 32GB 1TB RTX 5070",
            self.page(
                [
                    ("Placa gráfica", "NVIDIA GeForce RTX 5070 Laptop GPU"),
                    ("Memória gráfica", "8 GB GDDR7"),
                    ("TGP", "115 W"),
                ]
            ),
        )
        self.assertEqual(x["gpu_modelo"], "rtx 5070")
        self.assertEqual(x["vram_gb"], 8)
        self.assertEqual(x["tgp_w"], 115)

    def test_ram_is_not_vram(self):
        x = scraper.extract(
            "Portátil HP 15 i7-1255U 16GB 512GB",
            self.page([("Memória RAM", "16 GB DDR4"), ("Armazenamento", "512 GB SSD")]),
        )
        self.assertIsNone(x["gpu_modelo"])
        self.assertIsNone(x["vram_gb"])

    def test_unknown_keyboard_wrapper_is_accepted(self):
        unknown = {
            "teclado_pt": "desconhecido",
            "ram_gb": 16,
            "armazenamento_tb": 1,
            "ecra_res": "fhd",
            "ecra_hz": 120,
            "cpu_modelo": "core i7 13620h",
            "cpu_classe": "h",
            "gpu_tipo": "dedicada",
            "gpu_modelo": "rtx 4060",
            "fontes": {},
        }
        result = runner.score_allow_unknown(
            unknown,
            1200,
            {
                "gpu_base": {"rtx 4060": 65},
                "cpu_base": {"tier_1": 100, "tier_2": 85, "tier_3": 70},
            },
            {},
        )
        self.assertEqual(result["status"], "ACEITE")


if __name__ == "__main__":
    unittest.main()
