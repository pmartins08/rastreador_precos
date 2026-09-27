from __future__ import annotations

from identity_utils import canonical_gtin


def _canonical_item(item: dict) -> dict:
    out = dict(item or {})
    canonical = canonical_gtin(out.get("ean"))
    if canonical:
        out["ean"] = canonical
    return out


def install(tracker_module) -> None:
    """Canonicaliza GTIN apenas nos pontos de identidade/matching.

    O valor bruto vindo da loja continua preservado no item/histórico. A camada
    só garante que UPC-A/GTIN-12 e o EAN-13 equivalente com zero à esquerda
    representam a mesma configuração internamente.
    """
    if getattr(tracker_module, "_IDENTITY_TRUTH_GUARD_INSTALLED", False):
        return

    base_signature = tracker_module.configuration_signature
    base_match = tracker_module.match_configurations
    base_market = tracker_module.apply_exact_market_price_evidence

    def configuration_signature(item: dict, spec: dict) -> str:
        return base_signature(_canonical_item(item), spec)

    def match_configurations(left_item, left_spec, right_item, right_spec):
        return base_match(
            _canonical_item(left_item), left_spec,
            _canonical_item(right_item), right_spec,
        )

    def apply_exact_market_price_evidence(records: list[dict], settings: dict):
        backups: list[tuple[dict, object]] = []
        sentinel = object()
        for record in records:
            item = record.get("item") if isinstance(record, dict) else None
            if not isinstance(item, dict):
                continue
            canonical = canonical_gtin(item.get("ean"))
            if not canonical:
                continue
            backups.append((item, item.get("ean", sentinel)))
            item["ean"] = canonical
        try:
            return base_market(records, settings)
        finally:
            for item, raw in backups:
                if raw is sentinel:
                    item.pop("ean", None)
                else:
                    item["ean"] = raw

    tracker_module.configuration_signature = configuration_signature
    tracker_module.match_configurations = match_configurations
    tracker_module.apply_exact_market_price_evidence = apply_exact_market_price_evidence
    tracker_module._IDENTITY_TRUTH_GUARD_INSTALLED = True
