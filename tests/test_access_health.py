import unittest
from access_health import summarize_access


class AccessHealthTests(unittest.TestCase):
    def summarize(self, stats, requests=1):
        return summarize_access({"stores": {"Loja": stats}, "requests_by_store": {"Loja": requests}},
                                per_store_limit=60, total_limit=300)["stores"]["Loja"]

    def test_http_200_without_products_is_not_coverage(self):
        row = self.summarize({"acesso": {"resultado": "http_success"}})
        self.assertEqual(row["state"], "no_products")

    def test_history_does_not_hide_category_block(self):
        row = self.summarize({"acesso": {"resultado": "http_403"}, "bloqueada": False,
                              "fontes_descoberta": {"historico": 6}})
        self.assertEqual(row["state"], "history_only")
        self.assertEqual(row["category_outcome"], "http_403")

    def test_feed_can_provide_coverage_when_html_is_blocked(self):
        row = self.summarize({"acesso": {"resultado": "http_403"},
                              "fontes_descoberta": {"awin_feed": 20}, "aceites": 10})
        self.assertEqual(row["state"], "discovery_available")
        self.assertEqual(row["accepted"], 10)

    def test_catalog_only_does_not_claim_category_was_tested(self):
        row = self.summarize({"fontes_descoberta": {"catalog_json": 80}})
        self.assertEqual(row["category_outcome"], "not_attempted")
        self.assertEqual(row["state"], "discovery_available")

    def test_missing_feed_and_budget_limits_remain_explicit(self):
        row = self.summarize({"acesso": {"resultado": "http_403"},
                              "awin_feed_outcome": "not_configured"}, requests=60)
        self.assertEqual(row["state"], "blocked")
        self.assertEqual(row["feed_outcome"], "not_configured")
        self.assertTrue(row["store_budget_reached"])
