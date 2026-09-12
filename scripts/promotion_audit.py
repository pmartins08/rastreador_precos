"""Audita cobertura da campanha sem enviar notificações nem guardar estado."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner
import tracker
from promotion_runtime_guard import _radio_popular_laptop_campaign

config = tracker.load_json(tracker.CONFIG_PATH)
cat = next(dict(c) for c in config["category_urls"] if c["loja"] == "Radio Popular")
campaign = next(c for c in cat["campaign_urls"] if c["label"] == "50_por_250_set_2026")
cat["url"] = _radio_popular_laptop_campaign(campaign["url"])
response, _, outcome = tracker.adaptive_fetch(cat["url"], config, 15, store="Radio Popular", method="campaign_audit")
assert response is not None and response.status_code == 200, outcome
candidates = {}
stat = tracker._empty_store_stats()
tracker._discover_html(response, cat, 80, candidates, "segmento", stat)
promoted = [c for c in candidates.values() if c.get("promotions")]
print("CAMPAIGN_AUDIT", json.dumps({
    "pagination": stat.get("promotion_pagination"),
    "candidates": len(candidates), "promoted": len(promoted),
    "within_budget": sum(250 <= float(c.get("preco") or 0) <= 1500 for c in promoted),
    "requests": tracker.REQUESTS_USED, "notifications_sent": 0,
    "items": [{"title":c.get("titulo"), "price":c.get("preco"), "url":c["url"]} for c in promoted],
}, ensure_ascii=False))
assert stat.get("promotion_pagination", {}).get("complete"), stat
assert len(promoted) > 9, len(promoted)
