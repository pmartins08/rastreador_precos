from __future__ import annotations

import types
import unittest

import promotion_budget_guard


SETTINGS = {"budget_soft": 1300.0, "budget_hard": 1500.0}
RP_PROMO = {
    "kind": "TIERED_DISCOUNT",
    "title": "50€ por cada 250€",
    "threshold_step_eur": 250,
    "step_discount_eur": 50,
    "eligibility": "campaign_listing",
    "applicable": True,
}


def item(price: float, *, confirmed: bool = True, promo: dict | None = None) -> dict:
    row = {
        "loja": "Radio Popular",
        "titulo": "Portátil teste",
        "url": f"https://example.test/{price}",
        "preco": price,
        "promotions": [promo or RP_PROMO],
    }
    if confirmed:
        row["promotion_listing_live_confirmed"] = True
        row["promotion_price_live_confirmed"] = True
    return row


class PromotionBudgetViewTests(unittest.TestCase):
    def test_current_rp_rule_rescues_1750_1800_and_1850(self):
        expected = {
            1750.0: 1400.0,
            1800.0: 1450.0,
            1850.0: 1500.0,
        }
        for raw, checkout in expected.items():
            with self.subTest(raw=raw):
                view = promotion_budget_guard.budget_view(item(raw), SETTINGS)
                self.assertTrue(view["confirmed"])
                self.assertEqual(view["checkout_price"], checkout)
                self.assertTrue(view["fits_hard_budget"])
                self.assertTrue(view["rescued_by_promotion"])

    def test_1850_01_is_not_misclassified_inside_hard_budget(self):
        view = promotion_budget_guard.budget_view(item(1850.01), SETTINGS)
        self.assertEqual(view["checkout_price"], 1500.01)
        self.assertFalse(view["fits_hard_budget"])
        self.assertFalse(view["rescued_by_promotion"])

    def test_unconfirmed_campaign_never_changes_budget_view(self):
        view = promotion_budget_guard.budget_view(item(1750.0, confirmed=False), SETTINGS)
        self.assertFalse(view["confirmed"])
        self.assertEqual(view["checkout_price"], 1750.0)
        self.assertFalse(view["fits_hard_budget"])
        self.assertFalse(view["rescued_by_promotion"])

    def test_rule_is_generic_not_radio_popular_hardcoded(self):
        promo = {
            "kind": "TIERED_DISCOUNT",
            "title": "100€ por cada 400€",
            "threshold_step_eur": 400,
            "step_discount_eur": 100,
            "eligibility": "campaign_listing",
            "applicable": True,
        }
        view = promotion_budget_guard.budget_view(item(1800.0, promo=promo), SETTINGS)
        self.assertEqual(view["discount_eur"], 400.0)
        self.assertEqual(view["checkout_price"], 1400.0)
        self.assertTrue(view["rescued_by_promotion"])

    def test_main_gate_temporarily_uses_checkout_then_restores_label_price(self):
        rescued = item(1799.99)
        outside = item(1999.99)
        unconfirmed = item(1799.99, confirmed=False)
        rows = [rescued, outside, unconfirmed]

        count = promotion_budget_guard._apply_main_budget_gate(rows, SETTINGS)
        self.assertEqual(count, 1)
        self.assertEqual(rescued["preco"], 1449.99)
        self.assertEqual(outside["preco"], 1999.99)
        self.assertEqual(unconfirmed["preco"], 1799.99)
        self.assertLessEqual(float(rescued["preco"]), SETTINGS["budget_hard"])

        restored = promotion_budget_guard._restore_main_budget_gate(rows)
        self.assertEqual(restored, 1)
        self.assertEqual(rescued["preco"], 1799.99)
        self.assertEqual(rescued["promotion_budget_gate_checkout_price"], 1449.99)
        self.assertTrue(rescued["promotion_budget_gate_rescued"])


class PromotionBudgetRuntimeTests(unittest.TestCase):
    def test_pre_ranking_price_component_uses_effective_checkout(self):
        class Scraper:
            @staticmethod
            def price_score(price, settings):
                hard = settings["budget_hard"]
                return 100.0 if price <= hard else 70.0

        tracker = types.SimpleNamespace(
            scraper=Scraper(),
            candidate_priority=lambda _item, _weights, _settings: 50.0,
            _PROMOTION_BUDGET_GUARD_INSTALLED=False,
        )
        promotion_budget_guard.install(tracker)
        self.assertEqual(tracker.candidate_priority(item(1800.0), {}, SETTINGS), 60.5)
        self.assertEqual(
            tracker.candidate_priority(item(1800.0, confirmed=False), {}, SETTINGS),
            50.0,
        )

    def test_proxy_does_not_double_count_price_priority_delta(self):
        class Scraper:
            @staticmethod
            def price_score(price, settings):
                hard = settings["budget_hard"]
                return 100.0 if price <= hard else 70.0

        tracker = types.SimpleNamespace(
            scraper=Scraper(),
            candidate_priority=lambda row, _weights, settings: 0.35 * Scraper.price_score(row["preco"], settings),
            _PROMOTION_BUDGET_GUARD_INSTALLED=False,
        )
        promotion_budget_guard.install(tracker)
        rescued = item(1800.0)
        promotion_budget_guard._apply_main_budget_gate([rescued], SETTINGS)
        self.assertEqual(tracker.candidate_priority(rescued, {}, SETTINGS), 35.0)

    def test_scan_stats_expose_candidates_rescued_above_hard_budget(self):
        rows = [item(1299.0), item(1750.0), item(1800.0), item(2000.0)]

        class Scraper:
            @staticmethod
            def price_score(_price, _settings):
                return 100.0

        class Logger:
            @staticmethod
            def info(*_args, **_kwargs):
                return None

        tracker = types.SimpleNamespace(
            scraper=Scraper(),
            LOGGER=Logger(),
            candidate_priority=lambda _item, _weights, _settings: 50.0,
            scan_store=lambda _cat, _config, _settings: (rows, {}),
            _PROMOTION_BUDGET_GUARD_INSTALLED=False,
        )
        promotion_budget_guard.install(tracker)
        _items, stat = tracker.scan_store({"loja": "Radio Popular"}, {}, SETTINGS)
        promo = stat["promotion_budget"]
        self.assertEqual(promo["confirmed_candidates"], 4)
        self.assertEqual(promo["fits_hard_budget"], 3)
        self.assertEqual(promo["rescued_above_hard_budget"], 2)
        self.assertEqual(promo["max_rescued_gross_price"], 1800.0)
        self.assertEqual(promo["max_rescued_checkout_price"], 1450.0)

    def test_main_wrapper_survives_second_gate_scores_raw_and_restores_before_history(self):
        rows = [item(1799.99), item(1999.99)]
        seen = {
            "during_filter": None,
            "during_selection": None,
            "second_gate": [],
            "score_prices": [],
            "record_prices": [],
            "alert_prices": [],
        }

        class Scraper:
            @staticmethod
            def price_score(_price, _settings):
                return 100.0

            @staticmethod
            def tier_from_value(_value, _settings):
                return "OURO"

        class Logger:
            @staticmethod
            def info(*_args, **_kwargs):
                return None

        tracker = types.SimpleNamespace()
        tracker.scraper = Scraper()
        tracker.LOGGER = Logger()
        tracker._PROMOTION_BUDGET_GUARD_INSTALLED = False
        tracker.candidate_priority = lambda _item, _weights, _settings: 50.0
        tracker.scan_store = lambda _cat, _config, _settings: (rows, {})

        def base_select(items, _cache, _max_items, _weights, _settings):
            seen["during_selection"] = [row["preco"] for row in items]
            return items

        tracker.select_with_cache = base_select

        def base_score(spec, price, _weights, _settings):
            seen["score_prices"].append(price)
            return {
                "status": "ACEITE",
                "score_ranking": 80.0,
                "value_score": 110.0,
            }

        tracker.score_allow_unknown = base_score

        def base_record(_history, row, _spec, _assessment, _tier):
            seen["record_prices"].append(row["preco"])
            return None, row["url"]

        tracker.record_offer = base_record
        tracker.maybe_alert = lambda _history, row, *_args: (
            seen["alert_prices"].append(row["preco"]) or False,
            False,
        )

        def base_main():
            scanned, _stat = tracker.scan_store({"loja": "Radio Popular"}, {}, SETTINGS)
            seen["during_filter"] = [row["preco"] for row in scanned]
            clean = [row for row in scanned if float(row["preco"]) <= SETTINGS["budget_hard"]]
            selected = tracker.select_with_cache(clean, {}, 10, {}, SETTINGS)

            for row in selected:
                price = row["preco"]
                seen["second_gate"].append(float(price))
                if not (250.0 <= float(price) <= SETTINGS["budget_hard"]):
                    continue
                spec = {"page_url": row["url"]}
                assessment = tracker.score_allow_unknown(spec, float(price), {}, SETTINGS)
                tier = tracker.scraper.tier_from_value(assessment["value_score"], SETTINGS)
                previous, key = tracker.record_offer({}, row, spec, assessment, tier)
                tracker.maybe_alert({}, row, spec, assessment, tier, previous, key, SETTINGS)
            return selected

        tracker.main = base_main
        promotion_budget_guard.install(tracker)
        selected = tracker.main()

        self.assertEqual(seen["during_filter"], [1449.99, 1999.99])
        self.assertEqual(len(selected), 1)
        self.assertEqual(seen["during_selection"], [1449.99])
        self.assertEqual(seen["second_gate"], [1449.99])
        # O segundo gate vê checkout, mas o score normal continua ancorado no
        # preço bruto confirmado para não criar PRICE_CONFLICT falso.
        self.assertEqual(seen["score_prices"], [1799.99])
        self.assertEqual(seen["record_prices"], [1799.99])
        self.assertEqual(seen["alert_prices"], [1799.99])
        self.assertEqual(selected[0]["preco"], 1799.99)
        self.assertEqual(selected[0]["promotion_budget_gate_checkout_price"], 1449.99)
        self.assertTrue(selected[0]["promotion_budget_gate_rescued"])
        self.assertFalse(getattr(tracker, "_PROMOTION_BUDGET_MAIN_ACTIVE", False))


if __name__ == "__main__":
    unittest.main()
