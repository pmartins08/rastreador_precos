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


if __name__ == "__main__":
    unittest.main()
