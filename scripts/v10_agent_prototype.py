#!/usr/bin/env python3
"""Protótipo da arquitetura LapIntel V10 baseada no Google Antigravity SDK.

Demonstra:
- Schemas estruturados (`LaptopSpecExtraction` e `DealDecision`) para extração
  técnica (TGP, brilho SDR, gamut, SO tri-state, layout) e decisão de compra;
- Orquestrador (`Coordinator Agent`) com subagentes (`spec_extractor` e
  `deal_auditor`) via `allowed_subagents` e `max_subagent_depth`;
- Execução híbrida: Cloud (`LocalAgentConfig`), On-Device gratuito via LiteRT
  (`LiteRTAgentConfig`) ou servidor local OpenAI-compatível (`LocalOpenAIAgentConfig`);
- Limites operacionais e de tokens (`BudgetConfig` + inspeção de `StopReason`);
- Triggers periódicos (`every`) e persistência de sessão (`save_dir`);
- Modo `--dry-run` seguro para validação e CI sem necessidade de pacotes externos.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Literal

try:
    import pydantic  # type: ignore[import-not-found]

    HAS_PYDANTIC = True
except ImportError:
    pydantic = None  # type: ignore[assignment]
    HAS_PYDANTIC = False

try:
    from google.antigravity import (  # type: ignore[import-not-found]
        Agent,
        LiteRTAgentConfig,
        LocalAgentConfig,
        LocalOpenAIAgentConfig,
        types,
    )
    from google.antigravity.triggers import (  # type: ignore[import-not-found]
        TriggerContext,
        every,
    )

    HAS_ANTIGRAVITY_SDK = True
except ImportError:
    Agent = None  # type: ignore[assignment]
    LiteRTAgentConfig = None  # type: ignore[assignment]
    LocalAgentConfig = None  # type: ignore[assignment]
    LocalOpenAIAgentConfig = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    TriggerContext = Any  # type: ignore[assignment,misc]
    every = None  # type: ignore[assignment]
    HAS_ANTIGRAVITY_SDK = False


# =============================================================================
# 1. Schemas Estruturados (Pydantic quando disponível; fallback dataclass no CI)
# =============================================================================

OSStatusType = Literal["included", "none_or_freedos", "unknown"]
TierType = Literal["Diamante", "Ouro", "Prata", "Bronze", "Sem Tier"]

if HAS_PYDANTIC:

    class LaptopSpecExtraction(pydantic.BaseModel):
        """Especificações técnicas extraídas e verificadas ao nível do SKU/MPN."""

        store: str
        sku_or_mpn: str
        ean: str | None = None
        brand: str
        model_name: str
        listed_price_eur: float
        promo_discount_eur: float = 0.0
        gpu_model: str
        gpu_tgp_watts: int | None = None
        display_nits: int | None = None
        color_gamut_srgb_pct: int | None = None
        ram_gb: int
        storage_gb: int
        battery_wh: float | None = None
        weight_kg: float | None = None
        os_status: OSStatusType = "unknown"
        keyboard_layout: str = "PT"
        is_new_condition: bool = True
        in_stock_confirmed: bool = False

    class DealDecision(pydantic.BaseModel):
        """Decisão final auditada para uma oportunidade LapIntel V10."""

        spec: LaptopSpecExtraction
        effective_price_eur: float
        os_install_surcharge_eur: float
        eligible: bool
        ineligibility_reason: str | None = None
        value_score: float
        tier: TierType
        should_notify_ntfy: bool
        audit_summary: str

else:

    @dataclass
    class LaptopSpecExtraction:  # type: ignore[no-redef]
        """Fallback de especificações técnicas quando Pydantic não está instalado."""

        store: str
        sku_or_mpn: str
        brand: str
        model_name: str
        listed_price_eur: float
        gpu_model: str
        ram_gb: int
        storage_gb: int
        ean: str | None = None
        promo_discount_eur: float = 0.0
        gpu_tgp_watts: int | None = None
        display_nits: int | None = None
        color_gamut_srgb_pct: int | None = None
        battery_wh: float | None = None
        weight_kg: float | None = None
        os_status: OSStatusType = "unknown"
        keyboard_layout: str = "PT"
        is_new_condition: bool = True
        in_stock_confirmed: bool = False

    @dataclass
    class DealDecision:  # type: ignore[no-redef]
        """Fallback da decisão final quando Pydantic não está instalado."""

        spec: LaptopSpecExtraction
        effective_price_eur: float
        os_install_surcharge_eur: float
        eligible: bool
        value_score: float
        tier: TierType
        should_notify_ntfy: bool
        audit_summary: str
        ineligibility_reason: str | None = None


# =============================================================================
# 2. Políticas e Ferramenta Determinística de Avaliação (Custom Tool V10)
# =============================================================================

PREFERRED_BUDGET_EUR = 1400.0
MAX_BUDGET_EUR = 1600.0
NO_OS_SURCHARGE_EUR = 110.0
ALLOWED_BRANDS = {"asus", "lenovo", "hp", "acer", "gigabyte"}


def evaluate_laptop_deal_v10(
    store: str,
    sku_or_mpn: str,
    brand: str,
    model_name: str,
    listed_price_eur: float,
    gpu_model: str,
    ram_gb: int,
    storage_gb: int,
    promo_discount_eur: float = 0.0,
    gpu_tgp_watts: int | None = None,
    display_nits: int | None = None,
    color_gamut_srgb_pct: int | None = None,
    battery_wh: float | None = None,
    weight_kg: float | None = None,
    os_status: str = "unknown",
    keyboard_layout: str = "PT",
    is_new_condition: bool = True,
    in_stock_confirmed: bool = False,
    historical_bonus_pts: float = 0.0,
) -> str:
    """Calcula a elegibilidade, custo total e Value V9/V10 para um portátil.

    Aplica estritamente os guardrails do LapIntel PT:
    - Apenas artigos novos e com stock confirmado;
    - Exclusão de teclados espanhóis ('ES') e marcas fora da política;
    - Sobretaxa de +110 € quando Sem SO / FreeDOS explícito;
    - Orçamento máximo de 1.600 € (incluindo instalação de SO);
    - Tier Diamante >= 120.0 (único que ativa notificação NTFY).

    Args:
        store: Nome da loja portuguesa.
        sku_or_mpn: Referência exata do fabricante (MPN/SKU).
        brand: Marca do portátil.
        model_name: Designação comercial do modelo.
        listed_price_eur: Preço listado na loja em euros.
        gpu_model: Modelo da GPU dedicada ou integrada.
        ram_gb: Memória RAM em GB.
        storage_gb: Armazenamento SSD em GB.
        promo_discount_eur: Desconto promocional confirmado no carrinho.
        gpu_tgp_watts: TGP confirmado da GPU em Watts (opcional).
        display_nits: Brilho SDR confirmado em nits (opcional).
        color_gamut_srgb_pct: Cobertura sRGB em percentagem (opcional).
        battery_wh: Capacidade da bateria em Wh (opcional).
        weight_kg: Peso em kg (opcional).
        os_status: Estado do SO ('included', 'none_or_freedos' ou 'unknown').
        keyboard_layout: Idioma do teclado (ex.: 'PT', 'EN', 'ES').
        is_new_condition: True se artigo novo (não recondicionado/usado).
        in_stock_confirmed: True se disponibilidade imediata confirmada.
        historical_bonus_pts: Bónus histórico validado (0.0 a 5.0 pontos).
    """
    surcharge = NO_OS_SURCHARGE_EUR if os_status == "none_or_freedos" else 0.0
    effective_price = round(max(0.0, listed_price_eur - promo_discount_eur) + surcharge, 2)

    reasons: list[str] = []
    if not is_new_condition:
        reasons.append("Artigo usado, recondicionado ou de exposição excluído.")
    if not in_stock_confirmed:
        reasons.append("Sem stock confirmado (sem tier, ranking ou alerta).")
    if keyboard_layout.strip().upper() in {"ES", "ESP", "SPANISH", "ESPANHOL"}:
        reasons.append("Teclado espanhol explicitamente identificado excluído.")
    if brand.strip().lower() not in ALLOWED_BRANDS:
        reasons.append(f"Marca '{brand}' fora da política permitida.")
    if effective_price > MAX_BUDGET_EUR:
        reasons.append(
            f"Custo efetivo ({effective_price:.2f} €) excede o máximo de {MAX_BUDGET_EUR:.0f} €."
        )

    if reasons:
        payload = {
            "store": store,
            "sku_or_mpn": sku_or_mpn,
            "effective_price_eur": effective_price,
            "os_install_surcharge_eur": surcharge,
            "eligible": False,
            "ineligibility_reason": " ".join(reasons),
            "value_score": 0.0,
            "tier": "Sem Tier",
            "should_notify_ntfy": False,
        }
        return json.dumps(payload, ensure_ascii=False)

    # Pontuação base técnica e gaming alinhada com os pesos V9/V10
    gpu_upper = gpu_model.upper()
    if "4070" in gpu_upper or "5070" in gpu_upper:
        gaming_score = 92.0
    elif "4060" in gpu_upper or "5060" in gpu_upper:
        gaming_score = 84.0
    elif "4050" in gpu_upper:
        gaming_score = 72.0
    else:
        gaming_score = 60.0

    if gpu_tgp_watts is not None:
        if gpu_tgp_watts >= 115:
            gaming_score += 8.0
        elif gpu_tgp_watts < 75:
            gaming_score -= 8.0

    base_value = 78.0
    if ram_gb >= 32:
        base_value += 10.0
    elif ram_gb >= 16:
        base_value += 5.0

    if storage_gb >= 1000:
        base_value += 6.0

    if display_nits is not None and display_nits >= 350:
        base_value += 5.0
    if color_gamut_srgb_pct is not None and color_gamut_srgb_pct >= 100:
        base_value += 5.0
    if battery_wh is not None and battery_wh >= 75:
        base_value += 3.0
    if weight_kg is not None and weight_kg <= 2.3:
        base_value += 3.0
    if os_status == "unknown":
        base_value -= 4.0

    # Progressão de preço face ao orçamento preferencial (1.400 €)
    price_delta = PREFERRED_BUDGET_EUR - effective_price
    price_adjustment = max(-15.0, min(18.0, price_delta / 25.0))
    base_value += price_adjustment

    clamped_history = max(0.0, min(5.0, historical_bonus_pts))
    unified_value = round(
        min(150.0, (0.80 * base_value) + (0.30 * gaming_score) + clamped_history),
        2,
    )

    if unified_value >= 120.0:
        tier: TierType = "Diamante"
    elif unified_value >= 110.0:
        tier = "Ouro"
    elif unified_value >= 90.0:
        tier = "Prata"
    elif unified_value >= 70.0:
        tier = "Bronze"
    else:
        tier = "Sem Tier"

    os_note = (
        "SO incluído"
        if os_status == "included"
        else (
            f"Sem SO (+{NO_OS_SURCHARGE_EUR:.0f} € aplicados)"
            if os_status == "none_or_freedos"
            else "SO desconhecido (incerteza sinalizada)"
        )
    )
    summary = (
        f"[{tier}] {brand} {model_name} ({sku_or_mpn}) na {store}: "
        f"{effective_price:.2f} € ({os_note}) -> Value {unified_value:.2f}"
    )

    payload = {
        "store": store,
        "sku_or_mpn": sku_or_mpn,
        "effective_price_eur": effective_price,
        "os_install_surcharge_eur": surcharge,
        "eligible": True,
        "ineligibility_reason": None,
        "value_score": unified_value,
        "tier": tier,
        "should_notify_ntfy": tier == "Diamante",
        "audit_summary": summary,
    }
    return json.dumps(payload, ensure_ascii=False)


# =============================================================================
# 3. Construtor da Arquitetura Multi-Agente (Google Antigravity SDK)
# =============================================================================

SYSTEM_INSTRUCTIONS_V10 = """És o Coordinator Agent do LapIntel V10 (Portugal).
O teu objetivo é analisar oportunidades de portáteis no mercado português sem
quebrar nenhum guardrail da política:
1. Delega no subagente 'spec_extractor' a normalização das especificações técnicas
   (TGP, brilho SDR, sRGB, SO tri-state, teclado e MPN/EAN).
2. Delega no subagente 'deal_auditor' ou invoca a ferramenta 'evaluate_laptop_deal_v10'
   para validar elegibilidade, sobretaxa de SO (+110 € se Sem SO/FreeDOS) e Value.
3. Responde estritamente de acordo com o schema estruturado DealDecision.
"""


async def periodic_market_scan_trigger(ctx: TriggerContext) -> None:
    """Trigger periódico (6h/6h) para varrimento autónomo de oportunidades Diamante."""
    await ctx.send(
        "Executa a verificação periódica de 6 horas dos catálogos configurados "
        "e reporta exclusivamente oportunidades Diamante (Value >= 120) em stock."
    )


def build_v10_agent_config(
    *,
    use_local_litert: bool = False,
    model_path: str | None = None,
    ollama_model: str | None = None,
    save_dir: str | None = None,
    conversation_id: str | None = None,
    enable_periodic_trigger: bool = False,
) -> Any:
    """Constrói a configuração do agente LapIntel V10 para Cloud, LiteRT ou Ollama."""
    if not HAS_ANTIGRAVITY_SDK:
        raise RuntimeError(
            "O pacote 'google-antigravity' não está instalado neste ambiente. "
            "Instala com `pip install google-antigravity` ou usa `--dry-run`."
        )

    spec_extractor = types.SubagentConfig(
        name="spec_extractor",
        description=(
            "Extrai especificações verificadas ao nível do SKU/MPN (TGP, brilho SDR, "
            "gamut, estado do Sistema Operativo e idioma do teclado)."
        ),
        capabilities=types.SubagentCapabilities(
            agent_behavior=types.AgentBehavior.AUTONOMOUS,
            enabled_tools=[types.BuiltinTools.VIEW_FILE],
        ),
    )

    deal_auditor = types.SubagentConfig(
        name="deal_auditor",
        description=(
            "Audita disponibilidade real, condição de artigo novo, descontos de "
            "carrinho e valida a pontuação Value/Diamante."
        ),
        capabilities=types.SubagentCapabilities(
            agent_behavior=types.AgentBehavior.AUTONOMOUS,
            enabled_tools=[types.BuiltinTools.VIEW_FILE],
        ),
    )

    budget_config = types.BudgetConfig(
        max_model_calls=12,
        max_tool_calls=24,
        max_input_tokens=80_000,
        max_output_tokens=16_000,
        max_total_tokens=96_000,
    )

    compaction_config = types.CompactionConfig(token_threshold=50_000)
    active_triggers = (
        [every(21600, periodic_market_scan_trigger)] if enable_periodic_trigger else []
    )

    if use_local_litert:
        resolved_path = os.path.expanduser(
            model_path or "~/.litert-lm/models/gemma4-26b/model.litertlm"
        )
        return LiteRTAgentConfig(
            model_path=resolved_path,
            system_instructions=SYSTEM_INSTRUCTIONS_V10,
            tools=[evaluate_laptop_deal_v10],
            budget_config=budget_config,
            response_schema=DealDecision if HAS_PYDANTIC else None,
            save_dir=save_dir,
            conversation_id=conversation_id,
            triggers=active_triggers,
        )

    if ollama_model:
        return LocalOpenAIAgentConfig(
            model=ollama_model,
            base_url="http://localhost:11434/v1",
            system_instructions=SYSTEM_INSTRUCTIONS_V10,
            tools=[evaluate_laptop_deal_v10],
            budget_config=budget_config,
            response_schema=DealDecision if HAS_PYDANTIC else None,
            save_dir=save_dir,
            conversation_id=conversation_id,
            triggers=active_triggers,
        ).lightweight()

    return LocalAgentConfig(
        system_instructions=SYSTEM_INSTRUCTIONS_V10,
        tools=[evaluate_laptop_deal_v10],
        subagents=[spec_extractor, deal_auditor],
        capabilities=types.CapabilitiesConfig(
            agent_behavior=types.AgentBehavior.AUTONOMOUS,
            enable_subagents=True,
            max_subagent_depth=2,
            allowed_subagents=["spec_extractor", "deal_auditor"],
        ),
        budget_config=budget_config,
        compaction_config=compaction_config,
        response_schema=DealDecision if HAS_PYDANTIC else None,
        save_dir=save_dir,
        conversation_id=conversation_id,
        triggers=active_triggers,
    )


# =============================================================================
# 4. Execução Live vs. Simulação Dry-Run (Compatível com CI V9)
# =============================================================================


def run_dry_run_demo() -> dict[str, Any]:
    """Executa uma simulação determinística completa da pipeline V10 sem rede/API."""
    sample_spec = LaptopSpecExtraction(
        store="Globaldata",
        sku_or_mpn="83DH003KPG",
        ean="0198153214501",
        brand="Lenovo",
        model_name="Legion Slim 5 16AHP9",
        listed_price_eur=1249.0,
        promo_discount_eur=50.0,
        gpu_model="RTX 4070",
        gpu_tgp_watts=140,
        display_nits=350,
        color_gamut_srgb_pct=100,
        ram_gb=32,
        storage_gb=1000,
        battery_wh=80.0,
        weight_kg=2.3,
        os_status="none_or_freedos",
        keyboard_layout="PT",
        is_new_condition=True,
        in_stock_confirmed=True,
    )

    eval_json = evaluate_laptop_deal_v10(
        store=sample_spec.store,
        sku_or_mpn=sample_spec.sku_or_mpn,
        brand=sample_spec.brand,
        model_name=sample_spec.model_name,
        listed_price_eur=sample_spec.listed_price_eur,
        promo_discount_eur=sample_spec.promo_discount_eur,
        gpu_model=sample_spec.gpu_model,
        gpu_tgp_watts=sample_spec.gpu_tgp_watts,
        display_nits=sample_spec.display_nits,
        color_gamut_srgb_pct=sample_spec.color_gamut_srgb_pct,
        ram_gb=sample_spec.ram_gb,
        storage_gb=sample_spec.storage_gb,
        battery_wh=sample_spec.battery_wh,
        weight_kg=sample_spec.weight_kg,
        os_status=sample_spec.os_status,
        keyboard_layout=sample_spec.keyboard_layout,
        is_new_condition=sample_spec.is_new_condition,
        in_stock_confirmed=sample_spec.in_stock_confirmed,
        historical_bonus_pts=4.0,
    )
    eval_data = json.loads(eval_json)

    decision = DealDecision(
        spec=sample_spec,
        effective_price_eur=eval_data["effective_price_eur"],
        os_install_surcharge_eur=eval_data["os_install_surcharge_eur"],
        eligible=eval_data["eligible"],
        ineligibility_reason=eval_data["ineligibility_reason"],
        value_score=eval_data["value_score"],
        tier=eval_data["tier"],
        should_notify_ntfy=eval_data["should_notify_ntfy"],
        audit_summary=eval_data["audit_summary"],
    )

    if HAS_PYDANTIC and hasattr(decision, "model_dump"):
        return decision.model_dump()  # type: ignore[no-any-return]
    return asdict(decision)  # type: ignore[arg-type]


async def run_live_agent(args: argparse.Namespace) -> None:
    """Executa uma sessão real do agente LapIntel V10 com Google Antigravity SDK."""
    config = build_v10_agent_config(
        use_local_litert=args.local,
        model_path=args.model_path,
        ollama_model=args.ollama_model,
        save_dir=args.save_dir,
        conversation_id=args.conversation_id,
    )

    async with Agent(config=config) as agent:
        response = await agent.chat(args.prompt)

        structured = await response.structured_output()
        if structured is not None:
            print(json.dumps(structured, indent=2, ensure_ascii=False))
        else:
            print(await response.text())

        # Inspeção explícita de StopReason (alinhada com budget_limits do SDK)
        if response.stop_reason == types.StopReason.MAX_MODEL_CALLS_EXCEEDED:
            print("[ORÇAMENTO V10] Limite de chamadas ao modelo atingido.")
        elif response.stop_reason == types.StopReason.MAX_TOOL_CALLS_EXCEEDED:
            print("[ORÇAMENTO V10] Limite de invocações de ferramentas atingido.")
        elif response.stop_reason == types.StopReason.MAX_TOTAL_TOKENS_EXCEEDED:
            print("[ORÇAMENTO V10] Orçamento total de tokens da sessão atingido.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Processa argumentos de linha de comandos do protótipo V10."""
    parser = argparse.ArgumentParser(
        description="Protótipo LapIntel V10 com Google Antigravity SDK."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa a demonstração determinística offline sem chamadas de API.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Usa LiteRTAgentConfig (execução local gratuita on-device com Gemma 4).",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="Caminho absoluto para o ficheiro .litertlm (usado com --local).",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default=None,
        help="Usa LocalOpenAIAgentConfig com um modelo Ollama local (ex.: gemma4:26b).",
    )
    parser.add_argument(
        "--save-dir",
        type=str,
        default=None,
        help="Diretório para persistência de sessões do agente.",
    )
    parser.add_argument(
        "--conversation-id",
        type=str,
        default=None,
        help="ID da conversa a retomar a partir de --save-dir.",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=(
            "Analisa o portátil Lenovo Legion Slim 5 16AHP9 (MPN 83DH003KPG) na "
            "Globaldata por 1249€ com 50€ de desconto direto no carrinho, RTX 4070 "
            "140W, 32GB RAM, 1TB SSD, ecrã 350 nits 100% sRGB, sem SO, teclado PT "
            "e em stock confirmado."
        ),
        help="Prompt de entrada para análise pelo Coordinator Agent V10.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada CLI do protótipo LapIntel V10."""
    args = parse_args(argv)
    if args.dry_run or not HAS_ANTIGRAVITY_SDK:
        result = run_dry_run_demo()
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "sdk_installed": HAS_ANTIGRAVITY_SDK,
                    "pydantic_installed": HAS_PYDANTIC,
                    "decision": result,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    asyncio.run(run_live_agent(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
