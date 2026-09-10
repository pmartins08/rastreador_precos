from __future__ import annotations

import types
import unittest

import price_change_priority_guard


class PriceChangePriorityGuardTests(unittest.TestCase):
    def _module(self, latest):
        module = types.SimpleNamespace()
        module._PRICE_CHANGE_PRIORITY_GUARD_INSTALLED = False
        module.candidate_priority = lambda item, weights, settings: 50.0
        module.load_history = lambda: latest
        module.compact_history = lambda history: history
        module.latest_offer_by_url = lambda history: history
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


if __name__ == "__main__":
    unittest.main()
