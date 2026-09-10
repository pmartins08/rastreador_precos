from __future__ import annotations

import re
from urllib.parse import urlparse


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw.rstrip("/").lower()
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}".lower()


def _normal_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def install(tracker_module) -> None:
    """Garante prioridade de avaliação a ofertas históricas cujo preço mudou.

    Não altera score, Value, tier ou critérios de alerta. Apenas atua no
    pré-ranking, para uma alteração material já observada na descoberta atual
    não perder um dos slots de avaliação.
    """
    if getattr(tracker_module, "_PRICE_CHANGE_PRIORITY_GUARD_INSTALLED", False):
        return

    base_candidate_priority = tracker_module.candidate_priority
    index_holder: dict[str, object] = {}

    def indexes():
        if index_holder:
            return index_holder
        history = tracker_module.compact_history(tracker_module.load_history())
        latest = tracker_module.latest_offer_by_url(history)
        by_url = {}
        by_ean = {}
        by_mpn = {}
        for previous in latest.values():
            if not isinstance(previous, dict):
                continue
            store = str(previous.get("loja") or "")
            url = _canonical_url(previous.get("url"))
            if store and url:
                by_url[(store, url)] = previous
            ean = _normal_id(previous.get("ean"))
            if store and ean:
                by_ean[(store, ean)] = previous
            mpn = _normal_id(previous.get("mpn"))
            if store and mpn:
                by_mpn[(store, mpn)] = previous
        index_holder.update({"by_url": by_url, "by_ean": by_ean, "by_mpn": by_mpn})
        return index_holder

    def previous_for(item: dict):
        idx = indexes()
        store = str(item.get("loja") or "")
        if not store:
            return None
        url = _canonical_url(item.get("url"))
        if url:
            previous = idx["by_url"].get((store, url))
            if previous:
                return previous
        ean = _normal_id(item.get("ean"))
        if ean:
            previous = idx["by_ean"].get((store, ean))
            if previous:
                return previous
        mpn = _normal_id(item.get("mpn"))
        if mpn:
            return idx["by_mpn"].get((store, mpn))
        return None

    def candidate_priority(item, weights, settings):
        base = float(base_candidate_priority(item, weights, settings))
        previous = previous_for(item)
        if not isinstance(previous, dict):
            return base
        try:
            old_price = float(previous.get("price"))
            current_price = float(item.get("preco"))
        except (TypeError, ValueError):
            return base

        delta = old_price - current_price
        threshold = max(
            0.01,
            float(
                settings.get(
                    "historical_price_change_priority_min_eur",
                    settings.get("alerta_queda_preco_eur", 5.0),
                )
            ),
        )
        if abs(delta) + 1e-9 < threshold:
            return base

        # Quedas têm prioridade muito maior porque podem criar uma nova
        # oportunidade OURO/DIAMANTE. Subidas também são recalculadas, mas não
        # devem roubar slots às oportunidades.
        if delta > 0:
            bonus = float(settings.get("historical_price_drop_priority_bonus", 500.0))
        else:
            bonus = float(settings.get("historical_price_rise_priority_bonus", 100.0))
        return round(base + bonus, 3)

    tracker_module.candidate_priority = candidate_priority
    tracker_module._PRICE_CHANGE_PRIORITY_GUARD_INSTALLED = True
