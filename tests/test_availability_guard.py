import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
import unicodedata
from availability_guard import availability


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.tracker = SimpleNamespace(scraper=SimpleNamespace(norm=lambda v: unicodedata.normalize('NFKD', v).encode('ascii', 'ignore').decode().lower()))

    def test_aggregate_stock_cannot_override_no_home_delivery(self):
        item = {'loja':'Darty', 'stock':True}
        html = '<main><h1>Acer Nitro</h1>Entrega ao domícilio indisponível Recolhe na loja em 30 minutos</main>'
        row = availability(item, html, self.tracker)
        self.assertFalse(row['eligible'])
        self.assertEqual(row['status'], 'STORE_ONLY_UNVERIFIED')

    def test_home_delivery_can_confirm_darty(self):
        html = '<main><h1>Lenovo</h1>Recebe em casa Entrega 2 de outubro</main>'
        self.assertTrue(availability({'loja':'Darty','stock':True}, html, self.tracker)['eligible'])

    def test_stock_false_and_unknown_are_not_recommendations(self):
        for store in ('Darty','Globaldata','Clickfiel'):
            for stock in (False, None):
                self.assertFalse(availability({'loja':store,'stock':stock}, '', self.tracker)['eligible'])

    def test_related_products_do_not_confirm_home_delivery(self):
        html = '<main><div id="ProductInfo-test"><h1>Acer Nitro</h1>Entrega ao domícilio indisponível</div><aside>Entrega 2 de outubro</aside></main>'
        self.assertFalse(availability({'loja':'Darty','stock':True}, html, self.tracker)['eligible'])

    def test_actual_runner_rejects_unavailable_before_tiering(self):
        code = '''
import json, runner
config=json.load(open('config/config.json'))
spec=runner.scraper.specs('Acer Nitro i9-13900H RTX 5060 32GB 1TB')
spec['offer_availability']={'eligible':False,'status':'OUT_OF_STOCK'}
assessment=runner.tracker.score_allow_unknown(spec,1138.20,config['weights'],config['settings'])
assert assessment['status']=='REJEITADO',assessment
assert assessment.get('value_score') is None
assert runner.tracker.rejection_reason(assessment)=='availability_not_eligible'
assert __import__('rejection_guard')._CURRENT_REJECTION_REASON.get()=='availability_not_eligible'
'''
        # rejection_reason is imported by the telemetry guard, not exported by tracker.
        code = code.replace('runner.tracker.rejection_reason', '__import__("rejection_guard").rejection_reason')
        result = subprocess.run([sys.executable,'-c',code], cwd=Path(__file__).resolve().parents[1], capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_brain_rewards_better_display_and_confirmed_power(self):
        code = '''
import json, runner
config=json.load(open('config/config.json'))
spec=runner.scraper.specs('Lenovo Legion i7-13650HX RTX 5060 32GB 1TB 16 FHD 144Hz')
spec['teclado_pt']='confirmado'
spec['offer_availability']={'eligible':True,'status':'AVAILABLE'}
weak=dict(spec,tgp_w=60,ecra_brightness_nits=250,ecra_srgb_percent=65,ecra_painel='IPS')
strong=dict(spec,tgp_w=100,ecra_brightness_nits=500,ecra_srgb_percent=100,ecra_painel='OLED')
scores=[runner.tracker.score_allow_unknown(s,1400,config['weights'],config['settings']) for s in (weak,strong)]
assert all(s['status']=='ACEITE' for s in scores),scores
assert scores[1]['value_score']>scores[0]['value_score'],scores
assert scores[1].get('brain_policy'),scores
'''
        result = subprocess.run([sys.executable,'-c',code], cwd=Path(__file__).resolve().parents[1], capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
