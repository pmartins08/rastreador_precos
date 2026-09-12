import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import Mock

from radio_popular_pagination import collect_remaining, listing_state

HTML = """<div data-products-page="destaque" data-products-total="36" data-products-per-page="12"
data-products-where="1,2,3" data-products-order="relevancia asc"></div>
<aside id="filters"><form class="filter-form">
<input name="filters[category_n2_name][]" value="Computadores Portáteis" type="checkbox" checked>
<input name="filters[category_n2_name][]" value="Frigoríficos" type="checkbox">
<input name="filters[price][min]" value="545">
<input name="disabled" value="x" disabled>
</form></aside><a href="/produto/first">First</a>"""

class PaginationTests(unittest.TestCase):
    def tracker(self, pages, budget=True):
        tracker = SimpleNamespace(
            profile_order=lambda *args: ["chrome131"],
            consume_request=Mock(return_value=budget),
            headers=lambda profile: {},
            classify=lambda response: ("http_success", False),
            record_learning=Mock(),
            requests=SimpleNamespace(post=Mock(side_effect=[
                SimpleNamespace(json=lambda data=data: data) for data in pages
            ])),
            LOGGER=Mock(),
        )
        return tracker

    def run_pages(self, tracker):
        stat = {}
        discover = Mock(return_value=1)
        gained = collect_remaining(
            tracker, SimpleNamespace(text=HTML, url="https://www.radiopopular.pt/destaque/test"),
            {}, 80, {}, "promocao", stat, discover,
        )
        return gained, stat, discover

    def test_form_encoding_preserves_checked_category(self):
        state = listing_state(HTML)
        fields = parse_qs(state["payload"]["filters"])
        self.assertEqual(fields["filters[category_n2_name][]"], ["Computadores Portáteis"])
        self.assertNotIn("disabled", fields)
        self.assertEqual(state["payload"]["where"], "1,2,3")

    def test_follows_offsets_and_passes_campaign_provenance(self):
        tracker = self.tracker([
            {"modules": '<a href="/produto/second">Second</a>', "total": 36},
            {"modules": '<a href="/produto/third">Third</a>', "total": 36},
        ])
        gained, stat, discover = self.run_pages(tracker)
        self.assertEqual(gained, 2)
        self.assertEqual([c.kwargs["data"]["offset"] for c in tracker.requests.post.call_args_list], [12, 24])
        self.assertTrue(stat["promotion_pagination"]["complete"])
        self.assertEqual(stat["promotion_pagination"]["listing_items_seen"], 3)
        self.assertEqual(discover.call_args.args[4], "promocao")
        self.assertEqual(tracker.consume_request.call_count, 2)

    def test_repeated_page_stops_without_duplicate_discovery(self):
        tracker = self.tracker([{"modules": '<a href="/produto/first">First</a>', "total": 36}])
        _, stat, discover = self.run_pages(tracker)
        self.assertEqual(stat["promotion_pagination"]["stop_reason"], "repeated_page")
        discover.assert_not_called()

    def test_ignored_filters_never_feed_unrelated_products(self):
        tracker = self.tracker([{"modules": '<a href="/produto/fridge">Fridge</a>', "total": 10000}])
        _, stat, discover = self.run_pages(tracker)
        self.assertEqual(stat["promotion_pagination"]["stop_reason"], "listing_scope_changed")
        discover.assert_not_called()

    def test_request_budget_is_respected(self):
        tracker = self.tracker([], budget=False)
        _, stat, discover = self.run_pages(tracker)
        tracker.requests.post.assert_not_called()
        self.assertFalse(stat["promotion_pagination"]["complete"])

    def test_malformed_grid_is_ignored(self):
        self.assertIsNone(listing_state('<div data-products-page="destaque" data-products-total="bad"></div>'))

    def test_transient_timeout_retries_once_and_counts_each_request(self):
        tracker = self.tracker([])
        tracker.requests.post.side_effect = [
            TimeoutError("transient"),
            SimpleNamespace(json=lambda: {"modules": '<a href="/produto/second">Second</a>', "total": 36}),
            SimpleNamespace(json=lambda: {"modules": '<a href="/produto/third">Third</a>', "total": 36}),
        ]
        gained, stat, _ = self.run_pages(tracker)
        self.assertEqual(gained, 2)
        self.assertTrue(stat["promotion_pagination"]["complete"])
        self.assertEqual(tracker.consume_request.call_count, 3)
