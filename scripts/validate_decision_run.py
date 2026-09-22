from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

def parse_time(value):
    text = str(value or '').strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

data = json.loads(Path('data/history.json').read_text(encoding='utf-8'))
runs = (data.get('learning', {}) or {}).get('runs', []) or []
if not runs:
    raise SystemExit('Sem run V9 no histórico do benchmark')
run = max(runs, key=lambda row: str(row.get('timestamp') or ''))

base_tiers = run.get('base_tiers') or {}
effective_tiers = run.get('effective_tiers') or {}
canonical_tiers = run.get('tiers') or {}
truth = run.get('decision_truth') or {}
effective_top = run.get('effective_top') or []

if canonical_tiers != effective_tiers:
    raise SystemExit(
        f'tiers canónico diverge de effective_tiers: {canonical_tiers} != {effective_tiers}'
    )
if not base_tiers or not effective_tiers:
    raise SystemExit('base_tiers/effective_tiers ausentes no runtime V9')
if not truth:
    raise SystemExit('metadata decision_truth ausente no runtime V9')
if run.get('total_accepted', 0) and not effective_top:
    raise SystemExit('effective_top vazio apesar de existirem ofertas aceites')

run_time = parse_time(run.get('timestamp'))
runtime = float(run.get('runtime_seconds') or 0.0)
cutoff = run_time - timedelta(seconds=runtime + 5.0)
ceiling = run_time + timedelta(minutes=5)
recent = {}
for entries in (data.get('offers', {}) or {}).values():
    if not isinstance(entries, list):
        continue
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stamp = parse_time(entry.get('timestamp'))
        url = str(entry.get('url') or '')
        if not stamp or not url or stamp < cutoff or stamp > ceiling:
            continue
        previous = recent.get(url)
        if previous is None or stamp >= parse_time(previous.get('timestamp')):
            recent[url] = entry

counts = {'DIAMANTE': 0, 'OURO': 0, 'PRATA': 0, 'BRONZE': 0}
for entry in recent.values():
    if entry.get('decision_truth_schema') != 1:
        raise SystemExit(f'entrada recente sem decision_truth_schema=1: {entry.get("url")}')
    tier = str(entry.get('effective_tier') or '')
    value = float(entry.get('effective_value_score') or 0.0)
    if tier in counts:
        counts[tier] += 1
    if value > 120.0 and tier != 'DIAMANTE':
        raise SystemExit(
            f'invariante Value>120 quebrada: {value} => {tier} ({entry.get("url")})'
        )

if counts != effective_tiers:
    raise SystemExit(
        f'histórico recente diverge do resumo effective_tiers: {counts} != {effective_tiers}'
    )

print(
    'V9 E2E OK | '
    f"descobertos={run.get('total_candidates')} | "
    f"avaliados={run.get('total_evaluated')} | "
    f"aceites={run.get('total_accepted')} | "
    f"requests={run.get('access_requests')} | "
    f"detail={run.get('detail_fetches')} | "
    f"cache={run.get('cache_reused')} | "
    f"tempo={run.get('runtime_seconds')}s | "
    f"base={base_tiers} | effective={effective_tiers}"
)
print('V9 effective_top:', effective_top[:3])
