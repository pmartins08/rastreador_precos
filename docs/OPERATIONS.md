# Operação do Rastreador

## Execução automática

O workflow principal está em `.github/workflows/tracker.yml`.

- push para `main` com alterações de runtime/configuração → executa;
- documentação e ficheiros de estado isolados não disparam uma nova varredura;
- schedule → a cada 6 horas;
- `workflow_dispatch` → execução manual.

A execução usa Python 3.11 e valida sintaxe, JSON de configuração e testes antes de contactar lojas.

## Budgets de produção

Os limites correntes são definidos no workflow/configuração:

- `RUN_MAX_MINUTES=8`;
- `RUN_MAX_REQUESTS=300`;
- `RUN_MAX_REQUESTS_PER_STORE=60`;
- `RUN_MAX_DETAIL_FETCHES=90`;
- `max_evaluated_per_run=240`.

São fusíveis de segurança, não metas de consumo.

## NTFY

O secret `NTFY_TOPIC` é obrigatório no workflow de produção.

Existem dois mecanismos:

1. heartbeat principal enviado pelo próprio tracker;
2. heartbeat redundante do workflow se a run terminou mas o heartbeat principal não ficou registado.

Se o pipeline falhar, o workflow tenta enviar uma notificação de falha separada.

## Estado persistente

### `data/history.json`

Contém ofertas recentes, specs, tiers, estado de alertas e métricas de runs.

### `data/access_learning.json`

Aprende por loja/método/perfil:

- tentativas;
- sucessos;
- bloqueios;
- erros;
- rendimento de descoberta;
- resultados de chamadas de produto.

### `data/price_history.json`

Mantém histórico diário compacto a 90 dias por identidade forte ou URL local.

Os ficheiros são atualizados pelo workflow; não devem ser editados manualmente.

## Persistência concorrente

No fim de uma run bem-sucedida:

1. o estado produzido é copiado para `/tmp`;
2. o workflow atualiza a referência de `main`;
3. faz merge do estado atual com a run;
4. compacta histórico;
5. tenta `push` até três vezes em caso de corrida com outro commit.

Isto reduz perda de aprendizagem quando há commits/execuções próximas.

## Diagnóstico rápido

### Loja com 0 candidatos

Verificar, por esta ordem:

1. `stores.<loja>.bloqueada` na última run;
2. `fontes_descoberta`;
3. `sitemap_urls` e rendimento de sitemap;
4. `access_learning.json` por método/perfil;
5. padrões `product_path_hints` na configuração;
6. se a loja mudou HTML/rota pública.

### Muitos produtos em quarentena

Verificar:

1. `price_status`;
2. `price_confidence`;
3. sinais de preço da ficha;
4. conflitos de catálogo/ficha;
5. clusters cross-store por EAN/MPN.

### Muitos Prata com Value > 110

Verificar `gpu_tier_guard`. Em V8.8.7 isso pode ser correto quando a GPU é desconhecida/genérica.

### Heartbeat ausente

Verificar se `heartbeat_sent` ficou `false` na última run. O workflow tenta um canal redundante; se ambos falharem, validar `NTFY_TOPIC` e disponibilidade do ntfy.

## CI

`.github/workflows/ci.yml` corre em branches `feature/**`, `fix/**`, `chore/**` e `refactor/**`, além de pull requests para `main`.

Valida:

- compilação de todo o Python com `compileall`;
- `config/config.json` com `json.tool`;
- todos os testes `unittest` descobertos em `tests/`.

## Política de mudança

Uma alteração só deve ser integrada depois de:

1. testes passarem na branch;
2. diff ser revisto;
3. pull request passar CI;
4. mudanças de comportamento serem registadas no changelog;
5. quando relevante, a primeira run real ser comparada com a versão anterior.
