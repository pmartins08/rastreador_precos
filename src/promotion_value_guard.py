from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup


CASH_KINDS = {"DIRECT_DISCOUNT", "TIERED_DISCOUNT", "COUPON"}
ECONOMIC_KINDS = CASH_KINDS | {"STORE_CREDIT", "CASHBACK"}
NON_CASH_KINDS = {"GIFT", "BUNDLE_DISCOUNT", "FINANCING", "REFERENCE_DISCOUNT"}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def is_active(promotion: dict, today: date | None = None) -> bool:
    current = today or date.today()
    start = _day(promotion.get("valid_from"))
    end = _day(promotion.get("valid_until"))
    return (not start or current >= start) and (not end or current <= end)


def tiered_discount(price: float, *, step_eur: float, discount_eur: float, cap_eur: float | None = None) -> float:
    """Desconto por patamares completos; nunca atribui frações de patamar."""
    price = max(0.0, float(price))
    step = max(0.01, float(step_eur))
    discount = max(0.0, float(discount_eur))
    value = math.floor((price + 1e-9) / step) * discount
    if cap_eur is not None:
        value = min(value, max(0.0, float(cap_eur)))
    return round(min(price, value), 2)


def promotion_discount(promotion: dict, price: float) -> float:
    if not is_active(promotion) or promotion.get("applicable") is False:
        return 0.0
    if str(promotion.get("eligibility") or "").lower() in {"potential", "unknown"}:
        return 0.0
    kind = str(promotion.get("kind") or "").upper()
    if kind == "TIERED_DISCOUNT":
        return tiered_discount(
            price,
            step_eur=float(promotion.get("threshold_step_eur") or 250),
            discount_eur=float(promotion.get("step_discount_eur") or 0),
            cap_eur=_number(promotion.get("cap_eur")),
        )
    if kind in {"DIRECT_DISCOUNT", "COUPON"}:
        if promotion.get("requires_membership") or promotion.get("requires_subscription"):
            if not promotion.get("qualification_confirmed"):
                return 0.0
        fixed = _number(promotion.get("value_eur")) or 0.0
        percent = _number(promotion.get("percent")) or 0.0
        return round(min(price, max(fixed, price * percent / 100.0)), 2)
    return 0.0


def store_credit_value(promotion: dict, price: float) -> float:
    if not is_active(promotion) or promotion.get("applicable") is False:
        return 0.0
    if str(promotion.get("eligibility") or "").lower() in {"potential", "unknown"}:
        return 0.0
    if str(promotion.get("kind") or "").upper() not in {"STORE_CREDIT", "CASHBACK"}:
        return 0.0
    fixed = _number(promotion.get("value_eur")) or 0.0
    percent = _number(promotion.get("percent")) or 0.0
    cap = _number(promotion.get("cap_eur"))
    value = max(fixed, price * percent / 100.0)
    if cap is not None:
        value = min(value, cap)
    return round(min(price, max(0.0, value)), 2)


def dedupe(promotions: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for raw in promotions or []:
        if not isinstance(raw, dict):
            continue
        promo = {key: value for key, value in raw.items() if value is not None}
        marker = (
            str(promo.get("kind") or "").upper(),
            str(promo.get("title") or "").strip().lower(),
            str(promo.get("code") or "").strip().upper(),
            str(promo.get("valid_until") or ""),
        )
        if marker in seen:
            continue
        seen.add(marker)
        out.append(promo)
    return out


def economics(promotions: list[dict] | None, price: float) -> dict:
    """Separa preço pago em caixa de crédito/cashback e ofertas não monetárias."""
    current = [promo for promo in dedupe(promotions) if is_active(promo)]
    checkout_discounts = [promotion_discount(promo, price) for promo in current]
    checkout_discount = max(checkout_discounts, default=0.0)
    credits = [store_credit_value(promo, price) for promo in current]
    credit = max(credits, default=0.0)
    checkout_price = round(max(0.0, float(price) - checkout_discount), 2)
    economic_price = round(max(0.0, checkout_price - credit), 2)
    gifts = [
        str(promo.get("title") or "Oferta")
        for promo in current
        if str(promo.get("kind") or "").upper() == "GIFT"
    ]
    financing = [
        str(promo.get("title") or "Financiamento")
        for promo in current
        if str(promo.get("kind") or "").upper() == "FINANCING"
    ]
    conditional = [
        str(promo.get("title") or "Promoção condicional")
        for promo in current
        if (promo.get("requires_membership") or promo.get("requires_subscription"))
        and not promo.get("qualification_confirmed")
    ]
    return {
        "checkout_discount_eur": round(checkout_discount, 2),
        "effective_checkout_price": checkout_price,
        "store_credit_eur": round(credit, 2),
        "effective_economic_price": economic_price,
        "economic_benefit_eur": round(float(price) - economic_price, 2),
        "gifts": gifts,
        "financing": financing,
        "conditional": conditional,
    }


def fingerprint(promotions: list[dict] | None, price: float | None = None) -> str:
    payload = {"promotions": dedupe(promotions)}
    if price is not None:
        payload["economics"] = economics(promotions, float(price))
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _dates_from_text(text: str) -> tuple[str | None, str | None]:
    months = {
        "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12,
    }
    match = re.search(
        r"(?:de\s+)?(\d{1,2})\s*(?:a|até|-)\s*(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(20\d{2})",
        text, re.I,
    )
    if match:
        month = months.get(match.group(3).lower())
        if month:
            year = int(match.group(4))
            return date(year, month, int(match.group(1))).isoformat(), date(year, month, int(match.group(2))).isoformat()
    match = re.search(r"(\d{1,2})[/-](\d{1,2})\s*(?:a|até|-)\s*(\d{1,2})[/-](\d{1,2})\s+de\s+(20\d{2})", text, re.I)
    if match:
        year = int(match.group(5))
        return date(year, int(match.group(2)), int(match.group(1))).isoformat(), date(year, int(match.group(4)), int(match.group(3))).isoformat()
    match = re.search(r"(?:de\s+)?(\d{2})-(\d{2})-(20\d{2}).{0,35}?(\d{2})-(\d{2})-(20\d{2})", text, re.I)
    if match:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat(), date(int(match.group(6)), int(match.group(5)), int(match.group(4))).isoformat()
    return None, None


def parse_promotion_text(text: str, *, source: str = "page", eligibility: str = "explicit") -> list[dict]:
    """Extrai benefícios claros sem descontar duas vezes preços já promocionais."""
    clean = " ".join(str(text or "").split())
    lower = clean.lower()
    if not clean:
        return []
    valid_from, valid_until = _dates_from_text(clean)
    common = {"source": source, "eligibility": eligibility, "applicable": eligibility not in {"potential", "unknown"}}
    if valid_from:
        common["valid_from"] = valid_from
    if valid_until:
        common["valid_until"] = valid_until

    out: list[dict] = []
    tiered = re.search(r"(?:ganha|poupa|desconto(?:\s+de)?)\s*(\d+(?:[.,]\d+)?)\s*€\s*(?:por|a cada)\s*(?:cada\s*)?(\d+(?:[.,]\d+)?)\s*€", lower)
    if tiered:
        cap_match = re.search(r"(?:até|max(?:imo)?\.?)[^€]{0,20}?(\d+(?:[.,]\d+)?)\s*€", lower)
        out.append({
            **common,
            "kind": "TIERED_DISCOUNT",
            "title": f"{tiered.group(1)}€ por cada {tiered.group(2)}€",
            "step_discount_eur": _number(tiered.group(1)),
            "threshold_step_eur": _number(tiered.group(2)),
            "cap_eur": _number(cap_match.group(1)) if cap_match else None,
        })

    cart = re.search(r"(?:-|menos\s*)?(\d+(?:[.,]\d+)?)\s*€\s*(?:de\s*)?(?:desconto\s*)?extra\s+(?:no\s+)?carrinho", lower)
    if cart:
        out.append({**common, "kind": "DIRECT_DISCOUNT", "title": f"{cart.group(1)}€ extra no carrinho", "value_eur": _number(cart.group(1))})

    cart_percent = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:de\s*)?(?:desconto\s*)?extra\s+(?:no\s+)?carrinho", lower)
    if cart_percent:
        out.append({**common, "kind": "DIRECT_DISCOUNT", "title": f"{cart_percent.group(1)}% extra no carrinho", "percent": _number(cart_percent.group(1))})

    percent_code = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:de\s*)?(?:desconto\s*)?extra.{0,100}?(?:c[oó]digo|cup[aã]o)\s*[:\-]?\s*([A-Z0-9_-]{3,20})", clean, re.I)
    if percent_code:
        out.append({**common, "kind": "COUPON", "title": f"{percent_code.group(1)}% extra com código {percent_code.group(2)}", "percent": _number(percent_code.group(1)), "code": percent_code.group(2).upper()})

    fixed_code = re.search(r"(\d+(?:[.,]\d+)?)\s*€\s*(?:de\s*)?(?:desconto\s*)?extra.{0,100}?(?:c[oó]digo|cup[aã]o)\s*[:\-]?\s*([A-Z0-9_-]{3,20})", clean, re.I)
    if fixed_code:
        out.append({**common, "kind": "COUPON", "title": f"{fixed_code.group(1)}€ extra com código {fixed_code.group(2)}", "value_eur": _number(fixed_code.group(1)), "code": fixed_code.group(2).upper()})

    card = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s+(?:em|no)\s+cart[aã]o\s+fnac", lower)
    if card:
        out.append({**common, "kind": "STORE_CREDIT", "title": f"{card.group(1)}% em Cartão FNAC", "percent": _number(card.group(1)), "requires_membership": True})
    accumulated = re.search(r"acumula\s+(\d+(?:[.,]\d+)?)\s*€", lower)
    if accumulated:
        out.append({**common, "kind": "STORE_CREDIT", "title": f"Acumula {accumulated.group(1)}€", "value_eur": _number(accumulated.group(1)), "requires_membership": True})

    voucher = re.search(r"-?\s*(\d+(?:[.,]\d+)?)\s*€\s+(?:em\s+)?tal[aã]o", lower)
    if voucher:
        out.append({**common, "kind": "STORE_CREDIT", "title": f"{voucher.group(1)}€ em talão", "value_eur": _number(voucher.group(1))})
    voucher_percent = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s+(?:em\s+)?tal[aã]o", lower)
    if voucher_percent:
        out.append({**common, "kind": "STORE_CREDIT", "title": f"{voucher_percent.group(1)}% em talão", "percent": _number(voucher_percent.group(1))})

    cashback_percent = re.search(r"(?:cashback|reembolso)\s*(?:de|até|ate)?\s*(\d{1,2}(?:[.,]\d+)?)\s*%", lower)
    if not cashback_percent:
        cashback_percent = re.search(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:de\s*)?(?:cashback|reembolso)", lower)
    if cashback_percent:
        out.append({**common, "kind": "CASHBACK", "title": f"{cashback_percent.group(1)}% cashback", "percent": _number(cashback_percent.group(1))})
    cashback_fixed = re.search(r"(?:cashback|reembolso)\s*(?:de|até|ate)?\s*(\d+(?:[.,]\d+)?)\s*€", lower)
    if cashback_fixed:
        out.append({**common, "kind": "CASHBACK", "title": f"{cashback_fixed.group(1)}€ cashback", "value_eur": _number(cashback_fixed.group(1))})

    reference = re.search(r"(?:pvpr|pvp\s+recomendado|pre[cç]o\s+recomendado)\s*[:\-]?\s*(\d{2,5}(?:[.,]\d{1,2})?)\s*€", lower)
    if reference:
        percent = None
        around = lower[max(0, reference.start() - 80): reference.end() + 80]
        pct_match = re.search(r"-?\s*(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:sobre\s+)?(?:o\s+)?(?:pvpr|pvp)?", around)
        if pct_match:
            percent = _number(pct_match.group(1))
        out.append({
            **common,
            "kind": "REFERENCE_DISCOUNT",
            "title": f"Referência PVPR/PVP {reference.group(1)}€",
            "reference_price_eur": _number(reference.group(1)),
            "percent": percent,
            "applicable": False,
        })

    if re.search(r"\b(?:oferta|gr[aá]tis)\b", lower):
        gift = None
        for pattern in (
            r"oferta\s*:\s*([^|;]{3,80})",
            r"oferta\s+(control\s+resonant[^|;]{0,40})",
            r"(?:oferta|gr[aá]tis).{0,20}\b(norton[^|;]{0,50})",
        ):
            match = re.search(pattern, clean, re.I)
            if match:
                gift = match.group(1).strip(" .,-")
                break
        if gift:
            out.append({**common, "kind": "GIFT", "title": f"Oferta: {gift}"})

    if re.search(r"\bsem\s+juros\b|\b0%\s*(?:taeg|juros)\b", lower):
        match = re.search(r"(?:at[eé]\s*)?(\d{1,2})x\s+sem\s+juros", lower)
        title = f"Até {match.group(1)}x sem juros" if match else "Financiamento sem juros"
        out.append({**common, "kind": "FINANCING", "title": title})

    return dedupe(out)


def _product_context(html: str, title: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    if h1:
        node = h1
        best = h1.get_text(" ", strip=True)
        for _ in range(6):
            parent = getattr(node, "parent", None)
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            if 150 <= len(text) <= 18000:
                best = text
            if "adicionar ao carrinho" in text.lower() and len(text) <= 18000:
                return text
            node = parent
        if best:
            return best
    text = " ".join(soup.stripped_strings)
    normalized_title = " ".join(str(title or "").split())
    index = text.lower().find(normalized_title.lower()) if normalized_title else -1
    if index >= 0:
        return text[max(0, index - 600): index + len(normalized_title) + 6500]
    return text[:9000]


def extract_product_promotions(html: str, *, store: str, title: str = "") -> list[dict]:
    context = _product_context(html, title)
    return parse_promotion_text(context, source="product_page", eligibility="explicit")
