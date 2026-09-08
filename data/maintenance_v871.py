from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Padrao nao encontrado: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# scraper.py — guardrails de preco sem alterar o cerebro V8
# ---------------------------------------------------------------------------
path = ROOT / "scraper.py"
text = path.read_text(encoding="utf-8")

anchor = '''def best_product_price(
    values: list[float], minimum: float = 200.0, maximum: float = 4500.0
) -> float | None:
    valid = [float(value) for value in values if minimum <= float(value) <= maximum]
    return min(valid) if valid else None
'''
insert = anchor + '''\n\n# Guardrail de ingestao: impede que mensalidades/descontos absurdamente baixos\n# entrem no ranking como se fossem o preco total do portatil. Nao altera scoring.\nGPU_PRICE_SANITY_MIN = {\n    "rtx 5090": 1500.0,\n    "rtx 5080": 1000.0,\n    "rtx 5070 ti": 800.0,\n    "rtx 5070": 650.0,\n    "rtx 5060 ti": 550.0,\n    "rtx 5060": 450.0,\n    "rtx 5050": 400.0,\n    "rtx 4090": 1200.0,\n    "rtx 4080": 900.0,\n    "rtx 4070": 600.0,\n    "rtx 4060": 450.0,\n}\n\n\ndef price_is_plausible_for_title(title: str, price: float) -> bool:\n    value = float(price)\n    _models, _kind, model = gpus(title)\n    floor = GPU_PRICE_SANITY_MIN.get(model)\n    return floor is None or value >= floor\n'''
text = replace_once(text, anchor, insert, "price guardrail")

old = '''    price = best_product_price(_card_prices(card, cat))
    if price is None:
        return None
'''
new = '''    price = best_product_price(_card_prices(card, cat))
    if price is None or not price_is_plausible_for_title(title, price):
        return None
'''
text = replace_once(text, old, new, "candidate price sanity")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# tracker.py — preco forte, EAN de URL, PCDiga e escala
# ---------------------------------------------------------------------------
path = ROOT / "tracker.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'VERSION = "8.7"', 'VERSION = "8.7.1"', "version")
text = replace_once(
    text,
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7"}',
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7", "8.7.1"}',
    "compatible versions",
)

old_priorities = '''    priorities = {
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
'''
new_priorities = '''    # Com budget hard de 1500€, priorizamos familias com maior probabilidade de
    # cair dentro do nosso universo. Series premium continuam elegiveis, mas nao
    # gastam os primeiros probes do sitemap antes de TUF/LOQ/Victus/etc.
    priorities = {
        "tuf": 18,
        "loq": 18,
        "victus": 17,
        "vivobook": 14,
        "ideapad": 14,
        "omnibook": 12,
        "yoga": 10,
        "thinkbook": 9,
        "thinkpad": 8,
        "zenbook": 7,
        "legion": 6,
        "omen": 5,
        "rog": 3,
    }
'''
text = replace_once(text, old_priorities, new_priorities, "sitemap priorities")

old = '    sitemap_limit = int(settings.get("max_sitemap_urls_per_store", 80))\n'
new = '    sitemap_limit = int(cat.get("max_sitemap_urls", settings.get("max_sitemap_urls_per_store", 80)))\n'
text = replace_once(text, old, new, "per-store sitemap limit")

page_id_anchor = '''def page_identifiers(soup: BeautifulSoup) -> dict:
    text = " ".join(soup.stripped_strings)
    out = {}
    ean = re.search(r"(?:c[oó]digo\\s*)?(?:ean|gtin(?:-?1[234])?)\\s*[:#-]?\\s*([0-9][0-9\\s-]{6,20})", text, re.I)
    if ean:
        digits = re.sub(r"\\D", "", ean.group(1))
        if gtin_valid(digits):
            out["ean"] = digits
    mpn = re.search(r"(?:part[- ]?number|part\\s*number|mpn|p\\s*/\\s*n)\\s*[:#-]?\\s*([A-Z0-9][A-Z0-9._/#-]{4,})", text, re.I)
    if mpn:
        out["mpn"] = mpn.group(1).strip().rstrip(".,;:")
    sku = re.search(r"\\bsku\\s*[:#-]?\\s*([A-Z0-9][A-Z0-9._/#-]{4,})", text, re.I)
    if sku:
        out["sku"] = sku.group(1).strip().rstrip(".,;:")
    return out
'''
page_helpers = page_id_anchor + '''\n\ndef url_ean(url: str) -> str | None:\n    """Extrai GTIN/EAN embebido no URL publico (muito util na PCDiga)."""\n    path = urlparse(str(url or "")).path\n    for digits in reversed(re.findall(r"(?<!\\d)(\\d{8}|\\d{12,14})(?!\\d)", path)):\n        if gtin_valid(digits):\n            return digits\n    return None\n\n\ndef preferred_page_price(soup: BeautifulSoup, structured_price: float | None = None) -> float | None:\n    """Preco de produto por sinais fortes; nunca usa o menor euro da pagina inteira."""\n    selectors = [\n        "meta[itemprop='price'][content]",\n        "meta[property='product:price:amount'][content]",\n        "meta[property='og:price:amount'][content]",\n        "[itemprop='offers'] [itemprop='price']",\n        "[data-price-type='finalPrice'] [data-price-amount]",\n        "[data-price-type='finalPrice']",\n        "[class*='current-price']",\n        "[class*='currentPrice']",\n        "[class*='price-current']",\n        "[class*='priceCurrent']",\n        "[class*='final-price']",\n        "[class*='finalPrice']",\n        "[class*='special-price']",\n        "[class*='sale-price']",\n    ]\n    bad = (\n        "discount", "desconto", "saving", "poupanca", "poupa", "cashback",\n        "voucher", "cupao", "coupon", "mensal", "prestacao", "installment",\n        "financiamento", "finance", "old-price", "oldprice", "preco antigo",\n    )\n    values = []\n    seen = set()\n    for selector in selectors:\n        for node in soup.select(selector):\n            marker = id(node)\n            if marker in seen:\n                continue\n            seen.add(marker)\n            context = scraper.norm(\n                " ".join([\n                    " ".join(node.get("class", [])),\n                    str(node.get("id") or ""),\n                    node.get_text(" ", strip=True),\n                ])\n            )\n            if any(token in context for token in bad):\n                continue\n            raw = (\n                node.get("content")\n                or node.get("data-price-amount")\n                or node.get("data-price")\n                or node.get_text(" ", strip=True)\n            )\n            direct = scraper.parse_price_value(raw)\n            if direct is not None and 200 <= direct <= 10000:\n                values.append(float(direct))\n                continue\n            values.extend(v for v in scraper.prices(str(raw)) if 200 <= v <= 10000)\n    if values:\n        return min(values)\n    if structured_price is not None and 200 <= float(structured_price) <= 10000:\n        return float(structured_price)\n    return None\n'''
text = replace_once(text, page_id_anchor, page_helpers, "page price helpers")

old = '''    identifiers = page_identifiers(soup)
    for field in ("ean", "mpn", "sku"):
        value = structured.get(field) or identifiers.get(field) or result.get(field)
        if value:
            result[field] = str(value).strip()

    price = price_ld if price_ld is not None else item.get("preco")
    if price is None:
        price = scraper.best_product_price(scraper.prices(text))
    if price is not None and 200 <= float(price) <= 4500:
        result["preco"] = float(price)
'''
new = '''    identifiers = page_identifiers(soup)
    if not identifiers.get("ean"):
        identifiers["ean"] = url_ean(item.get("url", ""))
    for field in ("ean", "mpn", "sku"):
        value = structured.get(field) or identifiers.get(field) or result.get(field)
        if value:
            result[field] = str(value).strip()

    existing_price = item.get("preco")
    strong_page_price = preferred_page_price(soup, price_ld)
    if existing_price is not None and scraper.price_is_plausible_for_title(
        result.get("titulo", real_title), float(existing_price)
    ):
        price = float(existing_price)
    else:
        price = strong_page_price
    if price is not None and 200 <= float(price) <= 10000:
        result["preco"] = float(price)
'''
text = replace_once(text, old, new, "enrich price reconciliation")

old_seed = '''                seed = {
                    "loja": store,
                    "titulo": url.rstrip("/").split("/")[-1].replace("-", " "),
                    "preco": None,
                    "url": url,
                    "stock": None,
                }
'''
new_seed = '''                seed = {
                    "loja": store,
                    "titulo": url.rstrip("/").split("/")[-1].replace("-", " "),
                    "preco": None,
                    "url": url,
                    "stock": None,
                    "ean": url_ean(url),
                }
'''
text = replace_once(text, old_seed, new_seed, "sitemap seed EAN")

old_fail = '''                if mode == "identity" and cached_fallback is not None:
                    fallback = dict(cached_fallback)
                    fallback["identity_checked_at"] = now_iso()
                    fallback["detail_source"] = "identity_refresh_failed"
                    evaluated.append(fallback)
'''
new_fail = '''                if mode == "identity" and cached_fallback is not None:
                    # Falha de rede/acesso nao conta como identidade verificada; pode
                    # voltar a ser tentada numa run futura dentro do limite progressivo.
                    fallback = dict(cached_fallback)
                    fallback["detail_source"] = "identity_refresh_failed"
                    evaluated.append(fallback)
'''
text = replace_once(text, old_fail, new_fail, "identity failure retry")

old_eval = '''        price = item.get("preco")
        store = item["loja"]
        if price is None:
            continue
        spec = item.get("specs") or scraper.specs(item.get("titulo", ""))
        assessment = score_allow_unknown(spec, float(price), weights, settings)
'''
new_eval = '''        price = item.get("preco")
        store = item["loja"]
        if price is None:
            continue
        if not (min_price <= float(price) <= hard):
            stats[store]["rejeitados"] += 1
            continue
        if not scraper.price_is_plausible_for_title(item.get("titulo", ""), float(price)):
            stats[store]["rejeitados"] += 1
            continue
        spec = item.get("specs") or scraper.specs(item.get("titulo", ""))
        assessment = score_allow_unknown(spec, float(price), weights, settings)
'''
text = replace_once(text, old_eval, new_eval, "post-enrich hard budget")

text = text.replace('"Pré-ranking V8.7 |', '"Pré-ranking V8.7.1 |', 1)
text = text.replace('"V8.7 | Lojas=%d', '"V8.7.1 | Lojas=%d', 1)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# config — capacidade maior, mas ainda limitada por deadline e budgets
# ---------------------------------------------------------------------------
path = ROOT / "config" / "config.json"
config = json.loads(path.read_text(encoding="utf-8"))
settings = config["settings"]
settings["max_evaluated_per_run"] = 180
settings["max_detail_fetches_per_run"] = 70
settings["max_requests_per_run"] = 240
settings["max_requests_per_store"] = 50
settings["max_identity_refreshes_per_run"] = 16
settings["max_sitemap_urls_per_store"] = 100
for cat in config["category_urls"]:
    if cat["loja"] == "PCDiga":
        cat["target_candidates"] = 60
        cat["sitemap_probe_limit"] = 16
        cat["max_sitemaps"] = 6
        cat["max_sitemap_urls"] = 160
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# workflow — nomes/limites coerentes com V8.7.1
# ---------------------------------------------------------------------------
path = ROOT / ".github" / "workflows" / "tracker.yml"
workflow = path.read_text(encoding="utf-8")
workflow = workflow.replace("rastreador-precos-v86-main", "rastreador-precos-v87-main")
workflow = workflow.replace("Testes V8 + V8.6", "Testes V8 + V8.7")
workflow = workflow.replace("Executar Rastreador V8.6 adaptativo", "Executar Rastreador V8.7.1 adaptativo")
workflow = workflow.replace("RUN_MAX_REQUESTS: '180'", "RUN_MAX_REQUESTS: '240'")
workflow = workflow.replace("RUN_MAX_REQUESTS_PER_STORE: '40'", "RUN_MAX_REQUESTS_PER_STORE: '50'")
workflow = workflow.replace("RUN_MAX_DETAIL_FETCHES: '50'", "RUN_MAX_DETAIL_FETCHES: '70'")
workflow = workflow.replace("Rastreador V8.6 falhou", "Rastreador V8.7.1 falhou")
workflow = workflow.replace("pipeline V8.6", "pipeline V8.7.1")
workflow = workflow.replace("/tmp/history-v86.json", "/tmp/history-v87.json")
workflow = workflow.replace("/tmp/access-learning-v86.json", "/tmp/access-learning-v87.json")
workflow = workflow.replace("estado V8.6", "estado V8.7.1")
workflow = workflow.replace("Estado V8.6", "Estado V8.7.1")
path.write_text(workflow, encoding="utf-8")


# ---------------------------------------------------------------------------
# testes de regressao
# ---------------------------------------------------------------------------
path = ROOT / "tests" / "test_tracker.py"
tests = path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n    unittest.main()\n'
extra = r'''

class PriceSafetyV871Tests(unittest.TestCase):
    def test_absurd_rtx5090_card_price_is_rejected(self):
        html = """
        <article>
          <h3>ASUS ROG Strix Scar 16 RTX 5090 64GB 2TB</h3>
          <a href="/portatil-asus-rog-rtx5090">Produto</a>
          <span class="price-current">449,90 €</span>
        </article>
        """
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(
            card,
            "https://example.com/laptops",
            {"loja": "TEST", "product_path_hints": ["/portatil-asus-"]},
        )
        self.assertIsNone(item)

    def test_preferred_page_price_ignores_discount_amount(self):
        soup = BeautifulSoup(
            """
            <div>
              <span class="price-current">1.499,99 €</span>
              <span class="old-price">2.299,99 €</span>
              <span class="discount">-800,00 €</span>
            </div>
            """,
            "html.parser",
        )
        self.assertEqual(tracker.preferred_page_price(soup, 800.0), 1499.99)

    def test_url_ean_extracts_pcdiga_identifier(self):
        url = (
            "https://www.pcdiga.com/computadores-e-software/computadores-laptop/"
            "computadores-portateis/portatil-asus-tuf-90nr0kv1-m00h70-4711636583923"
        )
        self.assertEqual(tracker.url_ean(url), "4711636583923")

    def test_price_guardrail_allows_normal_rtx5060_deal(self):
        self.assertTrue(scraper.price_is_plausible_for_title("ASUS TUF RTX 5060", 899.0))
        self.assertFalse(scraper.price_is_plausible_for_title("ASUS ROG RTX 5090", 449.9))
'''
if marker not in tests:
    raise RuntimeError("Marcador final de testes nao encontrado")
tests = tests.replace(marker, extra + marker, 1)
path.write_text(tests, encoding="utf-8")


# ---------------------------------------------------------------------------
# limpeza pontual das duas observacoes falsas detetadas na run #127
# ---------------------------------------------------------------------------
path = ROOT / "data" / "history.json"
history = json.loads(path.read_text(encoding="utf-8"))
for key in list((history.get("offers") or {}).keys()):
    entries = history["offers"].get(key)
    if not isinstance(entries, list):
        continue
    cleaned = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("titulo") or "")
        price = float(entry.get("price") or 0)
        ean = str(entry.get("ean") or "")
        false_pcdiga = entry.get("loja") == "PCDiga" and ean == "4711636583923" and abs(price - 800.0) < 0.01
        false_global = entry.get("loja") == "Globaldata" and "G635LX" in title and price < 1500
        if false_pcdiga or false_global:
            continue
        cleaned.append(entry)
    if cleaned:
        history["offers"][key] = cleaned
    else:
        history["offers"].pop(key, None)
(history.get("alert_state") or {}).pop("cross_store:ean:4711636583923", None)
path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("V8.7.1 preparada: preco seguro, PCDiga otimizada e capacidade ampliada.")
