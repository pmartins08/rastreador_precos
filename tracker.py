from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from curl_cffi import requests

import scraper
from src.access_health import summarize_access


VERSION = "8.8.1"
COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7", "8.7.1", "8.8", "8.8.1"}
BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config" / "config.json"
HISTORY_PATH = BASE / "data" / "history.json"
LEARNING_PATH = BASE / "data" / "access_learning.json"

PROFILES = ["chrome131", "chrome146", "firefox147", "edge101", "safari17_0", "safari260"]
BLOCK_OUTCOMES = {"http_401", "http_403", "http_429", "challenge"}
RETRYABLE_SERVER = {"http_500", "http_502", "http_503", "http_504"}

LOCK = threading.RLock()
LOGGER = logging.getLogger("Tracker")

RUN_STARTED = 0.0
RUN_DEADLINE = 0.0
REQUESTS_USED = 0
REQUESTS_BY_STORE: dict[str, int] = defaultdict(int)
DETAIL_FETCHES_USED = 0
MAX_REQUESTS = 180
MAX_REQUESTS_PER_STORE = 40
MAX_DETAIL_FETCHES = 50
LEARNING: dict = {}


# ---------------------------------------------------------------------------
# Estado e aprendizagem de acesso
# ---------------------------------------------------------------------------


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
        "discovery": {},
        "last_updated": None,
    }


def load_learning() -> dict:
    data = load_json(LEARNING_PATH)
    if data.get("schema_version") != 2:
        data = {"schema_version": 2, "updated_at": now_iso(), "stores": {}}
    data.setdefault("stores", {})
    for store in data["stores"].values():
        if not isinstance(store, dict):
            continue
        store.setdefault("attempts", 0)
        store.setdefault("successes", 0)
        store.setdefault("blocks", 0)
        store.setdefault("errors", {})
        store.setdefault("profiles", {})
        store.setdefault("methods", {})
        store.setdefault("contexts", {})
        store.setdefault("discovery", {})
        store.setdefault("last_updated", None)
    return data


def bucket(store: str) -> dict:
    return LEARNING.setdefault("stores", {}).setdefault(store, new_bucket())


def context(store: str, method: str, profile: str) -> dict:
    return bucket(store)["contexts"].setdefault(method, {}).setdefault(
        profile,
        {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0, "results": {}},
    )


def record_learning(store: str, profile: str, outcome: str, method: str) -> None:
    with LOCK:
        b = bucket(store)
        b["attempts"] = int(b.get("attempts", 0)) + 1
        b["methods"][method] = int(b["methods"].get(method, 0)) + 1
        p = b["profiles"].setdefault(
            profile, {"attempts": 0, "successes": 0, "blocks": 0, "errors": 0}
        )
        c = context(store, method, profile)
        p["attempts"] = int(p.get("attempts", 0)) + 1
        c["attempts"] = int(c.get("attempts", 0)) + 1
        if outcome == "success":
            b["successes"] = int(b.get("successes", 0)) + 1
            p["successes"] = int(p.get("successes", 0)) + 1
            c["successes"] = int(c.get("successes", 0)) + 1
        elif outcome == "blocked":
            b["blocks"] = int(b.get("blocks", 0)) + 1
            p["blocks"] = int(p.get("blocks", 0)) + 1
            c["blocks"] = int(c.get("blocks", 0)) + 1
        else:
            p["errors"] = int(p.get("errors", 0)) + 1
            c["errors"] = int(c.get("errors", 0)) + 1
            b["errors"][outcome] = int(b["errors"].get(outcome, 0)) + 1
        b["last_updated"] = now_iso()


def record_result(store: str, method: str, profile: str, result: str) -> None:
    with LOCK:
        results = context(store, method, profile).setdefault("results", {})
        results[result] = int(results.get(result, 0)) + 1


def discovery_bucket(store: str, method: str) -> dict:
    return bucket(store).setdefault("discovery", {}).setdefault(
        method,
        {
            "attempts": 0,
            "requests": 0,
            "new_candidates": 0,
            "last_yield": 0.0,
            "ema_yield": 0.0,
            "last_updated": None,
        },
    )


def record_discovery_yield(store: str, method: str, requests_spent: int, new_candidates: int) -> None:
    if requests_spent <= 0:
        return
    with LOCK:
        stats = discovery_bucket(store, method)
        current_yield = max(0, int(new_candidates)) / max(1, int(requests_spent))
        attempts = int(stats.get("attempts", 0))
        previous_ema = float(stats.get("ema_yield", 0.0))
        stats["attempts"] = attempts + 1
        stats["requests"] = int(stats.get("requests", 0)) + int(requests_spent)
        stats["new_candidates"] = int(stats.get("new_candidates", 0)) + max(0, int(new_candidates))
        stats["last_yield"] = round(current_yield, 4)
        stats["ema_yield"] = round(current_yield if attempts == 0 else 0.70 * previous_ema + 0.30 * current_yield, 4)
        stats["last_updated"] = now_iso()


def discovery_score(store: str, method: str) -> float:
    stats = bucket(store).get("discovery", {}).get(method, {})
    attempts = int(stats.get("attempts", 0))
    if attempts <= 0:
        return 1.0  # exploração inicial
    requests_count = max(1, int(stats.get("requests", 0)))
    lifetime = int(stats.get("new_candidates", 0)) / requests_count
    recent = float(stats.get("ema_yield", lifetime))
    return round(0.55 * lifetime + 0.45 * recent, 4)


def discovery_routes(cat: dict, store: str) -> list[dict]:
    routes = []
    for index, raw in enumerate(cat.get("extra_discovery_urls", [])):
        if isinstance(raw, str):
            route = {"url": raw, "label": f"segment_{index + 1}"}
        elif isinstance(raw, dict) and raw.get("url"):
            route = {"url": str(raw["url"]), "label": str(raw.get("label") or f"segment_{index + 1}")}
        else:
            continue
        route["method_key"] = f"segment:{route['label']}"
        route["yield_score"] = discovery_score(store, route["method_key"])
        routes.append(route)
    return sorted(routes, key=lambda route: (-route["yield_score"], route["label"]))


def _record_discovery_stat(stat: dict, store: str, method: str, requests_before: int, candidates_before: int, candidates_after: int) -> None:
    spent = max(0, int(REQUESTS_BY_STORE.get(store, 0)) - int(requests_before))
    gained = max(0, int(candidates_after) - int(candidates_before))
    entry = stat["rendimento_descoberta"].setdefault(method, {"requests": 0, "new_candidates": 0, "yield": 0.0})
    entry["requests"] += spent
    entry["new_candidates"] += gained
    entry["yield"] = round(entry["new_candidates"] / max(1, entry["requests"]), 3)
    record_discovery_yield(store, method, spent, gained)


def _rate(stats: dict) -> tuple[float, int]:
    attempts = int(stats.get("attempts", 0))
    if attempts <= 0:
        return 0.25, 0
    successes = int(stats.get("successes", 0))
    blocks = int(stats.get("blocks", 0))
    errors = int(stats.get("errors", 0))
    smoothed = (successes + 1.0) / (attempts + 2.0)
    score = smoothed - 0.40 * blocks / attempts - 0.10 * errors / attempts
    return score, attempts


def profile_score(store: str, method: str, profile: str) -> tuple[float, int]:
    b = bucket(store)
    local = b.get("contexts", {}).get(method, {}).get(profile, {})
    global_stats = b.get("profiles", {}).get(profile, {})
    local_score, local_attempts = _rate(local)
    global_score, global_attempts = _rate(global_stats)

    if local_attempts:
        return (
            0.80 * local_score + 0.20 * global_score if global_attempts else local_score,
            local_attempts,
        )
    if global_attempts:
        return 0.92 * global_score, global_attempts
    return 0.25, 0


def _method_totals(store: str, method: str) -> tuple[int, int, int]:
    attempts = successes = blocks = 0
    for stats in bucket(store).get("contexts", {}).get(method, {}).values():
        attempts += int(stats.get("attempts", 0))
        successes += int(stats.get("successes", 0))
        blocks += int(stats.get("blocks", 0))
    return attempts, successes, blocks


def access_mode(store: str, method: str) -> str:
    # Um método novo deve ter uma oportunidade real de exploração mesmo quando
    # métodos antigos da mesma loja foram bloqueados.
    attempts, successes, blocks = _method_totals(store, method)
    if attempts == 0:
        return "normal"

    b = bucket(store)
    total_attempts = int(b.get("attempts", 0))
    total_successes = int(b.get("successes", 0))
    total_blocks = int(b.get("blocks", 0))
    if (
        total_attempts >= 30
        and total_successes == 0
        and total_blocks / max(1, total_attempts) >= 0.90
        and attempts >= 3
    ):
        return "probe"

    if attempts >= 12 and successes == 0 and blocks / max(1, attempts) >= 0.85:
        return "probe"
    return "normal"


def profile_order(store: str, method: str) -> list[str]:
    ranked = sorted(
        [(profile_score(store, method, p), index, p) for index, p in enumerate(PROFILES)],
        key=lambda item: (-item[0][0], -item[0][1], item[1]),
    )
    if access_mode(store, method) == "probe":
        probe_index = int(bucket(store).get("methods", {}).get(method, 0)) % len(ranked)
        return [ranked[probe_index][2]]

    selected = [profile for score, _, profile in ranked if score[1] > 0][:2]
    if not selected:
        selected = [ranked[0][2]]
    fresh = [profile for score, _, profile in ranked if score[1] == 0 and profile not in selected]
    if fresh and len(selected) < 3:
        selected.append(fresh[0])
    return list(dict.fromkeys(selected))[:3]


# ---------------------------------------------------------------------------
# HTTP adaptativo e budgets
# ---------------------------------------------------------------------------


def headers(profile: str) -> dict:
    common = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    if profile.startswith("safari"):
        common["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        )
    elif profile.startswith("firefox"):
        version = profile.removeprefix("firefox")
        common["User-Agent"] = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{version}.0) "
            f"Gecko/20100101 Firefox/{version}.0"
        )
    elif profile.startswith("edge"):
        version = profile.removeprefix("edge")
        common["User-Agent"] = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0"
        )
    else:
        version = profile.removeprefix("chrome")
        common["User-Agent"] = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        )
    return common


def store_for_url(url: str, config: dict) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for cat in config.get("category_urls", []):
        cat_host = urlparse(cat.get("url", "")).netloc.lower().removeprefix("www.")
        if cat_host == host:
            return cat["loja"]
    return host


def _looks_like_xml(response) -> bool:
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "xml" in content_type:
        return True
    prefix = str(response.text or "").lstrip()[:120].lower()
    return prefix.startswith("<?xml") or prefix.startswith("<urlset") or prefix.startswith("<sitemapindex")


def classify(response) -> tuple[str, bool]:
    if response is None:
        return "no_response", True
    code = int(response.status_code)
    if code in {401, 403, 429, 500, 502, 503, 504}:
        return f"http_{code}", True
    if code == 404:
        return "http_404", False

    if not _looks_like_xml(response):
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
            if any(marker in title or marker in visible for marker in markers) or "cf-chl-" in title:
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
        REQUESTS_BY_STORE[store] = int(REQUESTS_BY_STORE.get(store, 0)) + 1
        return True


def reserve_detail_slot() -> bool:
    global DETAIL_FETCHES_USED
    with LOCK:
        if DETAIL_FETCHES_USED >= MAX_DETAIL_FETCHES:
            return False
        DETAIL_FETCHES_USED += 1
        return True


def adaptive_fetch(
    url: str,
    config: dict,
    timeout_s: float = 8.0,
    *,
    store: str | None = None,
    method: str = "page",
):
    store = store or store_for_url(url, config)
    mode = access_mode(store, method)
    last = None
    last_profile = None
    last_outcome = "no_response"

    for index, profile in enumerate(profile_order(store, method)):
        max_attempts = 1 if mode == "probe" else (2 if index == 0 else 1)
        for attempt in range(max_attempts):
            if not consume_request(store):
                return last, last_profile, "request_budget_exhausted"
            last_profile = profile
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
                last_outcome = outcome
                record_learning(
                    store,
                    profile,
                    "success" if outcome == "http_success" else "blocked" if outcome in BLOCK_OUTCOMES else outcome,
                    method,
                )
                if outcome == "http_success":
                    return response, profile, outcome
                if outcome in BLOCK_OUTCOMES or not retryable:
                    break
                if outcome not in RETRYABLE_SERVER:
                    break
            except Exception as exc:
                last_outcome = "request_error"
                record_learning(store, profile, "request_error", method)
                LOGGER.warning("Acesso falhou | %s | %s | %s | %s", store, method, profile, exc)

            if attempt + 1 < max_attempts:
                time.sleep(0.4 + random.random() * 0.5)
        if not budget_available(store):
            break
    return last, last_profile, last_outcome


# ---------------------------------------------------------------------------
# Descoberta: categoria + segmentos/filtros + paginação + sitemap
# ---------------------------------------------------------------------------


def _merge_candidate(target: dict[str, dict], item: dict, source: str) -> bool:
    url = item.get("url")
    if not url:
        return False
    if url in target:
        existing = target[url]
        if existing.get("preco") is None and item.get("preco") is not None:
            existing["preco"] = item["preco"]
        if existing.get("stock") is None and item.get("stock") is not None:
            existing["stock"] = item["stock"]
        if item.get("specs") and not existing.get("specs"):
            existing["specs"] = item["specs"]
        existing.setdefault("discovery_sources", [])
        if source not in existing["discovery_sources"]:
            existing["discovery_sources"].append(source)
        return False
    row = dict(item)
    row["discovery_sources"] = [source]
    target[url] = row
    return True


def pagination_urls(html: str, current_url: str, category_url: str, limit: int = 5) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    current = urlparse(current_url)
    category = urlparse(category_url)
    candidates: list[tuple[int, int, str]] = []

    for anchor in soup.find_all("a", href=True):
        full = urljoin(current_url, anchor["href"])
        parsed = urlparse(full)
        if not scraper.same_host(full, category_url):
            continue
        if full.rstrip("/") == current_url.rstrip("/"):
            continue

        rel = {str(value).lower() for value in (anchor.get("rel") or [])}
        text = scraper.norm(
            " ".join(
                filter(
                    None,
                    [
                        anchor.get_text(" ", strip=True),
                        anchor.get("aria-label"),
                        anchor.get("title"),
                        " ".join(anchor.get("class", [])),
                        " ".join(anchor.parent.get("class", [])) if anchor.parent else "",
                    ],
                )
            )
        )
        query = parse_qs(parsed.query)
        page_number = None
        for key in ("page", "pageindex", "pagina", "p", "pg", "pagenumber"):
            raw = query.get(key)
            if raw and str(raw[0]).isdigit():
                page_number = int(raw[0])
                break
        if page_number is None:
            match = re.search(r"/(?:page|pagina)/?(\d+)(?:/|$)", parsed.path.lower())
            if match:
                page_number = int(match.group(1))

        pagination_context = any(
            marker in text
            for marker in ("pagination", "paginacao", "pager", "seguinte", "proxima", "next", "mais artigos")
        )
        if "next" in rel:
            candidates.append((0, page_number or 999, full))
        elif page_number and (pagination_context or parsed.path.rstrip("/") == category.path.rstrip("/")):
            candidates.append((1, page_number, full))

    out = []
    seen = set()
    for _, _, url in sorted(candidates):
        if url not in seen:
            seen.add(url)
            out.append(url)
            if len(out) >= limit:
                break
    return out


def configured_pagination_urls(cat: dict, max_pages: int) -> list[str]:
    template = cat.get("pagination_template")
    if not template or max_pages <= 1:
        return []
    start = int(cat.get("pagination_start", 2))
    out = []
    for page in range(start, start + max_pages - 1):
        rendered = str(template).format(page=page)
        out.append(urljoin(cat["url"], rendered))
    return out


def sitemap_parse(content: bytes, text: str, max_children: int = 10) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if root.tag.lower().endswith("sitemapindex"):
            children = [
                node.text.strip()
                for node in root.findall("sm:sitemap/sm:loc", ns)
                if node.text
            ]
            children.sort(
                key=lambda url: (
                    0
                    if any(marker in url.lower() for marker in ("product", "produto", "catalog", "portatil", "laptop"))
                    else 1,
                    url,
                )
            )
            return [], children[:max_children]
        return [
            node.text.strip()
            for node in root.findall("sm:url/sm:loc", ns)
            if node.text
        ], []
    except ET.ParseError:
        return re.findall(r"<loc>\s*(https?://[^\s<>]+)\s*</loc>", text, flags=re.I), []


def _brand_url_score(url: str) -> int:
    path = scraper.norm(urlparse(url).path.replace("-", " ").replace("_", " "))
    parent, sub = scraper.brand(path)
    if parent and sub:
        return 3
    if parent:
        return 2
    return 0


def _sitemap_product_score(url: str) -> int:
    text = scraper.norm(urlparse(url).path.replace("-", " ").replace("_", " "))
    score = _brand_url_score(url) * 10
    # Com budget hard de 1500€, priorizamos familias com maior probabilidade de
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
    for marker, bonus in priorities.items():
        if marker in text:
            score += bonus
    if any(marker in text for marker in ("rtx 5070", "rtx 5060", "rtx 5050")):
        score += 5
    return score


def _looks_like_product_url(url: str, cat: dict) -> bool:
    if not scraper.same_host(url, cat["url"]):
        return False
    path = urlparse(url).path.lower()
    if not scraper.product_path_ok(url, cat.get("product_path_hints", [])):
        return False
    if _brand_url_score(url) > 0:
        return True
    if path.endswith((".html", ".htm")):
        return True
    if re.search(r"/(?:a|a-|p|produto|product)[/-]?\d{3,}", path):
        return True
    return False


def discover_sitemap_urls(
    cat: dict,
    config: dict,
    *,
    max_urls: int = 80,
    max_sitemaps: int = 8,
) -> list[str]:
    store = cat["loja"]
    if access_mode(store, "sitemap") == "probe":
        return []

    origin = f"{urlparse(cat['url']).scheme}://{urlparse(cat['url']).netloc}"
    robots, _, _ = adaptive_fetch(
        urljoin(origin, "/robots.txt"), config, 6, store=store, method="robots"
    )
    seeds = []
    if robots and robots.status_code < 400:
        seeds = [
            line.split(":", 1)[1].strip()
            for line in robots.text.splitlines()
            if line.lower().startswith("sitemap:")
        ]
    if not seeds:
        seeds = [
            urljoin(origin, candidate)
            for candidate in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-products.xml")
        ]

    queue = deque(seeds)
    seen_sitemaps = set()
    found: dict[str, int] = {}
    while queue and len(seen_sitemaps) < max_sitemaps and budget_available(store):
        sitemap_url = queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        response, _, _ = adaptive_fetch(
            sitemap_url, config, 6, store=store, method="sitemap"
        )
        if not response or response.status_code >= 400:
            continue
        urls, children = sitemap_parse(response.content, response.text, max_sitemaps)
        for child in children:
            if child not in seen_sitemaps:
                queue.append(child)
        for url in urls:
            if _looks_like_product_url(url, cat):
                found[url] = max(found.get(url, 0), _sitemap_product_score(url))

    return [
        url
        for url, _score in sorted(found.items(), key=lambda item: (-item[1], item[0]))[:max_urls]
    ]


def jsonld_primary_product(soup: BeautifulSoup, page_url: str = "", title_hint: str = "") -> dict:
    products = scraper.jsonld_products(soup)
    if not products:
        return {}

    def clean_url(value: object) -> str:
        if not value:
            return ""
        parsed = urlparse(str(value))
        return parsed._replace(query="", fragment="").geturl().rstrip("/").lower()

    target_url = clean_url(page_url)
    if target_url:
        for product in products:
            if clean_url(product.get("url")) == target_url:
                return product

    hint = scraper.norm(title_hint)
    if hint:
        for product in products:
            candidate = scraper.norm(product.get("titulo", ""))
            if candidate and (candidate == hint or candidate in hint or hint in candidate):
                return product

    return next((product for product in products if product.get("preco") is not None), products[0])


def jsonld_price_title(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    product = jsonld_primary_product(soup)
    if not product:
        return None, None
    price = product.get("preco")
    return (float(price) if price is not None else None), product.get("titulo")


def gtin_valid(value: object) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) not in {8, 12, 13, 14}:
        return False
    body = [int(char) for char in digits[:-1]]
    check = int(digits[-1])
    total = sum(number * (3 if index % 2 == 0 else 1) for index, number in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def page_identifiers(soup: BeautifulSoup) -> dict:
    text = " ".join(soup.stripped_strings)
    out = {}
    ean = re.search(r"(?:c[oó]digo\s*)?(?:ean|gtin(?:-?1[234])?)\s*[:#-]?\s*([0-9][0-9\s-]{6,20})", text, re.I)
    if ean:
        digits = re.sub(r"\D", "", ean.group(1))
        if gtin_valid(digits):
            out["ean"] = digits
    mpn = re.search(r"(?:part[- ]?number|part\s*number|mpn|p\s*/\s*n)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/#-]{4,})", text, re.I)
    if mpn:
        out["mpn"] = mpn.group(1).strip().rstrip(".,;:")
    sku = re.search(r"\bsku\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/#-]{4,})", text, re.I)
    if sku:
        out["sku"] = sku.group(1).strip().rstrip(".,;:")
    return out


def url_ean(url: str) -> str | None:
    """Extrai GTIN/EAN embebido no URL publico (muito util na PCDiga)."""
    path = urlparse(str(url or "")).path
    for digits in reversed(re.findall(r"(?<!\d)(\d{8}|\d{12,14})(?!\d)", path)):
        if gtin_valid(digits):
            return digits
    return None


def preferred_page_price(soup: BeautifulSoup, structured_price: float | None = None) -> float | None:
    """Preco de produto por sinais fortes; nunca usa o menor euro da pagina inteira."""
    selectors = [
        "meta[itemprop='price'][content]",
        "meta[property='product:price:amount'][content]",
        "meta[property='og:price:amount'][content]",
        "[itemprop='offers'] [itemprop='price']",
        "[data-price-type='finalPrice'] [data-price-amount]",
        "[data-price-type='finalPrice']",
        "[class*='current-price']",
        "[class*='currentPrice']",
        "[class*='price-current']",
        "[class*='priceCurrent']",
        "[class*='final-price']",
        "[class*='finalPrice']",
        "[class*='special-price']",
        "[class*='sale-price']",
    ]
    bad = (
        "discount", "desconto", "saving", "poupanca", "poupa", "cashback",
        "voucher", "cupao", "coupon", "mensal", "prestacao", "installment",
        "financiamento", "finance", "old-price", "oldprice", "preco antigo",
    )
    values = []
    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            context = scraper.norm(
                " ".join([
                    " ".join(node.get("class", [])),
                    str(node.get("id") or ""),
                    node.get_text(" ", strip=True),
                ])
            )
            if any(token in context for token in bad):
                continue
            raw = (
                node.get("content")
                or node.get("data-price-amount")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            direct = scraper.parse_price_value(raw)
            if direct is not None and 200 <= direct <= 10000:
                values.append(float(direct))
                continue
            values.extend(v for v in scraper.prices(str(raw)) if 200 <= v <= 10000)
    if values:
        return min(values)
    if structured_price is not None and 200 <= float(structured_price) <= 10000:
        return float(structured_price)
    return None


def _product_fetch_urls(item: dict, config: dict) -> list[tuple[str, str]]:
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

    stock_value = scraper.stock(text)
    if stock_value is not None:
        result["stock"] = stock_value

    extracted = scraper.extract(result.get("titulo", real_title), soup)
    extracted["page_url"] = response.url
    extracted["acesso_profile"] = profile
    result["specs"] = extracted
    result["detail_source"] = "live"
    result["fetch_source"] = used_method
    result["identity_checked_at"] = now_iso()

    outcome = (
        "valid_product"
        if result.get("preco") is not None and scraper.eligible(result.get("titulo", ""))
        else "no_product_or_price"
    )
    record_result(store, used_method, profile or "none", outcome)
    return result, {"error": None, "profile": profile, "access": access, "result": outcome}


def _empty_store_stats() -> dict:
    return {
        "candidatos": 0,
        "avaliados": 0,
        "detalhes_live": 0,
        "identity_refreshes": 0,
        "price_refreshes": 0,
        "cache_reutilizada": 0,
        "aceites": 0,
        "rejeitados": 0,
        "bloqueada": False,
        "paginas_categoria": 0,
        "segmentos_categoria": 0,
        "sitemap_urls": 0,
        "fontes_descoberta": {
            "categoria": 0,
            "segmento": 0,
            "paginacao": 0,
            "sitemap": 0,
        },
        "rendimento_descoberta": {},
        "acesso": {},
    }


def _discover_html(response, route_cat: dict, target: int, candidates: dict[str, dict], source: str, stat: dict) -> int:
    before = len(candidates)
    for item in scraper.discover_category(response.text, route_cat, target):
        if _merge_candidate(candidates, item, source):
            stat["fontes_descoberta"][source] += 1
    return len(candidates) - before


def scan_store(cat: dict, config: dict, settings: dict) -> tuple[list[dict], dict]:
    store = cat["loja"]
    stat = _empty_store_stats()
    target = int(cat.get("target_candidates", settings.get("max_candidates_per_store", 60)))
    max_pages = int(cat.get("max_category_pages", settings.get("max_category_pages", 4)))
    sitemap_limit = int(cat.get("max_sitemap_urls", settings.get("max_sitemap_urls_per_store", 80)))
    supplement_limit = int(cat.get("sitemap_probe_limit", settings.get("sitemap_probe_limit", 6)))
    sitemap_threshold = int(settings.get("sitemap_supplement_below", 24))
    max_sitemaps = int(cat.get("max_sitemaps", 8))
    sitemap_enabled = bool(cat.get("sitemap_enabled", True))

    candidates: dict[str, dict] = {}
    pagination_queue: deque[tuple[str, str]] = deque()
    visited = set()

    before_requests = REQUESTS_BY_STORE.get(store, 0)
    before_candidates = len(candidates)
    response, profile, access = adaptive_fetch(
        cat["url"],
        config,
        min(8, float(cat.get("timeout_ms", 12000)) / 1000),
        store=store,
        method="category",
    )
    primary_ok = bool(response and response.status_code < 400)
    stat["acesso"] = {
        "perfil_categoria": profile,
        "resultado": access,
        "modo": access_mode(store, "category"),
    }
    if primary_ok:
        stat["paginas_categoria"] = 1
        _discover_html(response, cat, target, candidates, "categoria", stat)
        for page_url in pagination_urls(response.text, cat["url"], cat["url"], max_pages * 3):
            pagination_queue.append((page_url, cat["url"]))
    _record_discovery_stat(stat, store, "category", before_requests, before_candidates, len(candidates))

    # Templates confirmados podem funcionar mesmo que a landing principal esteja bloqueada.
    for page_url in configured_pagination_urls(cat, max_pages):
        pagination_queue.append((page_url, cat["url"]))

    # Fallbacks/segmentos públicos são tentados mesmo quando a categoria principal falha.
    for route in discovery_routes(cat, store)[:int(settings.get("max_segment_routes", 4))]:
        if len(candidates) >= target or not budget_available(store):
            break
        before_requests = REQUESTS_BY_STORE.get(store, 0)
        before_candidates = len(candidates)
        access_method = f"category_variant:{route['label']}"
        segment_response, _, segment_access = adaptive_fetch(
            route["url"], config, 7, store=store, method=access_method
        )
        if segment_response and segment_response.status_code < 400:
            stat["segmentos_categoria"] += 1
            segment_cat = dict(cat)
            segment_cat["url"] = route["url"]
            gained = _discover_html(segment_response, segment_cat, target, candidates, "segmento", stat)
            for page_url in pagination_urls(segment_response.text, route["url"], route["url"], max_pages * 2):
                pagination_queue.append((page_url, route["url"]))
            LOGGER.info(
                "Segmento | %s | %s | +%d | candidatos=%d | acesso=%s | yield_hist=%.2f",
                store, route["label"], gained, len(candidates), segment_access, route["yield_score"],
            )
        _record_discovery_stat(
            stat, store, route["method_key"], before_requests, before_candidates, len(candidates)
        )

    # Paginação real ou templates públicos, com deduplicação entre categoria e segmentos.
    pages_attempted = 0
    while pagination_queue and pages_attempted < max(0, max_pages - 1) and len(candidates) < target and budget_available(store):
        page_url, base_url = pagination_queue.popleft()
        marker = page_url.rstrip("/")
        if marker in visited or marker == cat["url"].rstrip("/"):
            continue
        visited.add(marker)
        pages_attempted += 1
        before_requests = REQUESTS_BY_STORE.get(store, 0)
        before_candidates = len(candidates)
        page_response, _, page_access = adaptive_fetch(
            page_url, config, 7, store=store, method="category_page"
        )
        if page_response and page_response.status_code < 400:
            stat["paginas_categoria"] += 1
            page_cat = dict(cat)
            page_cat["url"] = page_url
            gained = _discover_html(page_response, page_cat, target, candidates, "paginacao", stat)
            for discovered in pagination_urls(page_response.text, page_url, base_url, max_pages * 2):
                if discovered.rstrip("/") not in visited:
                    pagination_queue.append((discovered, base_url))
            LOGGER.info(
                "Paginação | %s | página=%d | +%d | candidatos=%d | acesso=%s",
                store, stat["paginas_categoria"], gained, len(candidates), page_access,
            )
        _record_discovery_stat(
            stat, store, "pagination", before_requests, before_candidates, len(candidates)
        )

    # Sitemap é um método independente: bloqueio da categoria não o desativa.
    if (
        sitemap_enabled
        and len(candidates) < min(target, sitemap_threshold)
        and access_mode(store, "sitemap") != "probe"
        and budget_available(store)
    ):
        before_requests = REQUESTS_BY_STORE.get(store, 0)
        before_candidates = len(candidates)
        sitemap_urls_found = discover_sitemap_urls(
            cat,
            config,
            max_urls=sitemap_limit,
            max_sitemaps=max_sitemaps,
        )
        stat["sitemap_urls"] = len(sitemap_urls_found)
        seeds = [url for url in sitemap_urls_found if url not in candidates][:supplement_limit]
        futures = []
        with ThreadPoolExecutor(max_workers=min(4, len(seeds) or 1)) as executor:
            for url in seeds:
                if not reserve_detail_slot():
                    break
                seed = {
                    "loja": store,
                    "titulo": url.rstrip("/").split("/")[-1].replace("-", " "),
                    "preco": None,
                    "url": url,
                    "stock": None,
                    "ean": url_ean(url),
                }
                futures.append(executor.submit(enrich, seed, config))
            for future in as_completed(futures):
                item, error = future.result()
                if (
                    not error.get("error")
                    and item.get("preco") is not None
                    and scraper.eligible(item.get("titulo", ""))
                ):
                    if _merge_candidate(candidates, item, "sitemap"):
                        stat["fontes_descoberta"]["sitemap"] += 1
                        stat["detalhes_live"] += 1
        _record_discovery_stat(stat, store, "sitemap", before_requests, before_candidates, len(candidates))

    stat["candidatos"] = len(candidates)
    stat["bloqueada"] = not primary_ok and stat["segmentos_categoria"] == 0 and len(candidates) == 0
    return list(candidates.values()), stat


# ---------------------------------------------------------------------------
# Seleção e cache de especificações
# ---------------------------------------------------------------------------


def candidate_priority(item: dict, weights: dict, settings: dict) -> float:
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
        weights.get("cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70}).get(cpu_tier, 50)
    )
    ram = spec.get("ram_gb")
    p_ram = 50.0 if ram is None else 100.0 if ram >= 32 else 80.0 if ram >= 16 else 40.0
    storage = spec.get("armazenamento_tb")
    p_storage = 50.0 if storage is None else 100.0 if storage >= 2 else 85.0 if storage >= 1 else 65.0
    hardware = 0.50 * p_gpu + 0.25 * p_cpu + 0.15 * p_ram + 0.10 * p_storage
    value_hint = 0.65 * hardware + 0.35 * scraper.price_score(price, settings)
    if gpu_model:
        value_hint += 8.0
    return round(value_hint, 3)


def select_for_evaluation(
    items: list[dict], max_items: int, weights: dict, settings: dict
) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[item["loja"]].append(item)
    for values in groups.values():
        values.sort(key=lambda row: (-candidate_priority(row, weights, settings), float(row.get("preco") or 99999)))

    if len(items) <= max_items:
        return sorted(items, key=lambda row: (-candidate_priority(row, weights, settings), float(row.get("preco") or 99999)))

    selected: list[dict] = []
    selected_urls = set()
    guaranteed = min(6, max(2, max_items // max(1, len(groups) * 2)))
    for store in sorted(groups):
        for item in groups[store][:guaranteed]:
            if len(selected) >= max_items:
                break
            key = (item["loja"], item["url"])
            if key not in selected_urls:
                selected.append(item)
                selected_urls.add(key)

    remaining = sorted(
        items,
        key=lambda row: (-candidate_priority(row, weights, settings), float(row.get("preco") or 99999)),
    )
    for item in remaining:
        if len(selected) >= max_items:
            break
        key = (item["loja"], item["url"])
        if key not in selected_urls:
            selected.append(item)
            selected_urls.add(key)
    return selected



def _normal_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", scraper.norm(value or ""))


def _model_codes(title: str) -> set[str]:
    codes = set()
    for raw in re.findall(r"\b[A-Z0-9]{2,}(?:[-_][A-Z0-9]{2,})+\b", str(title or "").upper()):
        compact = raw.replace("_", "-")
        if not compact.startswith(("RTX-", "DDR-")):
            codes.add(compact)
    return codes


def configuration_signature(item: dict, spec: dict) -> str:
    """Identidade local conservadora de uma configuração."""
    for field in ("ean", "mpn", "sku"):
        raw = item.get(field)
        if raw:
            return f"{field}:{_normal_id(raw)}"

    fields = [
        scraper.norm(item.get("titulo", "")),
        str(spec.get("marca") or "?"),
        str(spec.get("submarca") or "?"),
        str(spec.get("cpu_modelo") or "?"),
        str(spec.get("gpu_modelo") or spec.get("gpu_tipo") or "?"),
        f"ram:{spec.get('ram_gb') if spec.get('ram_gb') is not None else '?'}",
        f"ssd:{spec.get('armazenamento_tb') if spec.get('armazenamento_tb') is not None else '?'}",
        f"res:{spec.get('ecra_res') or '?'}",
        f"hz:{spec.get('ecra_hz') if spec.get('ecra_hz') is not None else '?'}",
    ]
    return "cfg:" + "|".join(fields)


def _spec_equal(left: object, right: object) -> bool:
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
        if re.fullmatch(r"\d+(?:gb|tb|hz|w)?", token):
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


def build_cross_store_matches(records: list[dict]) -> dict:
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    counts = {"EXATO": 0, "FORTE": 0, "PROVAVEL": 0, "NAO_FUNDIR": 0}
    probable = []
    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            left_record, right_record = records[left], records[right]
            if left_record["item"].get("loja") == right_record["item"].get("loja"):
                continue
            result = match_configurations(
                left_record["item"], left_record["spec"], right_record["item"], right_record["spec"]
            )
            level = result["level"]
            if level in counts:
                counts[level] += 1
            if level in {"EXATO", "FORTE"}:
                union(left, right)
            elif level == "PROVAVEL" and len(probable) < 20:
                probable.append(
                    {
                        "left_store": left_record["item"]["loja"],
                        "left_url": left_record["item"]["url"],
                        "right_store": right_record["item"]["loja"],
                        "right_url": right_record["item"]["url"],
                        "reason": result["reason"],
                    }
                )

    grouped = defaultdict(list)
    for index, record in enumerate(records):
        grouped[find(index)].append(record)

    groups = []
    for members in grouped.values():
        stores = {member["item"]["loja"] for member in members}
        if len(stores) < 2:
            continue
        offers = sorted(
            [
                {
                    "loja": member["item"]["loja"],
                    "url": member["item"]["url"],
                    "titulo": member["item"]["titulo"],
                    "price": float(member["item"]["preco"]),
                    "tier": member.get("tier"),
                    "value_score": member.get("assessment", {}).get("value_score"),
                }
                for member in members
            ],
            key=lambda offer: offer["price"],
        )
        groups.append(
            {
                "configuration_key": _group_configuration_key(members),
                "stores": sorted(stores),
                "best_store": offers[0]["loja"],
                "best_price": offers[0]["price"],
                "spread_eur": round(offers[-1]["price"] - offers[0]["price"], 2),
                "offers": offers,
            }
        )
    groups.sort(key=lambda group: (-len(group["stores"]), group["best_price"]))
    return {
        "exact_pairs": counts["EXATO"],
        "strong_pairs": counts["FORTE"],
        "probable_pairs": counts["PROVAVEL"],
        "conflicting_pairs": counts["NAO_FUNDIR"],
        "groups": groups[:30],
        "probable_review": probable,
    }


def _price_close(left: float, right: float, settings: dict) -> bool:
    abs_tol = float(settings.get("price_confirmation_tolerance_eur", 5.0))
    pct_tol = float(settings.get("price_confirmation_tolerance_pct", 1.5)) / 100.0
    return abs(float(left) - float(right)) <= max(abs_tol, max(float(left), float(right)) * pct_tol)


def _exact_market_key(item: dict) -> str | None:
    ean = _normal_id(item.get("ean"))
    if ean:
        return f"ean:{ean}"
    mpn = _normal_id(item.get("mpn"))
    if mpn:
        return f"mpn:{mpn}"
    return None


def apply_exact_market_price_evidence(records: list[dict], settings: dict) -> dict:
    """Confirma preço apenas com EAN/MPN exato em lojas independentes."""
    from statistics import median

    market_fields = (
        "market_price_confirmed", "market_price_confidence", "market_price_sources",
        "market_price_source_count", "market_price_identifier", "market_price_conflict",
    )
    for record in records:
        spec = record.get("spec") or {}
        for field in market_fields:
            spec.pop(field, None)

    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        item = record.get("item") or {}
        key = _exact_market_key(item)
        if key and item.get("preco") is not None:
            groups[key].append(record)

    confirmed_groups = 0
    outliers = 0
    for key, members in groups.items():
        if len({str(member["item"].get("loja")) for member in members}) < 2:
            continue

        candidates = []
        for center_member in members:
            center = float(center_member["item"]["preco"])
            cluster_by_store = {}
            for member in members:
                price = float(member["item"]["preco"])
                store = str(member["item"].get("loja"))
                if _price_close(center, price, settings):
                    previous = cluster_by_store.get(store)
                    if previous is None or abs(price - center) < abs(previous - center):
                        cluster_by_store[store] = price
            if len(cluster_by_store) >= 2:
                values = list(cluster_by_store.values())
                spread = max(values) - min(values)
                candidates.append((len(cluster_by_store), -spread, -center, cluster_by_store))

        if not candidates:
            continue
        _count, _spread, _center, cluster = max(candidates, key=lambda row: row[:3])
        market_price = round(float(median(cluster.values())), 2)
        source_stores = sorted(cluster)
        confirmed_groups += 1

        for member in members:
            spec = member["spec"]
            item_price = float(member["item"]["preco"])
            conflict = not _price_close(item_price, market_price, settings)
            spec["market_price_confirmed"] = market_price
            spec["market_price_confidence"] = "HIGH"
            spec["market_price_sources"] = source_stores
            spec["market_price_source_count"] = len(source_stores)
            spec["market_price_identifier"] = key
            spec["market_price_conflict"] = conflict
            outliers += int(conflict)

    return {"confirmed_groups": confirmed_groups, "outliers": outliers}


def select_with_cache(
    items: list[dict],
    spec_cache: dict[str, dict],
    max_items: int,
    weights: dict,
    settings: dict,
) -> list[dict]:
    """Cache aumenta cobertura: cached primeiro, slots restantes para produtos novos."""
    if max_items <= 0:
        return []
    cached = [
        item for item in items
        if item.get("specs") or (item.get("url") and item["url"] in spec_cache)
    ]
    cached_selected = select_for_evaluation(
        cached, min(max_items, len(cached)), weights, settings
    ) if cached else []
    cached_keys = {(item["loja"], item["url"]) for item in cached_selected}
    remaining_slots = max(0, max_items - len(cached_selected))
    if remaining_slots == 0:
        return cached_selected
    uncached = [
        item for item in items
        if (item["loja"], item["url"]) not in cached_keys
        and not item.get("specs")
        and item.get("url") not in spec_cache
    ]
    return cached_selected + select_for_evaluation(
        uncached, min(remaining_slots, len(uncached)), weights, settings
    )


PRICE_EVIDENCE_FIELDS = {
    "price_confirmed",
    "price_page_confidence",
    "price_evidence_sources",
    "price_evidence_count",
    "price_evidence_signals",
    "price_checked_at",
    "market_price_confirmed",
    "market_price_confidence",
    "market_price_sources",
    "market_price_source_count",
    "market_price_identifier",
    "market_price_conflict",
}


def _hardware_cache_copy(specs: dict) -> dict:
    """Specs persistem; evidência de preço é sempre recalculada na run atual."""
    return {key: value for key, value in specs.items() if key not in PRICE_EVIDENCE_FIELDS}


def latest_specs_by_url(history: dict) -> dict[str, dict]:
    out = {}
    for entries in (history.get("offers", {}) or {}).values():
        if not isinstance(entries, list) or not entries:
            continue
        entry = entries[-1]
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        specs = entry.get("specs")
        if url and isinstance(specs, dict) and entry.get("tracker_version") in COMPATIBLE_STATE_VERSIONS:
            out[url] = _hardware_cache_copy(specs)
    return out


def latest_offer_by_url(history: dict) -> dict[str, dict]:
    out = {}
    for entries in (history.get("offers", {}) or {}).values():
        if not isinstance(entries, list) or not entries:
            continue
        entry = entries[-1]
        if isinstance(entry, dict) and entry.get("url") and entry.get("tracker_version") in COMPATIBLE_STATE_VERSIONS:
            out[entry["url"]] = entry
    return out


def needs_identity_refresh(previous_meta: dict | None) -> bool:
    """Uma ficha cached só é reaberta se ainda não tiver ID forte nem tiver sido verificada para identidade."""
    if not isinstance(previous_meta, dict) or not previous_meta:
        return False
    if previous_meta.get("ean") or previous_meta.get("mpn"):
        return False
    return not bool(previous_meta.get("identity_checked_at"))



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




def reusable_price_evidence(previous_meta: dict | None, item: dict, settings: dict) -> dict:
    """Reutiliza confirmação da ficha apenas durante o TTL e se o preço atual coincidir."""
    if not isinstance(previous_meta, dict) or not previous_meta:
        return {}
    try:
        current_price = float(item.get("preco"))
    except (TypeError, ValueError):
        return {}
    if current_price >= float(settings.get("budget_soft", 1300.0)):
        return {}
    if needs_price_refresh(previous_meta, item, settings):
        return {}
    previous_spec = previous_meta.get("specs") if isinstance(previous_meta.get("specs"), dict) else {}
    fields = (
        "price_confirmed",
        "price_page_confidence",
        "price_evidence_sources",
        "price_evidence_count",
        "price_evidence_signals",
        "price_checked_at",
    )
    return {field: previous_spec[field] for field in fields if field in previous_spec}

def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
    adjusted = dict(spec)
    if adjusted.get("teclado_pt") == "desconhecido":
        adjusted["teclado_pt"] = "confirmado"
    return scraper.score(adjusted, price, weights, settings)


# ---------------------------------------------------------------------------
# NTFY: oportunidades + heartbeat independente
# ---------------------------------------------------------------------------


def ntfy_send(
    title: str,
    message: str,
    *,
    priority: int = 3,
    tags: list[str] | None = None,
) -> bool:
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    payload = {
        "topic": topic,
        "title": title[:180],
        "message": message,
        "tags": tags or ["computer"],
        "priority": priority,
    }
    for attempt in range(2):
        try:
            response = requests.post("https://ntfy.sh", json=payload, timeout=8)
            response.raise_for_status()
            return True
        except Exception as exc:
            LOGGER.warning("NTFY falhou | %s", exc)
            if attempt == 0:
                time.sleep(0.5 + random.random() * 0.5)
    return False


def send_heartbeat(run: dict) -> bool:
    stores_ok = sum(1 for stats in run["stores"].values() if not stats.get("bloqueada"))
    blocked = len(run["stores"]) - stores_ok
    matching = run.get("matching", {})
    message = (
        f"V{VERSION} operacional\n"
        f"Lojas acessíveis: {stores_ok}/{len(run['stores'])} | bloqueadas: {blocked}\n"
        f"Descobertos: {run['total_candidates']} | avaliados: {run['total_evaluated']} | aceites: {run['total_accepted']}\n"
        f"Detalhes live: {run['detail_fetches']} | cache: {run['cache_reused']} | identidade: {run.get('identity_refreshes', 0)} | preço: {run.get('price_refreshes', 0)}\n"
        f"Matching: {len(matching.get('groups', []))} grupos | exatos: {matching.get('exact_pairs', 0)} | fortes: {matching.get('strong_pairs', 0)}\n"
        f"Pedidos HTTP: {run['access_requests']} | tempo: {run['runtime_seconds']:.1f}s\n"
        f"D/O/P/B: {run['tiers']['DIAMANTE']}/{run['tiers']['OURO']}/{run['tiers']['PRATA']}/{run['tiers']['BRONZE']}"
    )
    return ntfy_send(
        f"💓 Heartbeat Rastreador V{VERSION}",
        message,
        priority=2,
        tags=["heartbeat", "computer"],
    )


# ---------------------------------------------------------------------------
# Histórico e alertas
# ---------------------------------------------------------------------------


def _history_base() -> dict:
    return {
        "schema_version": 8,
        "tracker_version": VERSION,
        "offers": {},
        "alert_state": {},
        "learning": {"runs": [], "stores": {}},
    }


def load_history() -> dict:
    history = load_json(HISTORY_PATH)
    if not isinstance(history, dict) or not isinstance(history.get("offers"), dict):
        history = _history_base()
    history.setdefault("schema_version", 8)
    history["tracker_version"] = VERSION
    history.setdefault("offers", {})
    history.setdefault("alert_state", {})
    history.setdefault("learning", {"runs": [], "stores": {}})
    history["learning"].setdefault("runs", [])
    history["learning"].setdefault("stores", {})
    return history



def compact_history(history: dict, entries_per_url: int = 3, keep_runs: int = 8) -> dict:
    """Mantém estado compatível V8.5+ sem perder cache recente, alertas e runs úteis."""
    out = _history_base()
    grouped: dict[str, list[dict]] = defaultdict(list)
    offers = history.get("offers", {}) if isinstance(history.get("offers"), dict) else {}
    for entries in offers.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not url or entry.get("tracker_version") not in COMPATIBLE_STATE_VERSIONS:
                continue
            grouped[str(url)].append(entry)

    for url, entries in grouped.items():
        out["offers"][url] = sorted(entries, key=_timestamp)[-entries_per_url:]

    active_urls = set(out["offers"])
    alerts = history.get("alert_state", {}) if isinstance(history.get("alert_state"), dict) else {}
    out["alert_state"] = {
        key: value for key, value in alerts.items()
        if (key in active_urls or str(key).startswith("cross_store:")) and isinstance(value, dict)
    }

    learning = history.get("learning", {}) if isinstance(history.get("learning"), dict) else {}
    runs = [
        run for run in (learning.get("runs", []) or [])
        if isinstance(run, dict) and run.get("runner_version") in COMPATIBLE_STATE_VERSIONS
    ]
    out["learning"]["runs"] = sorted(runs, key=_timestamp)[-keep_runs:]
    if isinstance(learning.get("stores"), dict):
        out["learning"]["stores"] = learning["stores"]
    out["tracker_version"] = VERSION
    return out


def previous_for_url(history: dict, url: str) -> dict | None:
    direct = history.get("offers", {}).get(url)
    if isinstance(direct, list) and direct:
        return direct[-1]
    for entries in history.get("offers", {}).values():
        if isinstance(entries, list) and entries and isinstance(entries[-1], dict):
            if entries[-1].get("url") == url:
                return entries[-1]
    return None


def record_offer(
    history: dict,
    item: dict,
    spec: dict,
    assessment: dict,
    tier: str | None,
) -> tuple[dict | None, str]:
    url = item["url"]
    previous = previous_for_url(history, url)
    key = url
    entries = history["offers"].setdefault(key, [])
    entries.append(
        {
            "timestamp": now_iso(),
            "tracker_version": VERSION,
            "loja": item["loja"],
            "titulo": item["titulo"],
            "price": item["preco"],
            "stock": item.get("stock"),
            "score_final": assessment["score_final"],
            "score_ranking": assessment["score_ranking"],
            "value_score": assessment["value_score"],
            "tier": tier,
            "specs": spec,
            "url": url,
            "configuration_key": configuration_signature(item, spec),
            "sku": item.get("sku"),
            "mpn": item.get("mpn"),
            "ean": item.get("ean"),
            "detail_source": item.get("detail_source"),
            "identity_checked_at": item.get("identity_checked_at"),
        }
    )
    del entries[:-30]
    return previous, key


def maybe_alert(
    history: dict,
    item: dict,
    spec: dict,
    assessment: dict,
    tier: str | None,
    previous: dict | None,
    alert_key: str,
    settings: dict,
) -> tuple[bool, bool]:
    if not tier or item.get("stock") is False:
        return False, False
    min_alert = float(settings.get("min_value_score_alerta", 70))
    if assessment["value_score"] < min_alert:
        return False, False

    order = {"BRONZE": 1, "PRATA": 2, "OURO": 3, "DIAMANTE": 4}
    min_notify = str(settings.get("alerta_min_tier", "OURO")).upper()
    prior = history["alert_state"].get(alert_key)
    base_price = previous.get("price") if previous else None
    base_value = float(previous.get("value_score", 0)) if previous else 0.0
    base_tier = previous.get("tier") if previous else None
    current_base = float(prior.get("price")) if prior and prior.get("price") is not None else base_price
    old_tier = prior.get("tier") if prior else base_tier
    price_drop = (
        current_base is not None
        and float(item["preco"]) <= current_base - float(settings.get("alerta_queda_preco_eur", 5))
    )
    opportunity = base_value < min_alert
    upgrade = bool(old_tier and order.get(tier, 0) > order.get(old_tier, 0))
    first = prior is None
    should_notify = first or opportunity or upgrade or price_drop
    can_push = order.get(tier, 0) >= order.get(min_notify, 3)
    if not should_notify:
        return False, False
    if not can_push:
        return False, True

    emoji = {"DIAMANTE": "💎", "OURO": "🥇"}.get(tier, "💻")
    title = f"{emoji} {tier}: {item['titulo']}"
    message = (
        f"{item['titulo']}\n"
        f"Loja: {item['loja']} | Preço: {float(item['preco']):.2f}€\n"
        f"Value: {assessment['value_score']:.1f} | Rank: {assessment['score_ranking']:.1f}\n"
        f"GPU: {spec.get('gpu_modelo') or spec.get('gpu_tipo')} | CPU: {spec.get('cpu_modelo') or '?'}\n"
        f"RAM: {spec.get('ram_gb') or '?'}GB | SSD: {spec.get('armazenamento_tb') or '?'}TB\n"
        f"{item['url']}"
    )
    sent = ntfy_send(
        title,
        message,
        priority=5 if tier == "DIAMANTE" else 3,
        tags=["computer", "rotating_light"],
    )
    if sent:
        history["alert_state"][alert_key] = {
            "timestamp": now_iso(),
            "price": item["preco"],
            "value_score": assessment["value_score"],
            "tier": tier,
        }
    return sent, False


def maybe_alert_cross_store(history: dict, group: dict, settings: dict) -> bool:
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
        f"{best['titulo']}\n"
        f"Melhor: {best['loja']} — {best['price']:.2f}€\n"
        f"Mais cara: {worst['loja']} — {worst['price']:.2f}€\n"
        f"Diferença: {spread:.2f}€ ({pct:.1f}%)\n"
        f"Tier/Value melhor oferta: {best.get('tier') or '—'} / {best.get('value_score') or '—'}\n"
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


# ---------------------------------------------------------------------------
# Execução V8.7
# ---------------------------------------------------------------------------


def main() -> dict:
    global RUN_STARTED, RUN_DEADLINE, REQUESTS_USED, REQUESTS_BY_STORE
    global DETAIL_FETCHES_USED, MAX_REQUESTS, MAX_REQUESTS_PER_STORE, MAX_DETAIL_FETCHES, LEARNING

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    RUN_STARTED = time.monotonic()
    RUN_DEADLINE = RUN_STARTED + max(1.0, float(os.getenv("RUN_MAX_MINUTES", "8"))) * 60
    REQUESTS_USED = 0
    REQUESTS_BY_STORE = defaultdict(int)
    DETAIL_FETCHES_USED = 0
    LEARNING = load_learning()

    config = load_json(CONFIG_PATH)
    settings = config.get("settings", {})
    weights = config.get("weights", {})
    MAX_REQUESTS = int(os.getenv("RUN_MAX_REQUESTS", settings.get("max_requests_per_run", 180)))
    MAX_REQUESTS_PER_STORE = int(
        os.getenv("RUN_MAX_REQUESTS_PER_STORE", settings.get("max_requests_per_store", 40))
    )
    MAX_DETAIL_FETCHES = int(
        os.getenv("RUN_MAX_DETAIL_FETCHES", settings.get("max_detail_fetches_per_run", 50))
    )
    max_evaluated = int(settings.get("max_evaluated_per_run", 60))
    min_price = float(settings.get("preco_minimo_global", 250))
    hard = float(settings.get("budget_hard", 1500))

    history = compact_history(load_history())
    spec_cache = latest_specs_by_url(history)
    offer_cache = latest_offer_by_url(history)
    all_items: list[dict] = []
    stats: dict[str, dict] = {}

    for cat in config.get("category_urls", []):
        if not budget_available():
            break
        store = cat["loja"]
        items, stat = scan_store(cat, config, settings)
        clean = []
        seen = set()
        for item in items:
            price = item.get("preco")
            url = item.get("url")
            if (
                url
                and url not in seen
                and price is not None
                and min_price <= float(price) <= hard
                and scraper.eligible(item.get("titulo", ""))
            ):
                seen.add(url)
                clean.append(item)
        stat["candidatos"] = len(clean)
        stats[store] = stat
        all_items.extend(clean)
        LOGGER.info(
            "Scan | %s | candidatos=%d | páginas=%d | segmentos=%d | sitemap=%d | pedidos=%d | fontes=%s",
            store,
            len(clean),
            stat["paginas_categoria"],
            stat["segmentos_categoria"],
            stat["sitemap_urls"],
            REQUESTS_BY_STORE.get(store, 0),
            stat["fontes_descoberta"],
        )

    unique: dict[tuple[str, str], dict] = {}
    for item in all_items:
        unique.setdefault((item["loja"], item["url"]), item)
    selected = select_with_cache(list(unique.values()), spec_cache, max_evaluated, weights, settings)
    LOGGER.info(
        "Pré-ranking V8.8.1 | descobertos=%d | selecionados=%d | limite=%d | detalhe_max=%d",
        len(unique),
        len(selected),
        max_evaluated,
        MAX_DETAIL_FETCHES,
    )

    evaluated: list[dict] = []
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
            cached_item["specs"].update(reusable_price_evidence(previous_meta, item, settings))
            for field in ("ean", "mpn", "sku", "identity_checked_at"):
                if previous_meta.get(field) and not cached_item.get(field):
                    cached_item[field] = previous_meta[field]
            cached_pending.append((item, cached_item, previous_meta))
            continue

        if reserve_detail_slot():
            to_fetch.append(item)

    max_price_refreshes = max(0, int(settings.get("max_price_refreshes_per_run", 12)))
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

    for original, cached_item, _ in cached_pending:
        if original["url"] in refresh_urls or original["url"] in price_refresh_urls:
            continue
        evaluated.append(cached_item)
        store = cached_item["loja"]
        stats[store]["avaliados"] += 1
        stats[store]["cache_reutilizada"] += 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}
        for item in to_fetch:
            futures[executor.submit(enrich, item, config)] = ("new", None)
        for item, cached_item in price_fetch:
            futures[executor.submit(enrich, item, config)] = ("price", cached_item)
        for item, cached_item in identity_fetch:
            futures[executor.submit(enrich, item, config)] = ("identity", cached_item)

        for future in as_completed(futures):
            mode, cached_fallback = futures[future]
            item, error = future.result()
            if error.get("error"):
                if mode in {"identity", "price"} and cached_fallback is not None:
                    # Falha de rede/acesso nao conta como identidade verificada; pode
                    # voltar a ser tentada numa run futura dentro do limite progressivo.
                    fallback = dict(cached_fallback)
                    fallback["detail_source"] = "price_refresh_failed" if mode == "price" else "identity_refresh_failed"
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
            elif mode == "price":
                item["detail_source"] = "price_refresh"
                stats[store]["price_refreshes"] += 1
            evaluated.append(item)
            stats[store]["avaliados"] += 1
            stats[store]["detalhes_live"] += 1

    preliminary_records = []
    for item in evaluated:
        spec = item.get("specs") or scraper.specs(item.get("titulo", ""))
        preliminary_records.append({"item": item, "spec": spec})
    market_evidence = apply_exact_market_price_evidence(preliminary_records, settings)
    LOGGER.info(
        "Preço cross-store | grupos_confirmados=%d | outliers=%d",
        market_evidence["confirmed_groups"], market_evidence["outliers"],
    )

    tiers = {"DIAMANTE": 0, "OURO": 0, "PRATA": 0, "BRONZE": 0}
    alerts = 0
    suppressed = 0
    current_ranked = []
    match_records = []

    for preliminary in preliminary_records:
        item = preliminary["item"]
        spec = preliminary["spec"]
        price = item.get("preco")
        store = item["loja"]
        if price is None:
            continue
        if not (min_price <= float(price) <= hard):
            stats[store]["rejeitados"] += 1
            continue
        if not scraper.price_is_plausible_for_title(item.get("titulo", ""), float(price)):
            stats[store]["rejeitados"] += 1
            continue
        assessment = score_allow_unknown(spec, float(price), weights, settings)
        if assessment.get("status") != "ACEITE":
            stats[store]["rejeitados"] += 1
            continue
        stats[store]["aceites"] += 1
        tier = scraper.tier_from_value(assessment["value_score"], settings)
        if tier:
            tiers[tier] += 1
        previous, alert_key = record_offer(history, item, spec, assessment, tier)
        sent, was_suppressed = maybe_alert(
            history, item, spec, assessment, tier, previous, alert_key, settings
        )
        alerts += int(sent)
        suppressed += int(was_suppressed)
        current_ranked.append((assessment["value_score"], item, tier, assessment))
        match_records.append({"item": item, "spec": spec, "assessment": assessment, "tier": tier})

    matching = build_cross_store_matches(match_records)
    cross_store_alerts = sum(
        int(maybe_alert_cross_store(history, group, settings))
        for group in matching.get("groups", [])
    )
    alerts += cross_store_alerts
    identity_refreshes = sum(row.get("identity_refreshes", 0) for row in stats.values())
    price_refreshes = sum(row.get("price_refreshes", 0) for row in stats.values())
    runtime = round(time.monotonic() - RUN_STARTED, 2)
    run = {
        "timestamp": now_iso(),
        "runner_version": VERSION,
        "stores": stats,
        "total_candidates": sum(row["candidatos"] for row in stats.values()),
        "selected_for_evaluation": len(selected),
        "total_evaluated": sum(row["avaliados"] for row in stats.values()),
        "total_accepted": sum(row["aceites"] for row in stats.values()),
        "alerts_sent": alerts,
        "notifications_suppressed": suppressed,
        "cross_store_alerts_sent": cross_store_alerts,
        "access_requests": REQUESTS_USED,
        "requests_by_store": dict(sorted(REQUESTS_BY_STORE.items())),
        "detail_fetches": DETAIL_FETCHES_USED,
        "identity_refreshes": identity_refreshes,
        "price_refreshes": price_refreshes,
        "cache_reused": sum(row["cache_reutilizada"] for row in stats.values()),
        "runtime_seconds": runtime,
        "tiers": tiers,
        "matching": matching,
    }

    run["access_health"] = summarize_access(
        run, per_store_limit=MAX_REQUESTS_PER_STORE, total_limit=MAX_REQUESTS
    )
    for store, health in run["access_health"]["stores"].items():
        LOGGER.info("Acesso | %s | estado=%s | categoria=%s | feed=%s | limite_loja=%s",
                    store, health["state"], health["category_outcome"], health["feed_outcome"],
                    health["store_budget_reached"])

    heartbeat_enabled = bool(settings.get("heartbeat_ntfy", True))
    run["heartbeat_sent"] = send_heartbeat(run) if heartbeat_enabled else False
    history["learning"]["runs"].append(run)
    history["learning"]["runs"] = history["learning"]["runs"][-60:]
    history["tracker_version"] = VERSION
    LEARNING["schema_version"] = 2
    LEARNING["updated_at"] = now_iso()
    save_json(HISTORY_PATH, history)
    save_json(LEARNING_PATH, LEARNING)

    LOGGER.info(
        "V8.8.1 | Lojas=%d | Descobertos=%d | Avaliados=%d | Aceites=%d | Pedidos=%d | "
        "Detalhes=%d | Cache=%d | Tempo=%.1fs | Heartbeat=%s | D=%d O=%d P=%d B=%d",
        len(stats),
        run["total_candidates"],
        run["total_evaluated"],
        run["total_accepted"],
        REQUESTS_USED,
        DETAIL_FETCHES_USED,
        run["cache_reused"],
        runtime,
        run["heartbeat_sent"],
        tiers["DIAMANTE"],
        tiers["OURO"],
        tiers["PRATA"],
        tiers["BRONZE"],
    )
    for store, stat in stats.items():
        LOGGER.info(
            "🏪 %s | cand=%d aval=%d live=%d id=%d price=%d cache=%d aceites=%d pedidos=%d bloqueada=%s",
            store,
            stat["candidatos"],
            stat["avaliados"],
            stat["detalhes_live"],
            stat.get("identity_refreshes", 0),
            stat.get("price_refreshes", 0),
            stat["cache_reutilizada"],
            stat["aceites"],
            REQUESTS_BY_STORE.get(store, 0),
            stat["bloqueada"],
        )
    LOGGER.info(
        "Matching | grupos=%d | exatos=%d | fortes=%d | prováveis=%d | conflitos=%d",
        len(matching["groups"]), matching["exact_pairs"], matching["strong_pairs"],
        matching["probable_pairs"], matching["conflicting_pairs"],
    )
    for group in matching["groups"][:5]:
        LOGGER.info(
            "MATCH | %s | melhor=%s %.2f€ | lojas=%s | spread=%.2f€",
            group["configuration_key"], group["best_store"], group["best_price"],
            ",".join(group["stores"]), group["spread_eur"],
        )
    for value, item, tier, assessment in sorted(current_ranked, reverse=True, key=lambda row: row[0])[:8]:
        LOGGER.info(
            "TOP | %s | %.2f€ | Value %.1f | Rank %.1f | %s | %s",
            item["loja"],
            float(item["preco"]),
            value,
            assessment["score_ranking"],
            tier or "—",
            item["titulo"],
        )
    return run


# ---------------------------------------------------------------------------
# Merge concorrente de estado (usado pelo GitHub Actions)
# ---------------------------------------------------------------------------


def _timestamp(record: dict) -> str:
    return str(record.get("timestamp") or record.get("updated_at") or "")


def _entry_id(entry: dict) -> tuple:
    return (
        entry.get("timestamp"),
        entry.get("url"),
        entry.get("price"),
        entry.get("value_score"),
        entry.get("tier"),
    )


def _merge_entry_lists(left: list, right: list, limit: int = 30) -> list:
    merged = {}
    for entry in [*left, *right]:
        if isinstance(entry, dict):
            merged[_entry_id(entry)] = entry
    return sorted(merged.values(), key=_timestamp)[-limit:]


def _merge_monotonic(left: Any, right: Any, key: str | None = None) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        return {
            name: _merge_monotonic(left.get(name), right.get(name), name)
            for name in set(left) | set(right)
        }
    if right is None:
        return left
    if left is None:
        return right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return max(left, right)
    if isinstance(left, list) and isinstance(right, list):
        result = []
        seen = set()
        for value in [*left, *right]:
            marker = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else repr(value)
            if marker not in seen:
                seen.add(marker)
                result.append(value)
        return result
    if key in {"updated_at", "last_updated", "timestamp"}:
        return max(str(left), str(right))
    return right


def merge_history(current: dict, run_state: dict) -> dict:
    out = _history_base()
    out["tracker_version"] = max(
        str(current.get("tracker_version", "")), str(run_state.get("tracker_version", ""))
    ) or VERSION
    current_offers = current.get("offers", {}) if isinstance(current.get("offers"), dict) else {}
    run_offers = run_state.get("offers", {}) if isinstance(run_state.get("offers"), dict) else {}
    for key in set(current_offers) | set(run_offers):
        left = current_offers.get(key, []) if isinstance(current_offers.get(key, []), list) else []
        right = run_offers.get(key, []) if isinstance(run_offers.get(key, []), list) else []
        out["offers"][key] = _merge_entry_lists(left, right)

    current_alerts = current.get("alert_state", {}) if isinstance(current.get("alert_state"), dict) else {}
    run_alerts = run_state.get("alert_state", {}) if isinstance(run_state.get("alert_state"), dict) else {}
    for key in set(current_alerts) | set(run_alerts):
        choices = [value for value in (current_alerts.get(key), run_alerts.get(key)) if isinstance(value, dict)]
        if choices:
            out["alert_state"][key] = max(choices, key=_timestamp)

    runs = {}
    for record in [
        *((current.get("learning", {}) or {}).get("runs", []) or []),
        *((run_state.get("learning", {}) or {}).get("runs", []) or []),
    ]:
        if isinstance(record, dict):
            marker = (record.get("timestamp"), record.get("runner_version"), record.get("access_requests"))
            runs[marker] = record
    out["learning"]["runs"] = sorted(runs.values(), key=_timestamp)[-60:]
    out["learning"]["stores"] = _merge_monotonic(
        (current.get("learning", {}) or {}).get("stores", {}),
        (run_state.get("learning", {}) or {}).get("stores", {}),
    )
    return compact_history(out)


def merge_access_learning(current: dict, run_state: dict) -> dict:
    merged = _merge_monotonic(current, run_state)
    if not isinstance(merged, dict):
        merged = {}
    merged["schema_version"] = 2
    return merged


def merge_state_files(
    history_current: Path,
    history_run: Path,
    learning_current: Path,
    learning_run: Path,
) -> None:
    save_json(history_current, merge_history(load_json(history_current), load_json(history_run)))
    save_json(
        learning_current,
        merge_access_learning(load_json(learning_current), load_json(learning_run)),
    )


def merge_cli(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Merge seguro do estado V8.6")
    parser.add_argument("--history-current", required=True, type=Path)
    parser.add_argument("--history-run", required=True, type=Path)
    parser.add_argument("--learning-current", required=True, type=Path)
    parser.add_argument("--learning-run", required=True, type=Path)
    args = parser.parse_args(argv)
    merge_state_files(
        args.history_current,
        args.history_run,
        args.learning_current,
        args.learning_run,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "merge-state":
        merge_cli(sys.argv[2:])
    else:
        main()
