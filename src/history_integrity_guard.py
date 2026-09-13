from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import historical_guard


# Casos auditados contra o fabricante/retalhistas independentes. A página RP
# publicou hardware incompatível com o EAN exato; não substituímos por specs
# "prováveis": removemos a oferta dessa fonte e obrigamos nova evidência futura.
KNOWN_INVALID_TECHNICAL_OFFERS = {
    "https://www.radiopopular.pt/produto/pc-portatil-lenovo-ideapad-s3-15iwc11-169": {
        "ean": "0199276826169",
        "reason": "EAN exato corresponde a Intel Core 7 350; ficha RP foi guardada como Ryzen AI 7 350",
    },
}

_PRICE_CONFLICT_PREFIX = "sinais de preço divergentes na ficha"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price_conflict_references(spec: dict) -> list[float]:
    values: list[float] = []
    for raw in spec.get("conflitos") or []:
        text = str(raw or "")
        if _PRICE_CONFLICT_PREFIX not in text.lower():
            continue
        for token in re.findall(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*€", text):
            try:
                values.append(float(token.replace(",", ".")))
            except ValueError:
                continue
    return values


def corruption_reason(url: str, record: dict) -> str | None:
    known = KNOWN_INVALID_TECHNICAL_OFFERS.get(str(url))
    if known:
        expected = "".join(ch for ch in str(known.get("ean") or "") if ch.isdigit())
        actual = "".join(ch for ch in str(record.get("ean") or "") if ch.isdigit())
        if not expected or actual == expected:
            return f"known_technical_conflict:{known['reason']}"

    raw_price = _number(record.get("price"))
    spec = record.get("specs") if isinstance(record.get("specs"), dict) else {}
    references = _price_conflict_references(spec)
    if raw_price is not None and references:
        reference = min(references)
        gap = reference - raw_price
        # Ex.: 295€ no cartão contra 749/799€ na ficha. Não apaga casos normais
        # como 1599€ atual vs 1699€ antigo/PVPR.
        if gap >= 100.0 and raw_price <= reference * 0.75:
            return f"price_conflict:{raw_price:.2f}<{reference:.2f}"

    confirmed = _number(spec.get("price_confirmed"))
    if raw_price is not None and confirmed is not None:
        gap = abs(confirmed - raw_price)
        tolerance = max(35.0, raw_price * 0.05)
        if gap >= tolerance:
            return f"confirmed_price_conflict:{raw_price:.2f}!={confirmed:.2f}"
    return None


def repair_history_data(history: dict) -> tuple[dict, list[dict]]:
    """Remove só registos com corrupção de alta confiança; preserva o resto."""
    out = json.loads(json.dumps(history)) if isinstance(history, dict) else {}
    offers = out.get("offers") if isinstance(out.get("offers"), dict) else {}
    removed: list[dict] = []
    for url in list(offers):
        entries = offers.get(url)
        if not isinstance(entries, list):
            continue
        clean = []
        for record in entries:
            if not isinstance(record, dict):
                clean.append(record)
                continue
            reason = corruption_reason(str(url), record)
            if reason:
                removed.append({
                    "url": str(url),
                    "title": record.get("titulo"),
                    "store": record.get("loja"),
                    "ean": record.get("ean"),
                    "timestamp": record.get("timestamp"),
                    "price": record.get("price"),
                    "reason": reason,
                })
            else:
                clean.append(record)
        if clean:
            offers[url] = clean
        else:
            offers.pop(url, None)
    out["offers"] = offers
    return out, removed


def rebuild_price_history(history: dict) -> dict:
    """Reconstrói os 90 dias exclusivamente a partir de observações não corrompidas."""
    state = {"schema_version": historical_guard.SCHEMA_VERSION, "updated_at": None, "identities": {}}
    offers = history.get("offers") if isinstance(history.get("offers"), dict) else {}
    rows: list[tuple[str, dict]] = []
    for url, entries in offers.items():
        if not isinstance(entries, list):
            continue
        for record in entries:
            if isinstance(record, dict):
                rows.append((str(url), record))
    rows.sort(key=lambda pair: str(pair[1].get("timestamp") or ""))

    for url, record in rows:
        price = _number(record.get("price"))
        if price is None or price <= 0:
            continue
        item = {
            "url": url,
            "loja": record.get("loja"),
            "titulo": record.get("titulo"),
            "ean": record.get("ean"),
            "mpn": record.get("mpn"),
        }
        historical_guard.observe(
            state,
            item,
            price,
            observed_at=str(record.get("timestamp") or "") or None,
        )
    state = historical_guard.compact(state)
    state["updated_at"] = historical_guard.now_iso()
    return state


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def repair_files(history_path: Path, price_history_path: Path) -> list[dict]:
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    repaired, removed = repair_history_data(history)
    if removed:
        _save(history_path, repaired)
        _save(price_history_path, rebuild_price_history(repaired))
    return removed


def install(tracker_module) -> None:
    """Limpa corrupção antes do runtime e impede-a de voltar via merge de estado."""
    if getattr(tracker_module, "_HISTORY_INTEGRITY_GUARD_INSTALLED", False):
        return
    base_main = tracker_module.main
    base_merge_history = tracker_module.merge_history

    def merge_history(current: dict, run_state: dict) -> dict:
        merged = base_merge_history(current, run_state)
        repaired, _removed = repair_history_data(merged)
        return repaired

    def main():
        removed = repair_files(tracker_module.HISTORY_PATH, historical_guard.PRICE_HISTORY_PATH)
        if removed:
            tracker_module.LOGGER.warning(
                "Integridade histórica | removidos=%d | urls=%d | histórico de preços reconstruído",
                len(removed), len({row['url'] for row in removed}),
            )
            for row in removed[:8]:
                tracker_module.LOGGER.warning(
                    "Histórico removido | %s | %s | %s",
                    row.get("store"), row.get("title"), row.get("reason"),
                )
        return base_main()

    tracker_module.merge_history = merge_history
    tracker_module.main = main
    tracker_module._HISTORY_INTEGRITY_GUARD_INSTALLED = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repara histórico e histórico de preços de forma conservadora.")
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--price-history", type=Path, required=True)
    args = parser.parse_args(argv)
    removed = repair_files(args.history, args.price_history)
    print(json.dumps({"removed": len(removed), "records": removed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
