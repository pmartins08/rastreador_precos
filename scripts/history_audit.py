from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


VALUE_KEYS = ("promotion_value_score", "value_score", "value")
TITLE_KEYS = ("titulo", "title", "name")
STORE_KEYS = ("loja", "store")
PRICE_KEYS = ("promotion_checkout_price", "checkout_price", "price", "preco")

# Configurações de VRAM que a NVIDIA publica de forma inequívoca para as GPUs
# Laptop RTX 50 abaixo. Usadas apenas para detetar incoerências; o auditor não
# altera dados.
KNOWN_LAPTOP_VRAM_GB = {
    "rtx 5090": 24.0,
    "rtx 5080": 16.0,
    "rtx 5070 ti": 12.0,
    "rtx 5060": 8.0,
    "rtx 5050": 8.0,
}


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first(mapping: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _norm_gpu(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"\b(?:nvidia|geforce|laptop gpu|notebook gpu)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _identity(record: dict) -> str:
    for key in ("ean", "mpn", "sku", "configuration_key", "url"):
        value = record.get(key)
        if value not in (None, ""):
            return f"{key}:{str(value).strip().lower()}"
    title = str(_first(record, TITLE_KEYS) or "").strip().lower()
    store = str(_first(record, STORE_KEYS) or "").strip().lower()
    return f"fallback:{store}:{title}"


def _value_record(record: dict, path: str) -> dict | None:
    title = _first(record, TITLE_KEYS)
    store = _first(record, STORE_KEYS)
    value = _float(_first(record, VALUE_KEYS))
    price = _float(_first(record, PRICE_KEYS))
    if value is None or not title or not store:
        return None
    return {
        "identity": _identity(record),
        "path": path,
        "timestamp": record.get("timestamp"),
        "store": str(store),
        "title": str(title),
        "price": price,
        "value": value,
        "tier": record.get("promotion_tier") or record.get("tier"),
        "url": record.get("url"),
        "ean": record.get("ean"),
        "mpn": record.get("mpn"),
        "sku": record.get("sku"),
        "configuration_key": record.get("configuration_key"),
    }


def _walk(value: Any, path: str = "$" ):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _explicit_ram_from_title(title: Any) -> float | None:
    text = str(title or "").lower()
    candidates = []
    patterns = (
        r"(?<!gddr)(\d{1,3})\s*gb\s*(?:ddr[345]|lpddr[345x]*|sodimm|so-dimm)\b",
        r"(?:ram|mem[oó]ria\s+ram)\s*[:=-]?\s*(\d{1,3})\s*gb\b",
        r"(\d{1,3})\s*gb\s*(?:ram)\b",
    )
    for pattern in patterns:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE):
            value = _float(raw)
            if value is not None:
                candidates.append(value)
    return max(candidates) if candidates else None


def _spec_suspicions(record: dict, path: str) -> list[dict]:
    specs = record.get("specs") if isinstance(record.get("specs"), dict) else record
    if not isinstance(specs, dict):
        return []

    title = record.get("titulo") or record.get("title") or ""
    store = record.get("loja") or record.get("store")
    url = record.get("url")
    gpu_type = str(specs.get("gpu_tipo") or "").lower()
    gpu_model = _norm_gpu(specs.get("gpu_modelo"))
    ram = _float(specs.get("ram_gb"))
    vram = _float(specs.get("vram_gb"))
    explicit_ram = _explicit_ram_from_title(title)
    out: list[dict] = []

    if explicit_ram is not None and ram is not None and abs(explicit_ram - ram) >= 0.5:
        out.append({
            "kind": "ram_title_mismatch",
            "path": path,
            "store": store,
            "title": title,
            "url": url,
            "ram_gb": ram,
            "explicit_title_ram_gb": explicit_ram,
        })

    expected_vram = KNOWN_LAPTOP_VRAM_GB.get(gpu_model)
    if gpu_type == "dedicada" and expected_vram is not None and vram is not None and abs(vram - expected_vram) >= 0.5:
        out.append({
            "kind": "known_gpu_vram_mismatch",
            "path": path,
            "store": store,
            "title": title,
            "url": url,
            "gpu_model": gpu_model,
            "vram_gb": vram,
            "expected_vram_gb": expected_vram,
            "ram_gb": ram,
        })

    if gpu_type == "dedicada" and ram is not None and vram is not None and ram >= 16 and abs(ram - vram) < 0.01:
        out.append({
            "kind": "ram_vram_equal_suspicious",
            "path": path,
            "store": store,
            "title": title,
            "url": url,
            "gpu_model": gpu_model or None,
            "ram_gb": ram,
            "vram_gb": vram,
        })

    return out


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    fraction = rank - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def audit(history: dict, matching: dict | None = None, price_history: dict | None = None) -> dict:
    observations: list[dict] = []
    suspects: list[dict] = []

    offers = history.get("offers", {}) if isinstance(history, dict) else {}
    if isinstance(offers, dict):
        for url, entries in offers.items():
            if not isinstance(entries, list):
                continue
            for index, record in enumerate(entries):
                if not isinstance(record, dict):
                    continue
                path = f"$.offers[{url!r}][{index}]"
                value_record = _value_record(record, path)
                if value_record:
                    observations.append(value_record)
                suspects.extend(_spec_suspicions(record, path))

    # matching_state contém o snapshot mais recente e pode revelar corrupção que
    # nunca chegou a gerar um alerta. Auditamo-lo separadamente, sem o misturar
    # na distribuição histórica de Value.
    if isinstance(matching, dict):
        for path, record in _walk(matching, "$.matching"):
            if isinstance(record, dict):
                suspects.extend(_spec_suspicions(record, path))

    best_by_identity: dict[str, dict] = {}
    for row in observations:
        current = best_by_identity.get(row["identity"])
        if current is None or row["value"] > current["value"]:
            best_by_identity[row["identity"]] = row

    unique = sorted(best_by_identity.values(), key=lambda row: row["value"], reverse=True)
    unique_values = [float(row["value"]) for row in unique]
    all_values = [float(row["value"]) for row in observations]
    threshold_counts = {
        str(threshold): sum(value >= threshold for value in unique_values)
        for threshold in (110, 115, 120, 122, 125)
    }
    tier_counts = Counter(str(row.get("tier") or "SEM_TIER").upper() for row in unique)
    suspect_counts = Counter(item["kind"] for item in suspects)

    price_series_count = 0
    if isinstance(price_history, dict):
        # Não assumimos schema interno; contamos séries com pelo menos um ponto.
        for _path, node in _walk(price_history, "$.price_history"):
            if isinstance(node, dict) and isinstance(node.get("points"), list) and node["points"]:
                price_series_count += 1

    return {
        "history_observations": len(observations),
        "unique_identities": len(unique),
        "price_history_series": price_series_count,
        "value_distribution_unique_best": {
            "max": round(max(unique_values), 3) if unique_values else None,
            "p90": round(_percentile(unique_values, 0.90), 3) if unique_values else None,
            "p95": round(_percentile(unique_values, 0.95), 3) if unique_values else None,
            "p99": round(_percentile(unique_values, 0.99), 3) if unique_values else None,
            "mean": round(sum(unique_values) / len(unique_values), 3) if unique_values else None,
            "threshold_counts": threshold_counts,
            "tier_counts": dict(sorted(tier_counts.items())),
        },
        "value_distribution_all_observations": {
            "count": len(all_values),
            "max": round(max(all_values), 3) if all_values else None,
        },
        "top10_unique_by_value": unique[:10],
        "suspect_counts": dict(sorted(suspect_counts.items())),
        "suspects": suspects[:200],
        "suspects_truncated": max(0, len(suspects) - 200),
    }


def _load(path: str | None) -> dict | None:
    if not path:
        return None
    file = Path(path)
    if not file.exists():
        return None
    value = json.loads(file.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita histórico, Value e incoerências do rastreador.")
    parser.add_argument("--history", default="data/history.json")
    parser.add_argument("--matching", default="data/matching_state.json")
    parser.add_argument("--price-history", default="data/price_history.json")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    history = _load(args.history) or {}
    report = audit(history, _load(args.matching), _load(args.price_history))
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True)
    print("HISTORY_AUDIT_JSON=" + payload)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
