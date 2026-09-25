from __future__ import annotations

import types
import unittest

import price_change_alert_guard


class _Logger:
    def info(self, *args, **kwargs):
        return None


class PriceChangeAlertGuardTests(unittest.TestCase):
    def _module(self):
        module = types.SimpleNamespace()
        module._PRICE_CHANGE_ALERT_GUARD_INSTALLED = False
        module.sent = []
        module.LOGGER = _Logger()
        module.now_iso = lambda: "2026-09-25T20:00:00Z"
        module.scraper = types.SimpleNamespace(
            tier_from_value=lambda value, settings: (
                "DIAMANTE" if float(value) > 120 else "OURO" if float(value) >= 110 else "PRATA"
            )
        )
        module.promotion_revalue_assessment = lambda assessment, checkout, settings: {
            "status": "ACEITE",
            "value_score": 123.0 if float(checkout) <= 900 else 115.0,
        }

        def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
            return False, False

        def ntfy_send(title, message, *, priority=3, tags=None):
            module.sent.append((title, message, priority, tags))
            return True

        module.maybe_alert = maybe_alert
        module.ntfy_send = ntfy_send
        return module

    def test_material_price_rise_notifies_when_current_offer_is_gold(self):
        module = self._module()
        price_change_alert_guard.install(module)
        url = "https://example.com/a"
        sent, suppressed = module.maybe_alert(
            {"alert_state": {}, "offers": {}},
            {
                "loja": "Darty",
                "titulo": "Lenovo Legion 5",
                "url": url,
                "preco": 1010.0,
                "stock": True,
            },
            {},
            {"status": "ACEITE", "value_score": 112.0},
            "OURO",
            {"price": 1000.0, "value_score": 113.0, "tier": "OURO"},
            url,
            {"alerta_queda_preco_eur": 5.0, "alerta_min_tier": "OURO"},
        )
        self.assertTrue(sent)
        self.assertFalse(suppressed)
        self.assertEqual(len(module.sent), 1)
        self.assertIn("1000.00€ → 1010.00€", module.sent[0][1])

    def test_price_change_below_gold_is_suppressed(self):
        module = self._module()
        price_change_alert_guard.install(module)
        sent, suppressed = module.maybe_alert(
            {"alert_state": {}, "offers": {}},
            {
                "loja": "Darty",
                "titulo": "ASUS VivoBook",
                "url": "https://example.com/b",
                "preco": 900.0,
                "stock": True,
            },
            {},
            {"status": "ACEITE", "value_score": 105.0},
            "PRATA",
            {"price": 890.0, "value_score": 106.0, "tier": "PRATA"},
            "https://example.com/b",
            {"alerta_queda_preco_eur": 5.0, "alerta_min_tier": "OURO"},
        )
        self.assertFalse(sent)
        self.assertTrue(suppressed)
        self.assertEqual(module.sent, [])

    def test_effective_checkout_price_is_used_for_promotion_change(self):
        module = self._module()
        price_change_alert_guard.install(module)
        promo = {
            "kind": "DIRECT_DISCOUNT",
            "title": "10% extra no carrinho",
            "percent": 10.0,
            "eligibility": "explicit",
            "applicable": True,
        }
        url = "https://example.com/c"
        sent, _ = module.maybe_alert(
            {"alert_state": {}, "offers": {}},
            {
                "loja": "Darty",
                "titulo": "Lenovo Legion",
                "url": url,
                "preco": 1000.0,
                "stock": True,
                "promotions": [promo],
                "promotion_price_live_confirmed": True,
            },
            {},
            {"status": "ACEITE", "value_score": 108.0},
            "PRATA",
            {
                "price": 1000.0,
                "promotion_checkout_price": 950.0,
                "promotion_value_score": 116.0,
                "promotion_tier": "OURO",
            },
            url,
            {"alerta_queda_preco_eur": 5.0, "alerta_min_tier": "OURO"},
        )
        self.assertTrue(sent)
        self.assertIn("950.00€ → 900.00€", module.sent[0][1])
        self.assertEqual(
            900.0,
            price_change_alert_guard.current_effective_snapshot(
                module,
                {
                    "preco": 1000.0,
                    "promotions": [promo],
                    "promotion_price_live_confirmed": True,
                },
                {"status": "ACEITE", "value_score": 108.0},
                "PRATA",
                {},
            )["price"],
        )


if __name__ == "__main__":
    unittest.main()
