from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from version import VERSION


ROOT = Path(__file__).resolve().parent.parent
MATCHING_STATE_PATH = ROOT / "data" / "matching_state.json"
SCHEMA_VERSION = 1
CRITICAL_FIELDS = (
    "cpu_modelo",
    "gpu_modelo",
    "ram_gb",
    "armazenamento_tb",
    "ecra_res",
    "ecra_hz",
)

_CAPTURE_ACTIVE = False
_CAPTURED_RECORDS: list[dict] = []
_CAPTURED_MATCHING: dict = {}
_CAPTURED_CONFLICTS: list[dict] = []


def _normal_id(value: object) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _same_strong_identifier(left_item: dict, right_item: dict) -> tuple[str | None, str | None]:
    left_ean = _normal_id(left_item.get("ean"))
    right_ean = _normal_id(right_item.get("ean"))
    if left_ean and left_ean == right_ean:
        return "ean", left_ean

    left_mpn = _normal_id(left_item.get("mpn"))
    right_mpn = _normal_id(right_item.get("mpn"))
    if left_mpn and left_mpn == right_mpn:
        return "mpn", left_mpn
    return None, None


def configuration_conflicts(tracker_module, left_spec: dict, right_spec: dict) -> list[str]:
    """Campos técnicos conhecidos nos dois lados que se contradizem."""
    comparator = getattr(tracker_module, "_spec_equal", None)
    conflicts: list[str] = []
    for field in CRITICAL_FIELDS:
        left = left_spec.get(field)
        right = right_spec.get(field)
        if left is None or right is None:
            continue
        same = comparator(left, right) if callable(comparator) else str(left).strip().lower() == str(right).strip().lower()
        if not same:
            conflicts.append(field)
    return conflicts


def _conflict_row(left_item: dict, right_item: dict, result: dict) -> dict:
    return {
        "level": result.get("level"),
        "reason": result.get("reason"),
        "fields": list(result.get("conflicting_fields") or []),
        "identifier_type": result.get("identifier_type"),
        "identifier": result.get("identifier"),
        "left_store": left_item.get("loja"),
        "left_url": left_item.get("url"),
        "left_title": left_item.get("titulo"),
        "right_store": right_item.get("loja"),
        "right_url": right_item.get("url"),
        "right_title": right_item.get("titulo"),
    }


def _identity_key(tracker_module, record: dict) -> str:
    item = record.get("item") or {}
    spec = record.get("spec") or {}
    for field in ("ean", "mpn"):
        value = _normal_id(item.get(field))
        if value:
            return f"{field}:{value}"
    return str(tracker_module.configuration_signature(item, spec))


def _identity_summary(tracker_module, records: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(_identity_key(tracker_module, record), []).append(record)

    rows: list[dict] = []
    for key, members in grouped.items():
        offers = []
        for member in members:
            item = member.get("item") or {}
            spec = member.get("spec") or {}
            offers.append(
                {
                    "store": item.get("loja"),
                    "url": item.get("url"),
                    "title": item.get("titulo"),
                    "price": item.get("preco"),
                    "ean": item.get("ean"),
                    "mpn": item.get("mpn"),
                    "cpu": spec.get("cpu_modelo"),
                    "gpu": spec.get("gpu_modelo") or spec.get("gpu_tipo"),
                    "ram_gb": spec.get("ram_gb"),
                    "storage_tb": spec.get("armazenamento_tb"),
                }
            )
        rows.append(
            {
                "identity": key,
                "stores": sorted({str(row.get("store")) for row in offers if row.get("store")}),
                "offers": offers,
            }
        )
    rows.sort(key=lambda row: (-len(row["stores"]), row["identity"]))
    return rows


def build_matching_state(tracker_module, records: list[dict], matching: dict, conflicts: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tracker_version": VERSION,
        "generated_at": tracker_module.now_iso(),
        "source": "current_run_records",
        "records_considered": len(records),
        "identity_count": len(_identity_summary(tracker_module, records)),
        "exact_pairs": int(matching.get("exact_pairs", 0)),
        "strong_pairs": int(matching.get("strong_pairs", 0)),
        "probable_pairs": int(matching.get("probable_pairs", 0)),
        "conflicting_pairs": int(matching.get("conflicting_pairs", 0)),
        "identities": _identity_summary(tracker_module, records),
        "cross_store_groups": list(matching.get("groups") or []),
        "probable_review": list(matching.get("probable_review") or []),
        "conflicts": conflicts,
    }


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def install(tracker_module) -> None:
    """Torna identificadores fortes subordinados à coerência técnica.

    EAN/MPN continuam a ser a melhor evidência de identidade, mas nunca podem
    fundir duas ofertas quando CPU/GPU/RAM/SSD/ecrã conhecidos se contradizem.
    O estado de matching persistido é puramente derivado dos registos da run.
    """
    if getattr(tracker_module, "_MATCHING_GUARD_INSTALLED", False):
        return

    base_match = tracker_module.match_configurations
    base_build = tracker_module.build_cross_store_matches
    base_main = tracker_module.main

    def match_configurations(left_item: dict, left_spec: dict, right_item: dict, right_spec: dict) -> dict:
        identifier_type, identifier = _same_strong_identifier(left_item, right_item)
        if identifier_type:
            conflicts = configuration_conflicts(tracker_module, left_spec, right_spec)
            if conflicts:
                result = {
                    "level": "NAO_FUNDIR",
                    "reason": "identificador forte contradiz configuração técnica",
                    "identifier_type": identifier_type,
                    "identifier": identifier,
                    "conflicting_fields": conflicts,
                }
                if _CAPTURE_ACTIVE:
                    _CAPTURED_CONFLICTS.append(_conflict_row(left_item, right_item, result))
                return result

        result = base_match(left_item, left_spec, right_item, right_spec)
        if _CAPTURE_ACTIVE and result.get("level") == "NAO_FUNDIR":
            _CAPTURED_CONFLICTS.append(_conflict_row(left_item, right_item, result))
        return result

    def build_cross_store_matches(records: list[dict]) -> dict:
        global _CAPTURE_ACTIVE, _CAPTURED_RECORDS, _CAPTURED_MATCHING, _CAPTURED_CONFLICTS
        _CAPTURED_RECORDS = list(records)
        _CAPTURED_CONFLICTS = []
        _CAPTURE_ACTIVE = True
        try:
            result = base_build(records)
        finally:
            _CAPTURE_ACTIVE = False
        _CAPTURED_MATCHING = dict(result)
        return result

    def main():
        global _CAPTURED_RECORDS, _CAPTURED_MATCHING, _CAPTURED_CONFLICTS
        _CAPTURED_RECORDS = []
        _CAPTURED_MATCHING = {}
        _CAPTURED_CONFLICTS = []
        run = base_main()
        if _CAPTURED_MATCHING:
            state = build_matching_state(
                tracker_module,
                _CAPTURED_RECORDS,
                _CAPTURED_MATCHING,
                list(_CAPTURED_CONFLICTS),
            )
            _save(MATCHING_STATE_PATH, state)
            if isinstance(run, dict):
                run["matching_state_records"] = state["records_considered"]
                run["matching_state_identities"] = state["identity_count"]
                run["matching_state_conflicts"] = len(state["conflicts"])
            tracker_module.LOGGER.info(
                "Matching state | registos=%d | identidades=%d | conflitos=%d | ficheiro=%s",
                state["records_considered"],
                state["identity_count"],
                len(state["conflicts"]),
                MATCHING_STATE_PATH.name,
            )
        return run

    tracker_module.match_configurations = match_configurations
    tracker_module.build_cross_store_matches = build_cross_store_matches
    tracker_module.main = main
    tracker_module._MATCHING_GUARD_INSTALLED = True
