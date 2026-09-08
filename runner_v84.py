from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from collections import defaultdict
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
SUBBRANDS = {
    "asus": {"rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"},
    "lenovo": {"legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"},
    "hp": {"omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"},
}

LOCK = threading.RLock()
LOGGER = logging.getLogger("Runner")

RUN_STARTED = 0.0
RUN_DEADLINE = 0.0
REQUESTS_USED = 0
REQUESTS_BY_STORE: dict[str, int] = defaultdict(int)
MAX_REQUESTS = 180
MAX_REQUESTS_PER_STORE = 30


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


def new_bucket() -> dict:
    return {
        "attempts": 0,
        "successes": 0,
        "blocks": 0,
        "errors": {},
        "profiles": {},
        "methods": {},
        "contexts": {},
        "last_updated": None,
    }


def load_learning() -> dict:
    data = load_json(LEARNING_PATH)
    if data.get("schema_version") == 2:
        data.setdefault("stores", {})
        for store in data["stores"].values():
            if isinstance(store, dict):
                store.setdefault("contexts", {})
                store.setdefault("profiles", {})
                store.setdefault("methods", {})
                store.setdefault("errors", {})
        return data

    out = {"schema_version": 2, "updated_at": now_iso(), "stores": {}}
    for store_name, old in (data.get("stores", {}) if isinstance(data, dict) else {}).items():
        if not isinstance(old, dict):
            continue
        b = new_bucket()
        for key in ("attempts", "successes", "blocks"):
            b[key] = int(old.get(key, 0))
        b["errors"] = old.get("errors", {}) if isinstance(old.get("errors"), dict) else {}
        b["profiles"] = old.get("profiles", {}) if isinstance(old.get("profiles"), dict) else {}
        b["methods"] = old.get("methods", {}) if isinstance(old.get("methods"), dict) else {}
        b["last_updated"] = old.get("last_updated")
        out["stores"][store_name] = b
    return out


LEARNING = load_learning()


def bucket(store: str) -> dict:
    return LEARNING["stores"].setdefault(store, new_bucket())


def context(store: str, method: str, profile: str) -> dict:
    return bucket(store)["contexts"].setdefault(method, {}).setdefault(
        profile,
        {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0, "results": {}},
    )


def record_learning(store: str, profile: str, outcome: str, method: str) -> None:
    with LOCK:
        b = bucket(store)
        b["attempts"] += 1
        b["methods"][method] = b["methods"].get(method, 0) + 1
        p = b["profiles"].setdefault(
            profile, {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0}
        )
        c = context(store, method, profile)
        p["attempts"] += 1
        c["attempts"] += 1
        if outcome == "success":
            b["successes"] += 1
            p["successes"] += 1
            c["successes"] += 1
        elif outcome == "blocked":
            b["blocks"] += 1
            p["blocks"] += 1
            c["blocks"] += 1
        else:
            p["errors"] += 1
            c["errors"] += 1
            b["errors"][outcome] = b["errors"].get(outcome, 0) + 1
        b["last_updated"] = now_iso()


def record_result(store: str, method: str, profile: str, result: str) -> None:
    with LOCK:
        results = context(store, method, profile).setdefault("results", {})
        results[result] = int(results.get(result, 0)) + 1


def _rate(stats: dict) -> tuple[float, int]:
    attempts = int(stats.get("attempts", 0))
    if attempts <= 0:
        return 0.25, 0
    successes = int(stats.get("successes", 0))
    blocks = int(stats.get("blocks", 0))
    errors = int(stats.get("errors", 0))
    rate = (successes + 1.0) / (attempts + 2.0)
    score = rate - 0.40 * blocks / attempts - 0.10 * errors / attempts
    return score, attempts


def profile_score(store: str, method: str, profile: str) -> tuple[float, int]:
    """Score browser profiles using method evidence plus store-wide evidence as a prior."""
    b = bucket(store)
    c = b.get("contexts", {}).get(method, {}).get(profile, {})
    global_stats = b.get("profiles", {}).get(profile, {})
    context_score, context_attempts = _rate(c)
    global_score, global_attempts = _rate(global_stats)

    if context_attempts:
        if global_attempts:
            return 0.78 * context_score + 0.22 * global_score, context_attempts
        return context_score, context_attempts
    if global_attempts:
        return 0.92 * global_score, global_attempts

    attempts = successes = blocks = errors = 0
    for other_method, profiles in b.get("contexts", {}).items():
        if other_method == method:
            continue
        d = profiles.get(profile, {})
        attempts += int(d.get("attempts", 0))
        successes += int(d.get("successes", 0))
        blocks += int(d.get("blocks", 0))
        errors += int(d.get("errors", 0))
    if attempts:
        score, _ = _rate(
            {"attempts": attempts, "successes": successes, "blocks": blocks, "errors": errors}
        )
        return 0.88 * score, attempts
    return 0.25, 0


def _method_totals(store: str, method: str) -> tuple[int, int, int]:
    attempts = successes = blocks = 0
    b = bucket(store)
    methods = [method]
    if method == "category":
        methods.append("page")
    for method_name in methods:
        for stats in b.get("contexts", {}).get(method_name, {}).values():
            attempts += int(stats.get("attempts", 0))
            successes += int(stats.get("successes", 0))
            blocks += int(stats.get("blocks", 0))
    return attempts, successes, blocks


def access_mode(store: str, method: str) -> str:
    """Use cheap probes when a store/method has overwhelming persistent blocking."""
    b = bucket(store)
    total_attempts = int(b.get("attempts", 0))
    total_successes = int(b.get("successes", 0))
    total_blocks = int(b.get("blocks", 0))

    if total_attempts >= 30 and total_successes == 0 and total_blocks / max(1, total_attempts) >= 0.90:
        return "probe"

    attempts, successes, blocks = _method_totals(store, method)
    if attempts >= 12 and successes == 0 and blocks / max(1, attempts) >= 0.85:
        return "probe"
    return "normal"


def profile_order(store: str, method: str) -> list[str]:
    scored = [(profile_score(store, method, p), i, p) for i, p in enumerate(PROFILES)]
    ranked = sorted(scored, key=lambda x: (-x[0][0], -x[0][1], x[1]))

    if access_mode(store, method) == "probe":
        probe_index = int(bucket(store).get("methods", {}).get(method, 0)) % len(ranked)
        return [ranked[probe_index][2]]

    selected = [p for score, _, p in ranked if score[1] > 0][:2]
    if not selected:
        selected = [ranked[0][2]]
    fresh = [p for score, _, p in ranked if score[1] == 0 and p not in selected]
    if fresh and len(selected) < 3:
        selected.append(fresh[0])
    return list(dict.fromkeys(selected))[:3]


def headers(profile: str) -> dict:
    h = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    if profile.startswith("safari"):
        h["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        )
    elif profile.startswith("firefox"):
        v = profile.removeprefix("firefox")
        h["User-Agent"] = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{v}.0) "
            f"Gecko/20100101 Firefox/{v}.0"
        )
    elif profile.startswith("edge"):
        v = profile.removeprefix("edge")
        h["User-Agent"] = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36 Edg/{v}.0.0.0"
        )
    else:
        v = profile.removeprefix("chrome")
        h["User-Agent"] = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
        )
    return h


def _same_url(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


def store_for_url(url: str, config: dict) -> str:
    host = urlparse(url).netloc
    return next(
        (
            c["loja"]
            for c in config.get("category_urls", [])
            if urlparse(c.get("url", "")).netloc == host
        ),
        host,
    )


def method_for_url(url: str, config: dict | None = None) -> str:
    path = urlparse(url).path.lower()
    if path.endswith("/robots.txt"):
        return "robots"
    if "sitemap" in path or path.endswith(".xml"):
        return "sitemap"

    if config:
        same_host_categories = [
            c
            for c in config.get("category_urls", [])
            if urlparse(c.get("url", "")).netloc == urlparse(url).netloc
        ]
        if any(_same_url(url, c.get("url", "")) for c in same_host_categories):
            return "category"
        if any(
            scraper.product_path_ok(url, c.get("product_path_hints", []))
            for c in same_host_categories
        ):
            return "product"

    if any(x in path for x in ("/produto/", "/product/", "/p/")):
        return "product"
    return "page"


def classify(response) -> tuple[str, bool]:
    if response is None:
        return "no_response", True
    code = response.status_code
    if code in {401, 403, 429, 500, 502, 503, 504}:
        return f"http_{code}", True
    if code == 404:
        return "http_404", False

    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "xml" not in content_type:
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            title = scraper.norm(soup.title.get_text(" ", strip=True) if soup.title else "")
            for node in soup(["script", "style", "noscript"]):
                node.decompose()
            visible = scraper.norm(" ".join(soup.stripped_strings))[:20000]
            markers = (
                "just a moment",
                "checking your browser",
                "verify you are human",
                "access denied",
                "robot check",
                "are you a robot",
                "captcha",
            )
            if any(m in title or m in visible for m in markers) or "cf-chl-" in title:
                return "challenge", True
        except Exception:
            pass
    return (f"http_{code}", False) if code >= 400 else ("http_success", False)


def budget_available(store: str | None = None) -> bool:
    with LOCK:
        if REQUESTS_USED >= MAX_REQUESTS:
            return False
        if RUN_DEADLINE > 0 and time.monotonic() >= RUN_DEADLINE:
            return False
        if store is not None and REQUESTS_BY_STORE.get(store, 0) >= MAX_REQUESTS_PER_STORE:
            return False
        return True


def consume_request(store: str) -> bool:
    global REQUESTS_USED
    with LOCK:
        if not budget_available(store):
            return False
        REQUESTS_USED += 1
        REQUESTS_BY_STORE[store] += 1
        return True


def adaptive_fetch(url: str, config: dict, timeout_s: float = 10.0):
    store = store_for_url(url, config)
    method = method_for_url(url, config)
    mode = access_mode(store, method)
    last = None

    for idx, profile in enumerate(profile_order(store, method)):
        attempts = 1 if mode == "probe" else (2 if idx == 0 else 1)
        for attempt in range(attempts):
            if not consume_request(store):
                return last, None, "request_budget_exhausted"
            try:
                response = requests.get(
                    url,
                    timeout=timeout_s,
                    impersonate=profile,
                    headers=headers(profile),
                    allow_redirects=True,
                )
                last = response
                outcome, retryable = classify(response)
                record_learning(
                    store,
                    profile,
                    "success" if outcome == "http_success" else ("blocked" if retryable else outcome),
                    method,
                )
                if outcome == "http_success":
                    return response, profile, outcome
                if not retryable:
                    break
            except Exception as exc:
                record_learning(store, profile, "request_error", method)
                LOGGER.warning("Acesso falhou: %s | %s | %s | %s", store, method, profile, exc)
            if attempt == 0 and attempts == 2:
                time.sleep(min(3.0, 0.6 + random.random()))
        if not budget_available(store):
            break
    return last, None, classify(last)[0] if last is not None else "no_response"


def sitemap_parse(content: bytes, text: str, max_children: int = 6) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if root.tag.lower().endswith("sitemapindex"):
            return [], [
                x.text.strip()
                for x in root.findall("sm:sitemap/sm:loc", ns)[:max_children]
                if x.text
            ]
        return [x.text.strip() for x in root.findall("sm:url/sm:loc", ns) if x.text], []
    except ET.ParseError:
        return scraper.re.findall(
            r"<loc>\s*(https?://[^\s<>]+)\s*</loc>", text, flags=scraper.re.I
        ), []


def discover_sitemaps(cat: dict, config: dict, max_urls: int = 30, max_indexes: int = 5) -> list[str]:
    store = cat["loja"]
    if access_mode(store, "category") == "probe":
        return []

    origin = f"{urlparse(cat['url']).scheme}://{urlparse(cat['url']).netloc}"
    robots, _, _ = adaptive_fetch(urljoin(origin, "/robots.txt"), config, 6)
    seeds = (
        [
            line.split(":", 1)[1].strip()
            for line in robots.text.splitlines()
            if line.lower().startswith("sitemap:")
        ]
        if robots and robots.status_code < 400
        else []
    )
    if not seeds:
        seeds = [
            urljoin(origin, x)
            for x in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-products.xml")
        ]

    seen_sitemaps: set[str] = set()
    seen_urls: set[str] = set()
    out: list[str] = []
    while (
        seeds
        and len(out) < max_urls
        and len(seen_sitemaps) < max_indexes
        and budget_available(store)
    ):
        sitemap_url = seeds.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        response, _, _ = adaptive_fetch(sitemap_url, config, 6)
        if not response or response.status_code >= 400:
            continue
        urls, children = sitemap_parse(response.content, response.text, max_indexes)
        seeds.extend(children)
        for product_url in urls:
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)
            if scraper.same_host(product_url, cat["url"]) and scraper.product_path_ok(
                product_url, cat.get("product_path_hints", [])
            ):
                out.append(product_url)
                if len(out) >= max_urls:
                    break
    return out


def infer_brand(text: str) -> tuple[str | None, str | None]:
    base, sub = scraper.brand(text)
    if base:
        return base, sub
    normalized = scraper.norm(text)
    for parent, children in SUBBRANDS.items():
        for child in sorted(children, key=len, reverse=True):
            if scraper.re.search(rf"\b{scraper.re.escape(child)}\b", normalized):
                return parent, child
    return None, None


def eligible(text: str) -> bool:
    if scraper.eligible(text):
        return True
    normalized = scraper.norm(text)
    if any(x in normalized for x in scraper.EXCLUDE):
        return False
    return infer_brand(text)[0] is not None


def loose_catalog_candidates(html: str, cat: dict, limit: int) -> list[dict]:
    """Fallback for catalogues whose cards do not match the V8 generic selectors."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()

    for heading in soup.find_all(["h2", "h3", "h4", "strong"]):
        title = heading.get_text(" ", strip=True)
        if not title or len(title) < 6 or not eligible(title):
            continue

        node = heading
        for _ in range(int(cat.get("parent_climb", 7))):
            node = node.parent
            if node is None:
                break
            text = node.get_text(" ", strip=True)
            values = scraper.prices(text)
            price = min(values) if values else None
            if price is None or not 200 <= price <= 4500:
                continue

            links = node.find_all("a", href=True)
            product_url = None
            for link in links:
                full_url = urljoin(cat["url"], link["href"])
                if scraper.same_host(full_url, cat["url"]) and scraper.product_path_ok(
                    full_url, cat.get("product_path_hints", [])
                ):
                    product_url = full_url
                    break
            if not product_url:
                continue
            if product_url in seen:
                break
            seen.add(product_url)
            out.append(
                {
                    "loja": cat["loja"],
                    "titulo": title.strip(),
                    "preco": price,
                    "url": product_url,
                    "stock": scraper.stock(text),
                }
            )
            break

        if len(out) >= limit:
            break
    return out


def discover_category(html: str, cat: dict, limit: int) -> list[dict]:
    primary = scraper.discover_category(html, cat, limit)
    if len(primary) >= limit:
        return primary[:limit]

    seen = {x.get("url") for x in primary if x.get("url")}
    for item in loose_catalog_candidates(html, cat, limit):
        if item.get("url") not in seen:
            primary.append(item)
            seen.add(item.get("url"))
            if len(primary) >= limit:
                break
    return primary[:limit]


def jsonld_price_title(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    data = scraper.jsonld_products(soup)
    if not data:
        return None, None
    for item in data:
        if item.get("preco"):
            return item["preco"], item.get("titulo")
    return None, data[0].get("titulo")


def enrich(item: dict, config: dict) -> tuple[dict, dict]:
    response, profile, access = adaptive_fetch(item["url"], config, 8)
    store = item["loja"]
    if not response or response.status_code >= 400:
        record_result(store, "product", profile or "none", "access_failed")
        return item, {"error": "access_failed", "profile": profile, "access": access}

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    price_ld, title_ld = jsonld_price_title(soup)
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    real_title = (
        (h1.get_text(" ", strip=True) if h1 else "")
        or page_title
        or title_ld
        or item["titulo"]
    )
    if title_ld and len(title_ld) >= 8 and eligible(title_ld):
        real_title = title_ld

    extracted = scraper.extract(real_title, soup)
    inferred_brand, inferred_subbrand = infer_brand(real_title)
    if not extracted.get("marca") and inferred_brand:
        extracted["marca"] = inferred_brand
        extracted["submarca"] = inferred_subbrand
        extracted.setdefault("fontes", {})["marca"] = "titulo_submarca"

    price = price_ld or item.get("preco")
    if price is None:
        values = scraper.prices(text)
        price = min(values) if values else None

    result = dict(item)
    if real_title and eligible(real_title):
        result["titulo"] = real_title
    if price is not None and 200 <= price <= 4500:
        result["preco"] = price
    stock_value = scraper.stock(text)
    if stock_value is not None:
        result["stock"] = stock_value

    extracted["page_url"] = response.url
    extracted["acesso_profile"] = profile
    outcome = "valid_product" if result.get("preco") and eligible(result["titulo"]) else "no_product_or_price"
    record_result(store, "product", profile or "none", outcome)
    return {**result, "specs": extracted}, {
        "error": None,
        "profile": profile,
        "access": access,
        "result": outcome,
    }


def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
    adjusted = dict(spec)
    if adjusted.get("teclado_pt") == "desconhecido":
        adjusted["teclado_pt"] = "confirmado"
    return scraper.score(adjusted, price, weights, settings)


def candidate_priority(item: dict, weights: dict, settings: dict) -> float:
    """Title-only estimate used only to decide which products deserve detail requests."""
    price = float(item.get("preco") or 99999)
    spec = scraper.specs(item.get("titulo", ""))
    gpu_model = spec.get("gpu_modelo")
    if spec.get("gpu_tipo") == "dedicada":
        p_gpu = float(weights.get("gpu_base", {}).get(gpu_model, 50))
    elif spec.get("gpu_tipo") == "integrada":
        p_gpu = 15.0
    else:
        p_gpu = 30.0

    _, cpu_tier, _ = scraper.cpu(spec.get("cpu_modelo") or item.get("titulo", ""))
    p_cpu = float(
        weights.get("cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70}).get(
            cpu_tier, 50
        )
    )
    ram = spec.get("ram_gb")
    p_ram = 50.0 if ram is None else 100.0 if ram >= 32 else 80.0 if ram >= 16 else 40.0
    storage = spec.get("armazenamento_tb")
    p_storage = (
        50.0
        if storage is None
        else 100.0
        if storage >= 2
        else 85.0
        if storage >= 1
        else 65.0
    )
    hardware = 0.50 * p_gpu + 0.25 * p_cpu + 0.15 * p_ram + 0.10 * p_storage
    value_hint = 0.65 * hardware + 0.35 * scraper.price_score(price, settings)
    if gpu_model:
        value_hint += 8.0
    return round(value_hint, 3)


def select_for_enrichment(
    items: list[dict], max_enrich: int, weights: dict, settings: dict
) -> list[dict]:
    if len(items) <= max_enrich:
        return sorted(
            items, key=lambda x: (-candidate_priority(x, weights, settings), float(x.get("preco") or 99999))
        )

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[item["loja"]].append(item)
    for store_items in groups.values():
        store_items.sort(
            key=lambda x: (-candidate_priority(x, weights, settings), float(x.get("preco") or 99999))
        )

    selected: list[dict] = []
    selected_keys: set[tuple[str, str]] = set()
    guaranteed = min(4, max(1, max_enrich // max(1, len(groups))))

    for store in sorted(groups):
        for item in groups[store][:guaranteed]:
            if len(selected) >= max_enrich:
                break
            key = (item["loja"], item["url"])
            if key not in selected_keys:
                selected.append(item)
                selected_keys.add(key)

    remaining = sorted(
        items,
        key=lambda x: (-candidate_priority(x, weights, settings), float(x.get("preco") or 99999)),
    )
    for item in remaining:
        if len(selected) >= max_enrich:
            break
        key = (item["loja"], item["url"])
        if key not in selected_keys:
            selected.append(item)
            selected_keys.add(key)
    return selected


def alert_send(title: str, message: str, priority: str = "default") -> bool:
    if not scraper.NTFY_TOPIC:
        return False
    payload = {
        "topic": scraper.NTFY_TOPIC,
        "title": title[:180],
        "message": message,
        "tags": ["computer", "rotating_light"],
        "priority": {"high": 5, "default": 3}.get(priority, 3),
    }
    for attempt in range(2):
        try:
            response = requests.post("https://ntfy.sh", json=payload, timeout=8)
            response.raise_for_status()
            return True
        except Exception as exc:
            LOGGER.warning("Falha ao enviar ntfy: %s", exc)
            if attempt == 0:
                time.sleep(0.5 + random.random())
    return False


def _empty_store_stats() -> dict:
    return {
        "candidatos": 0,
        "enriquecidos": 0,
        "aceites": 0,
        "rejeitados": 0,
        "bloqueada": False,
        "categorias": [],
    }


def main() -> None:
    global RUN_STARTED, RUN_DEADLINE, REQUESTS_USED, REQUESTS_BY_STORE
    global MAX_REQUESTS, MAX_REQUESTS_PER_STORE

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    RUN_STARTED = time.monotonic()
    minutes = max(1.0, float(os.getenv("RUN_MAX_MINUTES", "8")))
    RUN_DEADLINE = RUN_STARTED + minutes * 60

    config = load_json(BASE / "config" / "config.json")
    settings = config.get("settings", {})
    weights = config.get("weights", {})
    MAX_REQUESTS = int(
        os.getenv("RUN_MAX_REQUESTS", settings.get("max_requests_per_run", 180))
    )
    MAX_REQUESTS_PER_STORE = int(
        os.getenv(
            "RUN_MAX_REQUESTS_PER_STORE",
            settings.get("max_requests_per_store", 30),
        )
    )
    REQUESTS_USED = 0
    REQUESTS_BY_STORE = defaultdict(int)

    max_cat = int(settings.get("max_produtos_por_categoria", 30))
    max_enrich = min(int(settings.get("max_enriquecimentos_detalhe", 48)), 30)
    hard = float(settings.get("budget_hard", 1500))
    min_alert = float(settings.get("min_value_score_alerta", 70))
    min_notify = settings.get("alerta_min_tier", "OURO").upper()

    history = load_json(HISTORY_PATH)
    if history.get("schema_version") != 8:
        history = {
            "schema_version": 8,
            "offers": {},
            "alert_state": {},
            "learning": {"runs": [], "stores": {}},
        }
    history.setdefault("offers", {})
    history.setdefault("alert_state", {})
    history.setdefault("learning", {"runs": [], "stores": {}})

    all_items: list[dict] = []
    stats: dict[str, dict] = {}

    for cat in config.get("category_urls", []):
        if not budget_available():
            break
        store = cat["loja"]
        stat = stats.setdefault(store, _empty_store_stats())
        before_candidates = stat["candidatos"]

        response, profile, access = adaptive_fetch(
            cat["url"],
            config,
            min(8, float(cat.get("timeout_ms", 12000)) / 1000),
        )
        candidates = (
            discover_category(response.text, cat, max_cat)
            if response
            and response.status_code < 400
            and not scraper.blocked(response)[0]
            else []
        )

        if not candidates and access_mode(store, "category") != "probe":
            urls = discover_sitemaps(cat, config)
            seeds = [
                {
                    "loja": store,
                    "titulo": u.rstrip("/").split("/")[-1].replace("-", " "),
                    "preco": None,
                    "url": u,
                    "stock": None,
                }
                for u in urls[:8]
            ]
            if seeds:
                with ThreadPoolExecutor(max_workers=min(4, len(seeds))) as executor:
                    futures = [executor.submit(enrich, item, config) for item in seeds]
                    for future in as_completed(futures):
                        item, err = future.result()
                        if (
                            not err.get("error")
                            and item.get("preco")
                            and eligible(item.get("titulo", ""))
                        ):
                            candidates.append(item)

        clean: list[dict] = []
        seen: set[str] = set()
        for item in candidates:
            url = item.get("url")
            price = item.get("preco")
            if (
                url
                and price is not None
                and float(price) <= hard
                and url not in seen
                and eligible(item.get("titulo", ""))
            ):
                seen.add(url)
                clean.append(item)

        all_items.extend(clean)
        stat["candidatos"] += len(clean)
        blocked = not response or response.status_code >= 400
        stat["bloqueada"] = stat["bloqueada"] or blocked
        category_result = {
            "url": cat["url"],
            "perfil": profile,
            "resultado": access,
            "modo": access_mode(store, "category"),
            "candidatos": len(clean),
        }
        stat["categorias"].append(category_result)
        stat["acesso"] = {
            "perfil_categoria": profile,
            "resultado": access,
        }
        LOGGER.info(
            "Descoberta | %s | candidatos=%d (+%d) | acesso=%s | perfil=%s | modo=%s",
            store,
            stat["candidatos"],
            stat["candidatos"] - before_candidates,
            access,
            profile,
            category_result["modo"],
        )

    unique: dict[tuple[str, str], dict] = {}
    for item in all_items:
        unique.setdefault((item["loja"], item["url"]), item)

    work = select_for_enrichment(list(unique.values()), max_enrich, weights, settings)
    LOGGER.info(
        "Pré-ranking | descobertos=%d | selecionados=%d | limite=%d",
        len(unique),
        len(work),
        max_enrich,
    )

    enriched: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(enrich, item, config) for item in work]
        for future in as_completed(futures):
            item, err = future.result()
            if not err.get("error"):
                enriched.append(item)
                stats[item["loja"]]["enriquecidos"] += 1

    order = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}
    tiers = {key: 0 for key in order}
    alerts = 0
    suppressed = 0

    for item in enriched:
        price = item.get("preco")
        store = item["loja"]
        if price is None:
            continue

        spec = item.get("specs") or scraper.specs(item["titulo"])
        assessment = score_allow_unknown(spec, price, weights, settings)
        if assessment.get("status") != "ACEITE":
            stats[store]["rejeitados"] += 1
            continue

        stats[store]["aceites"] += 1
        tier = scraper.tier_from_value(assessment["value_score"], settings)
        if tier:
            tiers[tier] += 1

        key = f"{store}::{item['titulo']}"
        entries = history["offers"].setdefault(key, [])
        prev = entries[-1] if entries else None
        if prev is None:
            for old_entries in history["offers"].values():
                if (
                    old_entries
                    and isinstance(old_entries[-1], dict)
                    and old_entries[-1].get("url") == item["url"]
                ):
                    prev = old_entries[-1]
                    break

        base_price = prev.get("price") if prev else None
        base_value = float(prev.get("value_score", 0)) if prev else 0.0
        base_tier = prev.get("tier") if prev else None
        alert_key = f"{store}::{item['url']}"
        prior = history["alert_state"].get(alert_key)

        entries.append(
            {
                "timestamp": now_iso(),
                "price": price,
                "stock": item.get("stock"),
                "score_final": assessment["score_final"],
                "score_ranking": assessment["score_ranking"],
                "value_score": assessment["value_score"],
                "tier": tier,
                "specs": spec,
                "url": item["url"],
            }
        )
        del entries[:-30]

        if (
            tier
            and assessment["value_score"] >= min_alert
            and item.get("stock") is not False
        ):
            drop = float(settings.get("alerta_queda_preco_eur", 5))
            current_base = (
                float(prior.get("price"))
                if prior and prior.get("price") is not None
                else base_price
            )
            old_tier = prior.get("tier") if prior else base_tier
            price_drop = current_base is not None and price <= current_base - drop
            opportunity = base_value < min_alert
            upgrade = bool(old_tier and order.get(tier, 0) > order.get(old_tier, 0))
            first = prior is None
            should_notify = first or opportunity or upgrade or price_drop
            can_push = order.get(tier, 0) >= order.get(min_notify, 3)

            if should_notify and can_push:
                emoji = {"DIAMANTE": "💎", "OURO": "🥇"}[tier]
                title = f"{emoji} {tier}: {item['titulo']}"
                message = (
                    f"{item['titulo']}\n"
                    f"Loja: {store} | Preço: {price:.2f}€\n"
                    f"Value: {assessment['value_score']:.1f} | "
                    f"Rank: {assessment['score_ranking']:.1f}\n"
                    f"GPU: {spec.get('gpu_modelo') or spec.get('gpu_tipo')} | "
                    f"CPU: {spec.get('cpu_modelo') or '?'}\n"
                    f"RAM: {spec.get('ram_gb') or '?'}GB | "
                    f"SSD: {spec.get('armazenamento_tb') or '?'}TB\n"
                    f"{item['url']}"
                )
                if alert_send(
                    title, message, "high" if tier == "DIAMANTE" else "default"
                ):
                    alerts += 1
                    history["alert_state"][alert_key] = {
                        "timestamp": now_iso(),
                        "price": price,
                        "value_score": assessment["value_score"],
                        "tier": tier,
                    }
            elif should_notify:
                suppressed += 1

    runtime = round(time.monotonic() - RUN_STARTED, 2)
    run = {
        "timestamp": now_iso(),
        "runner_version": "8.4",
        "stores": stats,
        "total_candidates": sum(x["candidatos"] for x in stats.values()),
        "selected_for_enrichment": len(work),
        "total_enriched": sum(x["enriquecidos"] for x in stats.values()),
        "total_accepted": sum(x["aceites"] for x in stats.values()),
        "alerts_sent": alerts,
        "notifications_suppressed": suppressed,
        "access_requests": REQUESTS_USED,
        "requests_by_store": dict(sorted(REQUESTS_BY_STORE.items())),
        "runtime_seconds": runtime,
        "tiers": tiers,
    }
    history["learning"]["runs"].append(run)
    history["learning"]["runs"] = history["learning"]["runs"][-60:]

    LEARNING["schema_version"] = 2
    LEARNING["updated_at"] = now_iso()
    save_json(LEARNING_PATH, LEARNING)
    save_json(HISTORY_PATH, history)

    LOGGER.info(
        "V8.4 | Lojas=%d | Candidatos=%d | Selecionados=%d | Enriquecidos=%d | "
        "Aceites=%d | Pedidos=%d | Tempo=%.1fs | D=%d O=%d P=%d B=%d",
        len(stats),
        run["total_candidates"],
        run["selected_for_enrichment"],
        run["total_enriched"],
        run["total_accepted"],
        REQUESTS_USED,
        runtime,
        tiers["DIAMANTE"],
        tiers["OURO"],
        tiers["PRATA"],
        tiers["BRONZE"],
    )
    for store, stat in stats.items():
        LOGGER.info(
            "🏪 %s | candidatos=%d enriquecidos=%d aceites=%d rejeitados=%d "
            "pedidos=%d bloqueada=%s",
            store,
            stat["candidatos"],
            stat["enriquecidos"],
            stat["aceites"],
            stat["rejeitados"],
            REQUESTS_BY_STORE.get(store, 0),
            stat["bloqueada"],
        )


if __name__ == "__main__":
    main()
