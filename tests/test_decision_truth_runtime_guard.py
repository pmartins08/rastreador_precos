from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

from decision_truth_runtime_guard import install


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args, **kwargs):
        self.messages.append(("INFO", str(message), args))

    def warning(self, message, *args, **kwargs):
        self.messages.append(("WARNING", str(message), args))


class DecisionTruthRuntimeGuardTests(unittest.TestCase):
    def _tracker(self):
        logger = _Logger()
        tracker = SimpleNamespace()
        tracker.LOGGER = logger
        tracker.CONFIG_PATH = "config.json"
        tracker.load_json = lambda _path: {"settings": {"diamante_value_min": 120.0}}
        tracker.heartbeat_seen = None

        def record_offer(history, item, spec, assessment, tier):
            key = item["url"]
            entry = {
                "loja": item["loja"],
                "titulo": item["titulo"],
                "url": item["url"],
                "price": item["preco"],
                "score_ranking": assessment["score_ranking"],
                "value_score": assessment["value_score"],
                "tier": tier,
            }
            if item.get("promotion_value_score") is not None:
                entry.update(
                    {
                        "promotion_value_score": item["promotion_value_score"],
                        "promotion_tier": item.get("promotion_tier"),
                        "promotion_discount_eur": item.get("promotion_discount_eur", 0.0),
                        "promotion_checkout_price": item.get("promotion_checkout_price"),
                        "promotion_price_live_confirmed": bool(item.get("promotion_confirmed")),
                    }
                )
            history.setdefault("offers", {}).setdefault(key, []).append(entry)
            return None, key

        def send_heartbeat(run):
            tracker.heartbeat_seen = deepcopy(run)
            return True

        tracker.record_offer = record_offer
        tracker.send_heartbeat = send_heartbeat

        def main():
            history = {"offers": {}}
            base = {"status": "ACEITE", "score_ranking": 80.0}

            promo_item = {
                "loja": "Loja A",
                "titulo": "Portátil Promo",
                "url": "https://example.test/promo",
                "preco": 1599.99,
                "promotion_value_score": 123.6,
                "promotion_tier": "OURO",
                "promotion_discount_eur": 300.0,
                "promotion_checkout_price": 1299.99,
                "promotion_confirmed": True,
            }
            normal_item = {
                "loja": "Loja B",
                "titulo": "Portátil Normal",
                "url": "https://example.test/normal",
                "preco": 1199.99,
            }

            tracker.record_offer(
                history,
                promo_item,
                {},
                {**base, "value_score": 112.0},
                "OURO",
            )
            tracker.record_offer(
                history,
                normal_item,
                {},
                {**base, "value_score": 116.0},
                "OURO",
            )

            run = {
                "total_accepted": 2,
                "tiers": {"DIAMANTE": 0, "OURO": 2, "PRATA": 0, "BRONZE": 0},
            }
            run["heartbeat_sent"] = tracker.send_heartbeat(run)
            run["history_for_test"] = history
            return run

        tracker.main = main
        return tracker

    def test_runtime_promotes_confirmed_promo_to_effective_diamond(self):
        tracker = self._tracker()
        install(tracker)

        run = tracker.main()

        self.assertEqual(
            run["base_tiers"],
            {"DIAMANTE": 0, "OURO": 2, "PRATA": 0, "BRONZE": 0},
        )
        self.assertEqual(
            run["tiers"],
            {"DIAMANTE": 1, "OURO": 1, "PRATA": 0, "BRONZE": 0},
        )
        self.assertEqual(run["effective_tiers"], run["tiers"])
        self.assertEqual(run["decision_truth"]["promotion_applied_count"], 1)
        self.assertEqual(run["effective_top"][0]["tier"], "DIAMANTE")
        self.assertAlmostEqual(run["effective_top"][0]["value_score"], 123.6)
        self.assertAlmostEqual(run["effective_top"][0]["price"], 1299.99)

        promo_entry = run["history_for_test"]["offers"]["https://example.test/promo"][-1]
        self.assertEqual(promo_entry["base_tier"], "OURO")
        self.assertEqual(promo_entry["effective_tier"], "DIAMANTE")
        self.assertTrue(promo_entry["promotion_applied"])
        self.assertEqual(promo_entry["decision_truth_schema"], 1)

        self.assertEqual(tracker.heartbeat_seen["tiers"], run["tiers"])

    def test_unconfirmed_promotion_stays_base_decision(self):
        tracker = self._tracker()

        def main_unconfirmed():
            history = {"offers": {}}
            item = {
                "loja": "Loja A",
                "titulo": "Promo não confirmada",
                "url": "https://example.test/unconfirmed",
                "preco": 1599.99,
                "promotion_value_score": 124.0,
                "promotion_tier": "DIAMANTE",
                "promotion_discount_eur": 300.0,
                "promotion_checkout_price": 1299.99,
                "promotion_confirmed": False,
            }
            tracker.record_offer(
                history,
                item,
                {},
                {"status": "ACEITE", "score_ranking": 80.0, "value_score": 112.0},
                "OURO",
            )
            run = {
                "total_accepted": 1,
                "tiers": {"DIAMANTE": 0, "OURO": 1, "PRATA": 0, "BRONZE": 0},
            }
            tracker.send_heartbeat(run)
            run["history_for_test"] = history
            return run

        tracker.main = main_unconfirmed
        install(tracker)
        run = tracker.main()

        self.assertEqual(run["tiers"]["OURO"], 1)
        self.assertEqual(run["tiers"]["DIAMANTE"], 0)
        entry = run["history_for_test"]["offers"]["https://example.test/unconfirmed"][-1]
        self.assertFalse(entry["promotion_applied"])
        self.assertEqual(entry["effective_tier"], "OURO")


if __name__ == "__main__":
    unittest.main()
