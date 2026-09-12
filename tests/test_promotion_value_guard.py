from __future__ import annotations

from datetime import date
import unittest

import promotion_value_guard as guard


class PromotionValueGuardTests(unittest.TestCase):
    def test_radio_popular_50_per_250_schedule(self):
        cases = [
            (249.99, 0.0), (250.0, 50.0), (499.99, 50.0), (500.0, 100.0),
            (749.99, 100.0), (750.0, 150.0), (999.99, 150.0), (1000.0, 200.0),
            (1249.99, 200.0), (1250.0, 250.0), (1499.99, 250.0), (1500.0, 300.0),
            (2250.0, 450.0), (2500.0, 500.0), (3000.0, 500.0),
        ]
        for price, expected in cases:
            with self.subTest(price=price):
                self.assertEqual(
                    guard.tiered_discount(price, step_eur=250, discount_eur=50, cap_eur=500),
                    expected,
                )

    def test_expired_promotion_has_no_economic_effect(self):
        promo = {
            "kind": "DIRECT_DISCOUNT", "value_eur": 100, "applicable": True,
            "eligibility": "explicit", "valid_until": "2020-01-01",
        }
        self.assertFalse(guard.is_active(promo, date(2026, 9, 12)))
        self.assertEqual(guard.promotion_discount(promo, 999), 0.0)

    def test_potential_campaign_is_not_applied_to_checkout(self):
        promo = {
            "kind": "TIERED_DISCOUNT", "step_discount_eur": 50,
            "threshold_step_eur": 250, "cap_eur": 500,
            "eligibility": "potential", "applicable": True,
        }
        self.assertEqual(guard.economics([promo], 999)["effective_checkout_price"], 999.0)

    def test_confirmed_campaign_listing_changes_checkout_only(self):
        promo = {
            "kind": "TIERED_DISCOUNT", "step_discount_eur": 50,
            "threshold_step_eur": 250, "cap_eur": 500,
            "eligibility": "campaign_listing", "applicable": True,
        }
        economics = guard.economics([promo], 1299.99)
        self.assertEqual(economics["checkout_discount_eur"], 250.0)
        self.assertEqual(economics["effective_checkout_price"], 1049.99)

    def test_fnac_card_credit_does_not_fake_checkout_price(self):
        promo = {
            "kind": "STORE_CREDIT", "percent": 5, "eligibility": "explicit",
            "applicable": True, "requires_membership": True,
        }
        economics = guard.economics([promo], 1000)
        self.assertEqual(economics["effective_checkout_price"], 1000.0)
        self.assertEqual(economics["store_credit_eur"], 50.0)
        self.assertEqual(economics["effective_economic_price"], 950.0)

    def test_newsletter_coupon_is_conditional_until_qualification_confirmed(self):
        promo = {
            "kind": "COUPON", "value_eur": 5, "eligibility": "conditional",
            "applicable": True, "requires_subscription": True,
        }
        self.assertEqual(guard.economics([promo], 599)["checkout_discount_eur"], 0.0)
        promo["qualification_confirmed"] = True
        self.assertEqual(guard.economics([promo], 599)["checkout_discount_eur"], 5.0)

    def test_gift_and_financing_never_reduce_price(self):
        promos = [
            {"kind": "GIFT", "title": "Oferta: CONTROL Resonant", "eligibility": "explicit", "applicable": True},
            {"kind": "FINANCING", "title": "Até 24x sem juros", "eligibility": "explicit", "applicable": True},
        ]
        economics = guard.economics(promos, 1499)
        self.assertEqual(economics["effective_checkout_price"], 1499.0)
        self.assertEqual(economics["economic_benefit_eur"], 0.0)
        self.assertIn("Oferta: CONTROL Resonant", economics["gifts"])
        self.assertIn("Até 24x sem juros", economics["financing"])

    def test_parser_recognizes_radio_popular_tiered_promotion(self):
        promos = guard.parse_promotion_text(
            "12 a 15 de setembro de 2026. Ganha 50€ por cada 250€ em compras. Até 500€ desconto.",
            source="official", eligibility="campaign_listing",
        )
        promo = next(p for p in promos if p["kind"] == "TIERED_DISCOUNT")
        self.assertEqual(promo["step_discount_eur"], 50.0)
        self.assertEqual(promo["threshold_step_eur"], 250.0)
        self.assertEqual(promo["cap_eur"], 500.0)
        self.assertEqual(promo["valid_from"], "2026-09-12")
        self.assertEqual(promo["valid_until"], "2026-09-15")

    def test_parser_recognizes_fnac_credit_without_calling_it_discount(self):
        promos = guard.parse_promotion_text("5% em Cartão FNAC. Acumula 30€", source="product")
        kinds = [p["kind"] for p in promos]
        self.assertEqual(kinds.count("STORE_CREDIT"), 2)
        self.assertFalse(any(p["kind"] == "DIRECT_DISCOUNT" for p in promos))

    def test_parser_recognizes_cart_discount_and_coupon(self):
        cart = guard.parse_promotion_text("-5€ extra no carrinho", source="product")
        self.assertEqual(cart[0]["kind"], "DIRECT_DISCOUNT")
        coupon = guard.parse_promotion_text("10% desconto extra com código AULAS10", source="product")
        self.assertEqual(coupon[0]["kind"], "COUPON")
        self.assertEqual(coupon[0]["code"], "AULAS10")

    def test_parser_recognizes_gift_and_zero_interest_as_non_cash(self):
        promos = guard.parse_promotion_text("OFERTA: Norton. Até 24x Sem Juros", source="product")
        self.assertIn("GIFT", {p["kind"] for p in promos})
        self.assertIn("FINANCING", {p["kind"] for p in promos})


if __name__ == "__main__":
    unittest.main()
