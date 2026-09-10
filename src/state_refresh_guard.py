from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from version import STATE_EPOCH, VERSION


ROOT = Path(__file__).resolve().parent.parent
PRICE_HISTORY_PATH = ROOT / "data" / "price_history.json"
TOP5_PATH = ROOT / "data" / "top5_current.json"
EPOCH_PATH = ROOT / "data" / "state_epoch.json"
_REFRESH_ACTIVE = False


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def refresh_required(tracker_module) -> bool:
    history = tracker_module.load_json(tracker_module.HISTORY_PATH)
    epoch = _load(EPOCH_PATH)
    return history.get("state_epoch") != STATE_EPOCH or epoch.get("state_epoch") != STATE_EPOCH


def _reset_price_history() -> None:
    _save(
        PRICE_HISTORY_PATH,
        {"schema_version": 1, "updated_at": None, "identities": {}},
    )


def _reset_top5() -> None:
    _save(
        TOP5_PATH,
        {
            "schema_version": 1,
            "state_epoch": STATE_EPOCH,
            "tracker_version": VERSION,
            "generated_at": None,
            "ttl_hours": None,
            "items": [],
            "notification_campaigns": {},
        },
    )


def _prune_history_to_current_version(tracker_module) -> dict:
    raw = tracker_module.load_json(tracker_module.HISTORY_PATH)
    out = tracker_module._history_base()
    out["tracker_version"] = VERSION
    out["state_epoch"] = STATE_EPOCH

    for key, entries in (raw.get("offers", {}) or {}).items():
        if not isinstance(entries, list):
            continue
        current = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("tracker_version") == VERSION
        ]
        if current:
            out["offers"][key] = current[-3:]

    alerts = raw.get("alert_state", {}) if isinstance(raw.get("alert_state"), dict) else {}
    active_urls = set(out["offers"])
    out["alert_state"] = {
        key: value
        for key, value in alerts.items()
        if isinstance(value, dict)
        and (key in active_urls or str(key).startswith("cross_store:"))
    }

    runs = [
        run
        for run in ((raw.get("learning", {}) or {}).get("runs", []) or [])
        if isinstance(run, dict) and run.get("runner_version") == VERSION
    ]
    out["learning"]["runs"] = runs[-8:]
    # A aprendizagem HTTP real vive em access_learning.json e é preservada. O
    # agregado antigo de análises por loja no history não é necessário após refresh.
    out["learning"]["stores"] = {}
    tracker_module.save_json(tracker_module.HISTORY_PATH, out)
    return out


def install(tracker_module) -> None:
    """Executa um refresh analítico único quando muda a época de estado.

    O refresh preserva `access_learning.json`, usa o estado anterior apenas como
    bootstrap durante a primeira run e, depois de recalcular, elimina do estado
    persistente ofertas/runs de versões anteriores. O histórico de preços reinicia
    apenas quando o `STATE_EPOCH` muda, independentemente da versão pública.
    """
    if getattr(tracker_module, "_STATE_REFRESH_GUARD_INSTALLED", False):
        return

    base_main = tracker_module.main
    base_compact_history = tracker_module.compact_history
    base_merge_history = tracker_module.merge_history
    base_maybe_alert = tracker_module.maybe_alert
    base_maybe_alert_cross_store = tracker_module.maybe_alert_cross_store

    def compact_history(history: dict, *args, **kwargs):
        out = base_compact_history(history, *args, **kwargs)
        if isinstance(history, dict) and history.get("state_epoch"):
            out["state_epoch"] = history["state_epoch"]
        return out

    def merge_history(current: dict, run_state: dict) -> dict:
        # Primeira persistência do novo epoch: o estado antigo nunca volta a entrar
        # pelo merge concorrente do GitHub Actions.
        if run_state.get("state_epoch") == STATE_EPOCH and current.get("state_epoch") != STATE_EPOCH:
            out = compact_history(run_state)
            out["state_epoch"] = STATE_EPOCH
            return out
        out = base_merge_history(current, run_state)
        if current.get("state_epoch") == STATE_EPOCH or run_state.get("state_epoch") == STATE_EPOCH:
            out["state_epoch"] = STATE_EPOCH
        return out

    def maybe_alert(history, item, spec, assessment, tier, previous, alert_key, settings):
        if not _REFRESH_ACTIVE:
            return base_maybe_alert(
                history, item, spec, assessment, tier, previous, alert_key, settings
            )
        # Durante refresh não enviamos a cascata de "primeira oportunidade". O
        # estado fica semeado para as runs seguintes e o Top5 Guard envia apenas
        # as notificações configuradas para a campanha atual.
        if (
            tier
            and item.get("stock") is not False
            and float(assessment.get("value_score", 0.0))
            >= float(settings.get("min_value_score_alerta", 70.0))
        ):
            history.setdefault("alert_state", {})[alert_key] = {
                "timestamp": tracker_module.now_iso(),
                "price": item.get("preco"),
                "value_score": assessment.get("value_score"),
                "tier": tier,
                "seeded_by_refresh": STATE_EPOCH,
            }
        return False, False

    def maybe_alert_cross_store(history, group, settings):
        if not _REFRESH_ACTIVE:
            return base_maybe_alert_cross_store(history, group, settings)
        offers = group.get("offers", [])
        if len(offers) >= 2:
            best = offers[0]
            history.setdefault("alert_state", {})[
                f"cross_store:{group.get('configuration_key')}"
            ] = {
                "timestamp": tracker_module.now_iso(),
                "best_store": best.get("loja"),
                "best_price": best.get("price"),
                "spread_eur": group.get("spread_eur", 0.0),
                "seeded_by_refresh": STATE_EPOCH,
            }
        return False

    def main():
        global _REFRESH_ACTIVE
        do_refresh = refresh_required(tracker_module)
        if do_refresh:
            tracker_module.LOGGER.info(
                "Refresh de estado | epoch=%s | histórico de preços reiniciado | cache legado apenas bootstrap",
                STATE_EPOCH,
            )
            _reset_price_history()
            _reset_top5()
            _REFRESH_ACTIVE = True
        try:
            run = base_main()
        finally:
            _REFRESH_ACTIVE = False

        if do_refresh:
            cleaned = _prune_history_to_current_version(tracker_module)
            _save(
                EPOCH_PATH,
                {
                    "state_epoch": STATE_EPOCH,
                    "tracker_version": VERSION,
                    "refreshed_at": tracker_module.now_iso(),
                    "offers_after_refresh": len(cleaned.get("offers", {})),
                },
            )
            if isinstance(run, dict):
                run["state_refresh"] = True
                run["state_epoch"] = STATE_EPOCH
                run["offers_after_refresh"] = len(cleaned.get("offers", {}))
                # O tracker já tinha guardado a run antes da poda. Atualizamos a
                # run sobrevivente para manter a métrica visível no histórico novo.
                latest = tracker_module.load_json(tracker_module.HISTORY_PATH)
                runs = (latest.get("learning", {}) or {}).get("runs", [])
                if runs and isinstance(runs[-1], dict):
                    runs[-1].update(
                        {
                            "state_refresh": True,
                            "state_epoch": STATE_EPOCH,
                            "offers_after_refresh": len(cleaned.get("offers", {})),
                        }
                    )
                    tracker_module.save_json(tracker_module.HISTORY_PATH, latest)
        return run

    tracker_module.compact_history = compact_history
    tracker_module.merge_history = merge_history
    tracker_module.maybe_alert = maybe_alert
    tracker_module.maybe_alert_cross_store = maybe_alert_cross_store
    tracker_module.main = main
    tracker_module._STATE_REFRESH_GUARD_INSTALLED = True
