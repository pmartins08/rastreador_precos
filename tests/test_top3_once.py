import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("top3_once", Path(__file__).resolve().parents[1] / "scripts/send_top3_once.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Top3OnceTests(unittest.TestCase):
    def history(self):
        stamp = datetime.now(timezone.utc).isoformat()
        return {"learning": {"runs": [{"timestamp": stamp, "runtime_seconds": 50}]},
                "offers": {str(i): [{"timestamp": stamp, "stock": True, "price": 999,
                    "value_score": 130-i, "tier": "DIAMANTE" if i < 2 else "OURO",
                    "titulo": f"Laptop {i}", "loja": "Store", "url": f"https://store/{i}",
                    "configuration_key": str(i)}] for i in range(3)}}

    def test_current_top_three_and_configuration_deduplication(self):
        h = self.history()
        h["offers"]["duplicate"] = [dict(h["offers"]["0"][0], url="https://other/0")]
        rows = module.top3(h, {})
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r["tier"] == "DIAMANTE" for r in rows), 2)

    def test_stale_run_is_rejected(self):
        with self.assertRaises(ValueError):
            module.top3(self.history(), {}, now=datetime(2099, 1, 1, tzinfo=timezone.utc))

    def test_stock_and_silver_are_excluded(self):
        h = self.history()
        h["offers"]["0"][0]["stock"] = False
        h["offers"]["1"][0]["tier"] = "PRATA"
        with self.assertRaises(ValueError):
            module.top3(h, {})

    def test_existing_reservation_never_resends(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "data").mkdir()
            (root / "config/config.json").write_text(json.dumps({"settings": {"top3_once_request_id": "test"}}))
            (root / "data/top3_notification.json").write_text(json.dumps({"request_id": "test", "status": "reserved"}))
            with patch.object(module, "ROOT", root), patch("curl_cffi.requests.post") as post:
                module.main()
                post.assert_not_called()
