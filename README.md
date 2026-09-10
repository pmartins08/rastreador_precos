# Rastreador de Preços — V8.8.9

Sistema de monitorização e avaliação de **portáteis novos no mercado português**, orientado para uso académico/engenharia e gaming. O projeto descobre ofertas, extrai especificações, valida preços, compara configurações entre lojas, mantém histórico e envia oportunidades relevantes por **ntfy**.

## O que faz

O pipeline combina quatro áreas principais:

- **Descoberta** — categorias, paginação, campanhas, sitemaps, catálogos públicos e feeds autorizados opcionais.
- **Avaliação** — CPU, GPU, RAM, armazenamento, ecrã, bateria, peso e adequação do teclado.
- **Mercado** — histórico de preços, confirmação de preço, matching por EAN/MPN e comparação cross-store.
- **Operação** — cache, aprendizagem de acesso, budgets, cooldowns, heartbeat e persistência automática no GitHub Actions.

O cérebro técnico separa **FEUP**, **Gaming**, **Longevidade** e **Portabilidade**. O resultado técnico gera um `score_ranking`; o preço é combinado depois num `value_score`.

| Tier | Value mínimo base |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

A decisão final de tier também considera de forma contínua a dimensão Gaming. O `value_score` continua separado dessa influência, para preservar a leitura de valor/preço.

## Universo monitorizado

- **Marcas:** ASUS, Lenovo e HP, incluindo as respetivas famílias configuradas.
- **Lojas:** PCDiga, PcComponentes, Globaldata, Radio Popular, Darty, CHIP7, FNAC e Worten.
- **Estado:** apenas equipamento novo; usados, recondicionados e outlet são excluídos.
- **Orçamento:** `budget_soft` de 1300 € e limite normal de 1500 €.
- **Execução:** GitHub Actions a cada 6 horas, além de push relevante e execução manual.

## Alertas de preço

Uma oferta histórica reencontrada é novamente avaliada com o **preço atual**. Alterações materiais de preço recebem prioridade no pré-ranking para não ficarem fora dos slots de avaliação.

Por defeito:

- queda de pelo menos **5 €** é considerada material;
- o Value e o tier são recalculados com o preço atual;
- alertas de oportunidade são enviados apenas a partir de **OURO**;
- o último preço que gerou alerta funciona como referência para evitar spam por pequenas oscilações;
- uma subida de tier também pode originar novo alerta.

## Confiança de preço

Preços extraordinariamente baixos não são aceites só porque parecem bons. O Price Guard procura confirmação na ficha e, quando existe identidade forte, evidência cross-store.

Estados principais:

- `OK` — preço suficientemente suportado;
- `PRICE_UNCONFIRMED` — preço suspeito sem confirmação forte;
- `PRICE_CONFLICT` — fontes incompatíveis;
- quarentena — a oferta não entra em tiers nem gera alerta até existir evidência suficiente.

## Estrutura do repositório

```text
.
├── runner.py                 # entrypoint e composição do runtime
├── tracker.py                # descoberta, avaliação, estado, matching e ntfy
├── scraper.py                # parsing + cérebro técnico base
├── version.py                # versão pública e compatibilidade de estado
├── src/                      # camadas auxiliares de produção
│   ├── *_guard.py
│   ├── hardware_catalog.py
│   └── README.md
├── config/
│   └── config.json           # lojas, budgets, pesos e thresholds
├── data/                     # estado persistente gerado pelo runtime
├── tests/                    # regressões e integração
├── docs/                     # arquitetura, operação e calibrações
├── .github/workflows/
│   ├── ci.yml
│   └── tracker.yml
├── CHANGELOG.md
└── requirements.txt
```

A raiz fica reservada aos quatro módulos que explicam o sistema de ponta a ponta. As camadas especializadas vivem em `src/`, e os testes permanecem isolados em `tests/`.

## Principais camadas de `src/`

- `brain_guard.py` — correções técnicas pequenas e comprovadas ao scoring;
- `gpu_guard.py` — reconhecimento/calibração GPU e influência contínua no tier;
- `price_guard.py` — confirmação de preço, suspeição e quarentena;
- `market_guard.py` — consenso/desacordo cross-store;
- `historical_guard.py` — histórico diário compacto a 90 dias;
- `price_change_priority_guard.py` — prioridade a alterações materiais de preço;
- `coverage_guard.py` — cache, fallback, cooldown e eficiência de descoberta;
- `promotion_guard.py` — campanhas como geração de leads;
- `catalog_guard.py` — catálogos JSON públicos opcionais;
- `awin_feed_guard.py` — feeds Awin autorizados opcionais;
- `hardware_guard.py` / `hardware_catalog.py` — reconhecimento factual de hardware moderno;
- `state_refresh_guard.py` — fronteira entre gerações de estado;
- `top5_guard.py` — snapshot agregado das melhores configurações atuais.

## Estado persistente

`data/` contém informação operacional, não fixtures de teste:

- `history.json` — ofertas, specs, tiers, alertas e métricas recentes;
- `access_learning.json` — aprendizagem por loja/método/perfil;
- `price_history.json` — histórico diário compacto de preços;
- `top5_current.json` — Top 5 agregado do mercado conhecido;
- `state_epoch.json` — geração atual do estado persistente.

Estes ficheiros são atualizados pelo workflow e não devem ser editados manualmente.

## Desenvolvimento local

Requer Python 3.11.

```bash
python -m pip install -r requirements.txt
```

No Linux/macOS:

```bash
PYTHONPATH=src python -m compileall -q runner.py tracker.py scraper.py version.py src tests
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
python runner.py
```

No PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m compileall -q runner.py tracker.py scraper.py version.py src tests
python -m unittest discover -s tests -p 'test_*.py' -v
python runner.py
```

Para uma execução completa é necessário configurar `NTFY_TOPIC`. `AWIN_DATAFEED_API_KEY` é opcional e só ativa os feeds autorizados quando disponível.

## Automação

- `.github/workflows/ci.yml` valida sintaxe, configuração JSON e toda a suite de testes.
- `.github/workflows/tracker.yml` executa o rastreador, garante heartbeat e persiste o estado com proteção contra pushes concorrentes.

O workflow de produção usa budgets de tempo, requests globais, requests por loja e detail fetches como fusíveis de segurança.

## Documentação

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — fluxo e responsabilidades dos módulos;
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — execução, budgets, estado e diagnóstico;
- [`docs/GPU_CALIBRATION.md`](docs/GPU_CALIBRATION.md) — calibração e influência das GPUs/iGPUs;
- [`docs/AWIN_FEEDS.md`](docs/AWIN_FEEDS.md) — integração opcional de feeds autorizados;
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — próximas melhorias;
- [`CHANGELOG.md`](CHANGELOG.md) — histórico funcional consolidado.

## Princípios

- o cérebro não é alterado silenciosamente;
- preço e qualidade técnica são dimensões separadas;
- identidade cross-store exige evidência forte;
- preço excecional exige confirmação proporcional ao risco;
- cache deve aumentar cobertura sem esconder alterações de preço;
- bloqueios de lojas não justificam bypass de CAPTCHA ou mecanismos anti-bot;
- cada alteração relevante deve ser protegida por testes e observabilidade.
