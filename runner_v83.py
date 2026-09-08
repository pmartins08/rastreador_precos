from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from curl_cffi import requests
import scraper

BASE = Path(__file__).resolve().parent
HISTORY_PATH = BASE / "data" / "history.json"
LEARNING_PATH = BASE / "data" / "access_learning.json"
PROFILES = ["chrome131", "chrome146", "firefox147", "edge101", "safari17_0", "safari260"]
LOCK = threading.Lock()
LOGGER = logging.getLogger("Runner")
RUN_STARTED = 0.0
RUN_DEADLINE = 0.0
REQUESTS_USED = 0
MAX_REQUESTS = 180


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def new_bucket():
    return {"attempts": 0, "successes": 0, "blocks": 0, "errors": {}, "profiles": {}, "methods": {}, "contexts": {}, "last_updated": None}


def load_learning():
    data = load_json(LEARNING_PATH)
    if data.get("schema_version") == 2:
        data.setdefault("stores", {})
        return data
    out = {"schema_version": 2, "updated_at": now_iso(), "stores": {}}
    for store, old in (data.get("stores", {}) if isinstance(data, dict) else {}).items():
        if not isinstance(old, dict): continue
        b = new_bucket()
        for k in ("attempts", "successes", "blocks"): b[k] = int(old.get(k, 0))
        b["errors"] = old.get("errors", {}) if isinstance(old.get("errors"), dict) else {}
        b["profiles"] = old.get("profiles", {}) if isinstance(old.get("profiles"), dict) else {}
        b["methods"] = old.get("methods", {}) if isinstance(old.get("methods"), dict) else {}
        b["last_updated"] = old.get("last_updated")
        out["stores"][store] = b
    return out

LEARNING = load_learning()


def bucket(store):
    return LEARNING["stores"].setdefault(store, new_bucket())


def context(store, method, profile):
    return bucket(store)["contexts"].setdefault(method, {}).setdefault(profile, {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0, "results": {}})


def record_learning(store, profile, outcome, method):
    with LOCK:
        b = bucket(store)
        b["attempts"] += 1
        b["methods"][method] = b["methods"].get(method, 0) + 1
        p = b["profiles"].setdefault(profile, {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0})
        c = context(store, method, profile)
        p["attempts"] += 1; c["attempts"] += 1
        if outcome == "success":
            b["successes"] += 1; p["successes"] += 1; c["successes"] += 1
        elif outcome == "blocked":
            b["blocks"] += 1; p["blocks"] += 1; c["blocks"] += 1
        else:
            p["errors"] += 1; c["errors"] += 1; b["errors"][outcome] = b["errors"].get(outcome, 0) + 1
        b["last_updated"] = now_iso()


def record_result(store, method, profile, result):
    with LOCK:
        r = context(store, method, profile).setdefault("results", {})
        r[result] = int(r.get(result, 0)) + 1


def profile_score(store, method, profile):
    c = bucket(store).get("contexts", {}).get(method, {}).get(profile, {})
    a, s, b = int(c.get("attempts", 0)), int(c.get("successes", 0)), int(c.get("blocks", 0))
    if a: return (s + 1.0) / (a + 2.0) - 0.35 * b / max(1, a), a
    ta = ts = tb = 0
    for other, profiles in bucket(store).get("contexts", {}).items():
        if other == method: continue
        d = profiles.get(profile, {})
        ta += int(d.get("attempts", 0)); ts += int(d.get("successes", 0)); tb += int(d.get("blocks", 0))
    if ta: return 0.9 * ((ts + 1.0) / (ta + 2.0)) - 0.35 * tb / ta, 0
    return 0.2, 0


def profile_order(store, method):
    scored = [(profile_score(store, method, p), i, p) for i, p in enumerate(PROFILES)]
    ranked = sorted(scored, key=lambda x: (-x[0][0], -x[0][1], x[1]))
    selected = [p for _, _, p in ranked if profile_score(store, method, p)[1] > 0][:2]
    fresh = [p for _, _, p in ranked if profile_score(store, method, p)[1] == 0]
    if not selected: selected = [ranked[0][2]]
    if fresh and len(selected) < 3: selected.append(fresh[0])
    return selected[:3]


def headers(profile):
    h = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7"}
    if profile.startswith("safari"):
        h["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    elif profile.startswith("firefox"):
        v = profile.removeprefix("firefox"); h["User-Agent"] = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{v}.0) Gecko/20100101 Firefox/{v}.0"
    elif profile.startswith("edge"):
        v = profile.removeprefix("edge"); h["User-Agent"] = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36 Edg/{v}.0.0.0"
    else:
        v = profile.removeprefix("chrome"); h["User-Agent"] = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    return h


def method_for_url(url):
    path = urlparse(url).path.lower()
    if path.endswith("/robots.txt"): return "robots"
    if "sitemap" in path or path.endswith(".xml"): return "sitemap"
    if any(x in path for x in ("/produto/", "/product/", "/p/")): return "product"
    return "page"


def classify(response):
    if response is None: return "no_response", True
    code = response.status_code
    if code in {401, 403, 429, 500, 502, 503, 504}: return f"http_{code}", True
    if code == 404: return "http_404", False
    if "xml" not in str(response.headers.get("Content-Type", "")).lower():
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            title = scraper.norm(soup.title.get_text(" ", strip=True) if soup.title else "")
            for node in soup(["script", "style", "noscript"]): node.decompose()
            visible = scraper.norm(" ".join(soup.stripped_strings))[:20000]
            markers = ("just a moment", "checking your browser", "verify you are human", "access denied", "robot check", "are you a robot", "captcha")
            if any(m in title or m in visible for m in markers) or "cf-chl-" in title: return "challenge", True
        except Exception: pass
    return (f"http_{code}", False) if code >= 400 else ("http_success", False)


def budget_available():
    with LOCK:
        return REQUESTS_USED < MAX_REQUESTS and (RUN_DEADLINE <= 0 or time.monotonic() < RUN_DEADLINE)


def consume_request():
    global REQUESTS_USED
    with LOCK:
        if REQUESTS_USED >= MAX_REQUESTS or (RUN_DEADLINE > 0 and time.monotonic() >= RUN_DEADLINE): return False
        REQUESTS_USED += 1
        return True


def adaptive_fetch(url, config, timeout_s=10):
    store, method = store_for_url(url, config), method_for_url(url)
    last = None
    for idx, profile in enumerate(profile_order(store, method)):
        attempts = 2 if idx == 0 else 1
        for attempt in range(attempts):
            if not consume_request(): return last, None, "run_budget_exhausted"
            try:
                response = requests.get(url, timeout=timeout_s, impersonate=profile, headers=headers(profile), allow_redirects=True)
                last = response
                outcome, retryable = classify(response)
                record_learning(store, profile, "success" if outcome == "http_success" else ("blocked" if retryable else outcome), method)
                if outcome == "http_success": return response, profile, outcome
                if not retryable: break
                if attempt == 0 and attempts == 2: time.sleep(min(6, 1 + random.random()))
            except Exception as exc:
                record_learning(store, profile, "request_error", method)
                LOGGER.warning("Acesso falhou: %s | %s | %s | %s", store, method, profile, exc)
                if attempt == 0 and attempts == 2: time.sleep(min(6, 1 + random.random()))
        if not budget_available(): break
    return last, None, classify(last)[0] if last is not None else "no_response"


def sitemap_parse(content, text, max_children=6):
    try:
        root = ET.fromstring(content); ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if root.tag.lower().endswith("sitemapindex"):
            return [], [x.text.strip() for x in root.findall("sm:sitemap/sm:loc", ns)[:max_children] if x.text]
        return [x.text.strip() for x in root.findall("sm:url/sm:loc", ns) if x.text], []
    except ET.ParseError:
        return scraper.re.findall(r"<loc>\s*(https?://[^\s<>]+)\s*</loc>", text, flags=scraper.re.I), []


def discover_sitemaps(cat, config, max_urls=30, max_indexes=5):
    origin = f"{urlparse(cat['url']).scheme}://{urlparse(cat['url']).netloc}"
    robots, _, _ = adaptive_fetch(urljoin(origin, "/robots.txt"), config, 7)
    seeds = [line.split(":", 1)[1].strip() for line in robots.text.splitlines() if line.lower().startswith("sitemap:")] if robots and robots.status_code < 400 else []
    if not seeds: seeds = [urljoin(origin, x) for x in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-products.xml")]
    seen_sm, seen_url, out = set(), set(), []
    while seeds and len(out) < max_urls and len(seen_sm) < max_indexes and budget_available():
        sm = seeds.pop(0)
        if sm in seen_sm: continue
        seen_sm.add(sm)
        response, _, _ = adaptive_fetch(sm, config, 7)
        if not response or response.status_code >= 400: continue
        urls, children = sitemap_parse(response.content, response.text, max_indexes); seeds.extend(children)
        for url in urls:
            if url in seen_url: continue
            seen_url.add(url)
            if scraper.same_host(url, cat["url"]) and scraper.product_path_ok(url, cat.get("product_path_hints", [])):
                out.append(url)
                if len(out) >= max_urls: break
    return out


def jsonld_price_title(soup):
    data = scraper.jsonld_products(soup)
    if not data: return None, None
    for x in data:
        if x.get("preco"): return x["preco"], x.get("titulo")
    return None, data[0].get("titulo")


def enrich(item, config):
    response, profile, access = adaptive_fetch(item["url"], config, 9)
    store = item["loja"]
    if not response or response.status_code >= 400:
        record_result(store, "product", profile or "none", "access_failed")
        return item, {"error": "access_failed", "profile": profile, "access": access}
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    price_ld, title_ld = jsonld_price_title(soup)
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    real_title = ((h1.get_text(" ", strip=True) if h1 else "") or page_title or title_ld or item["titulo"])
    if title_ld and len(title_ld) >= 8 and scraper.eligible(title_ld): real_title = title_ld
    extracted = scraper.extract(real_title, soup)
    price = price_ld or item.get("preco")
    if price is None:
        vals = scraper.prices(text); price = min(vals) if vals else None
    result = dict(item)
    result["titulo"] = real_title if real_title and scraper.eligible(real_title) else item["titulo"]
    if price is not None and 200 <= price <= 4500: result["preco"] = price
    stock = scraper.stock(text)
    if stock is not None: result["stock"] = stock
    extracted["page_url"] = response.url; extracted["acesso_profile"] = profile
    outcome = "valid_product" if result.get("preco") and scraper.eligible(result["titulo"]) else "no_product_or_price"
    record_result(store, "product", profile or "none", outcome)
    return {**result, "specs": extracted}, {"error": None, "profile": profile, "access": access, "result": outcome}


def score_allow_unknown(spec, price, weights, settings):
    adjusted = dict(spec)
    if adjusted.get("teclado_pt") == "desconhecido": adjusted["teclado_pt"] = "confirmado"
    return scraper.score(adjusted, price, weights, settings)


def alert_send(title, message, priority="default"):
    if not scraper.NTFY_TOPIC: return False
    payload = {"topic": scraper.NTFY_TOPIC, "title": title[:180], "message": message, "tags": ["computer", "rotating_light"], "priority": {"high": 5, "default": 3}.get(priority, 3)}
    for attempt in range(2):
        try:
            r = requests.post("https://ntfy.sh", json=payload, timeout=8); r.raise_for_status(); return True
        except Exception:
            if attempt == 0: time.sleep(1 + random.random())
    return False


def main():
    global RUN_STARTED, RUN_DEADLINE, REQUESTS_USED, MAX_REQUESTS
    RUN_STARTED = time.monotonic()
    minutes = max(1.0, float(os.getenv("RUN_MAX_MINUTES", "8")))
    RUN_DEADLINE = RUN_STARTED + minutes * 60
    config = load_json(BASE / "config" / "config.json"); settings = config.get("settings", {}); weights = config.get("weights", {})
    MAX_REQUESTS = int(os.getenv("RUN_MAX_REQUESTS", settings.get("max_requests_per_run", 180))); REQUESTS_USED = 0
    max_cat = int(settings.get("max_produtos_por_categoria", 30)); max_enrich = min(int(settings.get("max_enriquecimentos_detalhe", 48)), 24)
    hard = float(settings.get("budget_hard", 1500)); min_alert = float(settings.get("min_value_score_alerta", 70)); min_notify = settings.get("alerta_min_tier", "OURO").upper()
    history = load_json(HISTORY_PATH)
    if history.get("schema_version") != 8: history = {"schema_version": 8, "offers": {}, "alert_state": {}, "learning": {"runs": [], "stores": {}}}
    history.setdefault("offers", {}); history.setdefault("alert_state", {}); history.setdefault("learning", {"runs": [], "stores": {}})
    all_items, stats = [], {}

    for cat in config.get("category_urls", []):
        if not budget_available(): break
        store = cat["loja"]; stats[store] = {"candidatos": 0, "enriquecidos": 0, "aceites": 0, "rejeitados": 0, "bloqueada": False}
        response, profile, access = adaptive_fetch(cat["url"], config, min(9, float(cat.get("timeout_ms", 12000)) / 1000))
        candidates = scraper.discover_category(response.text, cat, max_cat) if response and response.status_code < 400 and not scraper.blocked(response)[0] else []
        if not candidates:
            if not response or response.status_code >= 400: stats[store]["bloqueada"] = True
            urls = discover_sitemaps(cat, config)
            seeds = [{"loja": store, "titulo": u.rstrip("/").split("/")[-1].replace("-", " "), "preco": None, "url": u, "stock": None} for u in urls[:8]]
            with ThreadPoolExecutor(max_workers=min(4, len(seeds) or 1)) as ex:
                for fut in as_completed([ex.submit(enrich, x, config) for x in seeds]):
                    item, err = fut.result()
                    if not err.get("error") and item.get("preco") and scraper.eligible(item.get("titulo", "")): candidates.append(item)
        clean, seen = [], set()
        for item in candidates:
            url, price = item.get("url"), item.get("preco")
            if url and price is not None and price <= hard and url not in seen and scraper.eligible(item.get("titulo", "")):
                seen.add(url); clean.append(item)
        stats[store]["candidatos"] = len(clean); all_items.extend(clean); stats[store]["acesso"] = {"perfil_categoria": profile, "resultado": access}

    unique = {}
    for item in all_items: unique.setdefault((item["loja"], item["url"]), item)
    work = sorted(unique.values(), key=lambda x: float(x.get("preco") or 99999))[:max_enrich]
    enriched = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(enrich, item, config) for item in work]
        for fut in as_completed(futures):
            item, err = fut.result()
            if not err.get("error"): enriched.append(item); stats[item["loja"]]["enriquecidos"] += 1

    order = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}; tiers = {k: 0 for k in order}; alerts = suppressed = 0
    for item in enriched:
        price = item.get("preco"); store = item["loja"]
        if price is None: continue
        spec = item.get("specs") or scraper.specs(item["titulo"]); assessment = score_allow_unknown(spec, price, weights, settings)
        if assessment.get("status") != "ACEITE": stats[store]["rejeitados"] += 1; continue
        stats[store]["aceites"] += 1
        tier = scraper.tier_from_value(assessment["value_score"], settings)
        if tier: tiers[tier] += 1
        key = f"{store}::{item['titulo']}"; entries = history["offers"].setdefault(key, []); prev = entries[-1] if entries else None
        if prev is None:
            for old in history["offers"].values():
                if old and isinstance(old[-1], dict) and old[-1].get("url") == item["url"]: prev = old[-1]; break
        base_price = prev.get("price") if prev else None; base_value = float(prev.get("value_score", 0)) if prev else 0.0; base_tier = prev.get("tier") if prev else None
        alert_key = f"{store}::{item['url']}"; prior = history["alert_state"].get(alert_key)
        entries.append({"timestamp": now_iso(), "price": price, "stock": item.get("stock"), "score_final": assessment["score_final"], "score_ranking": assessment["score_ranking"], "value_score": assessment["value_score"], "tier": tier, "specs": spec, "url": item["url"]}); del entries[:-30]
        if tier and assessment["value_score"] >= min_alert and item.get("stock") is not False:
            drop = float(settings.get("alerta_queda_preco_eur", 5)); current_base = float(prior.get("price")) if prior and prior.get("price") is not None else base_price; old_tier = prior.get("tier") if prior else base_tier
            price_drop = current_base is not None and price <= current_base - drop; opportunity = base_value < min_alert; upgrade = bool(old_tier and order.get(tier, 0) > order.get(old_tier, 0)); first = prior is None; should = first or opportunity or upgrade or price_drop; can_push = order.get(tier, 0) >= order.get(min_notify, 3)
            if should and can_push:
                emoji = {"DIAMANTE": "💎", "OURO": "🥇"}[tier]; title = f"{emoji} {tier}: {item['titulo']}"; msg = f"{item['titulo']}\nLoja: {store} | Preço: {price:.2f}€\nValue: {assessment['value_score']:.1f} | Rank: {assessment['score_ranking']:.1f}\nGPU: {spec.get('gpu_modelo') or spec.get('gpu_tipo')} | CPU: {spec.get('cpu_modelo') or '?'}\nRAM: {spec.get('ram_gb') or '?'}GB | SSD: {spec.get('armazenamento_tb') or '?'}TB\n{item['url']}"
                if alert_send(title, msg, "high" if tier == "DIAMANTE" else "default"):
                    alerts += 1; history["alert_state"][alert_key] = {"timestamp": now_iso(), "price": price, "value_score": assessment["value_score"], "tier": tier}
            elif should: suppressed += 1

    runtime = round(time.monotonic() - RUN_STARTED, 2)
    run = {"timestamp": now_iso(), "stores": stats, "total_candidates": sum(x["candidatos"] for x in stats.values()), "total_accepted": sum(x["aceites"] for x in stats.values()), "alerts_sent": alerts, "notifications_suppressed": suppressed, "access_requests": REQUESTS_USED, "runtime_seconds": runtime}
    history["learning"]["runs"].append(run); history["learning"]["runs"] = history["learning"]["runs"][-60:]
    LEARNING["schema_version"] = 2; LEARNING["updated_at"] = now_iso(); save_json(LEARNING_PATH, LEARNING); save_json(HISTORY_PATH, history)
    LOGGER.info("V8.3 | Lojas=%d | Candidatos=%d | Enriquecidos=%d | Aceites=%d | Pedidos=%d | Tempo=%.1fs | D=%d O=%d P=%d B=%d", len(stats), sum(x["candidatos"] for x in stats.values()), sum(x["enriquecidos"] for x in stats.values()), sum(x["aceites"] for x in stats.values()), REQUESTS_USED, runtime, tiers["DIAMANTE"], tiers["OURO"], tiers["PRATA"], tiers["BRONZE"])
    for store, stat in stats.items(): LOGGER.info("🏪 %s: candidatos=%d enriquecidos=%d aceites=%d rejeitados=%d bloqueada=%s acesso=%s", store, stat["candidatos"], stat["enriquecidos"], stat["aceites"], stat["rejeitados"], stat["bloqueada"], stat.get("acesso"))


if __name__ == "__main__":
    main()
