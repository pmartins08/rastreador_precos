"""Mede ao vivo que preços brutos da campanha RP chegam ao orçamento efetivo."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Importa o composition root sem executar main(). Assim o probe usa exatamente
# as mesmas camadas de promoção/descoberta que a produção.
import runner  # noqa: F401
import tracker
from promotion_budget_guard import budget_view


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tracker.LEARNING = tracker.load_learning()
    tracker.REQUESTS_USED = 0
    tracker.REQUESTS_BY_STORE.clear()
    tracker.DETAIL_FETCHES_USED = 0
    tracker.RUN_DEADLINE = 0.0

    config = tracker.load_json(tracker.CONFIG_PATH)
    settings = config.get("settings", {})
    weights = config.get("weights", {})
    category = next(
        row for row in config.get("category_urls", []) if row.get("loja") == "Radio Popular"
    )
    items, stat = tracker.scan_store(category, config, settings)

    rows = []
    for item in items:
        view = budget_view(item, settings)
        if not view.get("confirmed"):
            continue
        rows.append(
            {
                "title": item.get("titulo"),
                "url": item.get("url"),
                "raw_price": view["raw_price"],
                "discount_eur": view["discount_eur"],
                "checkout_price": view["checkout_price"],
                "fits_hard_budget": view["fits_hard_budget"],
                "rescued_by_promotion": view["rescued_by_promotion"],
            }
        )

    rows.sort(key=lambda row: (-float(row["raw_price"]), str(row.get("title") or "")))
    rescued = [row for row in rows if row["rescued_by_promotion"]]
    over_hard = [row for row in rows if float(row["raw_price"]) > float(settings.get("budget_hard", 1500))]
    fits = [row for row in rows if row["fits_hard_budget"]]

    max_eval = int(settings.get("max_evaluated_per_run", 240))
    selected = tracker.select_with_cache(items, {}, max_eval, weights, settings)
    selected_urls = {str(item.get("url") or "") for item in selected}
    rescued_selected = [row for row in rescued if str(row.get("url") or "") in selected_urls]

    report = {
        "hard_budget": float(settings.get("budget_hard", 1500.0)),
        "campaign_listing_total": stat.get("campaign_pagination", {}).get("listing_total"),
        "campaign_complete": stat.get("campaign_pagination", {}).get("complete"),
        "candidates": len(items),
        "promotion_confirmed": len(rows),
        "gross_above_hard": len(over_hard),
        "fits_hard_after_promotion": len(fits),
        "rescued_above_hard": len(rescued),
        "selected_for_evaluation": len(selected),
        "rescued_selected_for_evaluation": len(rescued_selected),
        "max_confirmed_gross": max((row["raw_price"] for row in rows), default=None),
        "max_rescued_gross": max((row["raw_price"] for row in rescued), default=None),
        "max_rescued_checkout": max((row["checkout_price"] for row in rescued), default=None),
        "max_selected_rescued_gross": max(
            (row["raw_price"] for row in rescued_selected), default=None
        ),
        "promotion_budget_stats": stat.get("promotion_budget", {}),
        "highest_confirmed": rows[:15],
        "highest_rescued": rescued[:15],
        "requests_used": tracker.REQUESTS_USED,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("RP_PROMOTION_BUDGET " + json.dumps(report, ensure_ascii=False), flush=True)

    if not rows:
        raise RuntimeError("RP: nenhuma promoção live confirmada no universo descoberto")
    if not stat.get("promotion_live_confirmed"):
        raise RuntimeError("RP: regra promocional não foi confirmada ao vivo")
    if len(items) <= max_eval and len(rescued_selected) != len(rescued):
        raise RuntimeError(
            "RP: candidatos acima do hard budget resgatados pela promoção foram cortados antes da avaliação"
        )


if __name__ == "__main__":
    main()
