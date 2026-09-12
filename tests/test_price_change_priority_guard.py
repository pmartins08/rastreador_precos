from __future__ import annotations

import types
import unittest

import price_change_priority_guard


PROMO = {
    "kind": "TIERED_DISCOUNT",
    "title": "Ganha 50€ por cada 250€",
    "threshold_step_eur": 250.0,
    "step_discount_eur": 50.0,
    "cap_eur": 500.0,
    "eligibility": "campaign_listing",
    "applicable": True,
}


class PriceChangePriorityGuardTests(unittest.TestCase):
    def _module(self, latest, *, with_alerts=False):
        module = types.SimpleNamespace()
        module._PRICE_CHANGE_PRIORITY_GUARD_INSTALLED = False
        module.candidate_priority = lambda item, weights, settings: 50.0
        module.load_history = lambda: latest
        module.compact_history = lambda history: history
        module.latest_offer_by_url = lambda history: history
        if with_alerts:
            module.sent_messages = []

            def ntfy_send(title, message, *, priority=3, tags=None):
                module.sent_messages.append((title, message, priority, tags))
                return True

            def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
                sent = module.ntfy_send(
                    f"{tier}: {item['titulo']}",
                    (
                        f"{item['titulo']}\n"
                        f"Value: {float(assessment['value_score']):.1f}\n"
                        f"{item['url']}"
                    ),
                    priority=3,
                    tags=["computer"],
                )
                return sent, False

            module.ntfy_send = ntfy_send
            module.maybe_alert = maybe_alert
        return module

    def test_material_drop_gets_strong_priority(self):
        module = self._module(
            {"x": {"loja": "Darty", "url": "https://darty.pt/products/a", "price": 1200.0}}
        )
        price_change_priority_guard.install(module)
        score = module.candidate_priority(
            {"loja": "Darty", "url": "https://darty.pt/products/a?utm=x", "preco": 1195.0},
            {},
            {"alerta_queda_preco_eur": 5.0},
        )
        self.assertEqual(score, 550.0)

    def test_small_change_keeps_base_priority(self):
        module = self._module(
            {"x": {"loja": "Darty", "url": "https://darty.pt/products/a", "price": 1200.0}}
        )
        price_change_priority_guard.install(module)
        self.assertEqual(
            module.candidate_priority(
                {"loja": "Darty", "url": "https://darty.pt/products/a", "preco": 1197.0},
                {},
                {"alerta_queda_preco_eur": 5.0},
            ),
            50.0,
        )

    def test_material_rise_is_prioritized_but_less_than_drop(self):
        module = self._module(
            {"x": {"loja": "Darty", "url": "https://darty.pt/products/a", "price": 1200.0}}
        )
        price_change_priority_guard.install(module)
        self.assertEqual(
            module.candidate_priority(
                {"loja": "Darty", "url": "https://darty.pt/products/a", "preco": 1205.0},
                {},
                {"alerta_queda_preco_eur": 5.0},
            ),
            150.0,
        )

    def test_same_ean_can_match_changed_url_within_same_store(self):
        module = self._module(
            {
                "x": {
                    "loja": "Globaldata",
                    "url": "https://globaldata.pt/old-url",
                    "price": 1000.0,
                    "ean": "5601234567890",
                }
            }
        )
        price_change_priority_guard.install(module)
        score = module.candidate_priority(
            {
                "loja": "Globaldata",
                "url": "https://globaldata.pt/new-url",
                "ean": "5601234567890",
                "preco": 990.0,
            },
            {},
            {"alerta_queda_preco_eur": 5.0},
        )
        self.assertEqual(score, 550.0)

    def test_ean_from_other_store_never_creates_local_price_delta(self):
        module = self._module(
            {
                "x": {
                    "loja": "Darty",
                    "url": "https://darty.pt/products/a",
                    "price": 1000.0,
                    "ean": "5601234567890",
                }
            }
        )
        price_change_priority_guard.install(module)
        score = module.candidate_priority(
            {
                "loja": "Globaldata",
                "url": "https://globaldata.pt/a",
                "ean": "5601234567890",
                "preco": 900.0,
            },
            {},
            {"alerta_queda_preco_eur": 5.0},
        )
        self.assertEqual(score, 50.0)

    def test_normal_alert_shows_previous_and_recalculated_value(self):
        module = self._module({}, with_alerts=True)
        price_change_priority_guard.install(module)
        url = "https://example.com/produto/a"
        history = {"alert_state": {url: {"value_score": 110.0}}}
        sent, suppressed = module.maybe_alert(
            history,
            {"loja": "TEST", "titulo": "ASUS A", "url": url, "preco": 999.0},
            {},
            {"status": "ACEITE", "value_score": 114.0},
            "OURO",
            {"value_score": 111.0},
            url,
            {},
        )
        self.assertTrue(sent)
        self.assertFalse(suppressed)
        self.assertIn(
            "Variação Value: 110.0 → 114.0 (Δ +4.0)",
            module.sent_messages[-1][1],
        )

    def test_first_promo_alert_shows_normal_to_promotional_value(self):
        module = self._module({}, with_alerts=True)
        module.promotion_revalue_assessment = lambda assessment, checkout, settings: {
            "status": "ACEITE",
            "value_score": 123.3,
        }
        price_change_priority_guard.install(module)
        url = "https://example.com/produto/asus"
        item = {
            "loja": "TEST",
            "titulo": "ASUS TUF A16",
            "url": url,
            "preco": 1299.99,
            "promotions": [dict(PROMO)],
            "promotion_price_live_confirmed": True,
        }
        sent, _ = module.maybe_alert(
            {"alert_state": {}},
            item,
            {},
            {"status": "ACEITE", "value_score": 118.3},
            "OURO",
            None,
            url,
            {},
        )
        self.assertTrue(sent)
        self.assertIn(
            "Variação Value: 118.3 → 123.3 (Δ +5.0)",
            module.sent_messages[-1][1],
        )

    def test_later_promo_alert_uses_previous_promotional_value(self):
        module = self._module({}, with_alerts=True)
        module.promotion_revalue_assessment = lambda assessment, checkout, settings: {
            "status": "ACEITE",
            "value_score": 125.0,
        }
        price_change_priority_guard.install(module)
        url = "https://example.com/produto/asus"
        history = {
            "alert_state": {
                url: {
                    "value_score": 118.3,
                    "promotion_value_score": 123.3,
                }
            }
        }
        sent, _ = module.maybe_alert(
            history,
            {
                "loja": "TEST",
                "titulo": "ASUS TUF A16",
                "url": url,
                "preco": 1249.99,
                "promotions": [dict(PROMO)],
                "promotion_price_live_confirmed": True,
            },
            {},
            {"status": "ACEITE", "value_score": 119.0},
            "OURO",
            None,
            url,
            {},
        )
        self.assertTrue(sent)
        self.assertIn(
            "Variação Value: 123.3 → 125.0 (Δ +1.7)",
            module.sent_messages[-1][1],
        )


if __name__ == "__main__":
    unittest.main()
