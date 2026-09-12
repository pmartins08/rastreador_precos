import unittest

from gpu_guard import TierAwareValue
import promotion_runtime_guard


PROMO = {
    "kind": "TIERED_DISCOUNT",
    "title": "Ganha 50€ por cada 250€",
    "threshold_step_eur": 250.0,
    "step_discount_eur": 50.0,
    "cap_eur": 500.0,
    "eligibility": "campaign_listing",
    "applicable": True,
    "valid_from": "2026-09-12",
    "valid_until": "2026-09-15",
}


class DummyLogger:
    @staticmethod
    def info(*args, **kwargs):
        return None


class DummyScraper:
    @staticmethod
    def value_score(ranking, price, settings):
        return round(float(ranking) + max(0.0, (1000.0 - float(price)) / 20.0), 1)

    @staticmethod
    def exceptional_deal_bonus(price, confidence, settings):
        return 5.0 if confidence == "HIGH" and float(price) < 1000.0 else 0.0

    @staticmethod
    def tier_from_value(value, settings):
        adjusted = getattr(value, "tier_score", float(value))
        return "PRATA" if adjusted >= 90 else "BRONZE" if adjusted >= 70 else None


DummyScraper._PRICE_GUARD_ORIGINALS = {"value_score": DummyScraper.value_score}


class DummyTracker:
    def __init__(self):
        self._PROMOTION_RUNTIME_GUARD_INSTALLED = False
        self.scraper = DummyScraper()
        self.LOGGER = DummyLogger()
        self.CONFIG_PATH = "config"
        self.enrich_seen_price = "unset"
        self.alert_messages = []
        self.normal_alert_calls = []

    @staticmethod
    def discovery_routes(cat, store):
        return [{
            "label": "50_por_250_set_2026",
            "url": cat["campaign_urls"][0]["url"],
            "method_key": "campaign:50_por_250_set_2026",
            "priority": 160,
            "priority_band": 2,
            "yield_score": 0.0,
        }]

    @staticmethod
    def _discover_html(response, route_cat, target, candidates, source, stat):
        return route_cat["url"]

    @staticmethod
    def candidate_priority(item, weights, settings):
        return 10.0

    @staticmethod
    def select_with_cache(items, spec_cache, max_items, weights, settings):
        return list(items)

    def enrich(self, item, config):
        self.enrich_seen_price = item.get("preco")
        result = dict(item)
        result["preco"] = 699.99
        result["specs"] = {"teclado_pt": "confirmado"}
        return result, {"error": None}

    @staticmethod
    def needs_price_refresh(previous_meta, item, settings, *, current_time=None):
        return False

    @staticmethod
    def record_offer(history, item, spec, assessment, tier):
        key = item["url"]
        previous = history.get("offers", {}).get(key, [None])[-1] if history.get("offers", {}).get(key) else None
        history.setdefault("offers", {}).setdefault(key, []).append({"price": item["preco"]})
        return previous, key

    def maybe_alert(self, history, item, spec, assessment, tier, previous, alert_key, settings):
        self.normal_alert_calls.append(dict(item))
        return False, False

    @staticmethod
    def load_json(path):
        return {"weights": {}, "settings": {}}

    def ntfy_send(self, title, message, *, priority=3, tags=None):
        self.alert_messages.append((title, message))
        return True

    @staticmethod
    def now_iso():
        return "2026-09-12T12:00:00Z"


class PromotionRuntimeGuardTests(unittest.TestCase):
    def setUp(self):
        self.tracker = DummyTracker()
        promotion_runtime_guard.install(self.tracker)
        self.cat = {
            "loja": "Radio Popular",
            "campaign_urls": [{
                "label": "50_por_250_set_2026",
                "url": "https://www.radiopopular.pt/destaque/6a20120dc7e006.23735122?filters%5Bdisponibilidade%5D%5B%5D=Ocultar+Produtos+Indispon%C3%ADveis",
            }],
        }

    def item(self):
        return {
            "loja": "Radio Popular",
            "titulo": "PC PORTÁTIL ASUS TEST",
            "preco": 699.99,
            "url": "https://www.radiopopular.pt/produto/test",
            "promotions": [dict(PROMO)],
            "promotion_price_live_confirmed": True,
        }

    @staticmethod
    def accepted_assessment():
        return {
            "status": "ACEITE",
            "value_score": TierAwareValue(80.0, gaming_score=60.0),
            "score_ranking": 80.0,
            "score_final": 82.0,
            "detalhes": {"Gaming": 60.0},
            "exceptional_deal_bonus": 7.0,
            "price_status": "OK",
            "price_confirmed": 699.99,
        }

    def test_campaign_route_is_filtered_to_laptops(self):
        route = self.tracker.discovery_routes(self.cat, "Radio Popular")[0]
        self.assertIn("category_n2_name", route["url"])
        self.assertIn("Computadores+Port%C3%A1teis", route["url"])
        self.assertEqual(route["method_key"], "campaign:50_por_250_set_2026_portateis")
        self.assertGreaterEqual(route["priority_band"], 3)

    def test_promotion_candidate_loses_runtime_cache(self):
        item = self.item()
        cache = {item["url"]: {"ram_gb": 16}}
        selected = self.tracker.select_with_cache([item], cache, 10, {}, {})
        self.assertEqual(selected, [item])
        self.assertNotIn(item["url"], cache)

    def test_promotion_enrich_forces_live_price(self):
        item = self.item()
        result, status = self.tracker.enrich(item, {})
        self.assertIsNone(self.tracker.enrich_seen_price)
        self.assertIsNone(status["error"])
        self.assertEqual(result["preco"], 699.99)
        self.assertTrue(result["promotion_price_live_confirmed"])

    def test_revalue_keeps_ranking_and_uses_derived_opportunity_bonus(self):
        assessment = self.accepted_assessment()
        promo = self.tracker.promotion_revalue_assessment(assessment, 599.99, {})
        self.assertEqual(promo["status"], "ACEITE")
        self.assertEqual(promo["score_ranking"], 80.0)
        self.assertEqual(promo["price_confirmed"], 699.99)
        self.assertEqual(promo["exceptional_deal_bonus"], 5.0)
        self.assertEqual(promo["promotion_price_confidence"], "HIGH_DERIVED")
        self.assertGreater(float(promo["value_score"]), 80.0)
        self.assertEqual(promo["promotion_checkout_price"], 599.99)
        self.assertTrue(hasattr(promo["value_score"], "tier_score"))
        self.assertIsInstance(assessment["value_score"], TierAwareValue)
        self.assertEqual(float(assessment["value_score"]), 80.0)

    def test_new_eligibility_notifies_even_without_ouro(self):
        item = self.item()
        history = {"offers": {}, "alert_state": {}}
        sent, suppressed = self.tracker.maybe_alert(
            history,
            item,
            {"teclado_pt": "confirmado"},
            self.accepted_assessment(),
            "BRONZE",
            None,
            item["url"],
            {"promotion_alert_min_eur": 25.0, "alerta_queda_preco_eur": 5.0},
        )
        self.assertTrue(sent)
        self.assertFalse(suppressed)
        self.assertEqual(len(self.tracker.alert_messages), 1)
        state = history["alert_state"][item["url"]]
        self.assertEqual(state["promotion_discount_eur"], 100.0)
        self.assertEqual(state["promotion_checkout_price"], 599.99)
        self.assertGreater(state["promotion_value_score"], 80.0)

    def test_unknown_keyboard_does_not_get_promo_eligibility_alert(self):
        item = self.item()
        history = {"offers": {}, "alert_state": {}}
        sent, _ = self.tracker.maybe_alert(
            history,
            item,
            {"teclado_pt": "desconhecido"},
            self.accepted_assessment(),
            "BRONZE",
            None,
            item["url"],
            {"promotion_alert_min_eur": 25.0, "alerta_queda_preco_eur": 5.0},
        )
        self.assertFalse(sent)
        self.assertEqual(self.tracker.alert_messages, [])
        self.assertEqual(len(self.tracker.normal_alert_calls), 1)

    def test_unconfirmed_promo_price_does_not_alert(self):
        item = self.item()
        item["promotion_price_live_confirmed"] = False
        history = {"offers": {}, "alert_state": {}}
        sent, _ = self.tracker.maybe_alert(
            history,
            item,
            {"teclado_pt": "confirmado"},
            self.accepted_assessment(),
            "BRONZE",
            None,
            item["url"],
            {"promotion_alert_min_eur": 25.0, "alerta_queda_preco_eur": 5.0},
        )
        self.assertFalse(sent)
        self.assertEqual(self.tracker.alert_messages, [])

    def test_same_eligibility_does_not_send_duplicate_promo(self):
        item = self.item()
        fp = promotion_runtime_guard.promotion_value.fingerprint(item["promotions"])
        history = {
            "offers": {},
            "alert_state": {
                item["url"]: {
                    "promotion_eligibility_fingerprint": fp,
                    "promotion_checkout_price": 599.99,
                }
            },
        }
        sent, _ = self.tracker.maybe_alert(
            history,
            item,
            {"teclado_pt": "confirmado"},
            self.accepted_assessment(),
            "BRONZE",
            None,
            item["url"],
            {"promotion_alert_min_eur": 25.0, "alerta_queda_preco_eur": 5.0},
        )
        self.assertFalse(sent)
        self.assertEqual(self.tracker.alert_messages, [])
        self.assertEqual(len(self.tracker.normal_alert_calls), 1)
        self.assertNotIn("promotions", self.tracker.normal_alert_calls[0])


if __name__ == "__main__":
    unittest.main()
