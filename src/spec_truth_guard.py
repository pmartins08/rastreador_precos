from __future__ import annotations

import re
from collections import defaultdict

from identity_utils import canonical_identity_key


SAFE_FIELDS = (
    "cpu_modelo",
    "cpu_classe",
    "gpu_tipo",
    "gpu_modelo",
    "ram_gb",
    "ram_type",
    "armazenamento_tb",
    "ecra_res",
    "ecra_hz",
    "bateria_wh",
    "peso_kg",
    "ram_expansivel",
    "ssd_expansivel",
)
CRITICAL_FIELDS = (
    "cpu_modelo",
    "gpu_modelo",
    "ram_gb",
    "armazenamento_tb",
    "ecra_res",
    "ecra_hz",
)
SOURCE_FIELD = {
    "cpu_modelo": "cpu",
    "cpu_classe": "cpu",
    "gpu_tipo": "gpu",
    "gpu_modelo": "gpu",
    "ram_gb": "ram",
    "ram_type": "ram_type",
    "armazenamento_tb": "storage",
    "ecra_res": "resolution",
    "ecra_hz": "refresh",
    "bateria_wh": "battery",
    "peso_kg": "weight",
    "ram_expansivel": "ram_slots",
    "ssd_expansivel": "m2",
}


def _resolution(value: object) -> tuple[int, int] | None:
    values = [int(raw) for raw in re.findall(r"\d{3,4}", str(value or ""))]
    if len(values) < 2:
        return None
    return tuple(sorted(values[:2]))


def _equal(field: str, left: object, right: object) -> bool:
    if field == "ecra_res":
        a, b = _resolution(left), _resolution(right)
        if a is not None and b is not None:
            return a == b
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return abs(float(left) - float(right)) < 1e-6
        except (TypeError, ValueError):
            pass
    clean = lambda value: re.sub(r"\s+", " ", str(value or "").strip().lower())
    return clean(left) == clean(right)


def _agreed_value(field: str, facts: list[dict]) -> tuple[object | None, list[str], bool]:
    known = [(row["spec"].get(field), row["source"]) for row in facts if row["spec"].get(field) is not None]
    if not known:
        return None, [], True
    first = known[0][0]
    if any(not _equal(field, first, value) for value, _source in known[1:]):
        return None, sorted({source for _value, source in known}), False
    return first, sorted({source for _value, source in known}), True


def _latest_history_facts(history: dict) -> list[dict]:
    facts: list[dict] = []
    for entries in (history.get("offers", {}) or {}).values():
        if not isinstance(entries, list) or not entries:
            continue
        entry = entries[-1]
        if not isinstance(entry, dict) or not isinstance(entry.get("specs"), dict):
            continue
        item = {"ean": entry.get("ean"), "mpn": entry.get("mpn")}
        key = canonical_identity_key(item)
        if not key:
            continue
        spec = entry["specs"]
        if spec.get("market_identity_conflict"):
            continue
        facts.append({
            "identity": key,
            "spec": spec,
            "source": f"history:{entry.get('loja') or 'unknown'}",
        })
    return facts


def enrich_exact_specs(records: list[dict], history: dict) -> dict:
    """Preenche apenas campos ausentes quando a identidade forte é exata e coerente."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    current_by_identity: dict[str, list[dict]] = defaultdict(list)

    for record in records:
        if not isinstance(record, dict):
            continue
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        spec = record.get("spec") if isinstance(record.get("spec"), dict) else None
        if spec is None:
            continue
        key = canonical_identity_key(item)
        if not key:
            continue
        fact = {
            "identity": key,
            "spec": spec,
            "source": f"current:{item.get('loja') or 'unknown'}",
        }
        grouped[key].append(fact)
        current_by_identity[key].append(record)

    for fact in _latest_history_facts(history):
        if fact["identity"] in current_by_identity:
            grouped[fact["identity"]].append(fact)

    groups_used = 0
    fields_filled = 0
    skipped_conflicts = 0
    for key, targets in current_by_identity.items():
        facts = grouped.get(key, [])
        critical_conflict = False
        for field in CRITICAL_FIELDS:
            _value, _sources, agreed = _agreed_value(field, facts)
            if not agreed:
                critical_conflict = True
                break
        if critical_conflict:
            skipped_conflicts += 1
            continue

        group_filled = 0
        for field in SAFE_FIELDS:
            value, sources, agreed = _agreed_value(field, facts)
            if not agreed or value is None:
                continue
            for record in targets:
                spec = record["spec"]
                if spec.get(field) is not None:
                    continue
                spec[field] = value
                spec.setdefault("fontes", {}).setdefault(SOURCE_FIELD[field], "cross_store_exact")
                truth = spec.setdefault("cross_store_spec_truth", {})
                truth[field] = {
                    "identity": key,
                    "sources": sources,
                    "confidence": "EXACT_IDENTITY",
                }
                fields_filled += 1
                group_filled += 1
        if group_filled:
            groups_used += 1

    return {
        "groups_used": groups_used,
        "fields_filled": fields_filled,
        "groups_skipped_conflict": skipped_conflicts,
    }


def install(tracker_module) -> None:
    if getattr(tracker_module, "_SPEC_TRUTH_GUARD_INSTALLED", False):
        return

    base_market = tracker_module.apply_exact_market_price_evidence

    def apply_exact_market_price_evidence(records: list[dict], settings: dict):
        try:
            history = tracker_module.load_json(tracker_module.HISTORY_PATH)
        except Exception:
            history = {}
        truth = enrich_exact_specs(records, history if isinstance(history, dict) else {})
        summary = dict(base_market(records, settings) or {})
        summary["spec_truth_groups"] = truth["groups_used"]
        summary["spec_truth_fields"] = truth["fields_filled"]
        summary["spec_truth_conflicts"] = truth["groups_skipped_conflict"]
        if truth["fields_filled"] and hasattr(tracker_module, "LOGGER"):
            tracker_module.LOGGER.info(
                "Spec Truth | grupos=%d | campos=%d | conflitos=%d",
                truth["groups_used"], truth["fields_filled"], truth["groups_skipped_conflict"],
            )
        return summary

    tracker_module.apply_exact_market_price_evidence = apply_exact_market_price_evidence
    tracker_module._SPEC_TRUTH_GUARD_INSTALLED = True
