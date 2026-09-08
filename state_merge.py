from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
    merged: dict[tuple, dict] = {}
    for entry in [*left, *right]:
        if isinstance(entry, dict):
            merged[_entry_id(entry)] = entry
    ordered = sorted(merged.values(), key=_timestamp)
    return ordered[-limit:]


def merge_history(current: dict, run: dict) -> dict:
    out = {
        "schema_version": max(int(current.get("schema_version", 0)), int(run.get("schema_version", 0)), 8),
        "offers": {},
        "alert_state": {},
        "learning": {"runs": [], "stores": {}},
    }

    current_offers = current.get("offers", {}) if isinstance(current.get("offers"), dict) else {}
    run_offers = run.get("offers", {}) if isinstance(run.get("offers"), dict) else {}
    for key in set(current_offers) | set(run_offers):
        left = current_offers.get(key, []) if isinstance(current_offers.get(key, []), list) else []
        right = run_offers.get(key, []) if isinstance(run_offers.get(key, []), list) else []
        out["offers"][key] = _merge_entry_lists(left, right)

    current_alerts = current.get("alert_state", {}) if isinstance(current.get("alert_state"), dict) else {}
    run_alerts = run.get("alert_state", {}) if isinstance(run.get("alert_state"), dict) else {}
    for key in set(current_alerts) | set(run_alerts):
        choices = [x for x in (current_alerts.get(key), run_alerts.get(key)) if isinstance(x, dict)]
        if choices:
            out["alert_state"][key] = max(choices, key=_timestamp)

    current_learning = current.get("learning", {}) if isinstance(current.get("learning"), dict) else {}
    run_learning = run.get("learning", {}) if isinstance(run.get("learning"), dict) else {}
    runs_by_id: dict[tuple, dict] = {}
    for record in [
        *(current_learning.get("runs", []) if isinstance(current_learning.get("runs"), list) else []),
        *(run_learning.get("runs", []) if isinstance(run_learning.get("runs"), list) else []),
    ]:
        if not isinstance(record, dict):
            continue
        key = (
            record.get("timestamp"),
            record.get("runner_version"),
            record.get("access_requests"),
        )
        runs_by_id[key] = record
    out["learning"]["runs"] = sorted(runs_by_id.values(), key=_timestamp)[-60:]

    current_stores = current_learning.get("stores", {}) if isinstance(current_learning.get("stores"), dict) else {}
    run_stores = run_learning.get("stores", {}) if isinstance(run_learning.get("stores"), dict) else {}
    out["learning"]["stores"] = _merge_monotonic(current_stores, run_stores)
    return out


def _merge_monotonic(left: Any, right: Any, key: str | None = None) -> Any:
    """Merge de snapshots cumulativos: contadores nunca recuam e novos ramos são preservados."""
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


def merge_access_learning(current: dict, run: dict) -> dict:
    merged = _merge_monotonic(current, run)
    if not isinstance(merged, dict):
        merged = {}
    merged["schema_version"] = max(
        int(current.get("schema_version", 0)),
        int(run.get("schema_version", 0)),
        2,
    )
    return merged


def merge_files(history_current: Path, history_run: Path, learning_current: Path, learning_run: Path) -> None:
    history = merge_history(load_json(history_current), load_json(history_run))
    learning = merge_access_learning(load_json(learning_current), load_json(learning_run))
    save_json(history_current, history)
    save_json(learning_current, learning)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge seguro do estado do rastreador.")
    parser.add_argument("--history-current", required=True, type=Path)
    parser.add_argument("--history-run", required=True, type=Path)
    parser.add_argument("--learning-current", required=True, type=Path)
    parser.add_argument("--learning-run", required=True, type=Path)
    args = parser.parse_args()
    merge_files(args.history_current, args.history_run, args.learning_current, args.learning_run)


if __name__ == "__main__":
    main()
