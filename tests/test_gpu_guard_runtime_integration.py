import json
import subprocess
import sys
import textwrap
import unittest


class RealRuntimeGpuGuardTests(unittest.TestCase):
    def test_arc_140v_history_cache_uses_real_runner_composition(self):
        script = textwrap.dedent(
            r'''
            import json
            import re
            from pathlib import Path

            import runner  # instala guards na mesma ordem usada em produção
            import gpu_guard
            import scraper
            import tracker

            config = json.loads(Path("config/config.json").read_text(encoding="utf-8"))
            history = json.loads(Path("data/history.json").read_text(encoding="utf-8"))
            settings = config.get("settings", {})
            weights = config.get("weights", {})

            target = None
            for entries in (history.get("offers") or {}).values():
                if not isinstance(entries, list):
                    continue
                for entry in reversed(entries):
                    if isinstance(entry, dict) and entry.get("ean") == "0199251239182":
                        target = entry
                        break
                if target:
                    break

            assert target is not None, "HP OmniBook Arc 140V não encontrado no histórico real"
            item = {
                key: target.get(key)
                for key in ("loja", "titulo", "price", "url", "stock", "ean", "mpn", "sku")
            }
            item["preco"] = target["price"]
            spec = dict(target.get("specs") or {})
            spec["fontes"] = dict(spec.get("fontes") or {})
            spec["evidencias"] = dict(spec.get("evidencias") or {})
            spec["gpu_modelos_detectados"] = list(spec.get("gpu_modelos_detectados") or [])

            direct_normalized = re.sub(
                r"[^a-z0-9]+", " ", scraper.norm(item.get("titulo"))).strip()
            direct_identified = gpu_guard.identify_igpu(item.get("titulo"), scraper)

            records = [{"item": item, "spec": spec}]
            tracker.apply_exact_market_price_evidence(records, settings)
            assessment = tracker.score_allow_unknown(spec, float(item["preco"]), weights, settings)
            tier = scraper.tier_from_value(assessment["value_score"], settings)

            result = {
                "title": item.get("titulo"),
                "title_repr": repr(item.get("titulo")),
                "normalized": direct_normalized,
                "direct_identified": direct_identified,
                "gpu_tipo": spec.get("gpu_tipo"),
                "gpu_modelo": spec.get("gpu_modelo"),
                "guard": spec.get("gpu_tier_guard"),
                "value": float(assessment.get("value_score", 0)),
                "rank": assessment.get("score_ranking"),
                "tier": tier,
                "igpu_scoring": assessment.get("igpu_scoring"),
                "apply_market_module": tracker.apply_exact_market_price_evidence.__module__,
                "score_module": tracker.score_allow_unknown.__module__,
                "tier_module": scraper.tier_from_value.__module__,
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))

            assert result["direct_identified"] == "intel arc graphics 140v", result
            assert result["gpu_tipo"] == "integrada", result
            assert result["gpu_modelo"] == "intel arc graphics 140v", result
            assert result["guard"]["status"] == "INTEGRADA_MAPEADA", result
            assert result["igpu_scoring"] is not None, result
            assert result["tier"] == "OURO", result
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
                "Runtime real falhou.\nSTDOUT:\n"
                + completed.stdout
                + "\nSTDERR:\n"
                + completed.stderr
            )


if __name__ == "__main__":
    unittest.main()
