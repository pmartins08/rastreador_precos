import json
import subprocess
import sys
import textwrap
import unittest


class DecisionTruthRealRuntimeTests(unittest.TestCase):
    def test_real_runner_composition_exposes_one_effective_tier(self):
        script = textwrap.dedent(
            r'''
            import json
            from pathlib import Path

            import runner  # instala os guards na mesma ordem usada em produção
            import scraper
            import tracker

            config = json.loads(Path("config/config.json").read_text(encoding="utf-8"))
            settings = config.get("settings", {})

            assert getattr(tracker, "_DECISION_TRUTH_RUNTIME_GUARD_INSTALLED", False), "Decision Truth runtime não instalado"
            assert getattr(tracker, "_PROMOTION_RUNTIME_GUARD_INSTALLED", False), "Promotion runtime não instalado"

            promotion = {
                "kind": "TIERED_DISCOUNT",
                "title": "Ganha 50€ por cada 250€",
                "threshold_step_eur": 250.0,
                "step_discount_eur": 50.0,
                "cap_eur": 500.0,
                "eligibility": "campaign_listing",
                "applicable": True,
            }
            item = {
                "loja": "TEST",
                "titulo": "Portátil V9 Decision Truth RTX 5060 32GB 1TB",
                "preco": 1499.99,
                "url": "https://example.test/v9-decision-truth",
                "stock": True,
                "promotions": [promotion],
                "promotion_price_live_confirmed": True,
            }
            assessment = {
                "status": "ACEITE",
                "score_final": 100.0,
                "score_ranking": 150.0,
                "value_score": 112.0,
                "detalhes": {"Gaming": 90.0},
                "alertas": [],
            }
            base_tier = scraper.tier_from_value(assessment["value_score"], settings)
            history = {"offers": {}, "alert_state": {}, "learning": {"runs": [], "stores": {}}}

            tracker.record_offer(history, item, {}, assessment, base_tier)
            entry = history["offers"][item["url"]][-1]

            result = {
                "base_value": entry.get("base_value_score"),
                "base_tier": entry.get("base_tier"),
                "promo_value": entry.get("promotion_value_score"),
                "promo_tier": entry.get("promotion_tier"),
                "promotion_applied": entry.get("promotion_applied"),
                "effective_value": entry.get("effective_value_score"),
                "effective_tier": entry.get("effective_tier"),
                "decision_truth_schema": entry.get("decision_truth_schema"),
                "promotion_confirmed": entry.get("promotion_price_live_confirmed"),
                "promotion_discount_eur": entry.get("promotion_discount_eur"),
                "promotion_checkout_price": entry.get("promotion_checkout_price"),
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))

            assert result["decision_truth_schema"] == 1, result
            assert result["promotion_confirmed"] is True, result
            assert float(result["promotion_discount_eur"] or 0.0) > 0.0, result
            assert result["promotion_applied"] is True, result
            assert float(result["promo_value"] or 0.0) > 120.0, result
            assert result["promo_tier"] == "DIAMANTE", result
            assert result["effective_tier"] == "DIAMANTE", result
            assert abs(float(result["effective_value"]) - float(result["promo_value"])) < 0.001, result
            assert abs(float(result["base_value"]) - 112.0) < 0.001, result
            '''
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(
                "Composição real Decision Truth falhou.\nSTDOUT:\n"
                + completed.stdout
                + "\nSTDERR:\n"
                + completed.stderr
            )


if __name__ == "__main__":
    unittest.main()
