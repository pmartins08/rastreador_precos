import unittest

from bs4 import BeautifulSoup

import scraper
import radio_popular_card_guard


class RadioPopularCardGuardTests(unittest.TestCase):
    def setUp(self):
        # O módulo pode já estar instalado através de runner noutros testes; aqui
        # construímos uma cópia mínima do comportamento restaurando apenas o flag.
        if not getattr(scraper, "_RADIO_POPULAR_CARD_GUARD_INSTALLED", False):
            radio_popular_card_guard.install(scraper)
        self.cat = {
            "loja": "Radio Popular",
            "url": "https://www.radiopopular.pt/destaque/campanha",
            "product_path_hints": ["/produto/"],
        }

    def test_offer_title_before_designation_does_not_drop_product(self):
        html = '''
        <article class="product-grid-module module product link IPO-B-MIX_MATCH">
          <div class="offer-title">OFERTA: Norton</div>
          <div class="designation px-2">
            <a href="https://www.radiopopular.pt/produto/pc-portatil-asus-fa608uh-r72a55cb2">
              PC PORTÁTIL GAMING ASUS TUF A16 FA608UH-R72A55CB2
            </a>
          </div>
          <div class="old-price notranslate fl">PVPR* €1799,99</div>
          <div class="price notranslate fl" content="1299.99">1.299,99</div>
        </article>
        '''
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(card, self.cat["url"], self.cat)
        self.assertIsNotNone(item)
        self.assertEqual(item["titulo"], "PC PORTÁTIL GAMING ASUS TUF A16 FA608UH-R72A55CB2")
        self.assertEqual(item["preco"], 1299.99)
        self.assertTrue(item["url"].endswith("/pc-portatil-asus-fa608uh-r72a55cb2"))

    def test_pvpr_is_not_used_as_current_price(self):
        html = '''
        <article class="product-grid-module module product link">
          <div class="offer-title">OFERTA: Norton</div>
          <div class="designation"><a href="/produto/pc-portatil-asus-test">
            PC PORTÁTIL ASUS TUF A16 TEST
          </a></div>
          <div class="old-price notranslate fl" content="1799.99">PVPR 1.799,99</div>
          <div class="price notranslate fl" content="1299.99">1.299,99</div>
        </article>
        '''
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(card, self.cat["url"], self.cat)
        self.assertIsNotNone(item)
        self.assertEqual(item["preco"], 1299.99)

    def test_other_store_keeps_base_parser_result(self):
        html = '''
        <article><h3>Portátil ASUS Vivobook 16</h3>
          <a href="https://example.com/produto/asus">Portátil ASUS Vivobook 16</a>
          <div class="price" content="699.99">699,99</div>
        </article>
        '''
        cat = {
            "loja": "Outra",
            "url": "https://example.com/categoria",
            "product_path_hints": ["/produto/"],
        }
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(card, cat["url"], cat)
        self.assertIsNotNone(item)
        self.assertEqual(item["preco"], 699.99)


if __name__ == "__main__":
    unittest.main()
