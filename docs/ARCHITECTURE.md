# Arquitetura do Rastreador

## Objetivo

O projeto separa **decisão técnica**, **observação do mercado** e **guardrails operacionais**. A estrutura mantém o motor principal visível na raiz e isola as camadas especializadas em `src/`.

## Fluxo principal

```text
configuração de lojas
        ↓
descoberta de candidatos
        ↓
enriquecimento / cache
        ↓
extração de hardware e identidade
        ↓
validação de preço e mercado
        ↓
scoring técnico + Value
        ↓
tier + matching cross-store
        ↓
histórico / Top 5
        ↓
ntfy + persistência
```

## Núcleo na raiz

### `scraper.py`

Núcleo técnico base:

- normalização de texto e preços;
- identificação de marca/família;
- extração de CPU, GPU, RAM, SSD, ecrã, bateria, peso e teclado;
- scoring FEUP, Gaming, Longevidade e Portabilidade;
- `score_ranking`, `value_score` e thresholds base.

Alterações aqui têm impacto direto no cérebro e exigem regressões explícitas.

### `tracker.py`

Motor de observação do mercado:

- budgets globais e por loja;
- perfis de acesso e aprendizagem de sucesso/bloqueio;
- descoberta por categoria, segmento, paginação e sitemap;
- cache e refresh progressivo de identidade/preço;
- matching cross-store;
- histórico de ofertas;
- ntfy;
- métricas de cada run;
- merge concorrente de estado.

### `runner.py`

Composition root e entrypoint de produção. Adiciona `src/` ao path, instala as camadas pela ordem definida e expõe a execução normal e o comando `merge-state`.

### `version.py`

Fonte única da versão pública e da compatibilidade de estado. `VERSION` pode evoluir sem obrigar a reiniciar os dados; `STATE_EPOCH` só muda quando existe uma migração/refresh real de estado.

## Camadas em `src/`

### Decisão e hardware

- `brain_guard.py` — corrige lacunas técnicas comprovadas sem redesenhar o cérebro.
- `gpu_guard.py` — reconhecimento explícito de GPUs/iGPUs e influência contínua da dimensão Gaming no tier.
- `hardware_guard.py` — reconhecimento de hardware moderno e enriquecimento conservador.
- `hardware_catalog.py` — catálogo factual usado pelo hardware guard; não contém scores inventados.

### Preço e mercado

- `price_guard.py` — confirmação de preço, suspeição, quarentena e oportunidades excecionais verificadas.
- `market_guard.py` — consenso e desacordo entre lojas para identidades exatas.
- `historical_guard.py` — histórico diário compacto a 90 dias.
- `price_change_priority_guard.py` — dá prioridade de avaliação a alterações materiais de preço já observadas.

### Cobertura e descoberta

- `coverage_guard.py` — cache, fallback histórico controlado, probes adaptativos e cooldown de rotas improdutivas.
- `promotion_guard.py` — campanhas públicas como lead generation, nunca como prova de preço.
- `catalog_guard.py` — catálogos JSON públicos opcionais.
- `awin_feed_guard.py` — feeds autorizados opcionais para lojas com HTML difícil de aceder.
- `sitemap_route_guard.py` — seleção mais inteligente de filhos de sitemap.
- `sitemap_strategy_epoch_guard.py` — reinicia apenas a aprendizagem de sitemap quando a estratégia configurada muda.

### Estado e observabilidade

- `state_refresh_guard.py` — separa gerações de estado persistente quando o `STATE_EPOCH` muda.
- `top5_guard.py` — mantém o Top 5 atual agregado a partir de observações frescas.
- `rejection_guard.py` — classifica motivos de rejeição para telemetria.
- `version_guard.py` — compatibilidade temporária entre os labels históricos ainda existentes no tracker base e a versão pública única definida em `version.py`.

## Ordem de composição

A ordem em `runner.py` é intencional. Em termos funcionais:

1. extensões de parsing/preço de cartão;
2. Brain Guard;
3. Price Guard;
4. tracker base;
5. identidade adicional;
6. versão pública;
7. promoções e GPU/hardware;
8. mercado e histórico;
9. estado e descoberta complementar;
10. cobertura e estratégia de sitemap;
11. prioridade de mudanças de preço;
12. telemetria de rejeições;
13. Top 5.

Mudar esta ordem pode alterar os wrappers instalados por uma camada e deve ser tratado como mudança arquitetural.

## Identidade e matching

Hierarquia conservadora:

1. EAN/GTIN;
2. MPN/part number;
3. SKU/model code + configuração principal;
4. assinatura técnica apenas como apoio.

Confirmação de preço cross-store exige identidade forte. Sem essa evidência, configurações parecidas não são fundidas automaticamente.

## Estado

- `data/history.json` — ofertas, specs, alertas e runs recentes;
- `data/access_learning.json` — aprendizagem de acesso e rendimento;
- `data/price_history.json` — histórico diário compacto;
- `data/top5_current.json` — snapshot agregado das melhores configurações atuais;
- `data/state_epoch.json` — geração do estado persistente.

Os módulos movidos para `src/` resolvem estes caminhos a partir da raiz do projeto, para a reorganização não alterar o estado nem criar ficheiros duplicados.

## Testes

`tests/` contém regressões unitárias e integrações baseadas em casos reais. Estes ficheiros são parte da qualidade do produto, não artefactos temporários. O CI usa `PYTHONPATH=src` para testar as camadas auxiliares na nova localização.

## Regra de evolução

Antes de alterar o cérebro base, preferir:

1. melhorar extração/evidência;
2. adicionar ou simplificar uma camada pequena e testável;
3. acrescentar configuração;
4. medir o problema em produção.

Uma alteração de scoring base só deve acontecer com um caso real reproduzível, impacto quantificado e testes que protejam o comportamento pretendido.
