from __future__ import annotations

import json
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

import state_refresh_guard
from version import STATE_EPOCH, VERSION


class StateRefreshGuardTests(unittest.TestCase):
    def test_refresh_prunes_legacy_analysis_and_resets_price_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_paths = (
                state_refresh_guard.PRICE_HISTORY_PATH,
                state_refresh_guard.TOP5_PATH,
                state_refresh_guard.EPOCH_PATH,
            )
            state_refresh_guard.PRICE_HISTORY_PATH = root / "price_history.json"
            state_refresh_guard.TOP5_PATH = root / "top5_current.json"
            state_refresh_guard.EPOCH_PATH = root / "state_epoch.json"
            try:
                history_path = root / "history.json"
                history_path.write_text(
                    json.dumps(
                        {
                            "tracker_version": "8.8.7",
                            "offers": {
                                "old": [
                                    {
                                        "tracker_version": "8.8.7",
                                        "timestamp": "2026-09-08T10:00:00Z",
                                        "url": "https://old.test/laptop",
                                    }
                                ]
                            },
                            "alert_state": {"old": {"tier": "OURO"}},
                            "learning": {"runs": [{"runner_version": "8.8.7"}], "stores": {"x": 1}},
                        }
                    ),
                    encoding="utf-8",
                )
                state_refresh_guard.PRICE_HISTORY_PATH.write_text(
                    json.dumps({"schema_version": 1, "identities": {"ean:old": {"days": {"2026-09-08": {}}}}}),
                    encoding="utf-8",
                )

                def load_json(path):
                    try:
                        return json.loads(Path(path).read_text(encoding="utf-8"))
                    except FileNotFoundError:
                        return {}

                def save_json(path, value):
                    Path(path).write_text(json.dumps(value), encoding="utf-8")

                module = types.SimpleNamespace()
                module.HISTORY_PATH = history_path
                module.load_json = load_json
                module.save_json = save_json
                module.now_iso = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                module.LOGGER = types.SimpleNamespace(info=lambda *args, **kwargs: None)
                module._history_base = lambda: {
                    "schema_version": 8,
                    "tracker_version": VERSION,
                    "offers": {},
                    "alert_state": {},
                    "learning": {"runs": [], "stores": {}},
                }
                module.compact_history = lambda history, *args, **kwargs: dict(history)
                module.merge_history = lambda current, run_state: dict(run_state)
                module.maybe_alert = lambda *args, **kwargs: (True, False)
                module.maybe_alert_cross_store = lambda *args, **kwargs: True

                def base_main():
                    history = load_json(history_path)
                    history.setdefault("offers", {})["new"] = [
                        {
                            "tracker_version": VERSION,
                            "timestamp": module.now_iso(),
                            "url": "https://new.test/laptop",
                            "titulo": "ASUS TUF novo",
                        }
                    ]
                    history.setdefault("learning", {}).setdefault("runs", []).append(
                        {"runner_version": VERSION, "timestamp": module.now_iso()}
                    )
                    save_json(history_path, history)
                    return {"runner_version": VERSION}

                module.main = base_main
                state_refresh_guard.install(module)
                run = module.main()

                cleaned = load_json(history_path)
                self.assertEqual(cleaned["state_epoch"], STATE_EPOCH)
                self.assertEqual(set(cleaned["offers"]), {"new"})
                self.assertTrue(all(entry["tracker_version"] == VERSION for entry in cleaned["offers"]["new"]))
                self.assertEqual(cleaned["learning"]["stores"], {})
                self.assertTrue(run["state_refresh"])

                prices = load_json(state_refresh_guard.PRICE_HISTORY_PATH)
                self.assertEqual(prices["identities"], {})
                epoch = load_json(state_refresh_guard.EPOCH_PATH)
                self.assertEqual(epoch["state_epoch"], STATE_EPOCH)
            finally:
                (
                    state_refresh_guard.PRICE_HISTORY_PATH,
                    state_refresh_guard.TOP5_PATH,
                    state_refresh_guard.EPOCH_PATH,
                ) = old_paths

    def test_merge_does_not_reintroduce_pre_epoch_state(self):
        module = types.SimpleNamespace()
        module.main = lambda: {}
        module.compact_history = lambda history, *args, **kwargs: dict(history)
        module.merge_history = lambda current, run_state: {**current, **run_state}
        module.maybe_alert = lambda *args, **kwargs: (False, False)
        module.maybe_alert_cross_store = lambda *args, **kwargs: False
        state_refresh_guard.install(module)

        current = {"offers": {"legacy": [1]}}
        run_state = {"state_epoch": STATE_EPOCH, "offers": {"fresh": [2]}}
        merged = module.merge_history(current, run_state)
        self.assertEqual(merged["state_epoch"], STATE_EPOCH)
        self.assertEqual(set(merged["offers"]), {"fresh"})


if __name__ == "__main__":
    unittest.main()
