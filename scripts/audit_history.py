from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = ROOT / "data" / "history.json"
DEFAULT_CONFIG = ROOT / "config" / "config.json"


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _explicit_system_ram(title: str) -> int | None:
    text = _norm(title).replace(",", ".")
    patterns = (
        r"\b(\d{1,3})\s*gb\s*(?:ddr[345]|lpddr[345](?:x)?|ram|sodimm)\b",
        r"\b(?:ram|mem[oó]ria(?:\s+ram)?)\s*[:\-]?\s*(\d{1,3})\s*gb\b",
    )
    hits: list[int] = []
    for pattern in patterns:
        hits.extend(int(match) for match in re.findall(pattern, text, flags=re.I))
    hits = [value for value in hits if 4 <= value <= 256]
    if not hits:
        return None
    # Em títulos de lojas pode haver VRAM antes da RAM; padrões acima exigem
    # DDR/LPDDR/RAM/SODIMM e, por isso, não consideram "RTX 5060 8GB".
    return max(hits)


def _explicit_gpu(title: str) -> str | None:
    text = _norm(title)
    match = re.search(r"\brtx\s*(20|30|40|50)(\d{2})(?:\s*(ti))?\b", text, flags=re.I)
    if not match:
        return None
    return f"rtx {match.group(1)}{match.group(2)}" + (" ti" if match.group(3) else "")


def _explicit_storage_tb(title: str) -> float | None:
    text = _norm(title).replace(",", ".")
    tb = re.search(r"\b(\d+(?:\.\d+)?)\s*tb\s*(?:ssd|nvme|m\.2)?\b", text, flags=re.I)
    if tb:
        value = float(tb.group(1))
        return value if 0.1 <= value <= 16 else None
    gb = re.search(r"\b(\d{3,4})\s*gb\s*(?:ssd|nvme|m\.2)\b", text, flags=re.I)
    if gb:
        value = int(gb.group(1)) / 1024.0
        return value if 0.1 <= value <= 16 else None
    return None


def _canonical_gpu(value: Any) -> str | None:
    text = _norm(value)
    match = re.search(r"\brtx\s*(20|30|40|50)(\d{2})(?:\s*(ti))?\b", text, flags=re.I)
    if not match:
        return None
    return f"rtx {match.group(1)}{match.group(2)}" + (" ti" if match.group(3) else "")


def _identity(record: dict[str, Any], url: str) -> str:
    key = str(record.get("configuration_key") or "").strip()
    if key:
        return key
    for field in ("ean", "mpn", "sku"):
        value = str(record.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return f"url:{url}"


def _effective(record: dict[str, Any]) -> tuple[float | None, float | None, str]:
    promoted = bool(record.get("promotion_price_live_confirmed"))
    promo_value = _f(record.get("promotion_value_score")) if promoted else None
    promo_price = _f(record.get("promotion_checkout_price")) if promoted else None
    promo_tier = str(record.get("promotion_tier") or "").upper() if promoted else ""
    value = promo_value if promo_value is not None else _f(record.get("value_score"))
    price = promo_price if promo_price is not None else _f(record.get("price"))
    tier = promo_tier or str(record.get("tier") or "").upper()
    return value, price, tier


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * q
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    weight = index - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def latest_records(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    offers = data.get("offers") if isinstance(data.get("offers"), dict) else {}
    for url, entries in offers.items():
        if not isinstance(entries, list) or not entries:
            continue
        records = [entry for entry in entries if isinstance(entry, dict)]
        if not records:
            continue
        latest = max(records, key=lambda entry: str(entry.get("timestamp") or ""))
        out.append((str(url), latest))
    return out


def detect_record_problems(url: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    title = str(record.get("titulo") or "")
    specs = record.get("specs") if isinstance(record.get("specs"), dict) else {}

    title_ram = _explicit_system_ram(title)
    parsed_ram = specs.get("ram_gb")
    if title_ram is not None and isinstance(parsed_ram, (int, float)) and int(parsed_ram) != title_ram:
        problems.append({
            "severity": "CORRUPTION",
            "kind": "RAM_TITLE_MISMATCH",
            "url": url,
            "title": title,
            "title_ram_gb": title_ram,
            "parsed_ram_gb": parsed_ram,
        })

    title_gpu = _explicit_gpu(title)
    parsed_gpu = _canonical_gpu(specs.get("gpu_modelo"))
    if title_gpu and parsed_gpu and title_gpu != parsed_gpu:
        problems.append({
            "severity": "CORRUPTION",
            "kind": "GPU_TITLE_MISMATCH",
            "url": url,
            "title": title,
            "title_gpu": title_gpu,
            "parsed_gpu": parsed_gpu,
        })

    title_storage = _explicit_storage_tb(title)
    parsed_storage = _f(specs.get("armazenamento_tb"))
    if title_storage is not None and parsed_storage is not None:
        # 512 GB pode aparecer normalizado como 0.5 TB. Tolerância cobre 500/512.
        if abs(title_storage - parsed_storage) > 0.12:
            problems.append({
                "severity": "CORRUPTION",
                "kind": "STORAGE_TITLE_MISMATCH",
                "url": url,
                "title": title,
                "title_storage_tb": round(title_storage, 3),
                "parsed_storage_tb": parsed_storage,
            })

    price = _f(record.get("price"))
    confirmed = _f(specs.get("price_confirmed"))
    if price is not None and confirmed is not None and abs(price - confirmed) > max(5.0, price * 0.015):
        problems.append({
            "severity": "CORRUPTION",
            "kind": "PRICE_CONFIRMATION_MISMATCH",
            "url": url,
            "title": title,
            "history_price": price,
            "confirmed_price": confirmed,
        })

    value, effective_price, tier = _effective(record)
    if value is not None and value > 150:
        problems.append({
            "severity": "REVIEW",
            "kind": "EXTREME_VALUE",
            "url": url,
            "title": title,
            "value": value,
            "effective_price": effective_price,
            "tier": tier,
        })
    if effective_price is not None and effective_price < 250:
        problems.append({
            "severity": "REVIEW",
            "kind": "PRICE_BELOW_GLOBAL_FLOOR",
            "url": url,
            "title": title,
            "effective_price": effective_price,
            "value": value,
            "tier": tier,
        })
    return problems


def audit(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    records = latest_records(data)
    problems: list[dict[str, Any]] = []
    for url, record in records:
        problems.extend(detect_record_problems(url, record))

    corrupt_urls = {
        item["url"] for item in problems if item.get("severity") == "CORRUPTION"
    }
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}
    hard = float(settings.get("budget_hard", 1500.0))

    by_identity: dict[str, dict[str, Any]] = {}
    for url, record in records:
        if url in corrupt_urls or not bool(record.get("stock", True)):
            continue
        value, effective_price, tier = _effective(record)
        if value is None or effective_price is None or effective_price > hard:
            continue
        identity = _identity(record, url)
        candidate = {
            "identity": identity,
            "url": url,
            "store": record.get("loja"),
            "title": record.get("titulo"),
            "raw_price": _f(record.get("price")),
            "effective_price": effective_price,
            "value": value,
            "tier": tier,
            "timestamp": record.get("timestamp"),
            "promotion": bool(record.get("promotion_price_live_confirmed")),
        }
        old = by_identity.get(identity)
        if old is None or (candidate["value"], -candidate["effective_price"]) > (old["value"], -old["effective_price"]):
            by_identity[identity] = candidate

    current = sorted(
        by_identity.values(),
        key=lambda item: (item["value"], -item["effective_price"]),
        reverse=True,
    )
    values = [float(item["value"]) for item in current]
    thresholds = [110, 115, 120, 125, 130, 135]
    threshold_counts = {
        str(threshold): {
            "count": sum(value >= threshold for value in values),
            "pct": round(100.0 * sum(value >= threshold for value in values) / len(values), 2) if values else 0.0,
        }
        for threshold in thresholds
    }

    return {
        "latest_urls": len(records),
        "clean_current_identities": len(current),
        "problems": problems,
        "problem_counts": dict(Counter(item["kind"] for item in problems)),
        "corrupt_urls": sorted(corrupt_urls),
        "distribution": {
            "min": round(min(values), 2) if values else None,
            "median": round(_percentile(values, 0.50), 2) if values else None,
            "p90": round(_percentile(values, 0.90), 2) if values else None,
            "p95": round(_percentile(values, 0.95), 2) if values else None,
            "p97": round(_percentile(values, 0.97), 2) if values else None,
            "p99": round(_percentile(values, 0.99), 2) if values else None,
            "max": round(max(values), 2) if values else None,
            "thresholds": threshold_counts,
        },
        "top10": current[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita o histórico persistido sem alterar estado.")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.history.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    report = audit(data, config)
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
