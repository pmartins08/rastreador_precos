# LapIntel PT — Laptop Market Intelligence Engine

**LapIntel PT** é um motor de inteligência de mercado para portáteis novos em Portugal. Descobre ofertas, interpreta hardware, valida preços, acompanha histórico, cruza configurações entre lojas e calcula Value sem deixar dados de baixa confiança entrarem no ranking.

Versão pública atual: **9.0.0-beta.6**. O estado operacional detalhado está em [`docs/V9_BETA_STATUS.md`](docs/V9_BETA_STATUS.md).

## Objetivo

O sistema foi criado para apoiar uma compra real de portátil para utilização diária universitária/engenharia e gaming. O cérebro técnico avalia quatro dimensões — produtividade, gaming, longevidade e portabilidade — e combina o resultado com o preço num `value_score`.

A V8.8.9 permanece como baseline histórica do primeiro ciclo concluído. Os preços e rankings dessa fase são histórico, não recomendações atuais.

## Política de decisão

| Tier | Regra base |
|---|---:|
| Bronze | Value ≥ 70 |
| Prata | Value ≥ 90 |
| Ouro | Value ≥ 110 |
| Diamante | **Value > 120** |

A política final de tier é protegida por guards próprios. Os alertas normais NTFY são enviados apenas para **Ouro** e **Diamante**; uma alteração material de preço obriga a recalcular Value/tier antes de qualquer alerta.

## Universo monitorizado

Nove lojas estão configuradas:

**PCDiga · PcComponentes · Globaldata · Radio Popular · Darty · UPTECHBOX · CHIP7 · FNAC · Worten**

O sistema distingue três níveis importantes:

- **live** — preço/identidade confirmados diretamente por uma fonte suficientemente forte;
- **discovery** — o sistema consegue encontrar fichas/produtos, mas ainda não lhes dá autoridade económica;
- **blocked** — não existe neste momento uma rota pública produtiva suficiente.

Índices de pesquisa públicos podem ser usados como camada de discovery para lojas bloqueadas. Um preço encontrado num snippet fica sempre `INDEX_ONLY`: não pode entrar no scoring, histórico económico ou NTFY sozinho. A promoção a candidato exige identidade forte (EAN/MPN, conforme a loja) e confirmação live de preço com confiança HIGH.

## Arquitetura

O pipeline separa responsabilidades:

1. **Discovery** — categorias, paginação, campanhas, catálogos públicos, sitemaps, feeds autorizados opcionais e search-index conservador.
2. **Identity** — EAN/MPN/SKU e matching cross-store com veto explícito a conflitos de hardware.
3. **Price Truth** — confirmação de preço, deteção de outliers, consenso de mercado e quarentena de valores suspeitos.
4. **Brain** — scoring técnico base preservado e guards de hardware/GPU/display.
5. **Decision Truth** — preço efetivo, Value, tier, ranking e política de alerta coerentes.
6. **History** — séries compactas, ranking histórico, integridade e aprendizagem de acesso.

Principais travões de segurança: `price_guard`, `market_guard`, `matching_guard`, `history_integrity_guard`, `coverage_guard`, `tier_policy_guard`, `search_index_identity_guard` e `search_index_live_validation_guard`.

## Orçamento e elegibilidade

- equipamento novo; usados, recondicionados e outlet são excluídos;
- `budget_soft`: 1.300 €;
- limite normal: 1.500 €;
- campanhas confirmadas podem tornar elegível um artigo acima do limite normal quando o checkout efetivo fica dentro do orçamento;
- teclado português é informação valorizada, não gate obrigatório;
- layouts explicitamente indesejados podem ser tratados na análise final sem adulterar o scoring técnico.

## Operação

A produção corre em GitHub Actions de forma periódica e pode ser executada manualmente. O estado persistente fica em `data/` e é atualizado com merge concorrente controlado.

Para uma execução completa é necessário `NTFY_TOPIC`. `AWIN_DATAFEED_API_KEY` é opcional: quando ausente, o suporte Awin é um no-op e nenhum feed é inventado.

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m compileall -q runner.py tracker.py scraper.py version.py src tests scripts
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
python runner.py
```

## Estrutura

```text
.
├── runner.py
├── tracker.py
├── scraper.py
├── version.py
├── src/
├── config/config.json
├── data/
├── tests/
├── scripts/
├── docs/
└── .github/workflows/
```

## Documentação

- [`docs/V9_BETA_STATUS.md`](docs/V9_BETA_STATUS.md) — estado operacional atual;
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — arquitetura;
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — operação e diagnóstico;
- [`docs/STORE_ACCESS.md`](docs/STORE_ACCESS.md) — estratégias de acesso;
- [`docs/GPU_CALIBRATION.md`](docs/GPU_CALIBRATION.md) — calibração GPU/iGPU;
- [`docs/PROJECT_STORY.md`](docs/PROJECT_STORY.md) — evolução histórica do projeto;
- [`CHANGELOG.md`](CHANGELOG.md) — histórico funcional consolidado.

## Estado do projeto

A V9 beta está ativa e continua conservadora por desenho: **mais cobertura nunca justifica reduzir a confiança necessária para um preço influenciar uma decisão**. O próximo salto para V9 estável depende sobretudo de converter discovery das lojas bloqueadas em validação live sustentável e de continuar a melhorar o matching sem falsos merges.

## Créditos

**Pedro Martins** — ideia, requisitos, decisões de produto, validação e desenvolvimento.

**ChatGPT (OpenAI)** — co-desenvolvimento técnico assistido: arquitetura, implementação, debugging, testes, análise das runs e documentação.
