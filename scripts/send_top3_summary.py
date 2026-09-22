"""An explicitly requested, deduplicated summary of fresh accepted offers."""
from __future__ import annotations
import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from decision_truth_runtime_guard import _truth_from_entry
import promotion_value_guard


def timestamp(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def top3(history, settings, now=None, evaluate=None):
    now = now or datetime.now(timezone.utc)
    run = max(history['learning']['runs'], key=lambda r: r['timestamp'])
    end = timestamp(run['timestamp'])
    if not timedelta(0) <= now - end <= timedelta(hours=1):
        raise ValueError('Última execução ausente ou desatualizada')
    start = end - timedelta(seconds=float(run['runtime_seconds']) + 5)
    choices = {}
    for entries in history.get('offers', {}).values():
        if not entries:
            continue
        row = max(entries, key=lambda r: r.get('timestamp', ''))
        if not start <= timestamp(row['timestamp']) <= end or row.get('stock') is False:
            continue
        row = dict(row)
        active = any(promotion_value_guard.is_active(p) for p in row.get('promotions', []))
        if not active:
            row['promotion_price_live_confirmed'] = False
        if evaluate is not None:
            row = evaluate(row)
            if row is None:
                continue
        truth = _truth_from_entry(row, diamond_threshold=float(settings.get('diamante_value_min', 120)))
        if truth['effective_tier'] not in {'OURO', 'DIAMANTE'}:
            continue
        price = float(row.get('promotion_checkout_price') if truth['promotion_applied'] else row['price'])
        value = float(truth['effective_value_score'])
        if not math.isfinite(value) or not float(settings.get('preco_minimo_global', 250)) <= price <= float(settings.get('budget_hard', 1500)):
            continue
        candidate = dict(title=row['titulo'], store=row['loja'], url=row['url'], price=price,
                         value=value, tier=truth['effective_tier'], observed_at=row['timestamp'])
        identity = row.get('configuration_key') or row.get('ean') or row['url']
        old = choices.get(identity)
        if old is None or (value, -price) > (old['value'], -old['price']):
            choices[identity] = candidate
    result = sorted(choices.values(), key=lambda r: (-r['value'], r['price'], r['url']))[:3]
    if len(result) != 3:
        raise ValueError(f'Existem apenas {len(result)} configurações Ouro/Diamante atuais; resumo não enviado')
    return result


def persist(path, state):
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    for args in (['git', 'add', str(path.relative_to(ROOT))],
                 ['git', 'commit', '-m', 'chore: registar resumo Top3 solicitado [skip ci]'],
                 ['git', 'push', 'origin', 'HEAD:main']):
        subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request-id', required=True)
    args = parser.parse_args()
    path = ROOT / 'data/top3_summary_receipts.json'
    receipts = json.loads(path.read_text()) if path.exists() else {}
    if args.request_id in receipts:
        print('TOP3_SUMMARY_ALREADY_RESERVED_OR_SENT')
        return
    settings = json.loads((ROOT / 'config/config.json').read_text())['settings']
    # Re-evaluate fresh observed prices with the current production brain, so a
    # configuration correction during deployment cannot reuse an obsolete tier.
    sys.path.insert(0, str(ROOT))
    import runner
    config = runner.tracker.load_json(runner.tracker.CONFIG_PATH)
    settings = config['settings']
    def evaluate(row):
        result = dict(row)
        assessment = runner.tracker.score_allow_unknown(dict(row.get('specs') or {}), float(row['price']), config['weights'], settings)
        if assessment.get('status') != 'ACEITE':
            return None
        result['value_score'] = float(assessment['value_score'])
        result['tier'] = runner.scraper.tier_from_value(assessment['value_score'], settings)
        if row.get('promotion_price_live_confirmed') and float(row.get('promotion_discount_eur') or 0) > 0:
            from promotion_runtime_guard import _revalue_from_accepted
            promo = _revalue_from_accepted(runner.tracker, assessment, float(row['promotion_checkout_price']), settings)
            if promo.get('status') == 'ACEITE':
                result['promotion_value_score'] = float(promo['value_score'])
                result['promotion_tier'] = runner.scraper.tier_from_value(promo['value_score'], settings)
            else:
                result['promotion_price_live_confirmed'] = False
        return result
    rows = top3(json.loads((ROOT / 'data/history.json').read_text()), settings, evaluate=evaluate)
    topic = os.environ.get('NTFY_TOPIC', '').strip()
    if not topic:
        raise ValueError('NTFY_TOPIC ausente')
    receipts[args.request_id] = {'status': 'reserved', 'top3': rows, 'reserved_at': datetime.now(timezone.utc).isoformat()}
    persist(path, receipts)
    from curl_cffi import requests
    message = '\n\n'.join(f"{i}. {r['tier']} | {r['title']}\n{r['store']} | {r['price']:.2f}€ | Value {r['value']:.1f}\n{r['url']}" for i, r in enumerate(rows, 1))
    if args.request_id.endswith('-correction'):
        message = 'Corrige o resumo anterior: uma calibração antiga substituía o limiar Diamante de 120 por 118. Segue o Top3 recalculado com o limiar correto.\n\n' + message
    response = requests.post('https://ntfy.sh', json={'topic': topic, 'title': ('Correção — Top 3 V9 beta' if args.request_id.endswith('-correction') else 'V9 beta — Top 3 atual (resumo único)'), 'message': message, 'priority': 3, 'tags': ['computer', 'trophy']}, timeout=25, allow_redirects=False)
    response.raise_for_status()
    receipt = response.json()
    if not receipt.get('id'):
        raise ValueError('NTFY não devolveu comprovativo')
    receipts[args.request_id].update(status='sent', notification_id=receipt['id'], sent_at=datetime.now(timezone.utc).isoformat())
    persist(path, receipts)
    print('TOP3_SUMMARY_SENT ' + json.dumps(receipts[args.request_id], ensure_ascii=False))


if __name__ == '__main__':
    main()
