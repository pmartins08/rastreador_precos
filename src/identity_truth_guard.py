from __future__ import annotations

from identity_utils import canonical_gtin


def _canonical_item(item: dict) -> dict:
    out = dict(item or {})
    canonical = canonical_gtin(out.get("ean"))
    if canonical:
        out["ean"] = canonical
    return out


def _patch_historical_identity() -> None:
    """Faz o histórico diário reutilizar a mesma identidade GTIN canónica."""
    try:
        import historical_guard as historical
    except Exception:
        return
    if getattr(historical, "_CANONICAL_GTIN_PATCHED", False):
        return

    base_identity_key = historical.identity_key
    base_load = historical._load

    def identity_key(item: dict):
        canonical = canonical_gtin((item or {}).get("ean"))
        if canonical:
            return f"ean:{canonical}", "EXATO"
        return base_identity_key(item)

    def migrate(data: dict) -> dict:
        identities = data.get("identities") if isinstance(data, dict) else None
        if not isinstance(identities, dict):
            return data
        migrated: dict[str, dict] = {}
        for old_key, raw in identities.items():
            if not isinstance(raw, dict):
                continue
            canonical = canonical_gtin(raw.get("ean"))
            new_key = f"ean:{canonical}" if canonical else str(old_key)
            if new_key not in migrated:
                migrated[new_key] = dict(raw)
                if canonical:
                    migrated[new_key]["canonical_gtin"] = canonical
                continue

            left = migrated[new_key]
            right = raw
            merged = dict(left)
            for field in ("ean", "mpn", "title", "confidence"):
                if not merged.get(field) and right.get(field):
                    merged[field] = right[field]
            first_values = [value for value in (left.get("first_seen"), right.get("first_seen")) if value]
            last_values = [value for value in (left.get("last_seen"), right.get("last_seen")) if value]
            if first_values:
                merged["first_seen"] = min(first_values)
            if last_values:
                merged["last_seen"] = max(last_values)
            merged["confidence"] = "EXATO"
            if canonical:
                merged["canonical_gtin"] = canonical
            days = {}
            for raw_day in set((left.get("days") or {})) | set((right.get("days") or {})):
                days[raw_day] = historical._merge_day(
                    (left.get("days") or {}).get(raw_day, {}),
                    (right.get("days") or {}).get(raw_day, {}),
                )
            merged["days"] = days
            migrated[new_key] = merged
        data["identities"] = migrated
        return data

    def load(path):
        return migrate(base_load(path))

    historical.identity_key = identity_key
    historical._load = load
    historical._CANONICAL_GTIN_PATCHED = True


def install(tracker_module) -> None:
    """Canonicaliza GTIN apenas nos pontos de identidade/matching.

    O valor bruto vindo da loja continua preservado no item/histórico. A camada
    só garante que UPC-A/GTIN-12 e o EAN-13 equivalente com zero à esquerda
    representam a mesma configuração internamente.
    """
    if getattr(tracker_module, "_IDENTITY_TRUTH_GUARD_INSTALLED", False):
        return

    required = (
        "configuration_signature",
        "match_configurations",
        "apply_exact_market_price_evidence",
    )
    if not all(hasattr(tracker_module, name) for name in required):
        return

    _patch_historical_identity()
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
