# Operação do LapIntel PT — beta.12

## Execução automática

O workflow principal está em `.github/workflows/tracker.yml`.

- push relevante para `main` → executa;
- documentação e ficheiros de estado isolados não disparam nova varredura;
- schedule → a cada 6 horas;
- `workflow_dispatch` → execução manual.

A execução usa Python 3.11, `PYTHONPATH=src` e valida sintaxe, configuração e testes antes de contactar lojas.

## Entry point

O comando de produção continua simples:

```bash
python runner.py
```

`runner.py` adiciona `src/` ao path e instala as camadas auxiliares antes de chamar o motor em `tracker.py`.

## Budgets de produção

Os limites correntes são fusíveis de segurança:

- `RUN_MAX_MINUTES=10`;
- `RUN_MAX_REQUESTS=420`;
- `RUN_MAX_REQUESTS_PER_STORE=60`;
- `RUN_MAX_DETAIL_FETCHES=140`;
- `max_evaluated_per_run=300`.

Não são metas de consumo; o sistema deve gastar menos quando cache e aprendizagem o permitem.

## NTFY

O secret `NTFY_TOPIC` é obrigatório no workflow de produção.

Apenas oportunidades **DIAMANTE (Value ≥120)** são enviadas. O custo total e o tier são recalculados antes dos alertas normais, promocionais e de alteração material de preço. Alterações sem oportunidade elegível não produzem mensagens.

`heartbeat_ntfy=false`: heartbeat principal desligado. Os passos redundantes, os envios de deploy/falha e os resumos Top 3 antigos foram removidos do workflow. Falhas ficam nos logs e no estado do GitHub Actions.

O hook `finalize_run` prepara contagens, tiers e ranking antes da persistência, independentemente de existir heartbeat. Para reativar o heartbeat principal numa futura retoma, alterar `heartbeat_ntfy` para `true`; não é necessário recuperar os envios redundantes. Para voltar a incluir Ouro, ajustar `alerta_min_tier` e `min_value_score_alerta`, bem como a auditoria Diamante do workflow.

## Feeds Awin

`AWIN_DATAFEED_API_KEY` é opcional. Quando existe e a conta tem acesso aos feeds autorizados, `src/awin_feed_guard.py` pode complementar a descoberta de lojas configuradas. Sem o secret, a integração é um no-op.

## Estado persistente

### `data/history.json`

Ofertas recentes, specs, tiers, estado de alertas e métricas de runs.

### `data/access_learning.json`

Aprendizagem por loja/método/perfil: tentativas, sucessos, bloqueios, erros e rendimento de descoberta.

### `data/price_history.json`

Histórico diário compacto a 90 dias por EAN/MPN ou URL local quando falta identidade forte.

### `data/top5_current.json`

Snapshot agregado das melhores configurações atuais ainda frescas.

### `data/state_epoch.json`

Geração do estado persistente. A versão pública pode avançar sem alterar o epoch; o epoch só muda quando é necessária uma migração/limpeza real do estado.

Os ficheiros de `data/` são estado operacional e não devem ser editados manualmente.

## Persistência concorrente

No fim de uma run bem-sucedida:

1. o estado produzido é copiado para `/tmp`;
2. o workflow atualiza a referência de `main`;
3. faz merge do estado atual com a run;
4. faz merge do histórico diário com `src/historical_guard.py`;
5. tenta `push` até três vezes em caso de corrida com outro commit.

Isto reduz perda de aprendizagem quando há execuções ou commits próximos.

## Diagnóstico rápido

### Loja com 0 candidatos

Verificar por esta ordem:

1. `stores.<loja>.bloqueada` na última run;
2. `fontes_descoberta`;
3. `sitemap_urls` e rendimento de sitemap;
4. `access_learning.json` por método/perfil;
5. `product_path_hints` e rotas complementares na configuração;
6. feeds/catálogos públicos autorizados disponíveis;
7. eventual mudança de HTML/rota pública da loja.

### Muitos produtos em quarentena

Verificar `price_status`, `price_confidence`, sinais da ficha, conflitos catálogo/ficha e clusters exatos por EAN/MPN.

### Mudança de preço sem alerta

Confirmar:

- se a oferta foi reencontrada na run;
- se a alteração material chegou à avaliação;
- o `value_score` e tier recalculados;
- `alerta_min_tier`;
- o último preço guardado em `alert_state`;
- stock atual.

### Heartbeat ausente

É o comportamento esperado nesta fase. Consultar a última run no GitHub Actions para verificar operação e erros.

## CI

`.github/workflows/ci.yml` corre em pull requests para `main` e execução manual.

Valida:

- `runner.py`, `tracker.py`, `scraper.py`, `version.py`, `src/` e `tests/` com `compileall`;
- `config/config.json` com `json.tool`;
- toda a suite `unittest` em `tests/`.

Os testes são parte permanente do projeto; artefactos de smoke/release temporários não devem permanecer no repositório depois de cumprirem a função.

## Política de mudança

Uma alteração só deve ser integrada depois de:

1. passar testes na branch/PR;
2. rever o diff;
3. passar CI;
4. atualizar documentação quando a arquitetura ou operação muda;
5. comparar a primeira run real com a anterior quando existe impacto operacional.
