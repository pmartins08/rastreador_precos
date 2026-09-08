from pathlib import Path


def collapse_once(text: str, doubled: str, single: str, label: str) -> str:
    if doubled in text:
        text = text.replace(doubled, single, 1)
        print(f"deduplicado: {label}")
    return text


# ---------------------------------------------------------------------------
# price_guard.py — remover duplicações introduzidas pela migração concorrente.
# ---------------------------------------------------------------------------
p = Path("price_guard.py")
text = p.read_text(encoding="utf-8")
text = collapse_once(
    text,
    "from datetime import datetime, timezone\nfrom datetime import datetime, timezone\n",
    "from datetime import datetime, timezone\n",
    "import datetime",
)
price_checked = '        result["price_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")\n'
text = collapse_once(text, price_checked + price_checked, price_checked, "price_checked_at")
if text.count('VERSION = "8.8.1"') != 1:
    raise SystemExit("price_guard VERSION 8.8.1 inesperada")
if text.count(price_checked.strip()) != 1:
    raise SystemExit("price_checked_at deve existir exatamente uma vez")
p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# tracker.py — deduplicar blocos e fechar a semântica hardware-cache/preço-cache.
# ---------------------------------------------------------------------------
p = Path("tracker.py")
text = p.read_text(encoding="utf-8")

# Função needs_price_refresh duplicada: manter apenas a primeira definição.
needle = "\ndef needs_price_refresh(previous_meta: dict | None, item: dict, settings: dict, *, current_time: datetime | None = None) -> bool:"
starts = []
pos = 0
while True:
    idx = text.find(needle, pos)
    if idx < 0:
        break
    starts.append(idx)
    pos = idx + len(needle)
if len(starts) == 2:
    second = starts[1]
    end = text.find("\ndef score_allow_unknown", second)
    if end < 0:
        raise SystemExit("fim da segunda needs_price_refresh não encontrado")
    text = text[:second] + text[end:]
elif len(starts) != 1:
    raise SystemExit(f"needs_price_refresh ocorrências inesperadas: {len(starts)}")

# Dois blocos consecutivos de seleção de price_refresh: remover o segundo.
refresh_token = '    max_price_refreshes = max(0, int(settings.get("max_price_refreshes_per_run", 12)))\n'
refresh_positions = []
pos = 0
while True:
    idx = text.find(refresh_token, pos)
    if idx < 0:
        break
    refresh_positions.append(idx)
    pos = idx + len(refresh_token)
if len(refresh_positions) == 2:
    second = refresh_positions[1]
    identity = text.find('    max_identity_refreshes = max(0, int(settings.get("max_identity_refreshes_per_run", 12)))\n', second)
    if identity < 0:
        raise SystemExit("bloco identity após price refresh não encontrado")
    text = text[:second] + text[identity:]
elif len(refresh_positions) != 1:
    raise SystemExit(f"blocos price_refresh inesperados: {len(refresh_positions)}")

executor_block = '        for item, cached_item in price_fetch:\n            futures[executor.submit(enrich, item, config)] = ("price", cached_item)\n'
text = collapse_once(text, executor_block + executor_block, executor_block, "executor price_fetch")
price_result = '            elif mode == "price":\n                item["detail_source"] = "price_refresh"\n                stats[store]["price_refreshes"] += 1\n'
text = collapse_once(text, price_result + price_result, price_result, "resultado price_refresh")
sum_line = '    price_refreshes = sum(row.get("price_refreshes", 0) for row in stats.values())\n'
text = collapse_once(text, sum_line + sum_line, sum_line, "soma price_refreshes")
key_line = '        "price_refreshes": price_refreshes,\n'
text = collapse_once(text, key_line + key_line, key_line, "chave price_refreshes")

# price_checked_at também é evidência de preço, não hardware permanente.
if '    "price_checked_at",\n' not in text:
    marker = '    "price_evidence_signals",\n'
    if marker not in text:
        raise SystemExit("PRICE_EVIDENCE_FIELDS marker não encontrado")
    text = text.replace(marker, marker + '    "price_checked_at",\n', 1)

# Evidência recente pode ser reutilizada SOMENTE se continuar válida para o preço atual.
helper_marker = '\ndef score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:\n'
if 'def reusable_price_evidence(' not in text:
    helper = '''\n\ndef reusable_price_evidence(previous_meta: dict | None, item: dict, settings: dict) -> dict:\n    """Reutiliza confirmação da ficha apenas durante o TTL e se o preço atual coincidir."""\n    if not isinstance(previous_meta, dict) or not previous_meta:\n        return {}\n    try:\n        current_price = float(item.get("preco"))\n    except (TypeError, ValueError):\n        return {}\n    if current_price >= float(settings.get("budget_soft", 1300.0)):\n        return {}\n    if needs_price_refresh(previous_meta, item, settings):\n        return {}\n    previous_spec = previous_meta.get("specs") if isinstance(previous_meta.get("specs"), dict) else {}\n    fields = (\n        "price_confirmed",\n        "price_page_confidence",\n        "price_evidence_sources",\n        "price_evidence_count",\n        "price_evidence_signals",\n        "price_checked_at",\n    )\n    return {field: previous_spec[field] for field in fields if field in previous_spec}\n'''
    if helper_marker not in text:
        raise SystemExit("score_allow_unknown marker não encontrado")
    text = text.replace(helper_marker, helper + helper_marker, 1)

# Ao criar cached_item, reidratar apenas a confirmação de preço ainda válida.
cache_marker = '            cached_item["detail_source"] = "history_cache"\n            previous_meta = offer_cache.get(item["url"], {})\n'
cache_replacement = (
    '            cached_item["detail_source"] = "history_cache"\n'
    '            previous_meta = offer_cache.get(item["url"], {})\n'
    '            cached_item["specs"].update(reusable_price_evidence(previous_meta, item, settings))\n'
)
if 'cached_item["specs"].update(reusable_price_evidence' not in text:
    if cache_marker not in text:
        raise SystemExit("cached_item marker não encontrado")
    text = text.replace(cache_marker, cache_replacement, 1)

# Falha de refresh deve indicar se foi identidade ou preço.
old_failure = '                    fallback["detail_source"] = "identity_refresh_failed"\n'
new_failure = '                    fallback["detail_source"] = "price_refresh_failed" if mode == "price" else "identity_refresh_failed"\n'
if old_failure in text:
    text = text.replace(old_failure, new_failure, 1)

# Log por loja inclui refresh de preço para observabilidade.
old_log = '            "🏪 %s | cand=%d aval=%d live=%d id=%d cache=%d aceites=%d pedidos=%d bloqueada=%s",\n'
new_log = '            "🏪 %s | cand=%d aval=%d live=%d id=%d price=%d cache=%d aceites=%d pedidos=%d bloqueada=%s",\n'
if old_log in text:
    text = text.replace(old_log, new_log, 1)
    arg_marker = '            stat.get("identity_refreshes", 0),\n            stat["cache_reutilizada"],\n'
    if arg_marker not in text:
        raise SystemExit("argumentos log loja não encontrados")
    text = text.replace(
        arg_marker,
        '            stat.get("identity_refreshes", 0),\n            stat.get("price_refreshes", 0),\n            stat["cache_reutilizada"],\n',
        1,
    )

# Invariantes de fonte: cada bloco crítico apenas uma vez.
checks = {
    "needs_price_refresh": needle,
    "max_price_refreshes": refresh_token,
    "executor price_fetch": executor_block,
    "price result": price_result,
    "price sum": sum_line,
    "price key": key_line,
}
for label, token in checks.items():
    count = text.count(token)
    if count != 1:
        raise SystemExit(f"{label} deve existir 1x, encontrou {count}")
if text.count('def reusable_price_evidence(') != 1:
    raise SystemExit("reusable_price_evidence deve existir exatamente uma vez")

p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Testes adicionais contra regressões de TTL/reutilização de preço.
# ---------------------------------------------------------------------------
p = Path("tests/test_price_guard.py")
tests = p.read_text(encoding="utf-8")
if "test_recent_matching_price_evidence_is_reused" not in tests:
    insert = '''\n    def test_recent_matching_price_evidence_is_reused(self):\n        from datetime import datetime, timezone\n        now = datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc)\n        previous = {"specs": {\n            "price_confirmed": 1199.0,\n            "price_page_confidence": "HIGH",\n            "price_evidence_sources": ["jsonld", "meta"],\n            "price_evidence_count": 2,\n            "price_checked_at": "2026-09-08T17:00:00Z",\n        }}\n        item = {"preco": 1199.0}\n        settings = {"budget_soft": 1300, "price_confirmation_ttl_hours": 24}\n        self.assertFalse(tracker.needs_price_refresh(previous, item, settings, current_time=now))\n        evidence = tracker.reusable_price_evidence(previous, item, settings)\n        self.assertEqual(evidence["price_confirmed"], 1199.0)\n        self.assertEqual(evidence["price_page_confidence"], "HIGH")\n\n    def test_stale_price_evidence_is_not_reused(self):\n        previous = {"specs": {\n            "price_confirmed": 1199.0,\n            "price_page_confidence": "HIGH",\n            "price_checked_at": "2020-01-01T00:00:00Z",\n        }}\n        item = {"preco": 1199.0}\n        self.assertEqual(\n            tracker.reusable_price_evidence(previous, item, {"budget_soft": 1300, "price_confirmation_ttl_hours": 24}),\n            {},\n        )\n'''
    class_marker = 'class PriceRefreshV881Tests(unittest.TestCase):\n'
    idx = tests.find(class_marker)
    if idx < 0:
        raise SystemExit("PriceRefreshV881Tests não encontrada")
    # inserir no fim da classe, antes do if __main__
    main_marker = '\n\nif __name__ == "__main__":\n'
    if main_marker not in tests:
        raise SystemExit("main marker de testes não encontrado")
    tests = tests.replace(main_marker, insert + main_marker, 1)
p.write_text(tests, encoding="utf-8")
