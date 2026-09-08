from __future__ import annotations

from collections import defaultdict
from statistics import median


VERSION = "8.8.2"


def _normal_id(value: object) -> str:
    return "".join(char.lower() for char in str(value or "") if char.isalnum())


def _exact_key(item: dict) -> str | None:
    ean = _normal_id(item.get("ean"))
    if ean:
        return f"ean:{ean}"
    mpn = _normal_id(item.get("mpn"))
    if mpn:
        return f"mpn:{mpn}"
    return None


def mark_unresolved_market_disagreements(records: list[dict], settings: dict) -> dict:
    """Marca conflitos extremos entre lojas para o mesmo EAN/MPN.

    Esta camada só atua quando ainda não existe um cluster de pelo menos duas
    lojas concordantes produzido pelo market evidence normal. Com duas lojas a
    mostrar preços radicalmente diferentes não tentamos adivinhar qual está
    certa: ambas ficam em quarentena até surgir confirmação adicional.
    """
    fields = (
        "market_price_disagreement",
        "market_disagreement_identifier",
        "market_disagreement_prices",
        "market_disagreement_stores",
        "market_disagreement_spread_eur",
        "market_disagreement_spread_pct",
    )
    for record in records:
        spec = record.get("spec") or {}
        for field in fields:
            spec.pop(field, None)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        item = record.get("item") or {}
        key = _exact_key(item)
        if key and item.get("preco") is not None:
            grouped[key].append(record)

    min_eur = float(settings.get("market_disagreement_min_eur", 150.0))
    min_pct = float(settings.get("market_disagreement_min_pct", 20.0))
    disagreements = 0
    offers_marked = 0

    for key, members in grouped.items():
        stores = {str(member.get("item", {}).get("loja") or "") for member in members}
        stores.discard("")
        if len(stores) < 2:
            continue

        # Se o tracker já encontrou duas lojas concordantes, o conflito fica
        # resolvido pelo market_price_confirmed e o outlier é tratado pelo
        # price_guard existente.
        if any(
            str((member.get("spec") or {}).get("market_price_confidence") or "").upper() == "HIGH"
            for member in members
        ):
            continue

        by_store: dict[str, list[float]] = defaultdict(list)
        for member in members:
            item = member.get("item") or {}
            store = str(item.get("loja") or "")
            if store and item.get("preco") is not None:
                by_store[store].append(float(item["preco"]))
        representative = {
            store: float(median(values)) for store, values in by_store.items() if values
        }
        if len(representative) < 2:
            continue

        prices = list(representative.values())
        low, high = min(prices), max(prices)
        spread = high - low
        pct = spread / max(1.0, low) * 100.0
        if spread < min_eur or pct < min_pct:
            continue

        disagreements += 1
        stores_sorted = sorted(representative)
        prices_by_store = {
            store: round(representative[store], 2) for store in stores_sorted
        }
        for member in members:
            spec = member.get("spec") or {}
            spec["market_price_disagreement"] = True
            spec["market_disagreement_identifier"] = key
            spec["market_disagreement_prices"] = prices_by_store
            spec["market_disagreement_stores"] = stores_sorted
            spec["market_disagreement_spread_eur"] = round(spread, 2)
            spec["market_disagreement_spread_pct"] = round(pct, 2)
            offers_marked += 1

    return {"groups": disagreements, "offers": offers_marked}


def install(scraper_module, tracker_module) -> None:
    """Instala o guard sem alterar o cérebro técnico nem o matching base."""
    if getattr(tracker_module, "_MARKET_GUARD_INSTALLED", False):
        return

    original_market_evidence = tracker_module.apply_exact_market_price_evidence
    original_score_allow_unknown = tracker_module.score_allow_unknown

    def apply_market_evidence(records: list[dict], settings: dict) -> dict:
        summary = original_market_evidence(records, settings)
        unresolved = mark_unresolved_market_disagreements(records, settings)
        summary["disagreements"] = unresolved["groups"]
        summary["disagreement_offers"] = unresolved["offers"]
        if unresolved["groups"]:
            tracker_module.LOGGER.warning(
                "Desacordo de mercado | grupos=%d | ofertas_quarentena=%d",
                unresolved["groups"],
                unresolved["offers"],
            )
        return summary

    def score_allow_unknown(spec: dict, price: float, weights: dict, settings: dict) -> dict:
        if spec.get("market_price_disagreement"):
            prices = spec.get("market_disagreement_prices") or {}
            detail = ", ".join(
                f"{store} {float(value):.2f}€" for store, value in sorted(prices.items())
            )
            return {
                "status": "QUARENTENA",
                "price_status": "MARKET_DISAGREEMENT",
                "price_confidence": "LOW",
                "price_suspicious": True,
                "alertas": [
                    "Lojas com o mesmo EAN/MPN apresentam preços incompatíveis"
                    + (f": {detail}." if detail else ".")
                    + " É necessária confirmação adicional antes de pontuar ou alertar."
                ],
            }
        return original_score_allow_unknown(spec, price, weights, settings)

    tracker_module.apply_exact_market_price_evidence = apply_market_evidence
    tracker_module.score_allow_unknown = score_allow_unknown
    tracker_module._MARKET_GUARD_INSTALLED = True
    tracker_module._MARKET_GUARD_ORIGINALS = {
        "apply_exact_market_price_evidence": original_market_evidence,
        "score_allow_unknown": original_score_allow_unknown,
    }


def uninstall(tracker_module) -> None:
    originals = getattr(tracker_module, "_MARKET_GUARD_ORIGINALS", None)
    if originals:
        tracker_module.apply_exact_market_price_evidence = originals[
            "apply_exact_market_price_evidence"
        ]
        tracker_module.score_allow_unknown = originals["score_allow_unknown"]
    tracker_module._MARKET_GUARD_INSTALLED = False
    if hasattr(tracker_module, "_MARKET_GUARD_ORIGINALS"):
        delattr(tracker_module, "_MARKET_GUARD_ORIGINALS")
