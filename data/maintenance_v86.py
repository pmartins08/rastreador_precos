from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Bloco não encontrado: {label}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Regex não encontrou exatamente um bloco: {label} ({count})")
    return new


tracker_path = ROOT / "tracker.py"
tracker = tracker_path.read_text(encoding="utf-8")
tracker = replace_once(tracker, 'VERSION = "8.5"', 'VERSION = "8.6"\nCOMPATIBLE_STATE_VERSIONS = {"8.5", "8.6"}', "versão")
tracker = replace_once(
    tracker,
    '        "contexts": {},\n        "last_updated": None,',
    '        "contexts": {},\n        "discovery": {},\n        "last_updated": None,',
    "bucket discovery",
)
tracker = replace_once(
    tracker,
    '        store.setdefault("contexts", {})\n        store.setdefault("last_updated", None)',
    '        store.setdefault("contexts", {})\n        store.setdefault("discovery", {})\n        store.setdefault("last_updated", None)',
    "load discovery",
)

insert_discovery = '''def discovery_bucket(store: str, method: str) -> dict:\n    return bucket(store).setdefault("discovery", {}).setdefault(\n        method,\n        {\n            "attempts": 0,\n            "requests": 0,\n            "new_candidates": 0,\n            "last_yield": 0.0,\n            "ema_yield": 0.0,\n            "last_updated": None,\n        },\n    )\n\n\ndef record_discovery_yield(store: str, method: str, requests_spent: int, new_candidates: int) -> None:\n    if requests_spent <= 0:\n        return\n    with LOCK:\n        stats = discovery_bucket(store, method)\n        current_yield = max(0, int(new_candidates)) / max(1, int(requests_spent))\n        attempts = int(stats.get("attempts", 0))\n        previous_ema = float(stats.get("ema_yield", 0.0))\n        stats["attempts"] = attempts + 1\n        stats["requests"] = int(stats.get("requests", 0)) + int(requests_spent)\n        stats["new_candidates"] = int(stats.get("new_candidates", 0)) + max(0, int(new_candidates))\n        stats["last_yield"] = round(current_yield, 4)\n        stats["ema_yield"] = round(current_yield if attempts == 0 else 0.70 * previous_ema + 0.30 * current_yield, 4)\n        stats["last_updated"] = now_iso()\n\n\ndef discovery_score(store: str, method: str) -> float:\n    stats = bucket(store).get("discovery", {}).get(method, {})\n    attempts = int(stats.get("attempts", 0))\n    if attempts <= 0:\n        return 1.0  # exploração inicial\n    requests_count = max(1, int(stats.get("requests", 0)))\n    lifetime = int(stats.get("new_candidates", 0)) / requests_count\n    recent = float(stats.get("ema_yield", lifetime))\n    return round(0.55 * lifetime + 0.45 * recent, 4)\n\n\ndef discovery_routes(cat: dict, store: str) -> list[dict]:\n    routes = []\n    for index, raw in enumerate(cat.get("extra_discovery_urls", [])):\n        if isinstance(raw, str):\n            route = {"url": raw, "label": f"segment_{index + 1}"}\n        elif isinstance(raw, dict) and raw.get("url"):\n            route = {"url": str(raw["url"]), "label": str(raw.get("label") or f"segment_{index + 1}")}\n        else:\n            continue\n        route["method_key"] = f"segment:{route['label']}"\n        route["yield_score"] = discovery_score(store, route["method_key"])\n        routes.append(route)\n    return sorted(routes, key=lambda route: (-route["yield_score"], route["label"]))\n\n\ndef _record_discovery_stat(stat: dict, store: str, method: str, requests_before: int, candidates_before: int, candidates_after: int) -> None:\n    spent = max(0, int(REQUESTS_BY_STORE.get(store, 0)) - int(requests_before))\n    gained = max(0, int(candidates_after) - int(candidates_before))\n    entry = stat["rendimento_descoberta"].setdefault(method, {"requests": 0, "new_candidates": 0, "yield": 0.0})\n    entry["requests"] += spent\n    entry["new_candidates"] += gained\n    entry["yield"] = round(entry["new_candidates"] / max(1, entry["requests"]), 3)\n    record_discovery_yield(store, method, spent, gained)\n\n\n'''
tracker = replace_once(tracker, 'def _rate(stats: dict) -> tuple[float, int]:', insert_discovery + 'def _rate(stats: dict) -> tuple[float, int]:', "discovery learning functions")

new_access_mode = '''def access_mode(store: str, method: str) -> str:\n    # Um método novo deve ter uma oportunidade real de exploração mesmo quando\n    # métodos antigos da mesma loja foram bloqueados.\n    attempts, successes, blocks = _method_totals(store, method)\n    if attempts == 0:\n        return "normal"\n\n    b = bucket(store)\n    total_attempts = int(b.get("attempts", 0))\n    total_successes = int(b.get("successes", 0))\n    total_blocks = int(b.get("blocks", 0))\n    if (\n        total_attempts >= 30\n        and total_successes == 0\n        and total_blocks / max(1, total_attempts) >= 0.90\n        and attempts >= 3\n    ):\n        return "probe"\n\n    if attempts >= 12 and successes == 0 and blocks / max(1, attempts) >= 0.85:\n        return "probe"\n    return "normal"\n\n\ndef profile_order'''
tracker = regex_once(tracker, r'def access_mode\(store: str, method: str\) -> str:.*?\n\n\ndef profile_order', new_access_mode, "access mode")

tracker = replace_once(
    tracker,
    '    if access_mode(store, "category") == "probe":\n        return []',
    '    if access_mode(store, "sitemap") == "probe":\n        return []',
    "sitemap probe independente",
)

new_structured = r'''def jsonld_primary_product(soup: BeautifulSoup, page_url: str = "", title_hint: str = "") -> dict:
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


def enrich(item: dict, config: dict) -> tuple[dict, dict]:
    store = item["loja"]
    response, profile, access = adaptive_fetch(
        item["url"], config, 8, store=store, method="product"
    )
    if not response or response.status_code >= 400:
        record_result(store, "product", profile or "none", "access_failed")
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

    outcome = (
        "valid_product"
        if result.get("preco") is not None and scraper.eligible(result.get("titulo", ""))
        else "no_product_or_price"
    )
    record_result(store, "product", profile or "none", outcome)
    return result, {"error": None, "profile": profile, "access": access, "result": outcome}


'''
tracker = regex_once(tracker, r'def jsonld_price_title\(soup: BeautifulSoup\).*?\n\n\ndef _empty_store_stats', new_structured + 'def _empty_store_stats', "structured ids + enrich")

new_scan = r'''def _empty_store_stats() -> dict:
    return {
        "candidatos": 0,
        "avaliados": 0,
        "detalhes_live": 0,
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
    sitemap_limit = int(settings.get("max_sitemap_urls_per_store", 80))
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
    for route in discovery_routes(cat, store):
        if len(candidates) >= target or not budget_available(store):
            break
        before_requests = REQUESTS_BY_STORE.get(store, 0)
        before_candidates = len(candidates)
        segment_response, _, segment_access = adaptive_fetch(
            route["url"], config, 7, store=store, method="category_variant"
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
    pages_fetched = 0
    while pagination_queue and pages_fetched < max(0, max_pages - 1) and len(candidates) < target and budget_available(store):
        page_url, base_url = pagination_queue.popleft()
        marker = page_url.rstrip("/")
        if marker in visited or marker == cat["url"].rstrip("/"):
            continue
        visited.add(marker)
        before_requests = REQUESTS_BY_STORE.get(store, 0)
        before_candidates = len(candidates)
        page_response, _, page_access = adaptive_fetch(
            page_url, config, 7, store=store, method="category_page"
        )
        if page_response and page_response.status_code < 400:
            pages_fetched += 1
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
'''
tracker = regex_once(tracker, r'def _empty_store_stats\(\) -> dict:.*?# ---------------------------------------------------------------------------\n# Seleção e cache de especificações\n# ---------------------------------------------------------------------------\n', new_scan, "scan_store V8.6")

new_matching = r'''def _normal_id(value: object) -> str:
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


def match_configurations(left_item: dict, left_spec: dict, right_item: dict, right_spec: dict) -> dict:
    """Compara variantes entre lojas. Só EXATO/FORTE podem ser fundidos automaticamente."""
    left_brand, right_brand = left_spec.get("marca"), right_spec.get("marca")
    if left_brand and right_brand and left_brand != right_brand:
        return {"level": "SEM_MATCH", "reason": "marca diferente"}

    left_ean, right_ean = _normal_id(left_item.get("ean")), _normal_id(right_item.get("ean"))
    if left_ean and right_ean:
        if left_ean == right_ean:
            return {"level": "EXATO", "reason": "EAN/GTIN idêntico", "identifier": left_ean}
        return {"level": "NAO_FUNDIR", "reason": "EAN/GTIN diferente"}

    left_mpn, right_mpn = _normal_id(left_item.get("mpn")), _normal_id(right_item.get("mpn"))
    if left_mpn and right_mpn:
        if left_mpn == right_mpn:
            return {"level": "EXATO", "reason": "MPN/part number idêntico", "identifier": left_mpn}
        return {"level": "NAO_FUNDIR", "reason": "MPN/part number diferente"}

    critical = ("cpu_modelo", "gpu_modelo", "ram_gb", "armazenamento_tb", "ecra_res", "ecra_hz")
    known_equal = 0
    for field in critical:
        left_value, right_value = left_spec.get(field), right_spec.get(field)
        if left_value is not None and right_value is not None:
            if not _spec_equal(left_value, right_value):
                return {"level": "NAO_FUNDIR", "reason": f"configuração difere em {field}"}
            known_equal += 1

    left_codes = _model_codes(left_item.get("titulo", ""))
    right_codes = _model_codes(right_item.get("titulo", ""))
    shared_codes = left_codes & right_codes
    same_sku = bool(_normal_id(left_item.get("sku")) and _normal_id(left_item.get("sku")) == _normal_id(right_item.get("sku")))

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
    if known_equal >= 5 and left_brand and right_brand:
        return {"level": "PROVAVEL", "reason": "assinatura técnica muito próxima sem ID forte"}
    return {"level": "SEM_MATCH", "reason": "evidência insuficiente"}


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
                "configuration_key": configuration_signature(members[0]["item"], members[0]["spec"]),
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


def select_with_cache'''
tracker = regex_once(tracker, r'def configuration_signature\(item: dict, spec: dict\) -> str:.*?\n\n\ndef select_with_cache', new_matching, "matching cross-store")

tracker = replace_once(
    tracker,
    '        if url and isinstance(specs, dict) and entry.get("tracker_version") == VERSION:\n            out[url] = specs\n    return out',
    '        if url and isinstance(specs, dict) and entry.get("tracker_version") in COMPATIBLE_STATE_VERSIONS:\n            out[url] = specs\n    return out\n\n\ndef latest_offer_by_url(history: dict) -> dict[str, dict]:\n    out = {}\n    for entries in (history.get("offers", {}) or {}).values():\n        if not isinstance(entries, list) or not entries:\n            continue\n        entry = entries[-1]\n        if isinstance(entry, dict) and entry.get("url") and entry.get("tracker_version") in COMPATIBLE_STATE_VERSIONS:\n            out[entry["url"]] = entry\n    return out',
    "cache compat + offer metadata",
)

new_heartbeat = r'''def send_heartbeat(run: dict) -> bool:
    stores_ok = sum(1 for stats in run["stores"].values() if not stats.get("bloqueada"))
    blocked = len(run["stores"]) - stores_ok
    matching = run.get("matching", {})
    message = (
        f"V{VERSION} operacional\n"
        f"Lojas acessíveis: {stores_ok}/{len(run['stores'])} | bloqueadas: {blocked}\n"
        f"Descobertos: {run['total_candidates']} | avaliados: {run['total_evaluated']} | aceites: {run['total_accepted']}\n"
        f"Detalhes live: {run['detail_fetches']} | cache: {run['cache_reused']}\n"
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


'''
tracker = regex_once(tracker, r'def send_heartbeat\(run: dict\) -> bool:.*?# ---------------------------------------------------------------------------\n# Histórico e alertas', new_heartbeat + '# ---------------------------------------------------------------------------\n# Histórico e alertas', "heartbeat 8.6")

tracker = replace_once(
    tracker,
    '            if not url or entry.get("tracker_version") != VERSION:\n                continue',
    '            if not url or entry.get("tracker_version") not in COMPATIBLE_STATE_VERSIONS:\n                continue',
    "compact compatible entries",
)
tracker = replace_once(
    tracker,
    '        if isinstance(run, dict) and run.get("runner_version") == VERSION',
    '        if isinstance(run, dict) and run.get("runner_version") in COMPATIBLE_STATE_VERSIONS',
    "compact compatible runs",
)
tracker = replace_once(tracker, '"""Remove legado pré-V8.5 sem perder cache recente, alertas e runs úteis."""', '"""Mantém estado compatível V8.5+ sem perder cache recente, alertas e runs úteis."""', "compact doc")

tracker = replace_once(
    tracker,
    '    spec_cache = latest_specs_by_url(history)\n    all_items: list[dict] = []',
    '    spec_cache = latest_specs_by_url(history)\n    offer_cache = latest_offer_by_url(history)\n    all_items: list[dict] = []',
    "offer cache main",
)
tracker = replace_once(
    tracker,
    '            cached_item["specs"] = cached\n            cached_item["detail_source"] = "history_cache"',
    '            cached_item["specs"] = cached\n            cached_item["detail_source"] = "history_cache"\n            previous_meta = offer_cache.get(item["url"], {})\n            for field in ("ean", "mpn", "sku"):\n                if previous_meta.get(field) and not cached_item.get(field):\n                    cached_item[field] = previous_meta[field]',
    "restore ids from cache",
)
tracker = replace_once(
    tracker,
    '    current_ranked = []\n\n    for item in evaluated:',
    '    current_ranked = []\n    match_records = []\n\n    for item in evaluated:',
    "matching records init",
)
tracker = replace_once(
    tracker,
    '        current_ranked.append((assessment["value_score"], item, tier, assessment))\n\n    runtime = round(time.monotonic() - RUN_STARTED, 2)',
    '        current_ranked.append((assessment["value_score"], item, tier, assessment))\n        match_records.append({"item": item, "spec": spec, "assessment": assessment, "tier": tier})\n\n    matching = build_cross_store_matches(match_records)\n    runtime = round(time.monotonic() - RUN_STARTED, 2)',
    "build matching",
)
tracker = replace_once(
    '        "runtime_seconds": runtime,\n        "tiers": tiers,',
    '        "runtime_seconds": runtime,\n        "tiers": tiers,\n        "matching": matching,',
    "run matching field",
)
tracker = replace_once(
    '        "V8.5 | Lojas=%d | Descobertos=%d | Avaliados=%d | Aceites=%d | Pedidos=%d | "',
    '        "V8.6 | Lojas=%d | Descobertos=%d | Avaliados=%d | Aceites=%d | Pedidos=%d | "',
    "main log version",
)
tracker = replace_once(
    '    for value, item, tier, assessment in sorted(current_ranked, reverse=True, key=lambda row: row[0])[:8]:',
    '    LOGGER.info(\n        "Matching | grupos=%d | exatos=%d | fortes=%d | prováveis=%d | conflitos=%d",\n        len(matching["groups"]), matching["exact_pairs"], matching["strong_pairs"],\n        matching["probable_pairs"], matching["conflicting_pairs"],\n    )\n    for group in matching["groups"][:5]:\n        LOGGER.info(\n            "MATCH | %s | melhor=%s %.2f€ | lojas=%s | spread=%.2f€",\n            group["configuration_key"], group["best_store"], group["best_price"],\n            ",".join(group["stores"]), group["spread_eur"],\n        )\n    for value, item, tier, assessment in sorted(current_ranked, reverse=True, key=lambda row: row[0])[:8]:',
    "matching logs",
)
tracker_path.write_text(tracker, encoding="utf-8")

# Config: rotas públicas confirmadas e paginação observada.
config_path = ROOT / "config" / "config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
settings = config["settings"]
settings["max_segment_routes"] = 4
for cat in config["category_urls"]:
    store = cat["loja"]
    if store == "PCDiga":
        cat["extra_discovery_urls"] = [
            {"label": "lenovo_brand", "url": "https://www.pcdiga.com/portateis-lenovo"}
        ]
    elif store == "PcComponentes":
        cat["url"] = "https://www.pccomponentes.pt/categorias/computadores-portateis"
        cat["sitemap_enabled"] = False
        cat["extra_discovery_urls"] = [
            {"label": "legacy_category", "url": "https://www.pccomponentes.pt/categorias/portateis"},
            {"label": "asus_brand", "url": "https://www.pccomponentes.pt/marcas/asus/portateis"},
            {"label": "lenovo_brand", "url": "https://www.pccomponentes.pt/marcas/lenovo/portateis"},
            {"label": "hp_brand", "url": "https://www.pccomponentes.pt/marcas/hp/portateis"},
        ]
        for hint in ("/asus-", "/lenovo-", "/hp-"):
            if hint not in cat["product_path_hints"]:
                cat["product_path_hints"].append(hint)
    elif store == "Radio Popular":
        cat["extra_discovery_urls"] = [
            {"label": "tradicionais", "url": "https://www.radiopopular.pt/categoria/portateis-tradicionais-1"},
            {"label": "gaming", "url": "https://www.radiopopular.pt/categoria/portateis-gaming-3"},
            {"label": "hibridos", "url": "https://www.radiopopular.pt/categoria/portateis-hibridos"},
        ]
    elif store == "CHIP7":
        cat["max_category_pages"] = 4
        cat["pagination_start"] = 2
        cat["pagination_template"] = "https://chip7.pt/computadores/portateis?category.hierarchicalMenu%5Bcategories.lvl0%5D%5B0%5D=Computadores&category.hierarchicalMenu%5Bcategories.lvl0%5D%5B1%5D=Port%C3%A1teis&category.page={page}"
    elif store == "Worten":
        cat["sitemap_probe_limit"] = 3
        cat["max_sitemaps"] = 4
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Testes: compatibilidade 8.5->8.6 e novas regressões.
test_path = ROOT / "tests" / "test_tracker.py"
tests = test_path.read_text(encoding="utf-8")
tests = tests.replace('tracker_version": "8.5"', 'tracker_version": "8.6"')
tests = tests.replace('runner_version": "8.5"', 'runner_version": "8.6"')
tests = tests.replace("test_cache_only_reuses_v85_entries", "test_cache_reuses_compatible_v86_entries")
tests = tests.replace("test_compact_history_keeps_only_current_v85", "test_compact_history_keeps_compatible_v86")
old_sig_test = '''    def test_configuration_signature_prefers_sku(self):\n        left = {"titulo": "ASUS TUF Gaming A16 RTX 5050", "sku": "FA608-ABC"}\n        right = {"titulo": "TUF A16 promoção", "sku": "FA608-ABC"}\n        self.assertEqual(\n            tracker.configuration_signature(left, {}),\n            tracker.configuration_signature(right, {}),\n        )\n'''
new_sig_test = '''    def test_configuration_signature_prefers_strongest_identifier(self):\n        left = {"titulo": "ASUS TUF Gaming A16", "sku": "STORE-1", "mpn": "90NR0KS1-M00730", "ean": "4711636176743"}\n        right = {"titulo": "TUF A16 promoção", "sku": "STORE-2", "mpn": "90NR0KS1-M00730", "ean": "4711636176743"}\n        self.assertEqual(\n            tracker.configuration_signature(left, {}),\n            tracker.configuration_signature(right, {}),\n        )\n        self.assertTrue(tracker.configuration_signature(left, {}).startswith("ean:"))\n'''
tests = replace_once(tests, old_sig_test, new_sig_test, "test strong id hierarchy")
extra_tests = r'''
    def test_discovery_yield_orders_productive_routes_first(self):
        tracker.record_discovery_yield("YIELD", "segment:good", 2, 12)
        tracker.record_discovery_yield("YIELD", "segment:bad", 2, 0)
        routes = tracker.discovery_routes(
            {"extra_discovery_urls": [
                {"label": "bad", "url": "https://x/bad"},
                {"label": "good", "url": "https://x/good"},
            ]},
            "YIELD",
        )
        self.assertEqual(routes[0]["label"], "good")
        self.assertGreater(tracker.discovery_score("YIELD", "segment:good"), tracker.discovery_score("YIELD", "segment:bad"))

    def test_blocked_primary_can_use_public_fallback_route(self):
        blocked = type("Resp", (), {"status_code": 403, "text": "", "headers": {}})()
        html = '''<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"ASUS TUF Gaming A16 RTX 5060 32GB 1TB","url":"https://example.com/asus-tuf-a16","offers":{"@type":"Offer","price":"1199.00","availability":"https://schema.org/InStock"}}</script>'''
        ok = type("Resp", (), {"status_code": 200, "text": html, "headers": {"Content-Type": "text/html"}})()

        def fake_fetch(url, *_args, **_kwargs):
            if url.endswith("/primary"):
                return blocked, "chrome131", "http_403"
            return ok, "firefox147", "http_success"

        cat = {
            "loja": "TEST",
            "url": "https://example.com/primary",
            "target_candidates": 10,
            "sitemap_enabled": False,
            "product_path_hints": ["/asus-"],
            "extra_discovery_urls": [{"label": "asus", "url": "https://example.com/asus"}],
        }
        with patch.object(tracker, "adaptive_fetch", side_effect=fake_fetch):
            items, stat = tracker.scan_store(cat, {"category_urls": [cat]}, {"max_category_pages": 1})
        self.assertEqual(len(items), 1)
        self.assertFalse(stat["bloqueada"])

    def test_page_identifiers_validate_ean_and_part_number(self):
        soup = BeautifulSoup("<div>Part-Number: 83JE01KTPG Código EAN: 199276826244</div>", "html.parser")
        ids = tracker.page_identifiers(soup)
        self.assertEqual(ids["mpn"], "83JE01KTPG")
        self.assertEqual(ids["ean"], "199276826244")

    def test_matching_exact_by_ean(self):
        left_item = {"loja": "A", "titulo": "ASUS TUF A16", "ean": "4711636176743"}
        right_item = {"loja": "B", "titulo": "ASUS TUF A16 outra descrição", "ean": "4711636176743"}
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050 165Hz")
        self.assertEqual(tracker.match_configurations(left_item, spec, right_item, spec)["level"], "EXATO")

    def test_matching_never_merges_same_family_with_different_gpu_or_ssd(self):
        left_item = {"loja": "A", "titulo": "ASUS TUF Gaming A16 FA608UH-R72B55CS2"}
        right_item = {"loja": "B", "titulo": "ASUS TUF Gaming A16 FA608UH-R72B55CS2"}
        left_spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 512GB RTX 5050")
        right_spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5070")
        result = tracker.match_configurations(left_item, left_spec, right_item, right_spec)
        self.assertEqual(result["level"], "NAO_FUNDIR")

    def test_matching_strong_requires_model_code_and_core_configuration(self):
        left_item = {"loja": "A", "titulo": "ASUS TUF Gaming A16 FA608UH-R72B55CS2"}
        right_item = {"loja": "B", "titulo": "Portátil ASUS FA608UH-R72B55CS2 promoção"}
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        result = tracker.match_configurations(left_item, spec, right_item, spec)
        self.assertEqual(result["level"], "FORTE")

    def test_cross_store_groups_choose_cheapest_exact_offer(self):
        spec = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5050")
        records = [
            {"item": {"loja": "A", "url": "https://a/1", "titulo": "ASUS TUF A16", "preco": 1299, "ean": "4711636176743"}, "spec": spec, "assessment": {"value_score": 115}, "tier": "OURO"},
            {"item": {"loja": "B", "url": "https://b/1", "titulo": "ASUS TUF A16", "preco": 1199, "ean": "4711636176743"}, "spec": spec, "assessment": {"value_score": 118}, "tier": "OURO"},
        ]
        summary = tracker.build_cross_store_matches(records)
        self.assertEqual(summary["exact_pairs"], 1)
        self.assertEqual(len(summary["groups"]), 1)
        self.assertEqual(summary["groups"][0]["best_store"], "B")
        self.assertEqual(summary["groups"][0]["spread_eur"], 100.0)
'''
tests = replace_once(tests, '\n\nif __name__ == "__main__":', extra_tests + '\n\nif __name__ == "__main__":', "novos testes V8.6")
test_path.write_text(tests, encoding="utf-8")

# README e workflow.
readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8").replace("V8.5", "V8.6")
readme = readme.replace(
    "A V8.6 guarda esta assinatura como metadata, mas ainda não funde automaticamente ofertas entre lojas. Uma futura comparação cross-store só será ativada quando a identidade for suficientemente forte para evitar misturar variantes próximas.",
    "A V8.6 executa matching cross-store conservador em quatro níveis: **EXATO** (EAN/MPN), **FORTE** (model code + CPU/GPU/RAM/SSD), **PROVÁVEL** (apenas para revisão) e **NÃO FUNDIR** quando existe conflito técnico. Só EXATO/FORTE formam grupos automáticos de ofertas e nunca alteram o histórico individual de cada loja.",
)
readme = readme.replace(
    "A aprendizagem de acesso é persistida em `data/access_learning.json` e não é apagada quando o histórico de preços é compactado.",
    "A aprendizagem de acesso é persistida em `data/access_learning.json` e não é apagada quando o histórico de preços é compactado. A V8.6 aprende também o **rendimento de descoberta** (novos candidatos por request) por método/segmento e usa esse histórico para ordenar rotas alternativas mais produtivas.",
)
readme_path.write_text(readme, encoding="utf-8")

workflow_path = ROOT / ".github" / "workflows" / "tracker.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("V8.5", "V8.6").replace("v85", "v86")
workflow_path.write_text(workflow, encoding="utf-8")

# A migração é one-shot: remove-se a si própria e o workflow temporário antes do commit.
for rel in ("data/maintenance_v86.py", ".github/workflows/maintenance_v86.yml"):
    path = ROOT / rel
    if path.exists():
        path.unlink()

print("V8.6 preparada: descoberta por yield, fallbacks públicos, matching cross-store e IDs fortes.")
