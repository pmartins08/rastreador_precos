"""Resumo solicitado pelo utilizador; reserva persistente antes de um único POST."""
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


def timestamp(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def top3(history, settings, now=None):
    now = now or datetime.now(timezone.utc)
    run = history["learning"]["runs"][-1]
    finished = timestamp(run["timestamp"])
    if not timedelta(0) <= now - finished <= timedelta(hours=1):
        raise ValueError("Execução atual ausente ou desatualizada")
    started = finished - timedelta(seconds=float(run["runtime_seconds"]) + 5)
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
        tier = row.get("promotion_tier") if promo else row.get("tier")
        if tier not in {"OURO", "DIAMANTE"}:
            continue
        price = float(row.get("promotion_checkout_price") if promo else row["price"])
        value = float(row.get("promotion_value_score") if promo else row["value_score"])
        if not 250 <= price <= float(settings.get("budget_hard", 1500)):
            continue
        result = {"title": row["titulo"], "store": row["loja"], "url": row["url"],
                  "price": price, "value": value, "tier": tier, "promotion": promo,
                  "observed_at": row["timestamp"]}
        identity = row.get("configuration_key") or row.get("ean") or row["url"]
        old = choices.get(identity)
        if old is None or (value, -price) > (old["value"], -old["price"]):
            choices[identity] = result
    rows = sorted(choices.values(), key=lambda r: (-r["value"], r["price"], r["url"]))[:3]
    if len(rows) != 3:
        raise ValueError(f"Só existem {len(rows)} oportunidades atuais Ouro/Diamante")
    return rows


def persist(path, data, message):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    for args in (["git", "add", str(path.relative_to(ROOT))],
                 ["git", "commit", "-m", message + " [skip ci]"],
                 ["git", "push", "origin", "HEAD:main"]):
        subprocess.run(args, cwd=ROOT, check=True)


def main():
    settings = json.loads((ROOT / "config/config.json").read_text())["settings"]
    request_id = settings.get("top3_once_request_id")
    path = ROOT / "data/top3_notification.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    if not request_id or previous.get("request_id") == request_id:
        print("TOP3_ONCE: já processado; nenhum novo envio")
        return
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise ValueError("NTFY_TOPIC ausente")
    rows = top3(json.loads((ROOT / "data/history.json").read_text()), settings)
    state = {"request_id": request_id, "status": "reserved", "top3": rows,
             "reserved_at": datetime.now(timezone.utc).isoformat()}
    # Se o processo falhar após o POST, a reserva impede um envio duplicado.
    persist(path, state, "chore: reservar resumo Top 3 solicitado")
    message = "\n\n".join(
        f"{i}. {r['tier']} | {r['title']}\n{r['store']} | "
        f"{'Checkout promo' if r['promotion'] else 'Preço'}: {r['price']:.2f}€ | "
        f"Value: {r['value']:.1f}\n{r['url']}"
        for i, r in enumerate(rows, 1)
    )
    from curl_cffi import requests
    response = requests.post("https://ntfy.sh", json={"topic": topic,
        "title": "Top 3 atual — resumo único", "message": message,
        "priority": 3, "tags": ["computer", "trophy"]}, timeout=25, allow_redirects=False)
    response.raise_for_status()
    receipt = response.json()
    if not receipt.get("id"):
        raise ValueError("NTFY não devolveu comprovativo")
    state.update(status="sent", notification_id=receipt["id"],
                 sent_at=datetime.now(timezone.utc).isoformat())
    persist(path, state, "chore: confirmar envio único do Top 3")
    print("TOP3_ONCE_SENT " + json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
