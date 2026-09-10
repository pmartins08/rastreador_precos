from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from version import STATE_EPOCH, VERSION


ROOT = Path(__file__).resolve().parent.parent
TOP5_PATH = ROOT / "data" / "top5_current.json"
SCHEMA_VERSION = 1


def _load(path: Path | None = None) -> dict:
    path = path or TOP5_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(value: dict, path: Path | None = None) -> None:
    path = path or TOP5_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _age_hours(value: object, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - stamp).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def _latest_current_entries(history: dict, ttl_hours: float, now: datetime | None = None) -> list[dict]:
    if history.get("state_epoch") != STATE_EPOCH:
        return []
    rows: list[dict] = []
    for entries in (history.get("offers", {}) or {}).values():
        if not isinstance(entries, list):
            continue
        current = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("tracker_version") == VERSION
        ]
        if not current:
            continue
        entry = current[-1]
        age = _age_hours(entry.get("timestamp"), now=now)
        if age is None or age > ttl_hours or entry.get("stock") is False:
            continue
        try:
            price = float(entry.get("price"))
            value = float(entry.get("value_score"))
            ranking = float(entry.get("score_ranking"))
        except (TypeError, ValueError):
            continue
        if not entry.get("titulo") or not entry.get("url"):
            continue
        row = dict(entry)
        row["price"] = price
        row["value_score"] = value
        row["score_ranking"] = ranking
        rows.append(row)
    return rows


def build_current_top5(
    tracker_module,
    *,
    ttl_hours: float = 26.0,
    now: datetime | None = None,
) -> list[dict]:
    """Top 5 do estado atual, não apenas do conjunto observado numa única run.

    Agrega observações da versão pública atual ainda frescas no histórico. A
    mesma configuração exata aparece uma única vez e é representada pela melhor
    oferta atualmente conhecida.
    """
    history = tracker_module.load_json(tracker_module.HISTORY_PATH)
    rows = _latest_current_entries(history, max(1.0, float(ttl_hours)), now=now)

    by_configuration: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("configuration_key") or row.get("url"))
        previous = by_configuration.get(key)
        if previous is None:
            by_configuration[key] = row
            continue
        current_rank = (float(row["value_score"]), -float(row["price"]))
        previous_rank = (float(previous["value_score"]), -float(previous["price"]))
        if current_rank > previous_rank:
            by_configuration[key] = row

    ordered = sorted(
        by_configuration.values(),
        key=lambda row: (
            -float(row.get("value_score", 0.0)),
            -float(row.get("score_ranking", 0.0)),
            float(row.get("price", 99999.0)),
            str(row.get("titulo", "")),
        ),
    )[:5]

    out: list[dict] = []
    for index, row in enumerate(ordered, start=1):
        specs = row.get("specs") if isinstance(row.get("specs"), dict) else {}
        out.append(
            {
                "rank": index,
                "configuration_key": row.get("configuration_key") or row.get("url"),
                "title": row.get("titulo"),
                "store": row.get("loja"),
                "price": round(float(row.get("price")), 2),
                "value_score": round(float(row.get("value_score")), 1),
                "score_ranking": round(float(row.get("score_ranking")), 1),
                "tier": row.get("tier"),
                "url": row.get("url"),
                "ean": row.get("ean"),
                "mpn": row.get("mpn"),
                "cpu": specs.get("cpu_modelo"),
                "gpu": specs.get("gpu_modelo") or specs.get("gpu_tipo"),
                "ram_gb": specs.get("ram_gb"),
                "storage_tb": specs.get("armazenamento_tb"),
                "keyboard_pt": specs.get("teclado_pt"),
                "observed_at": row.get("timestamp"),
            }
        )
    return out


def _notification_key(item: dict) -> str:
    return str(item.get("configuration_key") or item.get("url") or item.get("title"))


def _notify_item(tracker_module, item: dict) -> bool:
    rank = int(item.get("rank", 0))
    tier = str(item.get("tier") or "SEM TIER")
    title = str(item.get("title") or "Portátil")
    message = (
        f"TOP {rank} ATUAL — mercado V{VERSION}\n"
        f"{title}\n"
        f"Loja: {item.get('store')} | Preço: {float(item.get('price', 0)):.2f}€\n"
        f"Value: {float(item.get('value_score', 0)):.1f} | Rank: {float(item.get('score_ranking', 0)):.1f} | Tier: {tier}\n"
        f"GPU: {item.get('gpu') or '?'} | CPU: {item.get('cpu') or '?'}\n"
        f"RAM: {item.get('ram_gb') or '?'}GB | SSD: {item.get('storage_tb') or '?'}TB\n"
        f"{item.get('url')}"
    )
    return tracker_module.ntfy_send(
        f"🏆 Top {rank} atual — {tier}",
        message,
        priority=4 if rank <= 3 else 3,
        tags=["trophy", "computer"],
    )


def persist_and_notify(tracker_module, run: dict | None = None) -> dict:
    config = tracker_module.load_json(tracker_module.CONFIG_PATH)
    settings = config.get("settings", {}) if isinstance(config, dict) else {}
    ttl_hours = float(settings.get("top5_current_ttl_hours", 26.0))
    items = build_current_top5(tracker_module, ttl_hours=ttl_hours)

    previous = _load()
    campaigns = (
        dict(previous.get("notification_campaigns") or {})
        if previous.get("state_epoch") == STATE_EPOCH
        else {}
    )
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "state_epoch": STATE_EPOCH,
        "tracker_version": VERSION,
        "generated_at": tracker_module.now_iso(),
        "ttl_hours": ttl_hours,
        "definition": "top 5 de configurações atuais agregadas de observações frescas; não top 5 isolado da run",
        "items": items,
        "notification_campaigns": campaigns,
    }

    sent_now = 0
    release = str(settings.get("top5_notify_once_version") or "").strip()
    if release and release == VERSION and items:
        campaign = snapshot["notification_campaigns"].setdefault(
            release,
            {"sent_keys": [], "complete": False, "started_at": tracker_module.now_iso()},
        )
        sent_keys = set(campaign.get("sent_keys") or [])
        for item in items:
            key = _notification_key(item)
            if key in sent_keys:
                continue
            if _notify_item(tracker_module, item):
                sent_keys.add(key)
                sent_now += 1
                campaign["sent_keys"] = sorted(sent_keys)
                campaign["last_sent_at"] = tracker_module.now_iso()
                _save(snapshot)
        current_keys = {_notification_key(item) for item in items}
        campaign["complete"] = len(items) >= 5 and current_keys.issubset(sent_keys)
        if campaign["complete"]:
            campaign["completed_at"] = tracker_module.now_iso()

    _save(snapshot)

    if isinstance(run, dict):
        run["top5_current_count"] = len(items)
        run["top5_notifications_sent"] = sent_now
        run["top5_snapshot_at"] = snapshot["generated_at"]
        try:
            history = tracker_module.load_json(tracker_module.HISTORY_PATH)
            runs = (history.get("learning", {}) or {}).get("runs", [])
            if runs and isinstance(runs[-1], dict):
                runs[-1].update(
                    {
                        "top5_current_count": len(items),
                        "top5_notifications_sent": sent_now,
                        "top5_snapshot_at": snapshot["generated_at"],
                    }
                )
                tracker_module.save_json(tracker_module.HISTORY_PATH, history)
        except Exception:
            tracker_module.LOGGER.warning("Top5 guardou snapshot mas não anexou métricas à run")
    return snapshot


def install(tracker_module) -> None:
    if getattr(tracker_module, "_TOP5_GUARD_INSTALLED", False):
        return
    base_main = tracker_module.main

    def main():
        run = base_main()
        snapshot = persist_and_notify(tracker_module, run if isinstance(run, dict) else None)
        tracker_module.LOGGER.info(
            "Top5 atual | itens=%d | notificações_nesta_run=%d | snapshot=%s",
            len(snapshot.get("items", [])),
            int((run or {}).get("top5_notifications_sent", 0)) if isinstance(run, dict) else 0,
            TOP5_PATH.name,
        )
        return run

    tracker_module.main = main
    tracker_module._TOP5_GUARD_INSTALLED = True
