from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

import runner
from price_guard import page_price_evidence


class OfficialStorePriceTests(unittest.TestCase):
    def test_asus_30_day_minimum_does_not_replace_current_price(self):
        soup = BeautifulSoup(
            """
            <html><head>
              <meta itemprop="price" content="1499.99">
              <meta property="product:price:amount" content="1499.99">
            </head><body>
              <div class="current-price">1 499,99 €</div>
              <div class="price-history">
                Preço mais baixo praticado nos 30 dias anteriores à promoção
                <span class="old-price">1 299,99 €</span>
              </div>
            </body></html>
            """,
            "html.parser",
        )
        evidence = page_price_evidence(soup, runner.scraper)
        self.assertEqual(evidence["price"], 1499.99)
        self.assertEqual(evidence["confidence"], "HIGH")
        self.assertEqual(runner._safe_page_price(soup), 1499.99)

    def test_asus_current_price_is_not_replaced_by_regular_price(self):
        soup = BeautifulSoup(
            """
            <html><head>
              <meta itemprop="price" content="1199.99">
              <meta property="product:price:amount" content="1199.99">
            </head><body>
              <div class="current-price">1 199,99 €</div>
              <div class="old-price">Regular Price 1 499,99 €</div>
            </body></html>
            """,
            "html.parser",
        )
        self.assertEqual(runner._safe_page_price(soup), 1199.99)

    def test_asus_card_ignores_lower_30_day_history(self):
        card = BeautifulSoup(
            """
            <article class="product-card">
              <a href="/pt/90abc-portatil-asus-tuf.html"><h3>Portátil ASUS TUF A16</h3></a>
              <span class="current-price">1 499,99 €</span>
              <div class="price-history">
                Preço mais baixo praticado nos 30 dias anteriores à promoção
                <span class="old-price">1 299,99 €</span>
              </div>
            </article>
            """,
            "html.parser",
        ).article
        prices = runner.scraper._card_prices(card, {"loja": "ASUS Store"})
        self.assertIn(1499.99, prices)
        self.assertNotIn(1299.99, prices)

    def test_other_stores_keep_existing_card_price_parser(self):
        card = BeautifulSoup(
            '<article><span class="price">999,99 €</span></article>',
            "html.parser",
        ).article
        self.assertIn(999.99, runner.scraper._card_prices(card, {"loja": "OTHER"}))


if __name__ == "__main__":
    unittest.main()
