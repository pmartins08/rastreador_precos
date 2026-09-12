import unittest

from bs4 import BeautifulSoup

import scraper
from hardware_guard import _extra_linear_pairs
from promotion_live_guard import _configured_route_promotions, _verified_promotions


class RadioPopularLiveRouteAndSpecsTests(unittest.TestCase):
    def test_filtered_campaign_route_keeps_configured_economics(self):
        base = "https://www.radiopopular.pt/destaque/campanha-xyz?filters%5Bdisponibilidade%5D=x"
        filtered = (
            "https://www.radiopopular.pt/destaque/campanha-xyz?"
            "filters%5Bcategory_n2_name%5D%5B%5D=Computadores+Portateis&"
            "filters%5Bdisponibilidade%5D=x"
        )
        cat = {
            "url": filtered,
            "campaign_urls": [{
                "label": "50_por_250",
                "url": base,
                "promotion": {
                    "kind": "TIERED_DISCOUNT",
                    "title": "Ganha 50€ por cada 250€ em compras (até 500€)",
                    "threshold_step_eur": 250.0,
                    "step_discount_eur": 50.0,
                    "cap_eur": 500.0,
                    "eligibility": "campaign_listing",
                    "applicable": True,
                    "source": "official_campaign",
                },
            }],
        }
        configured = _configured_route_promotions(cat)
        self.assertEqual(len(configured), 1)
        self.assertEqual(configured[0]["cap_eur"], 500.0)

        live = [{
            "kind": "TIERED_DISCOUNT",
            "title": "50€ por cada 250€",
            "threshold_step_eur": 250.0,
            "step_discount_eur": 50.0,
            "cap_eur": 5500.0,
            "eligibility": "campaign_listing",
            "applicable": True,
            "source": "campaign_page_live",
        }]
        verified = _verified_promotions(configured, live)
        self.assertEqual(len(verified), 1)
        self.assertTrue(verified[0]["live_verified"])
        # A landing confirma a regra; o teto oficial configurado continua a ser 500€.
        self.assertEqual(verified[0]["cap_eur"], 500.0)

    def test_radio_popular_split_labels_extract_real_hardware(self):
        html = """
        <section>
          <div>Família de processador</div><div>AMD Ryzen™ 7</div>
          <div>Modelo de processador</div><div>260</div>
          <div>Modelo da placa gráfica discreto</div><div>NVIDIA GeForce RTX 5050</div>
          <div>Memória de placa gráfica discreta</div><div>8 GB</div>
          <div>Tipo de memória gráfica discreta</div><div>GDDR7</div>
          <div>Tipo de memória interna</div><div>DDR5-SDRAM</div>
          <div>Slots de memória</div><div>2x SO-DIMM</div>
          <div>Capacidade da memória incorporada</div><div>32 GB</div>
          <div>Capacidade total de armazenamento</div><div>1 TB</div>
          <div>Capacidade de bateria</div><div>90 Wh</div>
          <div>Tamanho do ecrã na diagonal</div><div>40,6 cm (16&quot;)</div>
          <div>Resolução</div><div>1920 x 1200 pixels</div>
          <div>Luminosidade</div><div>300 cd/m²</div>
          <div>Tipo de painel</div><div>IPS-Level</div>
          <div>Taxa máxima de actualização</div><div>165 Hz</div>
          <div>Peso</div><div>2,2 kg</div>
        </section>
        """
        soup = BeautifulSoup(html, "html.parser")
        out = scraper.specs("PC PORTÁTIL GAMING ASUS TUF A16 FA608UH-R72A55CB2")
        pairs = [*scraper.pairs(soup), *_extra_linear_pairs(soup, scraper)]
        by = {}
        for pair in pairs:
            by.setdefault(pair[0], []).append(pair)
        for key in (
            "gpu", "cpu", "ram", "storage", "vram", "battery", "weight",
            "resolution", "screen", "refresh", "brightness", "panel",
            "ram_type", "ram_slots",
        ):
            chosen = scraper.best(by.get(key, []))
            if chosen:
                scraper.apply_pair(out, key, chosen[2], chosen[3])

        self.assertEqual(out["cpu_modelo"], "ryzen 7 260")
        self.assertEqual(out["gpu_tipo"], "dedicada")
        self.assertEqual(out["gpu_modelo"], "rtx 5050")
        self.assertEqual(out["vram_gb"], 8)
        self.assertEqual(out["ram_gb"], 32)
        self.assertTrue(out["ram_expansivel"])
        self.assertEqual(out["armazenamento_tb"], 1.0)
        self.assertEqual(out["bateria_wh"], 90)
        self.assertEqual(out["ecra_res"], "fhd+")
        self.assertEqual(out["ecra_hz"], 165)
        self.assertEqual(out["ecra_tamanho"], 16.0)
        self.assertEqual(out["ecra_brightness_nits"], 300)
        self.assertEqual(out["peso_kg"], 2.2)


if __name__ == "__main__":
    unittest.main()
