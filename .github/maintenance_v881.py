from pathlib import Path
import json


def must_replace(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    if old not in text:
        raise SystemExit(f"marker não encontrado: {label}")
    return text.replace(old, new, count)


# price_guard: versão + timestamp real da confirmação de preço.
p = Path("price_guard.py")
text = p.read_text(encoding="utf-8")
text = must_replace(
    text,
    "from typing import Any\n",
    "from typing import Any\nfrom datetime import datetime, timezone\n",
    "price_guard import",
)
text = must_replace(text, 'VERSION = "8.8"', 'VERSION = "8.8.1"', "price_guard version")
needle = '        result["price_evidence_count"] = evidence["source_count"]\n'
text = must_replace(
    text,
    needle,
    needle + '        result["price_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")\n',
    "price_checked_at",
)
p.write_text(text, encoding="utf-8")


# tracker: versão real, compatibilidade e refresh de preço separado da cache de hardware.
p = Path("tracker.py")
text = p.read_text(encoding="utf-8")
text = must_replace(text, 'VERSION = "8.7.1"', 'VERSION = "8.8.1"', "tracker version")
text = must_replace(
    text,
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7", "8.7.1"}',
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7", "8.7.1", "8.8", "8.8.1"}',
    "compatible versions",
)
text = text.replace("V8.7.1", "V8.8.1")

marker = "\n\ndef score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:\n"
helper = '''


def needs_price_refresh(previous_meta: dict | None, item: dict, settings: dict, *, current_time: datetime | None = None) -> bool:
    """Preço atual é volátil e não deve herdar confiança indefinidamente da cache de hardware."""
    if not isinstance(previous_meta, dict) or not previous_meta:
        return False
    try:
        current_price = float(item.get("preco"))
    except (TypeError, ValueError):
        return False
    soft = float(settings.get("budget_soft", 1300.0))
    if current_price >= soft:
        return False

    previous_spec = previous_meta.get("specs") if isinstance(previous_meta.get("specs"), dict) else {}
    confirmed = previous_spec.get("price_confirmed")
    confidence = str(previous_spec.get("price_page_confidence") or "UNKNOWN").upper()
    checked_at = previous_spec.get("price_checked_at")
    if confirmed is None or confidence != "HIGH" or not checked_at:
        return True

    try:
        confirmed_value = float(confirmed)
    except (TypeError, ValueError):
        return True
    tolerance = max(
        float(settings.get("price_confirmation_tolerance_eur", 5.0)),
        max(current_price, confirmed_value) * float(settings.get("price_confirmation_tolerance_pct", 1.5)) / 100.0,
    )
    if abs(current_price - confirmed_value) > tolerance:
        return True

    try:
        stamp = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        now = current_time or datetime.now(timezone.utc)
        age_hours = max(0.0, (now - stamp).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return True
    return age_hours >= float(settings.get("price_confirmation_ttl_hours", 24.0))
'''
text = must_replace(text, marker, helper + marker, "needs_price_refresh")

text = must_replace(
    text,
    '        "identity_refreshes": 0,\n        "cache_reutilizada": 0,',
    '        "identity_refreshes": 0,\n        "price_refreshes": 0,\n        "cache_reutilizada": 0,',
    "store stats",
)

start_token = '    max_identity_refreshes = max(0, int(settings.get("max_identity_refreshes_per_run", 12)))\n'
end_token = '    for original, cached_item, _ in cached_pending:\n'
start = text.find(start_token)
end = text.find(end_token, start)
if start < 0 or end < 0:
    raise SystemExit("refresh block não encontrado")
replacement = '''    max_price_refreshes = max(0, int(settings.get("max_price_refreshes_per_run", 12)))
    price_refresh_candidates = sorted(
        [
            (candidate_priority(original, weights, settings), original, cached_item, previous_meta)
            for original, cached_item, previous_meta in cached_pending
            if needs_price_refresh(previous_meta, original, settings)
        ],
        key=lambda row: -row[0],
    )
    price_refresh_urls = set()
    price_fetch: list[tuple[dict, dict]] = []
    for _, original, cached_item, _ in price_refresh_candidates:
        if len(price_fetch) >= max_price_refreshes or not reserve_detail_slot():
            break
        price_refresh_urls.add(original["url"])
        price_fetch.append((original, cached_item))

    max_identity_refreshes = max(0, int(settings.get("max_identity_refreshes_per_run", 12)))
    refresh_candidates = sorted(
        [
            (candidate_priority(original, weights, settings), original, cached_item, previous_meta)
            for original, cached_item, previous_meta in cached_pending
            if original["url"] not in price_refresh_urls and needs_identity_refresh(previous_meta)
        ],
        key=lambda row: -row[0],
    )
    refresh_urls = set()
    identity_fetch: list[tuple[dict, dict]] = []
    for _, original, cached_item, _ in refresh_candidates:
        if len(identity_fetch) >= max_identity_refreshes or not reserve_detail_slot():
            break
        refresh_urls.add(original["url"])
        identity_fetch.append((original, cached_item))

'''
text = text[:start] + replacement + text[end:]

text = must_replace(
    text,
    '        if original["url"] in refresh_urls:\n',
    '        if original["url"] in refresh_urls or original["url"] in price_refresh_urls:\n',
    "cached skip",
)
text = must_replace(
    text,
    '        for item, cached_item in identity_fetch:\n            futures[executor.submit(enrich, item, config)] = ("identity", cached_item)\n',
    '        for item, cached_item in price_fetch:\n            futures[executor.submit(enrich, item, config)] = ("price", cached_item)\n        for item, cached_item in identity_fetch:\n            futures[executor.submit(enrich, item, config)] = ("identity", cached_item)\n',
    "executor price refresh",
)
text = must_replace(
    text,
    '                if mode == "identity" and cached_fallback is not None:\n',
    '                if mode in {"identity", "price"} and cached_fallback is not None:\n',
    "refresh fallback",
)
identity_block = '''            if mode == "identity":
                item["detail_source"] = "identity_refresh"
                item["identity_checked_at"] = item.get("identity_checked_at") or now_iso()
                stats[store]["identity_refreshes"] += 1
'''
replacement_block = identity_block + '''            elif mode == "price":
                item["detail_source"] = "price_refresh"
                stats[store]["price_refreshes"] += 1
'''
text = must_replace(text, identity_block, replacement_block, "price refresh result")

text = must_replace(
    text,
    '    identity_refreshes = sum(row.get("identity_refreshes", 0) for row in stats.values())\n',
    '    identity_refreshes = sum(row.get("identity_refreshes", 0) for row in stats.values())\n    price_refreshes = sum(row.get("price_refreshes", 0) for row in stats.values())\n',
    "price refresh total",
)
text = must_replace(
    text,
    '        "identity_refreshes": identity_refreshes,\n',
    '        "identity_refreshes": identity_refreshes,\n        "price_refreshes": price_refreshes,\n',
    "run price refresh",
)
heartbeat_old = "f\"Detalhes live: {run['detail_fetches']} | cache: {run['cache_reused']} | identidade: {run.get('identity_refreshes', 0)}\\n\""
heartbeat_new = "f\"Detalhes live: {run['detail_fetches']} | cache: {run['cache_reused']} | identidade: {run.get('identity_refreshes', 0)} | preço: {run.get('price_refreshes', 0)}\\n\""
text = must_replace(text, heartbeat_old, heartbeat_new, "heartbeat price refresh")
p.write_text(text, encoding="utf-8")


# Configurações explícitas da camada de preço.
p = Path("config/config.json")
cfg = json.loads(p.read_text(encoding="utf-8"))
s = cfg.setdefault("settings", {})
s["max_price_refreshes_per_run"] = 12
s["price_confirmation_ttl_hours"] = 24
s["price_confirmation_tolerance_eur"] = 5.0
s["price_confirmation_tolerance_pct"] = 1.5
s["exceptional_deal_bonus_max"] = 15.0
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# Regressões V8.8.1.
p = Path("tests/test_price_guard.py")
tests = p.read_text(encoding="utf-8")
if "import tracker\n" not in tests:
    tests = tests.replace("import scraper\n", "import scraper\nimport tracker\n", 1)
insert = '''

class PriceRefreshV881Tests(unittest.TestCase):
    def test_cached_low_price_without_current_confirmation_is_refreshed(self):
        previous = {"specs": {"price_confirmed": 1199.0, "price_page_confidence": "HIGH"}}
        item = {"preco": 1199.0}
        self.assertTrue(tracker.needs_price_refresh(previous, item, {"budget_soft": 1300}))

    def test_price_change_forces_refresh(self):
        previous = {"specs": {
            "price_confirmed": 1299.0,
            "price_page_confidence": "HIGH",
            "price_checked_at": "2026-09-08T12:00:00Z",
        }}
        item = {"preco": 999.0}
        self.assertTrue(tracker.needs_price_refresh(previous, item, {"budget_soft": 1300}))
'''
if "class PriceRefreshV881Tests" not in tests:
    tests = tests.replace('\n\nif __name__ == "__main__":\n', insert + '\n\nif __name__ == "__main__":\n', 1)
p.write_text(tests, encoding="utf-8")
