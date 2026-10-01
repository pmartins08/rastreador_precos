from __future__ import annotations

import unittest
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import product_promotion_guard
import promotion_value_guard as promotion_value


class ProductPromotionGuardTests(unittest.TestCase):
    def test_darty_iva_equation_is_division_not_23_percent(self):
        html = '<main><h1>Acer Nitro V15</h1><section>1399,99€<button>Adicionar ao carrinho</button><div>Desconto do IVA Extra em Carrinho</div><p>O valor final deste produto no carrinho é: 1.399,99€ / 1,23 = 1.138,20€</p><p>Exemplo: 499€/1,23 = 405,69€.</p></section></main>'
        promos = product_promotion_guard.extract_live_product_promotions(html, store='Darty', title='Acer Nitro V15')
        self.assertEqual(promotion_value.economics(promos, 1399.99)['effective_checkout_price'], 1138.20)
        bad = html.replace('1.138,20€', '999,99€')
        self.assertEqual(promotion_value.economics(product_promotion_guard.extract_live_product_promotions(bad, store='Darty'), 1399.99)['checkout_discount_eur'], 0)

    def test_em_carrinho_percent_and_fixed(self):
        for text, price in [('-10% EXTRA em Carrinho', 1349.99), ('-100€ Extra em Carrinho', 1399.99)]:
            self.assertEqual(promotion_value.economics(promotion_value.parse_promotion_text(text), 1499.99)['effective_checkout_price'], price)

    def test_actual_runner_installs_product_probe(self):
        code = "import runner; assert runner.tracker._PRODUCT_PROMOTION_GUARD_INSTALLED; assert runner.tracker.needs_price_refresh({'price':1499.99}, {'loja':'Darty', 'preco':1499.99}, {})"
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_detects_percent_extra_in_product_checkout_context(self):
        html = """
        <html><body><main>
          <h1>Lenovo Legion 5</h1>
          <section>
            <div>Preço 1499,99€</div>
            <div class="promo">10% EXTRA NO CARRINHO</div>
            <button>Adicionar ao carrinho</button>
          </section>
        </main></body></html>
        """
        promotions = product_promotion_guard.extract_live_product_promotions(
            html, store="Darty", title="Lenovo Legion 5"
        )
        economics = promotion_value.economics(promotions, 1499.99)
        self.assertEqual(economics["checkout_discount_eur"], 150.0)
        self.assertEqual(economics["effective_checkout_price"], 1349.99)

    def test_pvpr_reference_never_becomes_checkout_discount(self):
        html = """
        <main>
          <h1>Lenovo Legion 5</h1>
          <div>PVPR: 1699,99€</div>
          <div>-12% sobre PVPR</div>
          <div>1499,99€</div>
          <button>Adicionar ao carrinho</button>
        </main>
        """
        promotions = product_promotion_guard.extract_live_product_promotions(
            html, store="Darty", title="Lenovo Legion 5"
        )
        economics = promotion_value.economics(promotions, 1499.99)
        self.assertEqual(economics["checkout_discount_eur"], 0.0)
        self.assertEqual(economics["effective_checkout_price"], 1499.99)

    def test_probe_due_respects_ttl_and_store_scope(self):
        now = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
        fresh = {"product_promotion_checked_at": (now - timedelta(hours=2)).isoformat()}
        stale = {"product_promotion_checked_at": (now - timedelta(hours=8)).isoformat()}
        item = {"loja": "Darty"}
        settings = {"product_promotion_probe_ttl_hours": 6}
        self.assertFalse(
            product_promotion_guard.probe_due(
                fresh, item, settings, current_time=now
            )
        )
        self.assertTrue(
            product_promotion_guard.probe_due(
                stale, item, settings, current_time=now
            )
        )
        self.assertFalse(
            product_promotion_guard.probe_due(
                {}, {"loja": "CHIP7"}, settings, current_time=now
            )
        )


if __name__ == "__main__":
    unittest.main()
