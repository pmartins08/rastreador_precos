import importlib.util
from pathlib import Path
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('top3_summary', Path('scripts/send_top3_summary.py'))
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)

class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        self.h = {'learning': {'runs': [{'timestamp': self.now.isoformat(), 'runtime_seconds': 100}]}, 'offers': {}}
        for i, value in enumerate([123.3, 118.0, 115.0]):
            self.h['offers'][str(i)] = [dict(timestamp=self.now.isoformat(), stock=True, price=1000, value_score=value, tier='OURO', titulo=str(i), loja='TEST', url='https://test/' + str(i), configuration_key=str(i))]

    def test_raw_diamond_and_configuration_deduplication(self):
        duplicate = dict(self.h['offers']['0'][0], url='https://other/0', price=1100)
        self.h['offers']['duplicate'] = [duplicate]
        rows = summary.top3(self.h, {}, self.now)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['tier'], 'DIAMANTE')
        self.assertEqual(rows[0]['price'], 1000)

    def test_current_evaluator_replaces_obsolete_tier(self):
        def evaluate(row):
            return dict(row, tier='OURO', value_score=115.0)
        rows = summary.top3(self.h, {}, self.now, evaluate=evaluate)
        self.assertTrue(all(r['tier'] == 'OURO' and r['value'] == 115 for r in rows))

    def test_stale_run_is_never_sent(self):
        with self.assertRaises(ValueError):
            summary.top3(self.h, {}, datetime(2026, 9, 23, tzinfo=timezone.utc))

    def test_expired_promotion_does_not_inflate_value(self):
        row = self.h['offers']['1'][0]
        row.update(promotion_price_live_confirmed=True, promotion_tier='DIAMANTE', promotion_value_score=150, promotion_checkout_price=800, promotion_discount_eur=200, promotions=[{'valid_until': '2020-01-01'}])
        rows = summary.top3(self.h, {}, self.now)
        self.assertEqual(rows[1]['value'], 118)
        self.assertEqual(rows[1]['price'], 1000)

    def test_silver_or_out_of_stock_never_fills_top_three(self):
        for change in ({'tier':'PRATA'}, {'stock':False}):
            with self.subTest(change=change):
                old = dict(self.h['offers']['2'][0])
                self.h['offers']['2'][0].update(change)
                with self.assertRaises(ValueError):
                    summary.top3(self.h, {}, self.now)
                self.h['offers']['2'][0] = old

    def test_existing_reservation_prevents_network_and_new_send(self):
        with patch.object(summary.sys, 'argv', ['send_top3_summary', '--request-id', 'test']), patch.object(Path, 'exists', return_value=True), patch.object(Path, 'read_text', return_value='{"test":{"status":"reserved"}}'), patch.object(summary, 'persist') as persist, patch.object(summary, 'top3') as select:
            summary.main()
            persist.assert_not_called()
            select.assert_not_called()
