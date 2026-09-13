"""Reenvia uma única vez todos os DIAMANTE da run mais recente, sem limpar histórico."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import promotion_value_guard

REQUEST_ID = "pedro-diamonds-replay-2026-09-13-v1"
STATE_PATH = ROOT / "data/diamonds_notification.json"


def timestamp(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def current_diamonds(history, settings, now=None):
    now = now or datetime.now(timezone.utc)
    runs = (history.get("learning", {}) or {}).get("runs", []) or []
    if not runs:
        raise ValueError("Execução atual ausente")
    run = runs[-1]
    finished = timestamp(run["timestamp"])
    if not timedelta(0) <= now - finished <= timedelta(hours=1):
        raise ValueError("Execução atual ausente ou desatualizada")
    started = finished - timedelta(seconds=float(run.get("runtime_seconds") or 0) + 5)
    threshold = float(settings.get("diamante_value_min", 120.0))
    budget_hard = float(settings.get("budget_hard", 1500.0))
    budget_min = float(settings.get("preco_minimo_global", 250.0))

    choices = {}
    for entries in history.get("offers", {}).values():
        if not entries:
            continue
        row = max(entries, key=lambda r: r.get("timestamp", ""))
        if timestamp(row["timestamp"]) < started or row.get("stock") is False:
            continue

        promo = bool(row.get("promotion_price_live_confirmed")) and any(
            promotion_value_guard.is_active(p) for p in row.get("promotions", [])
        )
        raw_price = row.get("promotion_checkout_price") if promo else row.get("price")
        raw_value = row.get("promotion_value_score") if promo else row.get("value_score")
        if raw_price is None or raw_value is None:
            continue
        price = float(raw_price)
        value = float(raw_value)

        # Política pedida: acima de 120 é sempre DIAMANTE, independentemente de
        # qualquer tier auxiliar guardado no histórico.
        if value <= threshold or not budget_min <= price <= budget_hard:
            continue

        result = {
            "title": row.get("titulo") or row.get("title") or "Portátil",
            "store": row.get("loja") or "Loja",
            "url": row.get("url") or "",
            "price": price,
            "value": value,
            "tier": "DIAMANTE",
            "promotion": promo,
            "observed_at": row["timestamp"],
        }
        identity = row.get("configuration_key") or row.get("ean") or row.get("mpn") or row.get("url")
        old = choices.get(identity)
        if old is None or (value, -price) > (old["value"], -old["price"]):
            choices[identity] = result

    return sorted(choices.values(), key=lambda r: (-r["value"], r["price"], r["url"]))


def persist(data, message):
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for args in (
        ["git", "add", str(STATE_PATH.relative_to(ROOT))],
        ["git", "commit", "-m", message + " [skip ci]"],
        ["git", "push", "origin", "HEAD:main"],
    ):
        subprocess.run(args, cwd=ROOT, check=True)


def main():
    previous = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    if previous.get("request_id") == REQUEST_ID:
        print("DIAMONDS_ONCE: já processado; nenhum novo envio")
        return previous

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise ValueError("NTFY_TOPIC ausente")

    settings = json.loads((ROOT / "config/config.json").read_text(encoding="utf-8"))["settings"]
    history = json.loads((ROOT / "data/history.json").read_text(encoding="utf-8"))
    rows = current_diamonds(history, settings)
    state = {
        "request_id": REQUEST_ID,
        "status": "reserved",
        "count": len(rows),
        "diamonds": rows,
        "reserved_at": datetime.now(timezone.utc).isoformat(),
    }
    persist(state, "chore: reservar reenvio único de diamantes")

    from curl_cffi import requests

    receipts = []
    for index, row in enumerate(rows, 1):
        price_label = "Checkout promo" if row["promotion"] else "Preço"
        message = (
            f"{row['store']}\n"
            f"{price_label}: {row['price']:.2f}€\n"
            f"Value: {row['value']:.1f} | Tier: DIAMANTE\n"
            f"{row['url']}"
        )
        response = requests.post(
            "https://ntfy.sh",
            json={
                "topic": topic,
                "title": f"💎 DIAMANTE | {row['title']}",
                "message": message,
                "priority": 4,
                "tags": ["gem", "computer"],
            },
            timeout=25,
            allow_redirects=False,
        )
        response.raise_for_status()
        receipt = response.json()
        notification_id = str(receipt.get("id") or "").strip()
        if not notification_id:
            raise ValueError(f"NTFY sem comprovativo no DIAMANTE {index}")
        receipts.append({"index": index, "notification_id": notification_id, "url": row["url"]})
        print(f"DIAMOND_SENT {index}/{len(rows)} id={notification_id} value={row['value']:.1f} {row['store']}")

    state.update(
        status="sent",
        receipts=receipts,
        sent_at=datetime.now(timezone.utc).isoformat(),
    )
    persist(state, "chore: confirmar reenvio único de diamantes")
    print("DIAMONDS_ONCE_SENT " + json.dumps({"count": len(rows), "receipts": receipts}, ensure_ascii=False))
    return state


if __name__ == "__main__":
    main()
