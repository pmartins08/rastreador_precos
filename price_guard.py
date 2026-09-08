from __future__ import annotations

import json
from collections import defaultdict
from statistics import median
from typing import Any
from datetime import datetime, timezone


VERSION = "8.8.1"

# Estes valores NÃO são mínimos de compra. São apenas limiares de suspeita:
# abaixo deles, um negócio extraordinário precisa de confirmação forte antes
# de poder entrar no ranking/NTFY.
GPU_PRICE_SUSPICION_MIN = {
    "rtx 5090": 1500.0,
    "rtx 5080": 1000.0,
    "rtx 5070 ti": 800.0,
    "rtx 5070": 650.0,
    "rtx 5060 ti": 550.0,
    "rtx 5060": 450.0,
    "rtx 5050": 400.0,
    "rtx 4090": 1200.0,
    "rtx 4080": 900.0,
    "rtx 4070": 600.0,
    "rtx 4060": 450.0,
}

BAD_PRICE_CONTEXT = (
    "discount",
    "desconto",
    "saving",
    "poupanca",
    "poupa",
    "cashback",
    "voucher",
    "cupao",
    "coupon",
    "mensal",
    "prestacao",
    "installment",
    "financiamento",
    "finance",
    "month",
    "/ mes",
    "/mes",
    "por mes",
    "old-price",
    "oldprice",
    "preco antigo",
)

META_PRICE_SELECTORS = (
    "meta[itemprop='price'][content]",
    "meta[property='product:price:amount'][content]",
    "meta[property='og:price:amount'][content]",
)

VISIBLE_PRICE_SELECTORS = (
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
)


def _price_values(raw: object, scraper_module) -> list[float]:
    if raw is None:
        return []
    direct = scraper_module.parse_price_value(raw)
    if direct is not None and 200.0 <= float(direct) <= 10000.0:
        return [float(direct)]
    return [
        float(value)
        for value in scraper_module.prices(str(raw))
        if 200.0 <= float(value) <= 10000.0
    ]


def _close(left: float, right: float, settings: dict | None = None) -> bool:
    settings = settings or {}
    abs_tol = float(settings.get("price_confirmation_tolerance_eur", 5.0))
    pct_tol = float(settings.get("price_confirmation_tolerance_pct", 1.5)) / 100.0
    return abs(float(left) - float(right)) <= max(abs_tol, max(float(left), float(right)) * pct_tol)


def _jsonld_price_signals(soup, scraper_module) -> list[float]:
    values: list[float] = []

    def walk(node: Any, relevant: bool = False) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child, relevant)
            return
        if not isinstance(node, dict):
            return

        raw_type = node.get("@type")
        types = {str(value).lower() for value in raw_type} if isinstance(raw_type, list) else {str(raw_type or "").lower()}
        local_relevant = relevant or bool(types & {"product", "offer", "aggregateoffer"}) or "offers" in node

        if local_relevant:
            # 'highPrice' não é usado: em AggregateOffer pode representar a oferta
            # mais cara e não o preço atual do produto.
            for key in ("price", "lowPrice"):
                if key in node:
                    values.extend(_price_values(node.get(key), scraper_module))

        for key, child in node.items():
            if key == "@context":
                continue
            if isinstance(child, (dict, list)):
                walk(child, local_relevant or key == "offers")

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            walk(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return values


def _node_context(node, scraper_module) -> str:
    chunks = [
        " ".join(node.get("class", [])),
        str(node.get("id") or ""),
        node.get_text(" ", strip=True),
    ]
    parent = getattr(node, "parent", None)
    if parent is not None and getattr(parent, "attrs", None) is not None:
        chunks.extend(
            [
                " ".join(parent.get("class", [])),
                str(parent.get("id") or ""),
            ]
        )
    return scraper_module.norm(" ".join(chunks))


def page_price_evidence(soup, scraper_module, settings: dict | None = None) -> dict:
    """Extrai sinais de preço independentes da ficha e mede concordância.

    Famílias independentes: JSON-LD, meta de produto e preço visível/final.
    Um preço suspeito só é considerado confirmado quando pelo menos duas
    famílias concordam.
    """
    settings = settings or {}
    signals: dict[str, list[float]] = defaultdict(list)

    signals["jsonld"].extend(_jsonld_price_signals(soup, scraper_module))

    for selector in META_PRICE_SELECTORS:
        for node in soup.select(selector):
            raw = node.get("content") or node.get("value") or node.get_text(" ", strip=True)
            signals["meta"].extend(_price_values(raw, scraper_module))

    seen_nodes: set[int] = set()
    for selector in VISIBLE_PRICE_SELECTORS:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen_nodes or getattr(node, "name", "") == "meta":
                continue
            seen_nodes.add(marker)
            context = _node_context(node, scraper_module)
            if any(token in context for token in BAD_PRICE_CONTEXT):
                continue
            raw = (
                node.get("content")
                or node.get("data-price-amount")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            signals["visible"].extend(_price_values(raw, scraper_module))

    clean: dict[str, list[float]] = {}
    for source, values in signals.items():
        unique = sorted({round(float(value), 2) for value in values if 200 <= float(value) <= 10000})
        if unique:
            clean[source] = unique

    flattened = sorted({value for values in clean.values() for value in values})
    if not flattened:
        return {
            "price": None,
            "confidence": "UNKNOWN",
            "sources": [],
            "source_count": 0,
            "signals": {},
            "conflicts": [],
        }

    candidates = []
    for value in flattened:
        matching_sources = {
            source
            for source, source_values in clean.items()
            if any(_close(value, source_value, settings) for source_value in source_values)
        }
        structured = int("jsonld" in matching_sources) + int("meta" in matching_sources)
        # Em igualdade, JSON-LD/meta ganham ao texto visual. Dentro da mesma
        # família preferimos o valor mais baixo porque pode ser uma promoção.
        rank = (
            len(matching_sources),
            structured,
            int("jsonld" in matching_sources),
            int("meta" in matching_sources),
            -value,
        )
        candidates.append((rank, value, matching_sources))

    _, chosen, chosen_sources = max(candidates, key=lambda row: row[0])
    cluster_values = [
        value
        for values in clean.values()
        for value in values
        if _close(chosen, value, settings)
    ]
    confirmed = round(float(median(cluster_values)), 2) if cluster_values else round(float(chosen), 2)
    source_count = len(chosen_sources)
    confidence = "HIGH" if source_count >= 2 else "MEDIUM"
    conflicts = [value for value in flattened if not _close(confirmed, value, settings)]

    return {
        "price": confirmed,
        "confidence": confidence,
        "sources": sorted(chosen_sources),
        "source_count": source_count,
        "signals": clean,
        "conflicts": conflicts,
    }


def exceptional_deal_bonus(price: float, confidence: str, settings: dict | None = None) -> float:
    """Bónus de oportunidade abaixo de €1300, apenas com preço HIGH.

    Âncoras padrão:
      €1300 -> +0
      €1100 -> +4
      €900  -> +8
      €700  -> +11
      €500  -> +15
    """
    settings = settings or {}
    if str(confidence or "").upper() != "HIGH":
        return 0.0

    soft = float(settings.get("budget_soft", 1300.0))
    max_bonus = float(settings.get("exceptional_deal_bonus_max", 15.0))
    if float(price) >= soft:
        return 0.0

    # Mantemos as proporções das âncoras mesmo que budget_soft seja alterado.
    anchors = [
        (soft, 0.0),
        (soft - 200.0, max_bonus * 4.0 / 15.0),
        (soft - 400.0, max_bonus * 8.0 / 15.0),
        (soft - 600.0, max_bonus * 11.0 / 15.0),
        (soft - 800.0, max_bonus),
    ]
    value = float(price)
    if value <= anchors[-1][0]:
        return round(max_bonus, 1)

    for (high_price, high_bonus), (low_price, low_bonus) in zip(anchors, anchors[1:]):
        if low_price <= value <= high_price:
            fraction = (high_price - value) / max(1.0, high_price - low_price)
            return round(high_bonus + (low_bonus - high_bonus) * fraction, 1)
    return 0.0


def _suspicion_reason(spec: dict, price: float) -> str | None:
    value = float(price)
    gpu = spec.get("gpu_modelo")
    floor = GPU_PRICE_SUSPICION_MIN.get(gpu)
    if floor is not None and value < floor:
        return f"{gpu.upper()} a {value:.2f}€ está muito abaixo do intervalo esperado"

    if spec.get("gpu_tipo") == "dedicada" and value < 300.0:
        return f"GPU dedicada a {value:.2f}€ exige confirmação reforçada"

    cpu_model = str(spec.get("cpu_modelo") or "").lower()
    cpu_top = any(token in cpu_model for token in ("i9-", "core i9", "core 9", "ultra 9", "ryzen 9", "r9 "))
    if (
        cpu_top
        and (spec.get("ram_gb") or 0) >= 32
        and (spec.get("armazenamento_tb") or 0) >= 2
        and value < 700.0
    ):
        return f"configuração topo (CPU/32GB+/2TB+) a {value:.2f}€ exige confirmação reforçada"
    return None


def validate_price(spec: dict, price: float, settings: dict | None = None) -> dict:
    settings = settings or {}
    candidate = float(price)
    confirmed = spec.get("price_confirmed")
    page_confidence = str(spec.get("price_page_confidence") or "UNKNOWN").upper()
    sources = list(spec.get("price_evidence_sources") or [])
    market_confirmed = spec.get("market_price_confirmed")
    market_confidence = str(spec.get("market_price_confidence") or "UNKNOWN").upper()
    market_sources = list(spec.get("market_price_sources") or [])
    reason = _suspicion_reason(spec, candidate)

    if confirmed is not None:
        confirmed = float(confirmed)
        if not _close(candidate, confirmed, settings):
            return {
                "status": "PRICE_CONFLICT",
                "confidence": "LOW",
                "suspicious": bool(reason),
                "reason": (
                    f"Preço candidato {candidate:.2f}€ diverge da ficha ({confirmed:.2f}€; "
                    f"fontes: {', '.join(sources) or 'desconhecidas'})."
                ),
            }

    market_high = market_confirmed is not None and market_confidence == "HIGH"
    if market_high and not _close(candidate, float(market_confirmed), settings):
        return {
            "status": "PRICE_CONFLICT",
            "confidence": "LOW",
            "suspicious": bool(reason),
            "reason": (
                f"Preço candidato {candidate:.2f}€ diverge do mercado exato por EAN/MPN "
                f"({float(market_confirmed):.2f}€; lojas: {', '.join(market_sources) or 'desconhecidas'})."
            ),
        }

    if reason:
        page_high = confirmed is not None and page_confidence == "HIGH" and _close(candidate, confirmed, settings)
        market_matches = market_high and _close(candidate, float(market_confirmed), settings)
        if not page_high and not market_matches:
            return {
                "status": "PRICE_UNCONFIRMED",
                "confidence": "LOW",
                "suspicious": True,
                "reason": reason + "; falta confirmação forte na ficha ou por EAN/MPN cross-store.",
            }
        confirmation = "ficha" if page_high else "mercado cross-store por EAN/MPN"
        return {
            "status": "OK",
            "confidence": "HIGH",
            "suspicious": True,
            "reason": reason + f"; preço confirmado por {confirmation}.",
        }

    confidence = (
        "HIGH"
        if (confirmed is not None and page_confidence == "HIGH") or market_high
        else "MEDIUM"
        if confirmed is not None and page_confidence == "MEDIUM"
        else "UNKNOWN"
    )
    return {
        "status": "OK",
        "confidence": confidence,
        "suspicious": False,
        "reason": None,
    }


def install(scraper_module) -> None:
    """Instala a camada V8.8 por cima do cérebro V8 sem reescrever os pesos."""
    if getattr(scraper_module, "_PRICE_GUARD_INSTALLED", False):
        return

    originals = {
        "extract": scraper_module.extract,
        "score": scraper_module.score,
        "value_score": scraper_module.value_score,
        "price_is_plausible_for_title": scraper_module.price_is_plausible_for_title,
    }
    scraper_module._PRICE_GUARD_ORIGINALS = originals

    def price_is_plausible_for_title(_title: str, price: float) -> bool:
        # V8.8 deixa de matar oportunidades raras por um floor rígido. O filtro
        # sério acontece em validate_price(), usando evidência da ficha.
        try:
            return 200.0 <= float(price) <= 10000.0
        except (TypeError, ValueError):
            return False

    def price_is_suspicious_for_title(title: str, price: float) -> bool:
        _models, kind, model = scraper_module.gpus(title)
        pseudo = {"gpu_tipo": kind, "gpu_modelo": model}
        return _suspicion_reason(pseudo, float(price)) is not None

    def extract(title: str, soup) -> dict:
        result = originals["extract"](title, soup)
        evidence = page_price_evidence(soup, scraper_module)
        result["price_confirmed"] = evidence["price"]
        result["price_page_confidence"] = evidence["confidence"]
        result["price_evidence_sources"] = evidence["sources"]
        result["price_evidence_count"] = evidence["source_count"]
        result["price_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result["price_evidence_signals"] = evidence["signals"]
        if evidence["conflicts"]:
            result.setdefault("conflitos", []).append(
                "Sinais de preço divergentes na ficha: "
                + ", ".join(f"{value:.2f}€" for value in evidence["conflicts"][:4])
            )
        return result

    def value_score(ranking: float, price_value: float, settings: dict) -> float:
        base = float(originals["value_score"](ranking, price_value, settings))
        confidence = str(settings.get("_price_confidence", "UNKNOWN")).upper()
        bonus = exceptional_deal_bonus(price_value, confidence, settings)
        return round(max(0.0, min(150.0, base + bonus)), 1)

    def score(spec: dict, price_value: float, weights: dict, settings: dict) -> dict:
        validation = validate_price(spec, price_value, settings)
        if validation["status"] != "OK":
            return {
                "status": "QUARENTENA",
                "price_status": validation["status"],
                "price_confidence": validation["confidence"],
                "price_suspicious": validation["suspicious"],
                "alertas": [validation["reason"]],
            }

        adjusted_settings = dict(settings)
        adjusted_settings["_price_confidence"] = validation["confidence"]
        result = originals["score"](spec, price_value, weights, adjusted_settings)
        if result.get("status") == "ACEITE":
            bonus = exceptional_deal_bonus(price_value, validation["confidence"], adjusted_settings)
            result["price_status"] = "OK"
            result["price_confidence"] = validation["confidence"]
            result["price_suspicious"] = validation["suspicious"]
            result["price_confirmed"] = spec.get("price_confirmed")
            result["price_evidence_sources"] = list(spec.get("price_evidence_sources") or [])
            result["market_price_confirmed"] = spec.get("market_price_confirmed")
            result["market_price_sources"] = list(spec.get("market_price_sources") or [])
            result["exceptional_deal_bonus"] = bonus
            result["value_score_sem_bonus"] = round(float(result["value_score"]) - bonus, 1)
            if validation.get("reason"):
                result.setdefault("alertas", []).append(validation["reason"])
        return result

    scraper_module.price_is_plausible_for_title = price_is_plausible_for_title
    scraper_module.price_is_suspicious_for_title = price_is_suspicious_for_title
    scraper_module.page_price_evidence = lambda soup, settings=None: page_price_evidence(
        soup, scraper_module, settings
    )
    scraper_module.validate_price = validate_price
    scraper_module.exceptional_deal_bonus = exceptional_deal_bonus
    scraper_module.extract = extract
    scraper_module.value_score = value_score
    scraper_module.score = score
    scraper_module._PRICE_GUARD_INSTALLED = True


def uninstall(scraper_module) -> None:
    originals = getattr(scraper_module, "_PRICE_GUARD_ORIGINALS", None)
    if not originals:
        return
    for name, function in originals.items():
        setattr(scraper_module, name, function)
    for name in (
        "price_is_suspicious_for_title",
        "page_price_evidence",
        "validate_price",
        "exceptional_deal_bonus",
    ):
        if hasattr(scraper_module, name):
            delattr(scraper_module, name)
    if hasattr(scraper_module, "_PRICE_GUARD_ORIGINALS"):
        delattr(scraper_module, "_PRICE_GUARD_ORIGINALS")
    scraper_module._PRICE_GUARD_INSTALLED = False
