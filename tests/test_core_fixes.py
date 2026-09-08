import json
import unittest

from bs4 import BeautifulSoup

import runner  # aplica brain_runtime antes dos testes
import scraper
from catalog import candidate_from_card
from pricing import parse_price_value, prices


class CoreFixesTests(unittest.TestCase):
    def test_intel_hyphen_cpu_tier_and_class(self):
        model, tier, cpu_class = scraper.cpu("Intel Core i7-1255U")
        self.assertEqual(model, "i7-1255u")
        self.assertEqual(tier, "tier_2")
        self.assertEqual(cpu_class, "u_ultra")

    def test_intel_i9_shorthand_is_tier_one(self):
        _, tier, cpu_class = scraper.cpu("Intel i9-14900HX")
        self.assertEqual(tier, "tier_1")
        self.assertEqual(cpu_class, "hx")

    def test_ryzen_u_class(self):
        _, tier, cpu_class = scraper.cpu("AMD Ryzen 7 7840U")
        self.assertEqual(tier, "tier_2")
        self.assertEqual(cpu_class, "u_ultra")

    def test_european_grouped_prices(self):
        self.assertEqual(parse_price_value("1.399 €"), 1399.0)
        self.assertEqual(parse_price_value("1.399,99 €"), 1399.99)
        self.assertEqual(prices("PVP 1.399 €"), [1399.0])

    def test_card_ignores_installment_price(self):
        html = """
        <article>
          <h3>ASUS TUF Gaming A16 RTX 5070</h3>
          <a href="/portatil-asus-tuf-a16">Ver produto</a>
          <span class="price-month">49,99 € / mês</span>
          <span class="price-current">1.299,99 €</span>
        </article>
        """
        card = BeautifulSoup(html, "html.parser").article
        item = candidate_from_card(
            card,
            "https://example.com/laptops",
            {
                "loja": "TESTE",
                "product_path_hints": ["/portatil-asus-"],
            },
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["preco"], 1299.99)

    def test_jsonld_offers_list(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "ASUS TUF Gaming A16",
            "url": "https://example.com/portatil-asus-tuf-a16",
            "offers": [
                {
                    "@type": "Offer",
                    "price": "1.299,99",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }
        soup = BeautifulSoup(
            f'<script type="application/ld+json">{json.dumps(payload)}</script>',
            "html.parser",
        )
        products = scraper.jsonld_products(soup)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["preco"], 1299.99)
        self.assertTrue(products[0]["stock"])

    def test_subbrand_without_parent_is_supported(self):
        self.assertEqual(scraper.brand("ROG Zephyrus G16")[0], "asus")
        self.assertTrue(scraper.eligible("ROG Zephyrus G16 RTX 5070"))


if __name__ == "__main__":
    unittest.main()
