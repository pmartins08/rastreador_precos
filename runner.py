from __future__ import annotations

import json
import logging
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
PROFILES = ["chrome131", "chrome124", "safari17_0"]
LOCK = threading.Lock()
LOGGER = logging.getLogger("Runner")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def store_for_url(url: str, config: dict) -> str:
    host = urlparse(url).netloc
    for cat in config.get("category_urls", []):
        if urlparse(cat.get("url", "")).netloc == host:
            return cat.get("loja", host)
    return host


def learning_bucket(store: str) -> dict:
    with LOCK:
        data = load_json(LEARNING_PATH)
        stores = data.setdefault("stores", {})
        bucket = stores.setdefault(store, {"attempts": 0, "successes": 0, "blocks": 0, "errors": {}, "profiles": {}, "methods": {}, "last_updated": None})
        return bucket


def record_learning(store: str, profile: str, outcome: str, method: str) -> None:
    with LOCK:
        data = load_json(LEARNING_PATH)
        bucket = data.setdefault("stores", {}).setdefault(store, {"attempts": 0, "successes": 0, "blocks": 0, "errors": {}, "profiles": {}, "methods": {}, "last_updated": None})
        bucket["attempts"] += 1
        bucket["methods"][method] = bucket["methods"].get(method, 0) + 1
        p = bucket["profiles"].setdefault(profile, {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0})
        p["attempts"] += 1
        if outcome == "success":
            bucket["successes"] += 1
            p["successes"] += 1
        elif outcome == "blocked":
            bucket["blocks"] += 1
            p["blocks"] += 1
        else:
            p["errors"] += 1
            bucket["errors"][outcome] = bucket["errors"].get(outcome, 0) + 1
        bucket["last_updated"] = now_iso()
        data["schema_version"] = 1
        data.setdefault("updated_at", now_iso())
        save_json(LEARNING_PATH, data)


def profile_order(store: str) -> list[str]:
    bucket = learning_bucket(store)
    profiles = bucket.get("profiles", {})
    return sorted(PROFILES, key=lambda p: (-profiles.get(p, {}).get("successes", 0), profiles.get(p, {}).get("blocks", 0), profiles.get(p, {}).get("attempts", 0), PROFILES.index(p)))


def header_for(profile: str) -> dict:
    if profile == "safari17_0":
        return {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15", "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7"}
    version = profile.removeprefix("chrome")
    return {"User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8", "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8"}


def method_for_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith("/robots.txt"):
        return "robots"
    if "sitemap" in path or path.endswith(".xml"):
        return "sitemap"
    return "page"


def is_challenge(response) -> bool:
    try:
        soup = BeautifulSoup(response.text, "html.parser")
        title = scraper.norm(soup.title.get_text(" ", strip=True) if soup.title else "")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        visible = scraper.norm(" ".join(soup.stripped_strings))[:20000]
        markers = ["just a moment", "checking your browser", "verify you are human", "access denied", "robot check", "are you a robot"]
        return any(x in title or x in visible for x in markers) or "cf-chl-" in title or "captcha" in title
    except Exception:
        return False


def adaptive_fetch(url: str, config: dict, timeout_s: float = 15.0):
    store = store_for_url(url, config)
    method = method_for_url(url)
    last = None
    for profile in profile_order(store):
        for attempt in range(2):
            try:
                response = requests.get(url, timeout=timeout_s, impersonate=profile, headers=header_for(profile), allow_redirects=True)
                last = response
                blocked = response.status_code in {401, 403, 429, 500, 502, 503, 504} or is_challenge(response)
                if not blocked and response.status_code < 400:
                    record_learning(store, profile, "success", method)
                    return response, profile
                record_learning(store, profile, "blocked" if blocked else f"http_{response.status_code}", method)
                if response.status_code not in {408, 425, 429, 500, 502, 503, 504} and not is_challenge(response):
                    break
            except requests.RequestException:
                record_learning(store, profile, "request_error", method)
            if attempt == 0:
                time.sleep(1.0)
    return last, None


def sitemap_parse(content: bytes, text: str, max_children: int = 50) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        tag = root.tag.lower()
        if tag.endswith("sitemapindex"):
            return [], [x.text.strip() for x in root.findall("sm:sitemap/sm:loc", ns)[:max_children] if x.text]
        return [x.text.strip() for x in root.findall("sm:url/sm:loc", ns) if x.text], []
    except ET.ParseError:
        return scraper.re.findall(r"<loc>\s*(https?://[^\s<>]+)\s*</loc>", text, flags=scraper.re.I), []


def discover_sitemaps(cat: dict, config: dict, max_urls: int = 80, max_indexes: int = 20) -> list[str]:
    origin = f"{urlparse(cat['url']).scheme}://{urlparse(cat['url']).netloc}"
    robots, _ = adaptive_fetch(urljoin(origin, "/robots.txt"), config, 10)
    seeds = []
    if robots and robots.status_code < 400:
        seeds = [line.split(":", 1)[1].strip() for line in robots.text.splitlines() if line.lower().startswith("sitemap:")]
    if not seeds:
        seeds = [urljoin(origin, x) for x in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap-products.xml", "/product-sitemap.xml"]]
    seen_sm, seen_url, discovered = set(), set(), []
    while seeds and len(discovered) < max_urls and len(seen_sm) < max_indexes:
        sm = seeds.pop(0)
        if sm in seen_sm:
            continue
        seen_sm.add(sm)
        response, _ = adaptive_fetch(sm, config, 12)
        if not response or response.status_code >= 400:
            continue
        urls, children = sitemap_parse(response.content, response.text, max_children=max_indexes)
        seeds.extend(children)
        for url in urls:
            if url in seen_url:
                continue
            seen_url.add(url)
            if scraper.same_host(url, cat["url"]) and scraper.product_path_ok(url, cat.get("product_path_hints", [])):
                discovered.append(url)
                if len(discovered) >= max_urls:
                    break
    return discovered


def jsonld_price_and_title(soup: BeautifulSoup):
    data = scraper.jsonld_products(soup)
    if not data:
        return None, None
    for item in data:
        if item.get("preco"):
            return item["preco"], item.get("titulo")
    return None, data[0].get("titulo")


def enrich(item: dict, config: dict) -> tuple[dict, dict]:
    response, profile = adaptive_fetch(item["url"], config, 14)
    if not response or response.status_code >= 400:
        return item, {"error": f"HTTP {getattr(response, 'status_code', 'ERR')}", "profile": profile}
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    price_ld, title_ld = jsonld_price_and_title(soup)
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    real_title = (h1.get_text(" ", strip=True) if h1 else "") or page_title or title_ld or item["titulo"]
    if title_ld and len(title_ld) >= 8 and scraper.eligible(title_ld):
        real_title = title_ld
    extracted = scraper.extract(real_title if real_title else item["titulo"], soup)
    price = price_ld or item.get("preco")
    if price is None:
        values = scraper.prices(text)
        price = min(values) if values else None
    result = dict(item)
    if real_title and scraper.eligible(real_title):
        result["titulo"] = real_title
    if price is not None and 200 <= price <= 4500:
        result["preco"] = price
    state = scraper.stock(text)
    if state is not None:
        result["stock"] = state
    extracted["page_url"] = response.url
    extracted["acesso_profile"] = profile
    return {**result, "specs": extracted}, {"error": None, "profile": profile}


def alert_send(title: str, message: str, priority: str = "default") -> bool:
    topic = scraper.NTFY_TOPIC
    if not topic:
        LOGGER.warning("NTFY_TOPIC não definido.")
        return False
    payload = {"topic": topic, "title": title[:180], "message": message, "tags": ["computer", "rotating_light"], "priority": 4 if priority == "high" else 3}
    for attempt in range(3):
        try:
            r = requests.post("https://ntfy.sh", json=payload, timeout=15)
            r.raise_for_status()
            LOGGER.info("Notificação enviada: %s", title)
            return True
        except requests.RequestException as exc:
            LOGGER.error("ntfy falhou (tentativa %d/3): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(1 + attempt)
    return False


def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
    adjusted = dict(spec)
    if adjusted.get("teclado_pt") == "desconhecido":
        adjusted["teclado_pt"] = "confirmado"
    return scraper.score(adjusted, price, weights, settings)


def main() -> None:
    config = load_json(BASE / "config" / "config.json")
    settings, weights = config.get("settings", {}), config.get("weights", {})
    max_cat = int(settings.get("max_produtos_por_categoria", 30))
    max_enrich = int(settings.get("max_enriquecimentos_detalhe", 48))
    max_sitemap = min(100, max(30, max_cat * 3))
    budget_hard = float(settings.get("budget_hard", 1500))
    min_alert = float(settings.get("min_value_score_alerta", 70))
    history = load_json(HISTORY_PATH)
    if history.get("schema_version") != 8:
        history = {"schema_version": 8, "offers": {}, "alert_state": {}, "learning": {"runs": [], "stores": {}}}
    history.setdefault("offers", {}); history.setdefault("alert_state", {}); history.setdefault("learning", {"runs": [], "stores": {}})
    history["learning"].setdefault("runs", []); history["learning"].setdefault("stores", {})

    all_items, stats, errors = [], {}, {}
    run = {"timestamp": now_iso(), "stores": {}, "total_candidates": 0, "total_accepted": 0, "alerts": 0}
    for cat in config.get("category_urls", []):
        store = cat["loja"]
        stats[store] = {"encontrados": 0, "candidatos": 0, "enriquecidos": 0, "aceites": 0, "rejeitados": 0, "bloqueada": False}
        response, _ = adaptive_fetch(cat["url"], config, float(cat.get("timeout_ms", 12000)) / 1000)
        candidates = []
        if response and response.status_code < 400 and not scraper.blocked(response)[0]:
            candidates = scraper.discover_category(response.text, cat, max_cat)
        else:
            stats[store]["bloqueada"] = True
            errors[store] = scraper.blocked(response)[1] if response else "sem_resposta"
        if not candidates:
            urls = discover_sitemaps(cat, config, max_sitemap)
            seeds = [{"loja": store, "titulo": u.rstrip("/").split("/")[-1].replace("-", " "), "preco": None, "url": u, "stock": None} for u in urls]
            with ThreadPoolExecutor(max_workers=min(6, len(seeds) or 1)) as ex:
                futures = [ex.submit(enrich, item, config) for item in seeds[:max_enrich]]
                for future in as_completed(futures):
                    item, err = future.result()
                    if not err.get("error") and item.get("preco") and scraper.eligible(item.get("titulo", "")):
                        candidates.append(item)
            if candidates:
                stats[store]["bloqueada"], errors[store] = False, None
        clean, seen = [], set()
        for item in candidates:
            url = item.get("url")
            price = item.get("preco")
            if not url or price is None or price > budget_hard or url in seen:
                continue
            seen.add(url)
            if scraper.eligible(item.get("titulo", "")):
                clean.append(item)
        stats[store]["encontrados"] = stats[store]["candidatos"] = len(clean)
        all_items.extend(clean)
        learned = load_json(LEARNING_PATH).get("stores", {}).get(store, {})
        run["stores"][store] = {"profiles": learned.get("profiles", {}), "methods": learned.get("methods", {})}

    unique = {}
    for item in all_items:
        unique.setdefault((item["loja"], item["url"]), item)
    work = list(unique.values())[:max_enrich]
    enriched = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(enrich, item, config): item for item in work}
        for future in as_completed(futures):
            item, err = future.result()
            if not err.get("error"):
                enriched.append(item); stats[item["loja"]]["enriquecidos"] += 1

    tier_order = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}; tiers = {k: 0 for k in tier_order}; alerts = 0
    for item in enriched:
        store, price = item["loja"], item.get("preco")
        if price is None: continue
        spec = item.get("specs") or scraper.specs(item["titulo"])
        assessment = score_allow_unknown(spec, price, weights, settings)
        if assessment.get("status") != "ACEITE":
            stats[store]["rejeitados"] += 1; continue
        stats[store]["aceites"] += 1
        tier = scraper.tier_from_value(assessment["value_score"], settings)
        if tier: tiers[tier] += 1
        key = f"{store}::{item['titulo']}"; entries = history["offers"].setdefault(key, []); prev = entries[-1] if entries else None
        if prev is None:
            for old_entries in history["offers"].values():
                if old_entries and isinstance(old_entries[-1], dict) and old_entries[-1].get("url") == item["url"]:
                    prev = old_entries[-1]; break
        baseline_price = prev.get("price") if prev else None; baseline_value = float(prev.get("value_score", 0)) if prev else 0.0; baseline_tier = prev.get("tier") if prev else None
        alert_key = f"{store}::{item['url']}"; prior = history["alert_state"].get(alert_key)
        entry = {"timestamp": now_iso(), "price": price, "stock": item.get("stock"), "score_final": assessment["score_final"], "score_ranking": assessment["score_ranking"], "value_score": assessment["value_score"], "tier": tier, "specs": spec, "url": item["url"]}
        entries.append(entry); del entries[:-30]
        if tier and assessment["value_score"] >= min_alert and item.get("stock") is not False:
            drop = float(settings.get("alerta_queda_preco_eur", 5)); base = float(prior.get("price")) if prior and prior.get("price") is not None else baseline_price; old_tier = prior.get("tier") if prior else baseline_tier
            price_drop = base is not None and price <= base - drop; opportunity = baseline_value < min_alert; upgrade = bool(old_tier and tier_order.get(tier, 0) > tier_order.get(old_tier, 0)); first = prior is None
            if first or opportunity or upgrade or price_drop:
                reason = "nova oportunidade" if first else f"queda de {base-price:.2f}€" if price_drop else f"subida de {old_tier} para {tier}" if upgrade else "entrou no limiar de alerta"
                sent = alert_send(f"{tier}: {item['titulo']}", f"{item['titulo']}\nPreço: {price:.2f}€\nValue: {assessment['value_score']:.1f} | Rank: {assessment['score_ranking']:.1f}\nTier: {tier}\nMotivo: {reason}\n{item['url']}", "high" if tier in {"DIAMANTE", "OURO"} else "default")
                if sent:
                    alerts += 1
                    history["alert_state"][alert_key] = {"timestamp": now_iso(), "price": price, "value_score": assessment["value_score"], "tier": tier}

    run["total_candidates"] = sum(v["candidatos"] for v in stats.values()); run["total_accepted"] = sum(v["aceites"] for v in stats.values()); run["alerts"] = alerts
    history["learning"]["runs"].append(run); history["learning"]["runs"] = history["learning"]["runs"][-60:]
    save_json(HISTORY_PATH, history)
    LOGGER.info("V8 | Lojas=%d | Bloqueadas=%d | Encontrados=%d | Enriquecidos=%d | Aceites=%d | Alertas=%d | Diamante=%d | Ouro=%d | Prata=%d | Bronze=%d", len(stats), sum(v["bloqueada"] for v in stats.values()), sum(v["encontrados"] for v in stats.values()), sum(v["enriquecidos"] for v in stats.values()), sum(v["aceites"] for v in stats.values()), alerts, tiers["DIAMANTE"], tiers["OURO"], tiers["PRATA"], tiers["BRONZE"])
    for store, stat in stats.items():
        LOGGER.info("🏪 %s: encontrados=%d candidatos=%d enriquecidos=%d aceites=%d rejeitados=%d bloqueada=%s erro=%s", store, stat["encontrados"], stat["candidatos"], stat["enriquecidos"], stat["aceites"], stat["rejeitados"], stat["bloqueada"], errors.get(store))


if __name__ == "__main__":
    main()
