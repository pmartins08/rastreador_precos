#!/usr/bin/env python3
"""Auditoria programática da baseline inegociável do sistema LapIntel PT.

Este script é a ferramenta oficial do Agente 4 — Salvaguardador do Sistema
(System Guardian & Baseline Verifier). Inspeciona código, configurações e
contratos de decisão para garantir que os 8 pilares inegociáveis definidos em
docs/SYSTEM_GUARDIAN_BASELINE.md permanecem 100% íntegros.

Devolve exit code 0 em caso de conformidade total, ou 1 em caso de violação.
Compatível com Python 3.11+.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    val = str(candidate)
    if val not in sys.path:
        sys.path.insert(0, val)


@dataclass
class PillarResult:
    pillar_number: int
    name: str
    passed: bool
    violations: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


@dataclass
class GuardianAuditReport:
    timestamp: str
    repo_root: str
    passed: bool
    total_pillars: int
    passed_pillars: int
    failed_pillars: int
    pillars: list[PillarResult] = field(default_factory=list)
    veto_triggered: bool = False
    summary: str = ""


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(f"Ficheiro de configuração não encontrado: {config_path}")
    with config_path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Pilar 1: Foco exclusivo em portáteis
# ---------------------------------------------------------------------------
def audit_pillar_1_laptop_focus(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []

    category_urls = config.get("category_urls", [])
    if not category_urls:
        violations.append("Nenhuma categoria/loja configurada em category_urls.")

    non_laptop_patterns = [
        r"\b(?:desktop|secretaria|computador-de-secretaria|torre|all-in-one|aio)\b",
        r"\b(?:monitor|monitores|ecra-avulso)\b",
        r"\b(?:smartphone|telemovel|tablet|ipad)\b",
        r"\b(?:motherboard|placa-grafica|gpu-avulsa)\b",
    ]

    for entry in category_urls:
        store = entry.get("loja", "Desconhecida")
        url = entry.get("url", "").lower()
        laptop_only = entry.get("laptop_only", False)
        path_hints = [str(h).lower() for h in entry.get("product_path_hints", [])]

        is_laptop_url = any(
            token in url
            for token in ("portateis", "computadores-portateis", "laptops", "pcs")
        )
        has_laptop_hints = any("portatil" in hint or "laptop" in hint for hint in path_hints)

        if not laptop_only and not is_laptop_url:
            violations.append(
                f"Loja '{store}' sem flag 'laptop_only: true' e com URL não restrita a portáteis: {url}"
            )

        for pat in non_laptop_patterns:
            if re.search(pat, url):
                violations.append(
                    f"Loja '{store}' referencia categoria externa a portáteis na URL: {url}"
                )

    # Inspeciona motor de normalização e busca
    search_guard_file = repo_root / "src" / "search_index_guard.py"
    if search_guard_file.is_file():
        content = search_guard_file.read_text(encoding="utf-8")
        if "desktop" not in content or "monitor" not in content:
            violations.append(
                "Filtro _looks_like_laptop em search_index_guard.py perdeu marcadores de exclusão de não-portáteis."
            )
        else:
            details.append("Marcadores de exclusão de não-portáteis presentes em search_index_guard.py.")

    details.append(f"{len(category_urls)} lojas validadas para foco estrito em portáteis.")
    passed = len(violations) == 0
    return PillarResult(
        pillar_number=1,
        name="Foco exclusivo em portáteis",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 2: Fórmula unificada do Value V9/V10 e pontuação técnica
# ---------------------------------------------------------------------------
def audit_pillar_2_unified_value(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []
    settings = config.get("settings", {})

    if not settings.get("unified_value_enabled"):
        violations.append("Definição 'unified_value_enabled' deve estar ativa (true) em settings.")

    if float(settings.get("exceptional_deal_bonus_max", 0.0)) > 0.0:
        violations.append(
            f"exceptional_deal_bonus_max deve ser 0.0 para evitar duplo bónus de preço, atual: {settings.get('exceptional_deal_bonus_max')}"
        )

    # Verificação da função matemática calculate_opportunity
    try:
        from opportunity_guard import calculate_opportunity, historical_bonus

        # Caso base 1: valor 100, gaming 50 -> 100*0.80 + 50*1.5*0.20 = 80 + 15 = 95.0
        opp1 = calculate_opportunity(100.0, 50.0)
        expected1 = round(100.0 * 0.80 + 50.0 * 1.5 * 0.20, 1)
        if opp1.get("score") != expected1:
            violations.append(
                f"Fórmula calculate_opportunity(100, 50) divergiu: obtido {opp1.get('score')}, esperado {expected1}"
            )
        else:
            details.append(f"Teste unitário do Value: 100 base + 50 gaming -> {opp1.get('score')} (conforme).")

        # Caso base 2: teto máximo truncado a 150.0
        opp_cap = calculate_opportunity(150.0, 100.0, {"available": True, "days_observed": 10, "new_low": True})
        if opp_cap.get("score") > 150.0:
            violations.append(f"Teto do Value excedeu 150.0: {opp_cap.get('score')}")

        # Caso base 3: bónus histórico máximo de 5.0
        h_bonus = historical_bonus({"available": True, "days_observed": 5, "new_low": True})
        if h_bonus > 5.0 or h_bonus < 5.0:
            violations.append(f"historical_bonus para new_low deve ser 5.0, obtido: {h_bonus}")

    except Exception as exc:
        violations.append(f"Erro ao importar ou executar opportunity_guard.calculate_opportunity: {exc}")

    # Verificação do ficheiro de scoring técnico
    scoring_file = repo_root / "src" / "technical_scoring.py"
    if not scoring_file.is_file():
        violations.append("Ficheiro src/technical_scoring.py não encontrado.")
    else:
        content = scoring_file.read_text(encoding="utf-8")
        if "decision_utility_not_benchmark" not in content:
            violations.append("technical_scoring.py deve manter basis: decision_utility_not_benchmark.")
        if "tgp_multiplier" not in content:
            violations.append("technical_scoring.py deve preservar o multiplicador de TGP.")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=2,
        name="Fórmula unificada do Value V9/V10 e pontuação técnica",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 3: Penalização estrita de +110 € para Sem SO / FreeDOS e tri-state
# ---------------------------------------------------------------------------
def audit_pillar_3_os_penalty_and_tristate(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []
    settings = config.get("settings", {})

    os_cost = float(settings.get("windows_installation_cost_eur", 0.0))
    if os_cost != 110.0:
        violations.append(f"windows_installation_cost_eur deve ser exatamente 110.0 €, atual: {os_cost}")
    else:
        details.append("windows_installation_cost_eur fixado em 110.0 €.")

    try:
        from purchase_policy import enrich_purchase_specs, installation_cost
        import scraper

        # Teste 1: FreeDOS -> 'none' -> custo 110.0 €
        spec_freedos = enrich_purchase_specs(
            {}, "ASUS TUF Gaming", [("os", "Sistema Operativo", "FreeDOS")], scraper.norm
        )
        if spec_freedos.get("os_status") != "none":
            violations.append(f"FreeDOS deve produzir os_status='none', obtido: {spec_freedos.get('os_status')}")
        cost_freedos = installation_cost(spec_freedos, settings)
        if cost_freedos != 110.0:
            violations.append(f"installation_cost para 'none' deve ser 110.0, obtido: {cost_freedos}")
        else:
            details.append("FreeDOS penalizado com +110.0 € (conforme).")

        # Teste 2: Windows 11 -> 'windows' -> custo 0.0 €
        spec_win = enrich_purchase_specs(
            {}, "Lenovo Legion 5", [("os", "SO", "Windows 11 Home")], scraper.norm
        )
        if spec_win.get("os_status") != "windows":
            violations.append(f"Windows deve produzir os_status='windows', obtido: {spec_win.get('os_status')}")
        cost_win = installation_cost(spec_win, settings)
        if cost_win != 0.0:
            violations.append(f"installation_cost para 'windows' deve ser 0.0, obtido: {cost_win}")

        # Teste 3: Sem evidência de SO -> 'unknown' -> custo não presumido (0.0 €)
        spec_unk = enrich_purchase_specs({}, "HP Victus 16", [], scraper.norm)
        if spec_unk.get("os_status") != "unknown":
            violations.append(f"Sem evidência de SO deve produzir os_status='unknown', obtido: {spec_unk.get('os_status')}")
        cost_unk = installation_cost(spec_unk, settings)
        if cost_unk != 0.0:
            violations.append(f"Tri-state unknown não deve presumir custo (esperado 0.0), obtido: {cost_unk}")
        else:
            details.append("Tri-state 'unknown' preserva custo 0.0 € sem presunção indevida.")

        # Teste 4: Conflito de evidência -> 'conflict' -> custo 0.0 €
        spec_conf = enrich_purchase_specs(
            {}, "Portátil Windows 11", [("os", "SO", "Sem Sistema Operativo")], scraper.norm
        )
        if spec_conf.get("os_status") != "conflict":
            violations.append(f"Evidência mista deve produzir os_status='conflict', obtido: {spec_conf.get('os_status')}")
        cost_conf = installation_cost(spec_conf, settings)
        if cost_conf != 0.0:
            violations.append(f"Tri-state conflict não deve presumir custo, obtido: {cost_conf}")

    except Exception as exc:
        violations.append(f"Erro ao verificar purchase_policy: {exc}")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=3,
        name="Penalização estrita de +110 € para Sem SO e tri-state de incerteza",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 4: Exclusão mandatória de teclados espanhóis e usados/recondicionados
# ---------------------------------------------------------------------------
def audit_pillar_4_exclusions(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []

    try:
        from purchase_policy import enrich_purchase_specs
        import scraper

        # Exclusão de Teclado Espanhol
        spec_es = enrich_purchase_specs(
            {}, "ASUS ROG", [("keyboard", "Teclado", "Espanhol")], scraper.norm
        )
        if spec_es.get("keyboard_layout") != "es":
            violations.append(
                f"Teclado espanhol deve produzir keyboard_layout='es', obtido: {spec_es.get('keyboard_layout')}"
            )
        else:
            details.append("Deteção de layout 'es' confirmada em purchase_policy.")

        spec_pt = enrich_purchase_specs(
            {}, "ASUS ROG", [("keyboard", "Teclado", "Português")], scraper.norm
        )
        if spec_pt.get("keyboard_layout") == "es":
            violations.append("Layout português classificado erradamente como espanhol.")

        # Rejeição de Recondicionados e Artigos de Exposição
        recond = scraper.eligible("Portátil ASUS ROG Strix recondicionado")
        if recond is not False:
            violations.append("Portátil com marcador 'recondicionado' não foi excluído por scraper.eligible.")
        else:
            details.append("Exclusão de 'recondicionado' ativa e funcional.")

        expo = scraper.eligible("Portátil Lenovo Legion artigo de exposicao")
        if expo is not False:
            violations.append("Portátil com marcador 'artigo de exposicao' não foi excluído por scraper.eligible.")
        else:
            details.append("Exclusão de 'artigo de exposicao' ativa e funcional.")

        usado = scraper.eligible("Portátil HP Omen usado")
        if usado is not False:
            violations.append("Portátil com marcador 'usado' não foi excluído por scraper.eligible.")
        else:
            details.append("Exclusão de 'usado' ativa e funcional.")

    except Exception as exc:
        violations.append(f"Erro ao verificar exclusões em scraper/purchase_policy: {exc}")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=4,
        name="Exclusão mandatória de teclados espanhóis e artigos usados/recondicionados",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 5: Limites orçamentais (1.400 € preferencial / 1.600 € teto máximo)
# ---------------------------------------------------------------------------
def audit_pillar_5_budget_limits(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []
    settings = config.get("settings", {})

    budget_soft = float(settings.get("budget_soft", 0.0))
    budget_hard = float(settings.get("budget_hard", 0.0))

    if budget_soft != 1400.0:
        violations.append(f"budget_soft deve ser exatamente 1400.0 €, atual: {budget_soft}")
    else:
        details.append("budget_soft fixado em 1400.0 €.")

    if budget_hard != 1600.0:
        violations.append(f"budget_hard deve ser exatamente 1600.0 €, atual: {budget_hard}")
    else:
        details.append("budget_hard fixado em 1600.0 €.")

    try:
        from purchase_policy import total_cost
        # Simula teste de teto orçamental com instalação
        price = 1520.0
        inst_cost = 110.0
        tot = total_cost(price, inst_cost)
        if tot <= budget_hard:
            violations.append(
                f"total_cost({price}, {inst_cost}) produziu {tot}, devia exceder teto orçamental de {budget_hard}"
            )
        else:
            details.append(f"Rejeição por teto com instalação validada: {price} + {inst_cost} = {tot} > {budget_hard} €.")
    except Exception as exc:
        violations.append(f"Erro ao validar cálculo de custo total: {exc}")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=5,
        name="Limites orçamentais (1.400 € preferencial / 1.600 € teto máximo)",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 6: Alertas NTFY exclusivos para o tier Diamante
# ---------------------------------------------------------------------------
def audit_pillar_6_ntfy_diamond_only(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []
    settings = config.get("settings", {})

    min_tier = str(settings.get("alerta_min_tier", "")).upper()
    if min_tier != "DIAMANTE":
        violations.append(f"alerta_min_tier deve ser estritamente 'DIAMANTE', atual: '{min_tier}'")
    else:
        details.append("alerta_min_tier configurado para 'DIAMANTE'.")

    min_val = float(settings.get("min_value_score_alerta", 0.0))
    if min_val < 120.0:
        violations.append(f"min_value_score_alerta não pode ser inferior a 120.0, atual: {min_val}")
    else:
        details.append(f"min_value_score_alerta configurado para {min_val} (>= 120.0).")

    diamante_min = float(settings.get("diamante_value_min", 0.0))
    if diamante_min != 120.0:
        violations.append(f"diamante_value_min deve ser exatamente 120.0, atual: {diamante_min}")
    else:
        details.append("diamante_value_min fixado em 120.0.")

    heartbeat = settings.get("heartbeat_ntfy", True)
    if heartbeat is True:
        violations.append("heartbeat_ntfy deve estar desativado (false) em produção silenciosa.")
    else:
        details.append("heartbeat_ntfy desativado para silêncio operacional.")

    # Verificação de dependência de stock confirmado
    avail_guard_file = repo_root / "src" / "availability_guard.py"
    if avail_guard_file.is_file():
        content = avail_guard_file.read_text(encoding="utf-8")
        if "eligible" not in content or "OUT_OF_STOCK" not in content:
            violations.append("availability_guard.py perdeu a verificação de elegibilidade de stock.")
        else:
            details.append("availability_guard.py exige disponibilidade elegível antes do scoring.")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=6,
        name="Alertas NTFY exclusivos para o tier Diamante (Value >= 120 e stock confirmado)",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 7: Sincronização de disponibilidade (6h) vs. cache de hardware (24h)
# ---------------------------------------------------------------------------
def audit_pillar_7_sync_availability_and_cache(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []
    settings = config.get("settings", {})

    price_ttl = int(settings.get("price_confirmation_ttl_hours", 0))
    if price_ttl < 24:
        violations.append(f"price_confirmation_ttl_hours não deve ser inferior a 24h, atual: {price_ttl}")
    else:
        details.append(f"Cache de preço/hardware com TTL de {price_ttl}h (>= 24h).")

    # Verificação do TTL de disponibilidade de 6 horas
    try:
        from availability_guard import fresh

        now = datetime.now(timezone.utc)
        recent_stamp = (now - timedelta(hours=2)).isoformat()
        old_stamp = (now - timedelta(hours=7)).isoformat()

        # Recente (2h atrás) deve ser considerado fresco
        if not fresh({"checked_at": recent_stamp}, settings):
            violations.append("availability_guard.fresh rejeitou incorretamente registo com 2h.")

        # Antigo (7h atrás) deve expirar dado o TTL de 6h
        if fresh({"checked_at": old_stamp}, settings):
            violations.append("availability_guard.fresh aceitou incorretamente registo com 7h (TTL deve ser 6h).")
        else:
            details.append("TTL de disponibilidade de 6h verificado com sucesso via availability_guard.fresh.")

    except Exception as exc:
        violations.append(f"Erro ao testar availability_guard.fresh: {exc}")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=7,
        name="Sincronização estrita de disponibilidade (6h) vs. cache de hardware (24h)",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Pilar 8: Integridade da suite de testes (423+ testes)
# ---------------------------------------------------------------------------
def audit_pillar_8_test_suite_integrity(config: dict[str, Any], repo_root: Path) -> PillarResult:
    violations: list[str] = []
    details: list[str] = []
    tests_dir = repo_root / "tests"

    if not tests_dir.is_dir():
        violations.append(f"Diretório de testes não encontrado: {tests_dir}")
        return PillarResult(
            pillar_number=8,
            name="Integridade da suite de testes",
            passed=False,
            violations=violations,
            details=details,
        )

    test_files = list(tests_dir.glob("test_*.py"))
    # O repositório possui tipicamente 55+ ficheiros de teste que compõem os 423+ testes
    if len(test_files) < 45:
        violations.append(
            f"Contagem de ficheiros de teste suspeita: {len(test_files)} (esperado >= 45 para cobrir os 423+ testes)"
        )
    else:
        details.append(f"{len(test_files)} ficheiros de teste unitários detetados em tests/.")

    # Ficheiros críticos de salvaguarda que nunca podem ser eliminados
    critical_tests = [
        "test_availability_guard.py",
        "test_closeout_policy.py",
        "test_opportunity_guard.py",
        "test_tier_policy_guard.py",
        "test_technical_scoring.py",
        "test_keyboard_optional.py",
        "test_price_guard.py",
        "test_rejection_guard.py",
        "test_tracker.py",
    ]
    for ct in critical_tests:
        if not (tests_dir / ct).is_file():
            violations.append(f"Ficheiro de teste guardrail crítico ausente: tests/{ct}")

    # Inspeciona workflow do CI
    ci_workflow = repo_root / ".github" / "workflows" / "ci.yml"
    if ci_workflow.is_file():
        ci_content = ci_workflow.read_text(encoding="utf-8")
        if "unittest discover" not in ci_content:
            violations.append(".github/workflows/ci.yml não executa descoberta integral de unittest.")
        else:
            details.append("CI configurado com descoberta integral de testes (unittest discover).")
    else:
        violations.append("Ficheiro .github/workflows/ci.yml não encontrado.")

    passed = len(violations) == 0
    return PillarResult(
        pillar_number=8,
        name="Integridade da suite de testes (423+ testes preservados)",
        passed=passed,
        violations=violations,
        details=details,
    )


# ---------------------------------------------------------------------------
# Orquestrador Principal da Auditoria
# ---------------------------------------------------------------------------
def run_system_guardian_audit(
    repo_root: Path | None = None,
    config_path: Path | None = None,
) -> GuardianAuditReport:
    root = repo_root or ROOT
    cfg_path = config_path or (root / "config" / "config.json")
    config = _load_config(cfg_path)

    pillars = [
        audit_pillar_1_laptop_focus(config, root),
        audit_pillar_2_unified_value(config, root),
        audit_pillar_3_os_penalty_and_tristate(config, root),
        audit_pillar_4_exclusions(config, root),
        audit_pillar_5_budget_limits(config, root),
        audit_pillar_6_ntfy_diamond_only(config, root),
        audit_pillar_7_sync_availability_and_cache(config, root),
        audit_pillar_8_test_suite_integrity(config, root),
    ]

    failed_pillars = sum(1 for p in pillars if not p.passed)
    passed_pillars = len(pillars) - failed_pillars
    all_passed = failed_pillars == 0

    summary_text = (
        "Baseline 100% ÍNTEGRA. Todos os 8 pilares cumprem as diretrizes do utilizador."
        if all_passed
        else f"VETO ATIVADO! {failed_pillars} de 8 pilares foram violados."
    )

    return GuardianAuditReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo_root=str(root),
        passed=all_passed,
        total_pillars=len(pillars),
        passed_pillars=passed_pillars,
        failed_pillars=failed_pillars,
        pillars=pillars,
        veto_triggered=not all_passed,
        summary=summary_text,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auditoria da Baseline do Sistema LapIntel PT (Agente 4 - System Guardian)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "config.json",
        help="Caminho para o ficheiro de configuração config.json",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Caminho para a raiz do repositório",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Caminho opcional para exportar o relatório em JSON",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Apresenta detalhes exaustivos da verificação de cada pilar",
    )
    args = parser.parse_args()

    report = run_system_guardian_audit(repo_root=args.root, config_path=args.config)

    print("=" * 72)
    print("LapIntel PT — Auditoria do Salvaguardador do Sistema (System Guardian)")
    print(f"Timestamp: {report.timestamp}")
    print(f"Resultado Geral: {'[PASSOU - 100% ÍNTEGRO]' if report.passed else '[FALHOU - VETO ACIONADO]'}")
    print("=" * 72)

    for p in report.pillars:
        status_mark = "✔" if p.passed else "✖"
        print(f"[{status_mark}] Pilar {p.pillar_number}: {p.name}")
        if args.verbose or not p.passed:
            for detail in p.details:
                print(f"    • {detail}")
        if not p.passed:
            for violation in p.violations:
                print(f"    ! VIOLAÇÃO: {violation}")

    print("-" * 72)
    print(f"Resumo: {report.summary}")
    print("=" * 72)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with args.json_out.open("w", encoding="utf-8") as f:
            json.dump(asdict(report), f, indent=2, ensure_ascii=False)
        print(f"Relatório exportado para: {args.json_out}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
