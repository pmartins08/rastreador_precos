from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"bloco não encontrado: {label}")
    return text.replace(old, new, 1)


tracker_path = ROOT / "tracker.py"
tracker = tracker_path.read_text(encoding="utf-8")
tracker = replace_once(tracker, 'VERSION = "8.6.1"', 'VERSION = "8.7"', "versão")
tracker = replace_once(
    tracker,
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1"}',
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7"}',
    "compatibilidade",
)

tracker = replace_once(
    tracker,
    '''    result["specs"] = extracted
    result["detail_source"] = "live"
    result["fetch_source"] = used_method''',
    '''    result["specs"] = extracted
    result["detail_source"] = "live"
    result["fetch_source"] = used_method
    result["identity_checked_at"] = now_iso()''',
    "marca identidade live",
)
tracker = replace_once(
    tracker,
    '''        "detalhes_live": 0,
        "cache_reutilizada": 0,''',
    '''        "detalhes_live": 0,
        "identity_refreshes": 0,
        "cache_reutilizada": 0,''',
    "stats identidade",
)

helper_marker = '''def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
'''
helper = '''def needs_identity_refresh(previous_meta: dict | None) -> bool:
    """Uma ficha cached só é reaberta se ainda não tiver ID forte nem tiver sido verificada para identidade."""
    if not isinstance(previous_meta, dict) or not previous_meta:
        return False
    if previous_meta.get("ean") or previous_meta.get("mpn"):
        return False
    return not bool(previous_meta.get("identity_checked_at"))


'''
tracker = replace_once(tracker, helper_marker, helper + helper_marker, "helper identidade")

tracker = replace_once(
    tracker,
    '''            "sku": item.get("sku"),
            "mpn": item.get("mpn"),
            "ean": item.get("ean"),''',
    '''            "sku": item.get("sku"),
            "mpn": item.get("mpn"),
            "ean": item.get("ean"),
            "detail_source": item.get("detail_source"),
            "identity_checked_at": item.get("identity_checked_at"),''',
    "persistência identidade",
)

start = tracker.index('    evaluated: list[dict] = []\n    to_fetch = []')
end = tracker.index('\n    tiers = {"DIAMANTE": 0, "OURO": 0, "PRATA": 0, "BRONZE": 0}', start)
new_eval = '''    evaluated: list[dict] = []
    to_fetch: list[dict] = []
    cached_pending: list[tuple[dict, dict, dict]] = []

    # Primeiro reservamos detalhe para produtos genuinamente novos. Identidade cached
    # usa apenas a folga restante, para nunca roubar cobertura aos produtos novos.
    for item in selected:
        store = item["loja"]
        if item.get("specs"):
            evaluated.append(item)
            stats[store]["avaliados"] += 1
            continue

        cached = spec_cache.get(item["url"])
        if cached:
            cached_item = dict(item)
            cached_item["specs"] = cached
            cached_item["detail_source"] = "history_cache"
            previous_meta = offer_cache.get(item["url"], {})
            for field in ("ean", "mpn", "sku", "identity_checked_at"):
                if previous_meta.get(field) and not cached_item.get(field):
                    cached_item[field] = previous_meta[field]
            cached_pending.append((item, cached_item, previous_meta))
            continue

        if reserve_detail_slot():
            to_fetch.append(item)

    max_identity_refreshes = max(0, int(settings.get("max_identity_refreshes_per_run", 12)))
    refresh_candidates = sorted(
        [
            (candidate_priority(original, weights, settings), original, cached_item, previous_meta)
            for original, cached_item, previous_meta in cached_pending
            if needs_identity_refresh(previous_meta)
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

    for original, cached_item, _ in cached_pending:
        if original["url"] in refresh_urls:
            continue
        evaluated.append(cached_item)
        store = cached_item["loja"]
        stats[store]["avaliados"] += 1
        stats[store]["cache_reutilizada"] += 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}
        for item in to_fetch:
            futures[executor.submit(enrich, item, config)] = ("new", None)
        for item, cached_item in identity_fetch:
            futures[executor.submit(enrich, item, config)] = ("identity", cached_item)

        for future in as_completed(futures):
            mode, cached_fallback = futures[future]
            item, error = future.result()
            if error.get("error"):
                if mode == "identity" and cached_fallback is not None:
                    fallback = dict(cached_fallback)
                    fallback["identity_checked_at"] = now_iso()
                    fallback["detail_source"] = "identity_refresh_failed"
                    evaluated.append(fallback)
                    store = fallback["loja"]
                    stats[store]["avaliados"] += 1
                    stats[store]["cache_reutilizada"] += 1
                continue

            store = item["loja"]
            if mode == "identity":
                item["detail_source"] = "identity_refresh"
                item["identity_checked_at"] = item.get("identity_checked_at") or now_iso()
                stats[store]["identity_refreshes"] += 1
            evaluated.append(item)
            stats[store]["avaliados"] += 1
            stats[store]["detalhes_live"] += 1
'''
tracker = tracker[:start] + new_eval + tracker[end:]

tracker = replace_once(
    tracker,
    '''    alerts += cross_store_alerts
    runtime = round(time.monotonic() - RUN_STARTED, 2)''',
    '''    alerts += cross_store_alerts
    identity_refreshes = sum(row.get("identity_refreshes", 0) for row in stats.values())
    runtime = round(time.monotonic() - RUN_STARTED, 2)''',
    "métrica identidade",
)
tracker = replace_once(
    tracker,
    '''        "detail_fetches": DETAIL_FETCHES_USED,
        "cache_reused": sum(row["cache_reutilizada"] for row in stats.values()),''',
    '''        "detail_fetches": DETAIL_FETCHES_USED,
        "identity_refreshes": identity_refreshes,
        "cache_reused": sum(row["cache_reutilizada"] for row in stats.values()),''',
    "run identidade",
)
tracker = replace_once(
    tracker,
    '''        f"Detalhes live: {run['detail_fetches']} | cache: {run['cache_reused']}\\n"
        f"Matching:''',
    '''        f"Detalhes live: {run['detail_fetches']} | cache: {run['cache_reused']} | identidade: {run.get('identity_refreshes', 0)}\\n"
        f"Matching:''',
    "heartbeat identidade",
)
tracker = replace_once(
    tracker,
    '''            "🏪 %s | cand=%d aval=%d live=%d cache=%d aceites=%d pedidos=%d bloqueada=%s",
            store,
            stat["candidatos"],
            stat["avaliados"],
            stat["detalhes_live"],
            stat["cache_reutilizada"],''',
    '''            "🏪 %s | cand=%d aval=%d live=%d id=%d cache=%d aceites=%d pedidos=%d bloqueada=%s",
            store,
            stat["candidatos"],
            stat["avaliados"],
            stat["detalhes_live"],
            stat.get("identity_refreshes", 0),
            stat["cache_reutilizada"],''',
    "log identidade",
)
tracker = tracker.replace("# Execução V8.6", "# Execução V8.7", 1)
tracker = tracker.replace('"Pré-ranking V8.6 |', '"Pré-ranking V8.7 |', 1)
tracker = tracker.replace('"V8.6 | Lojas=', '"V8.7 | Lojas=', 1)
tracker_path.write_text(tracker, encoding="utf-8")

config_path = ROOT / "config" / "config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
config.setdefault("settings", {})["max_identity_refreshes_per_run"] = 12
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

test_path = ROOT / "tests" / "test_tracker.py"
tests = test_path.read_text(encoding="utf-8")
extra = '''
    def test_identity_refresh_only_for_unchecked_missing_strong_id(self):
        self.assertTrue(tracker.needs_identity_refresh({"url": "x", "ean": None, "mpn": None}))
        self.assertFalse(tracker.needs_identity_refresh({"url": "x", "ean": "4711636176743"}))
        self.assertFalse(tracker.needs_identity_refresh({"url": "x", "identity_checked_at": "2026-09-08T00:00:00Z"}))

    def test_identity_refresh_ignores_empty_metadata(self):
        self.assertFalse(tracker.needs_identity_refresh({}))
        self.assertFalse(tracker.needs_identity_refresh(None))
'''
marker = '\n\nif __name__ == "__main__":'
if marker not in tests:
    raise SystemExit("fim da suite não encontrado")
tests = tests.replace(marker, '\n' + extra + marker, 1)
test_path.write_text(tests, encoding="utf-8")

readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8")
readme = readme.replace("V8.6.1", "V8.7")
readme += "\n\n## Identidade progressiva V8.7\n\nA cache continua a maximizar cobertura, mas a folga de detail fetches pode agora refrescar gradualmente até 12 ofertas cached por run que ainda não tenham EAN/MPN. Produtos novos mantêm sempre prioridade. Cada URL guarda `identity_checked_at`, evitando reabrir repetidamente uma ficha que já foi verificada sem encontrar um identificador forte.\n"
readme_path.write_text(readme, encoding="utf-8")

Path(__file__).unlink()
print("V8.7 preparada: enriquecimento progressivo de identidade.")
