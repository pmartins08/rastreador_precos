# LapIntel PT — Laptop Market Intelligence Engine

> De um ASUS TUF escolhido à mão a um sistema que descobriu sozinho o portátil certo.

**LapIntel PT** é um motor de inteligência de mercado para portáteis novos em Portugal, desenvolvido para descobrir ofertas, interpretar hardware, validar preços, comparar configurações entre lojas e transformar tudo isso numa decisão explicável.

A linha atual é a **V8.8.9**. O objetivo original do projeto foi cumprido em 13 de setembro de 2026: depois de evoluir de um simples comparador de preços para um sistema de decisão, o LapIntel PT encontrou três oportunidades Diamante e ajudou a fechar a compra do **Lenovo Legion 5 15AHP-682**.

## O resultado que fechou o ciclo

Na última run operacional validada da V8.8.9:

| Métrica | Resultado |
|---|---:|
| Testes | **325 OK** |
| Lojas configuradas | **9** |
| Candidatos descobertos | **356** |
| Candidatos avaliados | **300** |
| Ofertas aceites | **230** |
| Pedidos de acesso | **128** |
| Detalhes abertos | **40** |
| Reutilizações de cache | **266** |
| Tempo de execução | **341,6 s** |
| Lojas com acesso útil | **6 / 9** |

A campanha da Radio Popular foi percorrida em 13 páginas, encontrou 154 itens de listagem e confirmou 142 candidatos. Dez portáteis que estavam acima do limite normal de 1.500 € passaram a entrar no orçamento depois da promoção.

### Os três Diamantes finais

| Posição | Portátil | Loja | Value efetivo |
|---|---|---|---:|
| 🥇 | **Lenovo Legion 5 15AHP-682** | Radio Popular | **123,6** |
| 🥈 | ASUS TUF A16 FA608UH-R72A55CB2 | Radio Popular | **123,3** |
| 🥉 | ASUS TUF A16 FA608UM-R72A56CB1 | Radio Popular | **121,9** |

**Escolha final:** Lenovo Legion 5 15AHP-682 — Ryzen 7 250, RTX 5060 8 GB, 32 GB RAM, 1 TB SSD e ecrã OLED 2560×1600 a 165 Hz. O preço de campanha considerado pelo sistema foi aproximadamente **1.299,99 €**, dentro do orçamento definido.

Há uma simetria de que nos orgulhamos: na V1, o utilizador escolheu primeiro um ASUS TUF e pediu ao software para encontrar o preço. Na V8.8.9, o software percorreu o mercado, avaliou centenas de candidatos, encontrou os Diamantes e ajudou a escolher o Lenovo.

## Como funciona

O pipeline combina quatro áreas principais:

- **Descoberta** — categorias, paginação, campanhas, sitemaps, catálogos públicos e feeds autorizados opcionais.
- **Avaliação** — CPU, GPU, RAM, armazenamento, ecrã, bateria, peso e outras especificações relevantes.
- **Mercado** — histórico de preços, confirmação de preço, matching por EAN/MPN e comparação cross-store.
- **Operação** — cache, aprendizagem de acesso, budgets, cooldowns, heartbeat e persistência automática no GitHub Actions.

O cérebro técnico separa quatro dimensões:

- 🎓 **FEUP** — produtividade, engenharia e utilização académica;
- 🎮 **Gaming** — capacidade gráfica e desempenho em jogos;
- ⏳ **Longevidade** — margem para continuar relevante ao longo dos anos;
- 🎒 **Portabilidade** — adequação ao uso diário, peso e autonomia.

O resultado técnico gera um `score_ranking`; o preço é combinado depois num `value_score`.

## Value e tiers

| Tier | Regra base |
|---|---:|
| Bronze | Value ≥ 70 |
| Prata | Value ≥ 90 |
| Ouro | Value ≥ 110 |
| 💎 Diamante | **Value > 120** |

A regra superior é deliberadamente absoluta: **qualquer Value bruto/efetivo acima de 120 é Diamante**. Abaixo desse limiar, a lógica GPU-aware continua a influenciar o tier sem adulterar o `value_score` bruto.

Os alertas normais de oportunidade são enviados apenas para **OURO** e **DIAMANTE**. Alterações materiais de preço obrigam a recalcular Value/tier antes de decidir se existe novo alerta.

## Universo monitorizado

A V8.8.9 está configurada para nove lojas:

**PCDiga · PcComponentes · Globaldata · Radio Popular · Darty · UPTECHBOX · CHIP7 · FNAC · Worten**

Na run final, PCDiga, Globaldata, Radio Popular, Darty, UPTECHBOX e FNAC deram acesso útil; PcComponentes, CHIP7 e Worten continuaram bloqueadas por HTTP 403 nas rotas testadas. O sistema trata esses bloqueios como limitações operacionais e não tenta contornar CAPTCHA ou mecanismos anti-bot.

- **Estado:** apenas equipamento novo; usados, recondicionados e outlet são excluídos.
- **Orçamento:** `budget_soft` de 1.300 € e limite normal de 1.500 €.
- **Execução:** GitHub Actions a cada 6 horas, além de execução manual.
- **Teclado:** o layout português é valorizado como informação, mas não é um gate obrigatório.

## Guards: inteligência com travões

Um dos maiores aprendizados do projeto foi perceber que um bom algoritmo de decisão continua a falhar se receber dados errados. A arquitetura passou a proteger o cérebro com camadas especializadas:

- `brain_guard.py` — correções técnicas pequenas e comprovadas ao scoring;
- `gpu_guard.py` — reconhecimento/calibração GPU e influência no tier;
- `price_guard.py` — confirmação de preço, suspeição e quarentena;
- `market_guard.py` — consenso/desacordo cross-store;
- `matching_guard.py` — coerência de identidade e veto a merges contraditórios;
- `history_integrity_guard.py` — impede que conflitos conhecidos contaminem o estado persistente;
- `coverage_guard.py` — cache, fallback, cooldown e eficiência de descoberta;
- `promotion_guard.py` / `promotion_coverage_guard.py` — campanhas como fonte económica real, não apenas banners;
- `hardware_guard.py` / `hardware_catalog.py` — reconhecimento factual de hardware moderno;
- `tier_policy_guard.py` — garante a política final de Diamante acima de Value 120.

## Estrutura do repositório

```text
.
├── runner.py                 # entrypoint e composição do runtime
├── tracker.py                # descoberta, avaliação, estado, matching e ntfy
├── scraper.py                # parsing + cérebro técnico base
├── version.py                # versão pública e compatibilidade de estado
├── src/                      # camadas auxiliares de produção
├── config/config.json        # lojas, budgets, pesos e thresholds
├── data/                     # estado persistente gerado pelo runtime
├── tests/                    # regressões e integração
├── scripts/                  # auditoria e probes operacionais
├── docs/                     # arquitetura, operação, história e roadmap
├── .github/workflows/        # CI e execução de produção
├── CHANGELOG.md
└── requirements.txt
```

## Desenvolvimento local

Requer Python 3.11.

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m compileall -q runner.py tracker.py scraper.py version.py src tests scripts
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
python runner.py
```

Para uma execução completa é necessário configurar `NTFY_TOPIC`. `AWIN_DATAFEED_API_KEY` é opcional e só ativa feeds autorizados quando disponíveis.

## Documentação

- [`docs/PROJECT_STORY.md`](docs/PROJECT_STORY.md) — a história completa, do primeiro ASUS TUF ao Lenovo Legion escolhido;
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — fluxo e responsabilidades dos módulos;
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — execução, budgets, estado e diagnóstico;
- [`docs/GPU_CALIBRATION.md`](docs/GPU_CALIBRATION.md) — calibração e influência das GPUs/iGPUs;
- [`docs/STORE_ACCESS.md`](docs/STORE_ACCESS.md) — estado e estratégias de acesso por loja;
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — o que falta para uma eventual V9;
- [`CHANGELOG.md`](CHANGELOG.md) — histórico funcional consolidado.

## Estado do projeto

**Missão principal: cumprida.** A V8.8.9 é suficientemente madura para ter produzido uma decisão real e útil. A V9 permanece como próximo capítulo opcional: não é necessária para provar o projeto, mas pode transformá-lo num motor ainda mais completo de cobertura, matching e inteligência histórica.

## Créditos

**Pedro Martins** — ideia, requisitos, decisões de produto, validação do mercado e desenvolvimento do projeto.

**ChatGPT (OpenAI)** — co-desenvolvimento técnico assistido: arquitetura, implementação, debugging, testes, análise das runs, documentação e apoio à decisão final.

> Construído em conjunto, iterado com dados reais e concluído com uma compra real.
