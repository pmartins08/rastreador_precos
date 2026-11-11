# Documento Normativo: Baseline Inegociável do Sistema LapIntel PT
**Papel Operacional:** Agente 4 — Salvaguardador do Sistema (System Guardian & Baseline Verifier)  
**Versão da Baseline:** V9 Estável / Transição V10  
**Data:** 11 de Novembro de 2026  
**Localização do Projeto:** `lapintel-main`

---

## 1. Missão e Princípios de Salvaguarda

O LapIntel PT foi concebido e calibrado pelo utilizador como um motor de elevada precisão para identificação e ranqueamento de oportunidades económicas em Portugal. A sua eficácia assenta em contratos rigorosos de integridade de dados, pontuação técnica imune a incentivos comerciais e filtros de compra sem concessões.

O **Salvaguardador do Sistema (System Guardian)** atua como a autoridade de fiscalização interna da integridade do sistema. A sua função é:
1. Assegurar que a base de conhecimento e código construída pelo utilizador se mantém 100% intacta.
2. Garantir que todas as evoluções arquiteturais (incluindo o protótipo multi-agente V10 e novas integrações) expandem as capacidades da plataforma sem remover, degradar ou afrouxar propriedades e contratos existentes.
3. Exercer o **Protocolo de Veto** de forma automática caso qualquer subagente, proposta ou alteração tente violar os pilares fundamentais.

---

## 2. Os 8 Pilares Inegociáveis da Baseline

### Pilar 1: Foco Exclusivo em Computadores Portáteis
- **Regra:** O escopo do sistema limita-se estritamente a computadores portáteis (laptops/notebooks).
- **Proibições:** É expressamente vedada a admissão, rastreio ou pontuação de qualquer outra categoria (computadores de secretária/desktops, monitores avulsos, placas gráficas avulsas, periféricos isolados como ratos e teclados, consolas portáteis não PC, tablets ou smartphones).
- **Implementação:**
  - Todas as entradas de lojas em `config/config.json` (`category_urls`) devem manter ativa a flag `"laptop_only": true` e apontar exclusivamente para taxonomias de portáteis.
  - O motor de normalização e descoberta (`scraper.py` e `search_index_guard.py`) mantém filtros de rejeição por termos proibidos no título e no caminho da URL.

### Pilar 2: Fórmula Unificada do Value V9/V10 e Pontuação Técnica Preservadas
- **Regra:** O cálculo de valor económico é regido pela fórmula unificada de oportunidade, que harmoniza o valor intrínseco do equipamento com o contexto gaming e o histórico de preço, sem duplas penalizações ou bónus duplicados.
- **Fórmula Mandatória:**
  $$\text{Value} = \min\left(150.0, \, 0.80 \times \text{BaseValue} + 0.20 \times (\text{Gaming} \times 1.5) + \text{BonusHistorico}\right)$$
  - $\text{BaseValue}$: Pontuação base do cérebro sem bónus de preço artificial (`value_score_sem_bonus`), calculada estritamente sobre a pontuação técnica ponderada e o custo total de aquisição.
  - $\text{Gaming}$: Score técnico de desempenho gráfico (0 a 100) escalonado com multiplicador 1.5 (peso efetivo de 30 pontos no teto máximo de 150).
  - $\text{BonusHistorico}$: Bonificação estrita de contexto histórico baseada em mínimos observados (máximo absoluto de 5.0 pontos; 0 se observado menos de 3 dias).
- **Invariantes:**
  - `"unified_value_enabled": true` em `config/config.json`.
  - `"exceptional_deal_bonus_max": 0.0`: O antigo bónus absoluto de preço baixo foi extinto; o preço já é premiado contínua e boundedly via `price_score`.
  - As funções de utilidade de ecrã (resolução 40%, brilho nits 20%, gamut sRGB/DCI-P3/NTSC 20%, painel 10%, dimensão 10%) e multiplicador de TGP em `technical_scoring.py` são definitivas e refletem limites reais de engenharia, nunca benchmarks teóricos fabricados.

### Pilar 3: Penalização Estrita de +110 € para Sem SO / FreeDOS e Tri-State de Incerteza
- **Regra:** Nenhum portátil sem sistema operativo utilizável pode ser comparado diretamente com equipamentos com licença Windows sem que o custo real de regularização seja repercutido no preço efetivo de compra.
- **Custos e Estados de SO (`os_status`):**
  - `'windows'`: Windows 10/11 Home ou Pro confirmado na ficha técnica $\rightarrow$ custo adicional: **0,00 €**.
  - `'none'`: Ausência de SO, FreeDOS, Linux, Endless OS ou DOS confirmado $\rightarrow$ penalização mandatória de **+110,00 €** (`windows_installation_cost_eur: 110.0`).
  - `'unknown'`: Informação de sistema operativo omissa na ficha pública $\rightarrow$ custo de instalação **não presumido** (0,00 € adicionais), mantendo o artigo elegível mas gerando obrigatoriamente o alerta: `"Sistema operativo por confirmar; custo de instalação não presumido."` e agendando revalidação gradual de identidade.
  - `'conflict'`: Evidência mista (ex.: título diz Windows mas tabela de especificações diz FreeDOS) $\rightarrow$ custo **não presumido** (0,00 €), com alerta registado e necessidade de confirmação humana ou de fonte oficial do fabricante.
- **Impacto Económico:** O cálculo de `purchase_total_eur` (`preço + custo_instalação`) substitui o preço de montra no cálculo de Value e na verificação do teto orçamental.

### Pilar 4: Exclusão Mandatória de Teclados Espanhóis ('ES') e de Artigos Usados/Recondicionados/Exposição
- **Regra 4A (Teclados):** Qualquer portátil com layout de teclado explicitamente identificado como Espanhol (`keyboard_layout == 'es'`) é sumariamente **REJEITADO** no pipeline de admissão (`"Teclado espanhol confirmado."`). Layouts em Português (`'pt'`), Inglês/Internacional (`'en'`) ou não especificados (`'unknown'`) são permitidos.
- **Regra 4B (Condição do Produto):** Artigos recondicionados, seminovos, em segunda mão, caixas abertas ou unidades de exposição em loja física são sumariamente **REJEITADOS** (`scraper.eligible()` devolve `False`). Apenas produtos novos, selados de fábrica e com garantia integral de consumidor são elegíveis.

### Pilar 5: Limites Orçamentais Inegociáveis (1.400 € Preferencial / 1.600 € Teto Máximo com SO)
- **Regra:** O espectro orçamental da plataforma protege o utilizador de dispersão para nichos de luxo com retornos decrescentes:
  - `budget_soft`: **1.400,00 €** — Orçamento preferencial de referência. Abaixo deste patamar, a pontuação de preço é suave, contínua e incentivada (`below_soft_price_points_per_eur: 0.08`, teto 20.0).
  - `budget_hard`: **1.600,00 €** — Teto máximo absoluto inegociável.
- **Condição de Rejeição Mandatória:**
  $$\text{purchase\_total\_eur} = \text{preço\_montra} + \text{custo\_instalação} > 1.600,00 € \implies \textbf{REJEITADO}$$
  Um portátil com preço de montra de 1.520 € sem sistema operativo resulta num custo total de $1.520 + 110 = 1.630 €$, sendo imediatamente rejeitado pelo filtro orçamental.

### Pilar 6: Alertas NTFY Exclusivos para Tier Diamante (Value >= 120.0 e Stock Confirmado)
- **Regra:** O canal de alertas push (NTFY) foi concebido para alta relevância e silêncio operacional, evitando fadiga de notificações.
- **Condições Cumulativas para Alerta de Oportunidade:**
  1. $\text{Tier} == \textbf{DIAMANTE}$ (`alerta_min_tier: "DIAMANTE"`).
  2. $\text{Value} \ge 120.0$ (`min_value_score_alerta: 120.0` e `diamante_value_min: 120.0`).
  3. $\text{Disponibilidade Confirmada}$: `offer_availability.eligible == True`.
  4. Queda de preço real superior ou igual a 5,00 € (`alerta_queda_preco_eur: 5.0`) ou nova oportunidade em stock.
- **Condições de Silêncio:**
  - Sem confirmação de disponibilidade elegível, não há tier nem emissão de alerta (mesmo que o Value teórico seja superior a 120.0).
  - O heartbeat periódico do NTFY encontra-se desativado em produção (`heartbeat_ntfy: false`).

### Pilar 7: Sincronização Estrita de Disponibilidade (6h) vs. Cache de Hardware (24h) com Live Refresh Ativo
- **Regra:** Desacoplamento temporal estrito entre a imutabilidade do hardware e a volatilidade comercial:
  - **Cache de Hardware e Preço:** TTL de 24 horas (`price_confirmation_ttl_hours: 24`). Especificações de CPU, GPU, ecrã e RAM não mudam no tempo.
  - **Cache de Disponibilidade/Stock:** TTL estrito de **6 horas** (`availability_ttl_hours: 6`).
- **Mecanismo de Live Refresh:**
  - Após 6 horas, o estado de disponibilidade expira. Lojas com stock não explícito ou com políticas mistas de entrega (como Darty, Auchan, Clickfiel e Rádio Popular) acionam sondagens ativas de entrega ao domicílio (`home_delivery: True`).
  - Ofertas com disponibilidade expirada nunca recebem tier ativo ou alerta sem nova confirmação live.

### Pilar 8: Integridade Absoluta da Suite de Testes (423+ Testes sem Regressões)
- **Regra:** O repositório conta com uma malha de proteção de mais de 423 testes unitários e de integração organizados em `tests/`.
- **Requisitos de Aceitação:**
  - `python -m unittest discover -s tests -p 'test_*.py' -v` deve passar com **0 falhas e 0 erros**.
  - Validação estrita de sintaxe Python via `compileall` em todos os módulos (`src`, `tests`, `scripts`).
  - Validação estrita do ficheiro de configuração via `json.tool config/config.json`.
  - Auditoria de histórico e thresholds (`history_audit.py` e `tier_threshold_audit.py`).
  - Nenhuma alteração de código pode remover testes existentes para mascarar regressões ou afrouxar asserções.

---

## 3. Protocolo de Veto Operacional

Caso qualquer proposta, agente autónomo, subagente de desenvolvimento ou modificação humana tente introduzir alterações no sistema, o **System Guardian** aplica o seguinte fluxo decisório:

```
[Início: Deteção de Alteração / Proposta]
               │
               ▼
┌──────────────────────────────────────────────┐
│  Executar scripts/system_guardian_audit.py   │
└──────────────────────────────────────────────┘
               │
               ├───────────────────┬───────────────────┐
               ▼                   ▼                   ▼
    [Violação de Pilar]     [Afrouxamento]      [100% Conforme]
               │                   │                   │
               ▼                   ▼                   ▼
     ┌───────────────────┐┌──────────────────┐┌─────────────────┐
     │  VETO AUTOMÁTICO  ││ PEDIDO AUDIÊNCIA ││   APROVAÇÃO E   │
     │ Bloqueio Imediato ││  AO UTILIZADOR   ││  REGISTO LIMPO │
     └───────────────────┘└──────────────────┘└─────────────────┘
```

### Regras do Veto Automático:
1. **Tentativa de diluição de categorias:** Propostas para incluir telemóveis, tablets, consolas ou desktops sem autorização expressa do utilizador são **vetadas no primeiro ciclo**.
2. **Alteração de limiares de alerta:** Tentativas de descer o limiar de alerta NTFY para Ouro, Prata ou baixar o threshold de 120.0 são **vetadas imediatamente**.
3. **Remoção de custos de SO:** Qualquer supressão da taxa de 110 € para FreeDOS ou tentativa de presumir licença Windows em artigos sem confirmação é **vetada**.
4. **Admissão de espanhóis ou recondicionados:** Qualquer afrouxamento do filtro de teclados `'es'` ou aceitação de recondicionados é **vetado**.
5. **Subida do orçamento hard:** Qualquer tentativa de aceitar compras acima de 1.600 € é **vetada**.

---

## 4. Matriz de Mapeamento Técnico dos Pilares

| Pilar | Ficheiro(s) de Código Fonte | Chaves de Configuração (`config/config.json`) | Testes Unitários de Salvaguarda |
|---|---|---|---|
| **1. Foco Portáteis** | `src/scraper.py`, `src/search_index_guard.py` | `category_urls[].laptop_only: true` | `test_tracker.py`, `test_search_index_guard.py` |
| **2. Fórmula Value** | `src/opportunity_guard.py`, `src/technical_scoring.py` | `unified_value_enabled: true`, `exceptional_deal_bonus_max: 0.0` | `test_closeout_policy.py`, `test_technical_scoring.py` |
| **3. SO +110 €** | `src/purchase_policy.py`, `src/opportunity_guard.py` | `windows_installation_cost_eur: 110.0` | `test_closeout_policy.py`, `test_opportunity_guard.py` |
| **4. Teclado ES & Usados** | `src/purchase_policy.py`, `src/scraper.py` | Regras de rejeição de hardware e catálogo | `test_keyboard_optional.py`, `test_rejection_guard.py` |
| **5. Limites Orçamento** | `src/opportunity_guard.py`, `src/scraper.py` | `budget_soft: 1400.0`, `budget_hard: 1600.0` | `test_closeout_policy.py`, `test_current_budget.py` |
| **6. Alertas Diamante** | `src/tier_policy_guard.py`, `src/opportunity_guard.py` | `alerta_min_tier: "DIAMANTE"`, `diamante_value_min: 120.0` | `test_tier_policy_guard.py`, `test_price_change_alert_guard.py` |
| **7. Sincronização 6h/24h** | `src/availability_guard.py` | `price_confirmation_ttl_hours: 24`, TTL disponibilidade: 6h | `test_availability_guard.py`, `test_state_refresh_guard.py` |
| **8. Suite de Testes** | Toda a pasta `tests/` | `.github/workflows/ci.yml` | Todos os 423+ testes em `tests/` |

---

## 5. Validação Programática Contínua

O cumprimento desta baseline é verificado em permanência pelo script executável:
```bash
python scripts/system_guardian_audit.py --verbose
```
O CI do GitHub Actions em `.github/workflows/ci.yml` deve executar este script como barreira obrigatória antes de qualquer merge na branch `main`. Se o script devolver exit code `1`, o build falha imediatamente com a discriminação da violação do pilar correspondente.
