from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from identity_utils import canonical_gtin


SCHEMA_VERSION = 1
WINDOW_DAYS = 90
ROOT = Path(__file__).resolve().parent.parent
PRICE_HISTORY_PATH = ROOT / "data" / "price_history.json"

_STATE: dict = {}
_BASELINE_STATE: dict = {}
_CURRENT_ALERT_CONTEXT: dict | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        data = {"schema_version": SCHEMA_VERSION, "updated_at": None, "identities": {}}
    data.setdefault("identities", {})
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at"] = now_iso()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _clone(data: dict) -> dict:
    return json.loads(json.dumps(data))


def _normal_id(value: object) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def identity_key(item: dict) -> tuple[str | None, str]:
    """Identidade histórica: GTIN canónico/MPN forte, URL local como fallback."""
    raw_ean = _normal_id(item.get("ean"))
    canonical = canonical_gtin(item.get("ean"))
    if canonical:
        return f"ean:{canonical}", "EXATO"
    if raw_ean:
        # Compatibilidade conservadora: EAN legado inválido continua estável,
        # mas nunca é "corrigido" para outro GTIN.
        return f"ean:{raw_ean}", "EXATO"
    mpn = _normal_id(item.get("mpn"))
    if mpn:
        return f"mpn:{mpn}", "EXATO"
    url = str(item.get("url") or "").strip()
    if url:
        digest = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        return f"url:{digest}", "LOCAL"
    return None, "NONE"


def _canonical_stored_key(key: str, entry: dict) -> tuple[str, str | None]:
    """Migra chaves EAN/UPC legadas para GTIN-14 sem inventar identificadores."""
    if not str(key).startswith("ean:"):
        return str(key), None
    suffix = str(key).split(":", 1)[1]
    canonical = canonical_gtin(entry.get("ean") or suffix)
    if not canonical:
        return str(key), None
    return f"ean:{canonical}", canonical


def _iso_min(*values: object) -> str | None:
    rows = [str(value) for value in values if value]
    return min(rows) if rows else None


def _iso_max(*values: object) -> str | None:
    rows = [str(value) for value in values if value]
    return max(rows) if rows else None


def _merge_alias_day(left: dict, right: dict) -> dict:
    """Consolida duas aliases da mesma identidade sem inflar retries.

    Se as lojas do mesmo dia são disjuntas, são observações independentes e
    somamos amostras. Se há sobreposição, usamos o maior contador/soma para não
    duplicar a mesma observação durante uma migração/retry.
    """
    if not isinstance(left, dict):
        left = {}
    if not isinstance(right, dict):
        right = {}
    minima = [float(row["min"]) for row in (left, right) if row.get("min") is not None]
    maxima = [float(row["max"]) for row in (left, right) if row.get("max") is not None]
    left_stores = set(left.get("stores") or [])
    right_stores = set(right.get("stores") or [])
    disjoint = bool(left_stores and right_stores and left_stores.isdisjoint(right_stores))
    if disjoint:
        samples = int(left.get("samples", 0)) + int(right.get("samples", 0))
        total = float(left.get("sum", 0.0)) + float(right.get("sum", 0.0))
    else:
        samples = max(int(left.get("samples", 0)), int(right.get("samples", 0)))
        total = max(float(left.get("sum", 0.0)), float(right.get("sum", 0.0)))
    latest = right if right else left
    return {
        "min": round(min(minima), 2) if minima else None,
        "max": round(max(maxima), 2) if maxima else None,
        "last": latest.get("last"),
        "sum": round(total, 2),
        "samples": samples,
        "stores": sorted(left_stores | right_stores),
    }


def _merge_alias_entries(left: dict, right: dict, canonical: str | None) -> dict:
    left = _clone(left) if isinstance(left, dict) else {}
    right = _clone(right) if isinstance(right, dict) else {}
    latest_is_right = str(right.get("last_seen") or "") >= str(left.get("last_seen") or "")
    latest = right if latest_is_right else left
    other = left if latest_is_right else right

    out = dict(other)
    out.update({k: v for k, v in latest.items() if k != "days" and v is not None})
    out["first_seen"] = _iso_min(left.get("first_seen"), right.get("first_seen"))
    out["last_seen"] = _iso_max(left.get("last_seen"), right.get("last_seen"))
    out["confidence"] = "EXATO" if "EXATO" in {left.get("confidence"), right.get("confidence")} else (
        latest.get("confidence") or other.get("confidence")
    )
    if out.get("confidence") == "EXATO":
        out["url"] = None
    if canonical:
        out["gtin14"] = canonical
        raw_candidates = [
            str(value)
            for value in (left.get("ean"), right.get("ean"))
            if value
        ]
        if raw_candidates:
            out["ean"] = max(raw_candidates, key=len)

    days = {}
    all_days = set((left.get("days") or {})) | set((right.get("days") or {}))
    for raw_day in all_days:
        days[raw_day] = _merge_alias_day(
            (left.get("days") or {}).get(raw_day, {}),
            (right.get("days") or {}).get(raw_day, {}),
        )
    out["days"] = days
    return out


def _day(value: str | None = None) -> date:
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _entry(state: dict, item: dict) -> tuple[str | None, str, dict | None]:
    key, confidence = identity_key(item)
    if not key:
        return None, confidence, None
    identities = state.setdefault("identities", {})
    entry = identities.setdefault(
        key,
        {
            "confidence": confidence,
            "ean": item.get("ean"),
            "mpn": item.get("mpn"),
            "url": item.get("url") if confidence == "LOCAL" else None,
            "title": item.get("titulo"),
            "first_seen": now_iso(),
            "last_seen": None,
            "days": {},
        },
    )
    if confidence == "EXATO":
        entry["confidence"] = "EXATO"
        entry["ean"] = item.get("ean") or entry.get("ean")
        entry["mpn"] = item.get("mpn") or entry.get("mpn")
        entry["url"] = None
        canonical = canonical_gtin(item.get("ean"))
        if canonical:
            entry["gtin14"] = canonical
    entry["title"] = item.get("titulo") or entry.get("title")
    return key, confidence, entry


def _recent_days(entry: dict, today: date, window_days: int = WINDOW_DAYS) -> list[tuple[date, dict]]:
    cutoff = today - timedelta(days=max(1, int(window_days)) - 1)
    rows = []
    for raw_day, stats in (entry.get("days") or {}).items():
        try:
            parsed = date.fromisoformat(str(raw_day))
        except ValueError:
            continue
        if cutoff <= parsed <= today and isinstance(stats, dict):
            rows.append((parsed, stats))
    return sorted(rows, key=lambda pair: pair[0])


def historical_context(
    state: dict,
    item: dict,
    current_price: float,
    *,
    today: date | None = None,
    window_days: int = WINDOW_DAYS,
) -> dict:
    key, confidence = identity_key(item)
    if not key:
        return {"available": False, "confidence": "NONE"}
    entry = (state.get("identities") or {}).get(key)
    if not isinstance(entry, dict):
        return {
            "available": False,
            "confidence": confidence,
            "identity": key,
            "window_days": int(window_days),
        }

    day = today or datetime.now(timezone.utc).date()
    rows = _recent_days(entry, day, window_days)
    if not rows:
        return {
            "available": False,
            "confidence": confidence,
            "identity": key,
            "window_days": int(window_days),
        }

    minima = [float(stats["min"]) for _, stats in rows if stats.get("min") is not None]
    sums = [float(stats.get("sum", 0.0)) for _, stats in rows]
    samples = sum(int(stats.get("samples", 0)) for _, stats in rows)
    stores = sorted(
        {
            str(store)
            for _, stats in rows
            for store in (stats.get("stores") or [])
            if store
        }
    )
    if not minima or samples <= 0:
        return {
            "available": False,
            "confidence": confidence,
            "identity": key,
            "window_days": int(window_days),
        }

    historical_min = min(minima)
    historical_avg = sum(sums) / samples
    historical_median_daily_min = float(median(minima))
    delta_min = float(current_price) - historical_min
    delta_min_pct = (delta_min / historical_min * 100.0) if historical_min else 0.0
    delta_avg_pct = (
        (float(current_price) - historical_avg) / historical_avg * 100.0
        if historical_avg
        else 0.0
    )
    tolerance = max(5.0, historical_min * 0.005)

    return {
        "available": True,
        "confidence": confidence,
        "identity": key,
        "window_days": int(window_days),
        "days_observed": len(rows),
        "samples": samples,
        "stores": stores,
        "min": round(historical_min, 2),
        "average": round(historical_avg, 2),
        "median_daily_min": round(historical_median_daily_min, 2),
        "delta_vs_min_eur": round(delta_min, 2),
        "delta_vs_min_pct": round(delta_min_pct, 2),
        "delta_vs_average_pct": round(delta_avg_pct, 2),
        "new_low": float(current_price) < historical_min - tolerance,
        "at_or_near_low": float(current_price) <= historical_min + tolerance,
    }


def observe(
    state: dict,
    item: dict,
    price: float,
    *,
    observed_at: str | None = None,
    window_days: int = WINDOW_DAYS,
) -> None:
    key, confidence, entry = _entry(state, item)
    if not key or entry is None:
        return
    day = _day(observed_at)
    raw_day = day.isoformat()
    stats = entry.setdefault("days", {}).setdefault(
        raw_day,
        {"min": float(price), "max": float(price), "last": float(price), "sum": 0.0, "samples": 0, "stores": []},
    )
    value = float(price)
    stats["min"] = round(min(float(stats.get("min", value)), value), 2)
    stats["max"] = round(max(float(stats.get("max", value)), value), 2)
    stats["last"] = round(value, 2)
    stats["sum"] = round(float(stats.get("sum", 0.0)) + value, 2)
    stats["samples"] = int(stats.get("samples", 0)) + 1
    store = str(item.get("loja") or "").strip()
    if store:
        stores = set(stats.get("stores") or [])
        stores.add(store)
        stats["stores"] = sorted(stores)
    if observed_at:
        entry["first_seen"] = _iso_min(entry.get("first_seen"), observed_at)
    entry["last_seen"] = observed_at or now_iso()
    entry["confidence"] = "EXATO" if confidence == "EXATO" else entry.get("confidence", confidence)
    _prune_entry(entry, day, window_days)


def _prune_entry(entry: dict, today: date, window_days: int = WINDOW_DAYS) -> None:
    cutoff = today - timedelta(days=max(1, int(window_days)) - 1)
    days = entry.get("days") or {}
    for raw_day in list(days):
        try:
            parsed = date.fromisoformat(str(raw_day))
        except ValueError:
            del days[raw_day]
            continue
        if parsed < cutoff:
            del days[raw_day]


def compact(state: dict, *, today: date | None = None, window_days: int = WINDOW_DAYS) -> dict:
    day = today or datetime.now(timezone.utc).date()
    out = {"schema_version": SCHEMA_VERSION, "updated_at": state.get("updated_at"), "identities": {}}
    for key, raw in (state.get("identities") or {}).items():
        if not isinstance(raw, dict):
            continue
        entry = _clone(raw)
        _prune_entry(entry, day, window_days)
        if not entry.get("days"):
            continue
        target_key, canonical = _canonical_stored_key(str(key), entry)
        if canonical:
            entry["gtin14"] = canonical
        existing = out["identities"].get(target_key)
        if isinstance(existing, dict):
            out["identities"][target_key] = _merge_alias_entries(existing, entry, canonical)
        else:
            out["identities"][target_key] = entry
    return out


def _merge_day(left: dict, right: dict) -> dict:
    values = [row for row in (left, right) if isinstance(row, dict)]
    if not values:
        return {}
    minima = [float(row["min"]) for row in values if row.get("min") is not None]
    maxima = [float(row["max"]) for row in values if row.get("max") is not None]
    latest = right if isinstance(right, dict) and right else left
    return {
        "min": round(min(minima), 2) if minima else None,
        "max": round(max(maxima), 2) if maxima else None,
        "last": latest.get("last"),
        "sum": round(max(float(left.get("sum", 0.0)), float(right.get("sum", 0.0))), 2),
        "samples": max(int(left.get("samples", 0)), int(right.get("samples", 0))),
        "stores": sorted(set(left.get("stores") or []) | set(right.get("stores") or [])),
    }


def merge_price_history(current: dict, run_state: dict) -> dict:
    """Merge idempotente pensado para retries do GitHub Actions."""
    left = compact(current)
    right = compact(run_state)
    out = {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "identities": {}}
    for key in set(left.get("identities", {})) | set(right.get("identities", {})):
        a = (left.get("identities") or {}).get(key, {})
        b = (right.get("identities") or {}).get(key, {})
        base = dict(a)
        base.update({k: v for k, v in b.items() if k != "days" and v is not None})
        days = {}
        for raw_day in set(a.get("days", {})) | set(b.get("days", {})):
            days[raw_day] = _merge_day(
                (a.get("days") or {}).get(raw_day, {}),
                (b.get("days") or {}).get(raw_day, {}),
            )
        base["days"] = days
        out["identities"][key] = base
    return compact(out)


def _format_context(context: dict | None) -> str:
    if not context or not context.get("available"):
        return ""
    label = "histórico exato" if context.get("confidence") == "EXATO" else "histórico desta oferta"
    note = (
        f"\n{label} {context.get('window_days', WINDOW_DAYS)}d: mín {context['min']:.2f}€ | "
        f"média {context['average']:.2f}€ | {context['days_observed']} dias"
    )
    if context.get("new_low"):
        note += " | NOVO MÍNIMO"
    elif context.get("at_or_near_low"):
        note += " | perto do mínimo"
    return note


def install(tracker_module) -> None:
    """Adiciona contexto histórico sem alterar Value, tier ou confiança de preço."""
    if getattr(tracker_module, "_HISTORICAL_GUARD_INSTALLED", False):
        return

    base_record_offer = tracker_module.record_offer
    base_maybe_alert = tracker_module.maybe_alert
    base_ntfy_send = tracker_module.ntfy_send
    base_main = tracker_module.main

    def record_offer(history, item, spec, assessment, tier):
        global _STATE, _BASELINE_STATE
        context = historical_context(_BASELINE_STATE, item, float(item["preco"]))
        assessment["historical_price"] = context
        previous, key = base_record_offer(history, item, spec, assessment, tier)
        entries = history.get("offers", {}).get(key, [])
        if entries and isinstance(entries[-1], dict):
            entries[-1]["historical_price"] = context
            entries[-1]["price_history_key"] = context.get("identity")
        observe(_STATE, item, float(item["preco"]))
        return previous, key

    def ntfy_send(title, message, *, priority=3, tags=None):
        note = _format_context(_CURRENT_ALERT_CONTEXT)
        if note and "Loja:" in str(message) and "Value:" in str(message):
            message = f"{message}{note}"
        return base_ntfy_send(title, message, priority=priority, tags=tags)

    def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
        global _CURRENT_ALERT_CONTEXT
        _CURRENT_ALERT_CONTEXT = assessment.get("historical_price")
        try:
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )
        finally:
            _CURRENT_ALERT_CONTEXT = None

    def main():
        global _STATE, _BASELINE_STATE
        _STATE = compact(_load(PRICE_HISTORY_PATH))
        _BASELINE_STATE = _clone(_STATE)
        run = base_main()
        _STATE = compact(_STATE)
        _save(PRICE_HISTORY_PATH, _STATE)
        if isinstance(run, dict):
            count = len(_STATE.get("identities", {}))
            run["price_history_identities"] = count
            # O tracker base já persistiu a run. Acrescentamos apenas esta métrica
            # ao registo mais recente para ficar disponível na apresentação futura.
            try:
                history = tracker_module.load_json(tracker_module.HISTORY_PATH)
                runs = (history.get("learning", {}) or {}).get("runs", [])
                if runs and isinstance(runs[-1], dict):
                    runs[-1]["price_history_identities"] = count
                    tracker_module.save_json(tracker_module.HISTORY_PATH, history)
            except Exception:
                tracker_module.LOGGER.warning(
                    "Histórico de preços guardado, mas a métrica da run não foi anexada ao history.json"
                )
        return run

    tracker_module.record_offer = record_offer
    tracker_module.ntfy_send = ntfy_send
    tracker_module.maybe_alert = maybe_alert
    tracker_module.main = main
    tracker_module._HISTORICAL_GUARD_INSTALLED = True


def merge_cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Merge seguro do histórico diário de preços")
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args(argv)
    merged = merge_price_history(_load(args.current), _load(args.run))
    _save(args.current, merged)


if __name__ == "__main__":
    merge_cli()
