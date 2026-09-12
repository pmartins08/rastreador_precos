from __future__ import annotations

import json
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import top5_guard
from version import STATE_EPOCH, VERSION


class Top5GuardTests(unittest.TestCase):
    def _entry(self, *, key, title, store, price, value, observed, stock=True):
        return {
            "timestamp": observed,
            "tracker_version": VERSION,
            "loja": store,
            "titulo": title,
            "price": price,
            "stock": stock,
            "score_final": 80.0,
            "score_ranking": value - 30.0,
            "value_score": value,
            "tier": "OURO" if value >= 110 else "PRATA",
            "specs": {
                "cpu_modelo": "cpu-test",
                "gpu_modelo": "rtx 5050",
                "ram_gb": 32,
                "armazenamento_tb": 1.0,
                "teclado_pt": "confirmado",
            },
            "url": f"https://{store.lower().replace(' ', '')}.test/{key}",
            "configuration_key": key,
        }

    def _tracker(self, *, root: Path, entries: list[dict], sent: list, minimum="OURO"):
        history_path = root / "history.json"
        config_path = root / "config.json"
        history_path.write_text(
            json.dumps(
                {
                    "state_epoch": STATE_EPOCH,
                    "learning": {"runs": [{}]},
                    "offers": {entry["url"]: [entry] for entry in entries},
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "settings": {
                        "top5_current_ttl_hours": 26,
                        "top5_notify_once_version": VERSION,
                        "alerta_min_tier": minimum,
                    }
                }
            ),
            encoding="utf-8",
        )

        def load_json(path):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        def save_json(path, value):
            Path(path).write_text(json.dumps(value), encoding="utf-8")

        return types.SimpleNamespace(
            HISTORY_PATH=history_path,
            CONFIG_PATH=config_path,
            load_json=load_json,
            save_json=save_json,
            now_iso=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ntfy_send=lambda title, message, priority=3, tags=None: sent.append((title, message)) or True,
            LOGGER=types.SimpleNamespace(warning=lambda *args, **kwargs: None),
        )

    def test_top5_is_aggregated_current_market_not_duplicate_offers(self):
        now = datetime.now(timezone.utc)
        fresh = now.isoformat().replace("+00:00", "Z")
        stale = (now - timedelta(hours=40)).isoformat().replace("+00:00", "Z")
        entries = [
            self._entry(key="ean:1", title="Laptop A", store="Loja A", price=1200, value=116, observed=fresh),
            self._entry(key="ean:1", title="Laptop A", store="Loja B", price=1100, value=118, observed=fresh),
            self._entry(key="ean:2", title="Laptop B", store="Loja A", price=1000, value=115, observed=fresh),
            self._entry(key="ean:3", title="Laptop C", store="Loja A", price=900, value=114, observed=fresh),
            self._entry(key="ean:4", title="Laptop D", store="Loja A", price=800, value=113, observed=fresh),
            self._entry(key="ean:5", title="Laptop E", store="Loja A", price=700, value=112, observed=fresh),
            self._entry(key="ean:6", title="Laptop F velho", store="Loja A", price=600, value=150, observed=stale),
        ]
        history = {
            "state_epoch": STATE_EPOCH,
            "offers": {entry["url"]: [entry] for entry in entries},
        }
        tracker = types.SimpleNamespace(HISTORY_PATH=Path("unused"), load_json=lambda _path: history)

        top = top5_guard.build_current_top5(tracker, ttl_hours=26, now=now)
        self.assertEqual(len(top), 5)
        self.assertEqual(top[0]["configuration_key"], "ean:1")
        self.assertEqual(top[0]["store"], "Loja B")
        self.assertNotIn("ean:6", {row["configuration_key"] for row in top})
        self.assertEqual(len({row["configuration_key"] for row in top}), 5)

    def test_one_time_campaign_sends_each_top5_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_top_path = top5_guard.TOP5_PATH
            top5_guard.TOP5_PATH = root / "top5_current.json"
            try:
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                entries = [
                    self._entry(
                        key=f"ean:{index}",
                        title=f"Laptop {index}",
                        store="Loja",
                        price=1000 + index,
                        value=120 - index,
                        observed=now,
                    )
                    for index in range(1, 6)
                ]
                sent = []
                tracker = self._tracker(root=root, entries=entries, sent=sent)
                first_run = {}
                top5_guard.persist_and_notify(tracker, first_run)
                second_run = {}
                top5_guard.persist_and_notify(tracker, second_run)

                self.assertEqual(len(sent), 5)
                self.assertEqual(first_run["top5_notifications_sent"], 5)
                self.assertEqual(second_run["top5_notifications_sent"], 0)
                snapshot = json.loads(top5_guard.TOP5_PATH.read_text(encoding="utf-8"))
                self.assertTrue(snapshot["notification_campaigns"][VERSION]["complete"])
            finally:
                top5_guard.TOP5_PATH = old_top_path

    def test_top5_never_notifies_silver_even_if_config_minimum_is_lower(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_top_path = top5_guard.TOP5_PATH
            top5_guard.TOP5_PATH = root / "top5_current.json"
            try:
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                entries = [
                    self._entry(key="ean:gold-1", title="Gold 1", store="Loja", price=1000, value=116, observed=now),
                    self._entry(key="ean:gold-2", title="Gold 2", store="Loja", price=1050, value=112, observed=now),
                    self._entry(key="ean:silver-1", title="Silver 1", store="Loja", price=700, value=109, observed=now),
                    self._entry(key="ean:silver-2", title="Silver 2", store="Loja", price=650, value=108, observed=now),
                    self._entry(key="ean:silver-3", title="Silver 3", store="Loja", price=600, value=107, observed=now),
                ]
                sent = []
                tracker = self._tracker(root=root, entries=entries, sent=sent, minimum="PRATA")

                first_run = {}
                top5_guard.persist_and_notify(tracker, first_run)
                second_run = {}
                top5_guard.persist_and_notify(tracker, second_run)

                self.assertEqual(len(sent), 2)
                self.assertEqual(first_run["top5_notifications_sent"], 2)
                self.assertEqual(second_run["top5_notifications_sent"], 0)
                self.assertTrue(all("OURO" in title for title, _message in sent))
                self.assertTrue(all("PRATA" not in message for _title, message in sent))
            finally:
                top5_guard.TOP5_PATH = old_top_path


if __name__ == "__main__":
    unittest.main()
