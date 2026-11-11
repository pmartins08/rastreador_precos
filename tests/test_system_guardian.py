"""Suite de testes do Salvaguardador do Sistema (System Guardian).

Garante que os 8 pilares inegociáveis definidos em docs/SYSTEM_GUARDIAN_BASELINE.md
são auditados rigorosamente e que o CI do GitHub Actions bloqueia automaticamente
qualquer tentativa de degradar ou afrouxar a baseline criada pelo utilizador.
Compatível com `unittest discover -s tests -p 'test_*.py'`.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src", ROOT / "scripts"):
    val = str(candidate)
    if val not in sys.path:
        sys.path.insert(0, val)

from system_guardian_audit import (
    audit_pillar_1_laptop_focus,
    audit_pillar_2_unified_value,
    audit_pillar_3_os_penalty_and_tristate,
    audit_pillar_4_exclusions,
    audit_pillar_5_budget_limits,
    audit_pillar_6_ntfy_diamond_only,
    audit_pillar_7_sync_availability_and_cache,
    audit_pillar_8_test_suite_integrity,
    run_system_guardian_audit,
)


class SystemGuardianTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_path = ROOT / "config" / "config.json"
        with cls.config_path.open(encoding="utf-8") as f:
            cls.base_config = json.load(f)

    def test_full_baseline_audit_passes_cleanly(self):
        """Verifica que o estado atual do repositório cumpre 100% dos 8 pilares."""
        report = run_system_guardian_audit(repo_root=ROOT, config_path=self.config_path)
        self.assertTrue(
            report.passed,
            f"A baseline atual falhou a auditoria do Guardian: {[p.violations for p in report.pillars if not p.passed]}",
        )
        self.assertEqual(report.total_pillars, 8)
        self.assertEqual(report.passed_pillars, 8)
        self.assertEqual(report.failed_pillars, 0)
        self.assertFalse(report.veto_triggered)

    def test_pillar_1_blocks_non_laptop_categories(self):
        """Pilar 1: Deteta e veta tentativa de incluir desktops ou categorias não-portáteis."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["category_urls"].append({
            "loja": "LojaTeste",
            "url": "https://www.exemplo.pt/desktops/computadores-secretaria",
            "laptop_only": False,
        })
        result = audit_pillar_1_laptop_focus(tampered_config, ROOT)
        self.assertFalse(result.passed)
        self.assertTrue(any("LojaTeste" in v for v in result.violations))

    def test_pillar_2_blocks_disabling_unified_value_or_reintroducing_bonus(self):
        """Pilar 2: Veta desativação do Value V9/V10 ou reintrodução do exceptional deal bonus."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["settings"]["unified_value_enabled"] = False
        result = audit_pillar_2_unified_value(tampered_config, ROOT)
        self.assertFalse(result.passed)
        self.assertTrue(any("unified_value_enabled" in v for v in result.violations))

        tampered_config2 = copy.deepcopy(self.base_config)
        tampered_config2["settings"]["exceptional_deal_bonus_max"] = 15.0
        result2 = audit_pillar_2_unified_value(tampered_config2, ROOT)
        self.assertFalse(result2.passed)
        self.assertTrue(any("exceptional_deal_bonus_max" in v for v in result2.violations))

    def test_pillar_3_blocks_tampering_with_os_penalty(self):
        """Pilar 3: Veta alteração ao custo de +110 € para máquinas sem sistema operativo."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["settings"]["windows_installation_cost_eur"] = 0.0
        result = audit_pillar_3_os_penalty_and_tristate(tampered_config, ROOT)
        self.assertFalse(result.passed)
        self.assertTrue(any("windows_installation_cost_eur" in v for v in result.violations))

    def test_pillar_4_exclusions_remain_strict(self):
        """Pilar 4: Confirma exclusão estrita de teclados espanhóis e usados/recondicionados."""
        result = audit_pillar_4_exclusions(self.base_config, ROOT)
        self.assertTrue(result.passed, f"Pilar 4 violado: {result.violations}")

    def test_pillar_5_blocks_tampering_with_budget_limits(self):
        """Pilar 5: Veta qualquer aumento do teto orçamental máximo de 1.600 €."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["settings"]["budget_hard"] = 1800.0
        result = audit_pillar_5_budget_limits(tampered_config, ROOT)
        self.assertFalse(result.passed)
        self.assertTrue(any("budget_hard" in v for v in result.violations))

        tampered_config2 = copy.deepcopy(self.base_config)
        tampered_config2["settings"]["budget_soft"] = 1200.0
        result2 = audit_pillar_5_budget_limits(tampered_config2, ROOT)
        self.assertFalse(result2.passed)
        self.assertTrue(any("budget_soft" in v for v in result2.violations))

    def test_pillar_6_blocks_lowering_alert_threshold_or_tier(self):
        """Pilar 6: Veta afrouxamento do limiar de alertas para abaixo de Diamante ou Value < 120."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["settings"]["alerta_min_tier"] = "OURO"
        result = audit_pillar_6_ntfy_diamond_only(tampered_config, ROOT)
        self.assertFalse(result.passed)
        self.assertTrue(any("alerta_min_tier" in v for v in result.violations))

        tampered_config2 = copy.deepcopy(self.base_config)
        tampered_config2["settings"]["heartbeat_ntfy"] = True
        result2 = audit_pillar_6_ntfy_diamond_only(tampered_config2, ROOT)
        self.assertFalse(result2.passed)
        self.assertTrue(any("heartbeat_ntfy" in v for v in result2.violations))

    def test_pillar_7_blocks_shortening_price_cache_or_stale_availability(self):
        """Pilar 7: Veta redução do TTL de cache de preço/hardware para menos de 24h."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["settings"]["price_confirmation_ttl_hours"] = 12
        result = audit_pillar_7_sync_availability_and_cache(tampered_config, ROOT)
        self.assertFalse(result.passed)
        self.assertTrue(any("price_confirmation_ttl_hours" in v for v in result.violations))

    def test_pillar_8_blocks_weakening_test_suite_or_missing_guardrails(self):
        """Pilar 8: Garante presença dos testes de guardrail e integridade da suite."""
        result = audit_pillar_8_test_suite_integrity(self.base_config, ROOT)
        self.assertTrue(result.passed, f"Pilar 8 violado: {result.violations}")

    def test_veto_protocol_triggers_on_violation(self):
        """Protocolo de Veto: Confirma acionamento de veto quando qualquer pilar é quebrado."""
        tampered_config = copy.deepcopy(self.base_config)
        tampered_config["settings"]["windows_installation_cost_eur"] = 50.0

        tmp_cfg = ROOT / "config" / "_tampered_test_config.json"
        try:
            with tmp_cfg.open("w", encoding="utf-8") as f:
                json.dump(tampered_config, f)

            report = run_system_guardian_audit(repo_root=ROOT, config_path=tmp_cfg)
            self.assertFalse(report.passed)
            self.assertTrue(report.veto_triggered)
            self.assertGreater(report.failed_pillars, 0)
            self.assertIn("VETO ATIVADO", report.summary)
        finally:
            if tmp_cfg.exists():
                tmp_cfg.unlink()


if __name__ == "__main__":
    unittest.main()
