from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"bloco não encontrado: {label}")
    return text.replace(old, new, 1)


tracker_path = ROOT / "tracker.py"
tracker = tracker_path.read_text(encoding="utf-8")
tracker = replace_once(tracker, 'VERSION = "8.6"', 'VERSION = "8.6.1"', "versão")
tracker = replace_once(
    tracker,
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6"}',
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1"}',
    "compatibilidade",
)

# Cada fallback público aprende acesso de forma independente.
tracker = replace_once(
    tracker,
    '''        segment_response, _, segment_access = adaptive_fetch(
            route["url"], config, 7, store=store, method="category_variant"
        )''',
    '''        access_method = f"category_variant:{route['label']}"
        segment_response, _, segment_access = adaptive_fetch(
            route["url"], config, 7, store=store, method=access_method
        )''',
    "método de segmento",
)

# Ranking de sitemap: dentro das marcas permitidas, famílias com maior probabilidade
# de valor/desempenho são testadas antes de URLs genéricas.
brand_block = '''def _brand_url_score(url: str) -> int:
    path = scraper.norm(urlparse(url).path.replace("-", " ").replace("_", " "))
    parent, sub = scraper.brand(path)
    if parent and sub:
        return 3
    if parent:
        return 2
    return 0
'''
brand_replacement = brand_block + '''\n\ndef _sitemap_product_score(url: str) -> int:
    text = scraper.norm(urlparse(url).path.replace("-", " ").replace("_", " "))
    score = _brand_url_score(url) * 10
    priorities = {
        "omen": 12,
        "victus": 11,
        "tuf": 12,
        "rog": 11,
        "loq": 12,
        "legion": 11,
        "zenbook": 8,
        "yoga": 8,
        "omnibook": 8,
        "vivobook": 6,
        "ideapad": 6,
        "thinkbook": 5,
        "thinkpad": 5,
    }
    for marker, bonus in priorities.items():
        if marker in text:
            score += bonus
    if any(marker in text for marker in ("rtx 5070", "rtx 5060", "rtx 5050")):
        score += 5
    return score
'''
tracker = replace_once(tracker, brand_block, brand_replacement, "prioridade sitemap")
tracker = replace_once(
    tracker,
    'found[url] = max(found.get(url, 0), _brand_url_score(url))',
    'found[url] = max(found.get(url, 0), _sitemap_product_score(url))',
    "score de sitemap",
)

# Fallback de host público para fichas de produto, mantendo URL canónico da oferta.
enrich_start = tracker.index('def enrich(item: dict, config: dict) -> tuple[dict, dict]:')
enrich_end = tracker.index('\n\ndef _empty_store_stats()', enrich_start)
old_enrich = tracker[enrich_start:enrich_end]
new_enrich = '''def _product_fetch_urls(item: dict, config: dict) -> list[tuple[str, str]]:
    original = str(item["url"])
    out = [(original, "product")]
    store = item.get("loja")
    cat = next((row for row in config.get("category_urls", []) if row.get("loja") == store), {})
    parsed = urlparse(original)
    for host in cat.get("product_fetch_host_fallbacks", []):
        fallback = parsed._replace(netloc=str(host), query="", fragment="").geturl()
        if fallback != original:
            out.append((fallback, f"product_fallback:{host}"))
    return out


def enrich(item: dict, config: dict) -> tuple[dict, dict]:
    store = item["loja"]
    response = None
    profile = None
    access = "no_response"
    used_method = "product"
    for fetch_url, method in _product_fetch_urls(item, config):
        response, profile, access = adaptive_fetch(
            fetch_url, config, 8, store=store, method=method
        )
        used_method = method
        if response and response.status_code < 400:
            break
    if not response or response.status_code >= 400:
        record_result(store, used_method, profile or "none", "access_failed")
        return item, {"error": "access_failed", "profile": profile, "access": access}

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    structured = jsonld_primary_product(soup, str(response.url), item.get("titulo", ""))
    price_ld = float(structured["preco"]) if structured.get("preco") is not None else None
    title_ld = structured.get("titulo")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    real_title = (
        (h1.get_text(" ", strip=True) if h1 else "")
        or title_ld
        or page_title
        or item.get("titulo", "")
    )
    if title_ld and len(title_ld) >= 8 and scraper.eligible(title_ld):
        real_title = title_ld

    result = dict(item)
    if real_title and scraper.eligible(real_title):
        result["titulo"] = real_title

    identifiers = page_identifiers(soup)
    for field in ("ean", "mpn", "sku"):
        value = structured.get(field) or identifiers.get(field) or result.get(field)
        if value:
            result[field] = str(value).strip()

    price = price_ld if price_ld is not None else item.get("preco")
    if price is None:
        price = scraper.best_product_price(scraper.prices(text))
    if price is not None and 200 <= float(price) <= 4500:
        result["preco"] = float(price)

    stock_value = scraper.stock(text)
    if stock_value is not None:
        result["stock"] = stock_value

    extracted = scraper.extract(result.get("titulo", real_title), soup)
    extracted["page_url"] = response.url
    extracted["acesso_profile"] = profile
    result["specs"] = extracted
    result["detail_source"] = "live"
    result["fetch_source"] = used_method

    outcome = (
        "valid_product"
        if result.get("preco") is not None and scraper.eligible(result.get("titulo", ""))
        else "no_product_or_price"
    )
    record_result(store, used_method, profile or "none", outcome)
    return result, {"error": None, "profile": profile, "access": access, "result": outcome}
'''
tracker = tracker[:enrich_start] + new_enrich + tracker[enrich_end:]

# Matching: primeiro decidir se há evidência de mesma família; IDs diferentes de
# produtos obviamente diferentes deixam de poluir a métrica de conflitos.
match_start = tracker.index('def _spec_equal(left: object, right: object) -> bool:')
match_end = tracker.index('\n\ndef build_cross_store_matches', match_start)
old_match = tracker[match_start:match_end]
new_match = '''def _spec_equal(left: object, right: object) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return scraper.norm(left or "") == scraper.norm(right or "")
    return left == right


def _title_tokens(title: str) -> set[str]:
    stop = {
        "portatil", "computador", "laptop", "gaming", "intel", "amd", "nvidia",
        "geforce", "radeon", "graphics", "windows", "sem", "ssd", "ddr4", "ddr5",
        "oled", "ips", "core", "ultra", "ryzen", "asus", "lenovo", "hp", "inc",
        "preto", "cinzento", "silver", "black", "grey", "gray", "polegadas",
    }
    out = set()
    for token in re.findall(r"[a-z0-9]+", scraper.norm(title or "")):
        if len(token) < 3 or token in stop:
            continue
        if re.fullmatch(r"\\d+(?:gb|tb|hz|w)?", token):
            continue
        out.add(token)
    return out


def _title_similarity(left: str, right: str) -> float:
    a, b = _title_tokens(left), _title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def match_configurations(left_item: dict, left_spec: dict, right_item: dict, right_spec: dict) -> dict:
    """Compara variantes entre lojas. Só EXATO/FORTE podem ser fundidos automaticamente."""
    left_brand, right_brand = left_spec.get("marca"), right_spec.get("marca")
    if left_brand and right_brand and left_brand != right_brand:
        return {"level": "SEM_MATCH", "reason": "marca diferente"}

    left_codes = _model_codes(left_item.get("titulo", ""))
    right_codes = _model_codes(right_item.get("titulo", ""))
    shared_codes = left_codes & right_codes
    title_similarity = _title_similarity(left_item.get("titulo", ""), right_item.get("titulo", ""))
    family_evidence = bool(shared_codes or title_similarity >= 0.60)

    left_ean, right_ean = _normal_id(left_item.get("ean")), _normal_id(right_item.get("ean"))
    if left_ean and right_ean:
        if left_ean == right_ean:
            return {"level": "EXATO", "reason": "EAN/GTIN idêntico", "identifier": left_ean}
        return {
            "level": "NAO_FUNDIR" if family_evidence else "SEM_MATCH",
            "reason": "EAN/GTIN diferente" if family_evidence else "EAN de produtos diferentes",
        }

    left_mpn, right_mpn = _normal_id(left_item.get("mpn")), _normal_id(right_item.get("mpn"))
    if left_mpn and right_mpn:
        if left_mpn == right_mpn:
            return {"level": "EXATO", "reason": "MPN/part number idêntico", "identifier": left_mpn}
        return {
            "level": "NAO_FUNDIR" if family_evidence else "SEM_MATCH",
            "reason": "MPN/part number diferente" if family_evidence else "MPN de produtos diferentes",
        }

    critical = ("cpu_modelo", "gpu_modelo", "ram_gb", "armazenamento_tb", "ecra_res", "ecra_hz")
    known_equal = 0
    for field in critical:
        left_value, right_value = left_spec.get(field), right_spec.get(field)
        if left_value is not None and right_value is not None:
            if not _spec_equal(left_value, right_value):
                if family_evidence:
                    return {"level": "NAO_FUNDIR", "reason": f"configuração difere em {field}"}
                return {"level": "SEM_MATCH", "reason": f"produto diferente em {field}"}
            known_equal += 1

    same_sku = bool(
        _normal_id(left_item.get("sku"))
        and _normal_id(left_item.get("sku")) == _normal_id(right_item.get("sku"))
    )
    core_fields = ("cpu_modelo", "gpu_modelo", "ram_gb", "armazenamento_tb")
    core_complete = all(
        left_spec.get(field) is not None
        and right_spec.get(field) is not None
        and _spec_equal(left_spec.get(field), right_spec.get(field))
        for field in core_fields
    )
    if shared_codes and core_complete:
        return {
            "level": "FORTE",
            "reason": "model code + CPU/GPU/RAM/SSD coincidem",
            "model_code": sorted(shared_codes)[0],
        }
    if same_sku and core_complete:
        return {"level": "FORTE", "reason": "SKU + configuração técnica coincidem"}
    if shared_codes and known_equal >= 2:
        return {
            "level": "PROVAVEL",
            "reason": "model code coincide mas faltam campos para fusão automática",
            "model_code": sorted(shared_codes)[0],
        }
    if title_similarity >= 0.72 and known_equal >= 5 and left_brand and right_brand:
        return {"level": "PROVAVEL", "reason": "título e assinatura técnica muito próximos sem ID forte"}
    return {"level": "SEM_MATCH", "reason": "evidência insuficiente"}


def _group_configuration_key(members: list[dict]) -> str:
    for field in ("ean", "mpn"):
        values = [_normal_id(member["item"].get(field)) for member in members]
        known = {value for value in values if value}
        if len(known) == 1 and len([value for value in values if value]) >= 2:
            return f"{field}:{next(iter(known))}"
    shared_codes = None
    for member in members:
        codes = _model_codes(member["item"].get("titulo", ""))
        shared_codes = codes if shared_codes is None else shared_codes & codes
    if shared_codes:
        spec = members[0]["spec"]
        code = sorted(shared_codes)[0]
        return (
            f"model:{code}|cpu:{scraper.norm(spec.get('cpu_modelo') or '?')}|"
            f"gpu:{scraper.norm(spec.get('gpu_modelo') or spec.get('gpu_tipo') or '?')}|"
            f"ram:{spec.get('ram_gb') or '?'}|ssd:{spec.get('armazenamento_tb') or '?'}"
        )
    return configuration_signature(members[0]["item"], members[0]["spec"])
'''
tracker = tracker[:match_start] + new_match + tracker[match_end:]
tracker = replace_once(
    tracker,
    '"configuration_key": configuration_signature(members[0]["item"], members[0]["spec"]),',
    '"configuration_key": _group_configuration_key(members),',
    "chave de grupo",
)

# Cross-store alert state tem de sobreviver à compactação.
tracker = replace_once(
    tracker,
    '''    out["alert_state"] = {
        key: value for key, value in alerts.items()
        if key in active_urls and isinstance(value, dict)
    }''',
    '''    out["alert_state"] = {
        key: value for key, value in alerts.items()
        if (key in active_urls or str(key).startswith("cross_store:")) and isinstance(value, dict)
    }''',
    "compactação cross-store",
)

# Alerta cross-store conservador: só tiers já notificáveis e diferença material.
insert_marker = '\n\n# ---------------------------------------------------------------------------\n# Execução V8.5\n# ---------------------------------------------------------------------------\n'
alert_func = '''\n\ndef maybe_alert_cross_store(history: dict, group: dict, settings: dict) -> bool:
    offers = group.get("offers", [])
    if len(offers) < 2:
        return False
    best, worst = offers[0], offers[-1]
    spread = float(group.get("spread_eur", 0.0))
    pct = (spread / max(1.0, float(best["price"]))) * 100.0
    min_eur = float(settings.get("cross_store_alert_min_eur", 50.0))
    min_pct = float(settings.get("cross_store_alert_min_pct", 5.0))
    if spread < min_eur and pct < min_pct:
        return False

    order = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}
    min_notify = str(settings.get("alerta_min_tier", "OURO")).upper()
    if order.get(str(best.get("tier") or ""), 0) < order.get(min_notify, 3):
        return False

    key = f"cross_store:{group['configuration_key']}"
    prior = history["alert_state"].get(key)
    if prior:
        same_store = prior.get("best_store") == best.get("loja")
        old_price = float(prior.get("best_price", best["price"]))
        old_spread = float(prior.get("spread_eur", spread))
        materially_better = float(best["price"]) <= old_price - float(settings.get("alerta_queda_preco_eur", 5.0))
        materially_wider = spread >= old_spread + min(10.0, min_eur / 2.0)
        if same_store and not materially_better and not materially_wider:
            return False

    message = (
        f"{best['titulo']}\\n"
        f"Melhor: {best['loja']} — {best['price']:.2f}€\\n"
        f"Mais cara: {worst['loja']} — {worst['price']:.2f}€\\n"
        f"Diferença: {spread:.2f}€ ({pct:.1f}%)\\n"
        f"Tier/Value melhor oferta: {best.get('tier') or '—'} / {best.get('value_score') or '—'}\\n"
        f"{best['url']}"
    )
    sent = ntfy_send(
        f"🔎 Melhor preço entre lojas: {best['loja']}",
        message,
        priority=3,
        tags=["computer", "moneybag"],
    )
    if sent:
        history["alert_state"][key] = {
            "timestamp": now_iso(),
            "best_store": best["loja"],
            "best_price": best["price"],
            "spread_eur": spread,
            "spread_pct": round(pct, 2),
        }
    return sent
'''
tracker = replace_once(tracker, insert_marker, alert_func + insert_marker.replace("V8.5", "V8.6"), "alerta cross-store")

tracker = replace_once(
    tracker,
    '''    matching = build_cross_store_matches(match_records)
    runtime = round(time.monotonic() - RUN_STARTED, 2)''',
    '''    matching = build_cross_store_matches(match_records)
    cross_store_alerts = sum(
        int(maybe_alert_cross_store(history, group, settings))
        for group in matching.get("groups", [])
    )
    alerts += cross_store_alerts
    runtime = round(time.monotonic() - RUN_STARTED, 2)''',
    "execução de alertas cross-store",
)
tracker = replace_once(
    tracker,
    '"notifications_suppressed": suppressed,',
    '"notifications_suppressed": suppressed,\n        "cross_store_alerts_sent": cross_store_alerts,',
    "métrica cross-store",
)
tracker = tracker.replace("Pré-ranking V8.5", "Pré-ranking V8.6")
tracker = tracker.replace("Merge seguro do estado V8.5", "Merge seguro do estado V8.6")
tracker_path.write_text(tracker, encoding="utf-8")

# Configuração.
config_path = ROOT / "config" / "config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
settings = config.setdefault("settings", {})
settings["cross_store_alert_min_eur"] = 50.0
settings["cross_store_alert_min_pct"] = 5.0
for cat in config.get("category_urls", []):
    if cat.get("loja") == "PCDiga":
        cat["sitemap_probe_limit"] = 10
        cat["product_fetch_host_fallbacks"] = ["publojas.pcdiga.com"]
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Regressões adicionais.
test_path = ROOT / "tests" / "test_tracker.py"
tests = test_path.read_text(encoding="utf-8")
extra = '''
    def test_sitemap_priority_prefers_performance_families(self):
        omen = "https://www.pcdiga.com/portatil-hp-omen-gaming-laptop-16-abc"
        generic = "https://www.pcdiga.com/portatil-hp-15-generic-abc"
        self.assertGreater(tracker._sitemap_product_score(omen), tracker._sitemap_product_score(generic))

    def test_product_fetch_urls_keep_canonical_and_add_public_fallback(self):
        item = {"loja": "PCDiga", "url": "https://www.pcdiga.com/path/produto"}
        cfg = {"category_urls": [{"loja": "PCDiga", "url": "https://www.pcdiga.com/cat", "product_fetch_host_fallbacks": ["publojas.pcdiga.com"]}]}
        urls = tracker._product_fetch_urls(item, cfg)
        self.assertEqual(urls[0][0], item["url"])
        self.assertEqual(urls[1][0], "https://publojas.pcdiga.com/path/produto")

    def test_unrelated_different_eans_are_not_conflicts(self):
        left = {"loja": "A", "titulo": "ASUS TUF A16", "ean": "4711636176743"}
        right = {"loja": "B", "titulo": "Lenovo LOQ 15", "ean": "199271075036"}
        left_spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        right_spec = scraper.specs("Lenovo LOQ i7-14700HX 32GB 1TB RTX 5070")
        self.assertEqual(tracker.match_configurations(left, left_spec, right, right_spec)["level"], "SEM_MATCH")

    def test_same_model_different_strong_id_is_conflict(self):
        left = {"loja": "A", "titulo": "ASUS TUF A16 FA608UH-R72B55CS2", "ean": "4711636176743"}
        right = {"loja": "B", "titulo": "ASUS TUF A16 FA608UH-R72B55CS2", "ean": "4711636338424"}
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        self.assertEqual(tracker.match_configurations(left, spec, right, spec)["level"], "NAO_FUNDIR")

    def test_cross_store_alert_requires_material_gap_and_ouro(self):
        history = {"alert_state": {}}
        group = {
            "configuration_key": "ean:4711636176743",
            "spread_eur": 100.0,
            "offers": [
                {"loja": "A", "url": "https://a/1", "titulo": "ASUS TUF", "price": 1199.0, "tier": "OURO", "value_score": 117.0},
                {"loja": "B", "url": "https://b/1", "titulo": "ASUS TUF", "price": 1299.0, "tier": "OURO", "value_score": 112.0},
            ],
        }
        with patch.object(tracker, "ntfy_send", return_value=True):
            self.assertTrue(tracker.maybe_alert_cross_store(history, group, {"alerta_min_tier": "OURO", "cross_store_alert_min_eur": 50, "cross_store_alert_min_pct": 5}))
            self.assertFalse(tracker.maybe_alert_cross_store(history, group, {"alerta_min_tier": "OURO", "cross_store_alert_min_eur": 50, "cross_store_alert_min_pct": 5}))
'''
marker = '\n\nif __name__ == "__main__":'
if marker not in tests:
    raise SystemExit("fim da suite não encontrado")
tests = tests.replace(marker, '\n' + extra + marker, 1)
test_path.write_text(tests, encoding="utf-8")

# README: notas operacionais, sem criar novos módulos.
readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8")
readme = readme.replace("V8.6", "V8.6.1")
readme += "\n\n## Refinamentos V8.6.1\n\n- O matching distingue produtos não relacionados de conflitos reais de variante.\n- Comparações cross-store só notificam quando a melhor oferta cumpre o tier mínimo e a diferença é pelo menos 50 € ou 5%.\n- A PCDiga prioriza famílias de maior interesse no sitemap e pode usar o host público `publojas.pcdiga.com` como fallback de ficha, mantendo a URL canónica da oferta.\n"
readme_path.write_text(readme, encoding="utf-8")

# One-shot: remove o próprio script antes do commit.
Path(__file__).unlink()
print("V8.6.1 preparada.")
