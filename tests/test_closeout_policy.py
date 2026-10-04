"""End-to-end scoring and delivery contracts for the post-purchase policy."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from purchase_policy import enrich_purchase_specs, installation_cost
from opportunity_guard import normalize_value_truth, historical_bonus
import scraper


class CloseoutPolicyTests(unittest.TestCase):
    def test_price_changes_below_soft_budget_are_continuous_and_bounded(self):
        settings = {'budget_soft': 1400, 'budget_hard': 1600}
        self.assertGreater(scraper.price_score(1200, settings), scraper.price_score(1300, settings))
        self.assertAlmostEqual(scraper.price_score(1399.99, settings), 150.0008)
        self.assertAlmostEqual(scraper.price_score(1400.01, settings), 149.9975)
        self.assertEqual(scraper.price_score(250, settings), 170)

    def test_unified_value_is_idempotent_and_has_no_second_gpu_penalty(self):
        row = {'status': 'ACEITE', 'value_score_sem_bonus': 120,
               'detalhes': {'Gaming': 80}, 'exceptional_deal_bonus': 15,
               'historical_price': {'available': True, 'days_observed': 5, 'new_low': True}}
        normalize_value_truth(row, unified=True)
        self.assertEqual(row['value_score'], 125)
        normalize_value_truth(row, unified=True)
        self.assertEqual(row['value_score'], 125)
        self.assertEqual(row['exceptional_deal_bonus'], 0)
        self.assertEqual(row['gpu_tier_influence']['multiplier'], 1)
        self.assertEqual(historical_bonus({'available': True, 'days_observed': 1, 'new_low': True}), 0)

    def test_os_and_keyboard_require_product_evidence(self):
        row = enrich_purchase_specs({}, 'ASUS TUF', [('os', 'Sistema operativo', 'FreeDOS', 'table'), ('keyboard', 'Teclado', 'Espanhol', 'table')], scraper.norm)
        self.assertEqual(installation_cost(row, {}), 110)
        self.assertEqual(row['keyboard_layout'], 'es')
        row = enrich_purchase_specs({}, 'ASUS Windows 11', [('os', 'Sistema operativo', 'FreeDOS', 'table')], scraper.norm)
        self.assertEqual(row['os_status'], 'conflict')
        self.assertEqual(installation_cost(row, {}), 0)
        self.assertEqual(installation_cost({}, {}), 0)

    def test_runtime_total_cost_promotions_and_diamond_only_notifications(self):
        script = r'''
import json
from unittest.mock import patch
from bs4 import BeautifulSoup
import runner, scraper, tracker
from opportunity_guard import calculate_opportunity
cfg = json.load(open('config/config.json'))
settings, weights = cfg['settings'], cfg['weights']
title = 'ASUS TUF Ryzen 7 8845HS RTX 5060 32GB 1TB'
spec = scraper.extract(title, BeautifulSoup('<table><tr><td>Sistema operativo</td><td>FreeDOS</td></tr></table>', 'html.parser'))
spec.update(price_confirmed=1400, price_confidence='HIGH', price_evidence_sources=['jsonld','meta'])
a = tracker.score_allow_unknown(spec, 1400, weights, settings)
assert a['status']=='ACEITE', a
assert a['purchase_total_eur']==1510, a
assert a['installation_cost_eur']==110, a
assert a['value_score']==calculate_opportunity(a['value_score_sem_bonus'], a['detalhes']['Gaming'])['score'], a
plain = dict(spec, os_status='windows')
b = tracker.score_allow_unknown(plain, 1400, weights, settings)
assert b['value_score'] > a['value_score'], (a,b)
promo = tracker.promotion_revalue_assessment(a, 1200, settings)
assert promo['purchase_total_eur']==1310, promo
assert promo['value_score'] > a['value_score'], (a,promo)
assert tracker.promotion_revalue_assessment(a, 1500, settings)['status']=='REJEITADO'
spec.update(price_confirmed=1500)
assert tracker.score_allow_unknown(spec, 1500, weights, settings)['status']=='REJEITADO'
spec['keyboard_layout']='es'
assert tracker.score_allow_unknown(spec, 1400, weights, settings)['status']=='REJEITADO'
# A checkout discount can rescue an otherwise over-budget OS-less laptop.
spec.pop('keyboard_layout')
spec['_purchase_item']={'url':'https://example.test/a', 'loja':'Test', 'promotion_price_live_confirmed':True,
 'promotions':[{'kind':'TIERED_DISCOUNT','title':'100 por 1000','threshold_step_eur':1000,'step_discount_eur':100,'applicable':True,'eligibility':'campaign_listing'}]}
c = tracker.score_allow_unknown(spec, 1500, weights, settings)
assert c['status']=='ACEITE', c
assert tracker.promotion_revalue_assessment(c,1400,settings)['purchase_total_eur']==1510
# All network delivery is mocked. No real notification is sent by tests.
item={'loja':'Test','titulo':title,'url':'https://example.test/a','preco':1200,'stock':True}
assessment={'status':'ACEITE','value_score':119,'score_ranking':85,'detalhes':{'Gaming':80}}
with patch.object(tracker,'ntfy_send',return_value=True) as send:
    history={'alert_state':{},'offers':{}}
    tracker.maybe_alert(history,item,{},assessment,'OURO',None,item['url'],settings)
    send.assert_not_called()
    assessment['value_score']=120
    tracker.maybe_alert(history,item,{},assessment,'DIAMANTE',None,item['url'],settings)
    assert send.call_count==1, send.call_args_list
assert scraper.tier_from_value(120,settings)=='DIAMANTE'
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflow_has_no_out_of_band_notification_senders(self):
        text = Path('.github/workflows/tracker.yml').read_text()
        self.assertNotIn('ntfy.sh', text)
        self.assertNotIn('send_top3_summary', text)
        settings = json.loads(Path('config/config.json').read_text())['settings']
        self.assertFalse(settings['heartbeat_ntfy'])
        self.assertEqual(settings['alerta_min_tier'], 'DIAMANTE')
