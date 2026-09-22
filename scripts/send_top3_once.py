"""Send one explicit Top 3 notification for the 2026-09-22 request.

The production workflow always invokes this helper, so the send is guarded by
both the GitHub event and the exact triggering commit subject.  Scheduled runs
and every other push remain no-ops.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

from curl_cffi import requests


_TRIGGER_SUBJECT = "ops: one-shot current top3 2026-09-22"
_HISTORY = Path("data/history.json")


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trigger_subject() -> str:
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if not sha:
        return ""
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%s", sha],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _effective(entry: dict) -> tuple[float, float, str]:
    promotion_confirmed = (
        entry.get("promotion_price_live_confirmed") is True
        and float(entry.get("promotion_discount_eur") or 0.0) > 0.0
    )
    value = entry.get("effective_value_score")
    price = entry.get("effective_price")
    tier = entry.get("effective_tier")
    if value is None:
        value = entry.get("promotion_value_score") if promotion_confirmed else entry.get("value_score")
    if price is None:
        price = entry.get("promotion_checkout_price") if promotion_confirmed else entry.get("price")
    if not tier:
        tier = entry.get("promotion_tier") if promotion_confirmed else entry.get("tier")
    return float(value or 0.0), float(price or 0.0), str(tier or "—")


def _current_top3(data: dict) -> list[dict]:
    runs = (data.get("learning", {}) or {}).get("runs", []) or []
    latest_run = max(
        (run for run in runs if isinstance(run, dict) and _parse_time(run.get("timestamp"))),
        key=lambda run: _parse_time(run.get("timestamp")),
        default=None,
    )
    if latest_run is None:
        raise RuntimeError("Sem run recente no histórico")

    run_time = _parse_time(latest_run.get("timestamp"))
    runtime = float(latest_run.get("runtime_seconds") or 0.0)
    window = timedelta(seconds=max(1800.0, runtime + 600.0))
    cutoff = run_time - window
    ceiling = run_time + timedelta(minutes=5)

    latest_by_url: dict[str, dict] = {}
    offers = data.get("offers", {}) if isinstance(data.get("offers"), dict) else {}
    for entries in offers.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            stamp = _parse_time(entry.get("timestamp"))
            url = str(entry.get("url") or "").strip()
            if not stamp or not url or stamp < cutoff or stamp > ceiling:
                continue
            previous = latest_by_url.get(url)
            previous_stamp = _parse_time(previous.get("timestamp")) if previous else None
            if previous is None or previous_stamp is None or stamp >= previous_stamp:
                latest_by_url[url] = entry

    ranked = []
    for entry in latest_by_url.values():
        value, price, tier = _effective(entry)
        if value <= 0 or price <= 0:
            continue
        ranked.append(
            {
                "titulo": str(entry.get("titulo") or "Portátil"),
                "loja": str(entry.get("loja") or "—"),
                "url": str(entry.get("url") or ""),
                "value": value,
                "price": price,
                "tier": tier,
            }
        )
    ranked.sort(key=lambda row: (row["value"], -row["price"]), reverse=True)
    if len(ranked) < 3:
        raise RuntimeError(f"A run atual só produziu {len(ranked)} ofertas elegíveis para Top 3")
    return ranked[:3]


def main() -> None:
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or _trigger_subject() != _TRIGGER_SUBJECT:
        print("TOP3 one-shot: inactive for this run")
        return

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise SystemExit("NTFY_TOPIC vazio")

    data = json.loads(_HISTORY.read_text(encoding="utf-8"))
    top3 = _current_top3(data)
    lines = []
    for index, row in enumerate(top3, start=1):
        lines.extend(
            [
                f"{index}. {row['titulo']}",
                f"{row['loja']} | {row['price']:.2f}€ | Value {row['value']:.1f} | {row['tier']}",
                row["url"],
            ]
        )
    payload = {
        "topic": topic,
        "title": "🏆 LapIntel PT — Top 3 atual",
        "message": "\n".join(lines),
        "priority": 4,
        "tags": ["computer", "trophy"],
    }
    response = requests.post("https://ntfy.sh", json=payload, timeout=12)
    response.raise_for_status()
    body = response.json()
    message_id = str(body.get("id") or "").strip()
    if not message_id:
        raise SystemExit("NTFY aceitou o pedido mas não devolveu id de mensagem")
    print(f"TOP3 one-shot enviado | id={message_id} | status={response.status_code}")
    for index, row in enumerate(top3, start=1):
        print(
            f"TOP3 #{index} | {row['loja']} | {row['price']:.2f}€ | "
            f"Value {row['value']:.1f} | {row['tier']} | {row['titulo']}"
        )


if __name__ == "__main__":
    main()
