# Rastreador de Preços — V8.8.7

Sistema de inteligência de mercado para portáteis em Portugal. O projeto descobre ofertas em várias lojas, extrai hardware, calcula adequação para **FEUP + gaming**, valida preços, compara configurações entre lojas, mantém histórico e envia oportunidades por **ntfy**.

A linha V8.x está focada em maturação e fiabilidade. V9/V10 são nomes provisórios para a próxima etapa do projeto, não apenas incrementos numéricos.

## Estado atual

- versão pública: **8.8.7**;
- marcas aceites: **ASUS, Lenovo e HP** e respetivas famílias configuradas;
- lojas monitorizadas: **PCDiga, PcComponentes, Globaldata, Radio Popular, Darty, CHIP7, FNAC e Worten**;
- apenas equipamento novo; usados, recondicionados e outlet são excluídos;
- orçamento normal: até **1500 €**, com `budget_soft` em **1300 €**;
- execução automática a cada **6 horas** no GitHub Actions;
- notificações de oportunidade e heartbeat por **ntfy**.

## Como o sistema decide

O cérebro V8 separa quatro dimensões:

1. **FEUP** — RAM, autonomia, armazenamento, ecrã e CPU;
2. **Gaming** — GPU, CPU, refresh rate e RAM;
3. **Longevidade** — RAM/SSD, expansibilidade, autonomia e CPU;
4. **Portabilidade** — peso.

O resultado técnico gera um `score_ranking`. O preço é depois combinado num `value_score` independente do rótulo de tier.

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

### GPU Guard

Ouro e Diamante exigem informação de GPU suficiente para justificar um selo premium.

- GPU dedicada mapeada → pode atingir Ouro/Diamante;
- iGPU explicitamente mapeada → pode atingir Ouro/Diamante se o Value justificar;
- GPU dedicada sem modelo conhecido → máximo Prata;
- iGPU genérica → máximo Prata;
- GPU desconhecida → máximo Prata.

A V8.8.7 acrescenta classes conservadoras para **Intel Arc Graphics 140V/130V** e **Radeon 890M/880M/860M/780M/760M/680M**. A calibração está documentada em [`docs/GPU_CALIBRATION.md`](docs/GPU_CALIBRATION.md).

O `value_score` bruto é preservado quando o GPU Guard limita o tier. Assim, falta de confiança na GPU não apaga uma potencial oportunidade; apenas impede um selo premium injustificado.

### Confiança de preço

Preços anormalmente baixos não são aceites nem rejeitados só pelo valor aparente. O Price Guard procura evidência na própria ficha e, quando existe identidade forte, contexto cross-store por EAN/MPN.

Estados principais:

- `OK` — preço suficientemente suportado;
- `PRICE_UNCONFIRMED` — oportunidade suspeita sem prova forte;
- `PRICE_CONFLICT` — catálogo, ficha ou mercado entram em conflito;
- quarentena — não entra em tiers nem gera alerta de oportunidade.

### Teclado

Um layout explicitamente não português é rejeitado pelo cérebro. Quando o layout não é identificável, o sistema continua a tentar obter evidência da ficha; a confirmação de teclado PT permanece uma área de qualidade de dados a reforçar antes da linha V9.

## Pipeline

```text
lojas / campanhas / sitemap
          ↓
descoberta adaptativa
          ↓
extração de ficha + identidade
          ↓
scraper.py — cérebro técnico base
          ↓
brain / gpu / price / market guards
          ↓
Value + tier
          ↓
matching cross-store + histórico
          ↓
ntfy + persistência de estado
```

`runner.py` é o composition root: carrega o cérebro e instala as camadas de proteção sem substituir a filosofia base do scoring.

## Estrutura do repositório

```text
version.py                 versão pública + compatibilidade de estado
scraper.py                 parsing de hardware + cérebro técnico V8
tracker.py                 descoberta, acesso, cache, matching, estado e ntfy
runner.py                  composição das camadas do runtime

brain_guard.py             correções técnicas comprovadas
 gpu_guard.py              confiança e calibração de GPU/iGPU
price_guard.py             validação de preço e quarentena
market_guard.py            consenso/desacordo cross-store
promotion_guard.py         campanhas e prioridade de descoberta
historical_guard.py        histórico compacto de preços
version_guard.py           compatibilidade com labels do tracker base

config/config.json         lojas, budgets, tiers e pesos
data/                      estado gerado pelo runtime
tests/                     testes de regressão e integração das camadas
docs/                      arquitetura, operação, calibrações e roadmap
.github/workflows/         CI e execução periódica
```

## Estado persistente

Os três ficheiros em `data/` fazem parte do produto e são atualizados pelo workflow:

- `history.json` — ofertas, specs, tiers, alertas e métricas recentes;
- `access_learning.json` — aprendizagem por loja/método/perfil;
- `price_history.json` — histórico diário compacto de preços.

Não devem ser editados manualmente. Mais detalhes em [`data/README.md`](data/README.md).

## Desenvolvimento local

Requer Python 3.11.

```bash
python -m pip install -r requirements.txt
python -m compileall -q .
python -m json.tool config/config.json > /dev/null
python -m unittest discover -s tests -p 'test_*.py' -v
```

Para executar o rastreador é necessário definir `NTFY_TOPIC` no ambiente e depois correr:

```bash
python runner.py
```

## Documentação

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — responsabilidades, fluxo e fronteiras entre módulos;
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — workflows, budgets, estado, ntfy e diagnóstico;
- [`docs/GPU_CALIBRATION.md`](docs/GPU_CALIBRATION.md) — calibração de GPUs integradas;
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — caminho para a próxima grande versão e preparação da futura apresentação;
- [`docs/validation/`](docs/validation/) — validações pós-release preservadas como evidência histórica;
- [`CHANGELOG.md`](CHANGELOG.md) — evolução funcional por versão.

## Princípios do projeto

- o cérebro não é alterado silenciosamente;
- guardrails devem ser pequenos, testáveis e explicáveis;
- preço e qualidade técnica são dimensões separadas;
- identidade cross-store exige evidência forte;
- uma loja bloqueada não justifica bypass de CAPTCHA ou mecanismos anti-bot;
- cache deve aumentar cobertura sem esconder alterações de preço;
- cada mudança relevante deve deixar testes, métricas ou documentação reutilizável para a futura apresentação do modelo.

## Próxima etapa

Antes de promover o projeto para V9/V10, o objetivo é consolidar cobertura real das lojas, qualidade de dados de teclado/GPU, matching cross-store, observabilidade e histórico suficiente para comparar versões com métricas reais. A arquitetura detalhada e os critérios estão no roadmap.
