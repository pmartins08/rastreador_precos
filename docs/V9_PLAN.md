# LapIntel PT — V9 Development Plan

## Baseline

A V9 parte de uma V8.8.9 funcional e validada em produção.

Última baseline validada antes do início da V9: **run #254 — 17/09/2026**.

- 321/321 testes: OK
- 9 lojas configuradas
- 234 portáteis descobertos
- 234 avaliados
- 116 aceites
- 178 requests
- 84 detail fetches
- 153 reutilizações de cache
- runtime: 310,1 s
- heartbeat NTFY: confirmado
- persistência de estado: confirmada
- acesso útil: Globaldata, Radio Popular, Darty, UPTECHBOX e FNAC
- bloqueadas/sem descoberta útil nessa run: PCDiga, PcComponentes, CHIP7 e Worten

A V9 não será uma reescrita do cérebro. O objetivo é tornar o sistema mais coerente, sustentável, eficiente e explicável.

---

## Objetivo da V9

Transformar o LapIntel PT de um motor que já funciona e tomou uma decisão real de compra num sistema com:

1. uma única fonte de verdade para decisão e observabilidade;
2. cobertura de mercado mais sustentável;
3. matching cross-store mais forte;
4. inteligência histórica suficientemente confiável para contextualizar preços;
5. eficiência mensurável por loja e por rota;
6. explicações de decisão mais claras para o utilizador.

---

## Workstream 1 — Effective Tier: uma única fonte de verdade

### Problema

Hoje o sistema consegue recalcular Value e tier com promoções, mas diferentes superfícies ainda podem usar conceitos distintos: tier base, tier promocional e tier mostrado no resumo.

### Meta

Criar uma única definição de **effective tier** usada por:

- ranking;
- resumo D/O/P/B;
- heartbeat;
- logs;
- notificações;
- histórico;
- futuros snapshots/dashboard.

### Regras a preservar

- Value efetivo **> 120 => DIAMANTE**;
- promoções expiradas não afetam checkout nem tier;
- promoções só alteram Value quando têm elegibilidade e preço suficientemente confirmados;
- o tier base continua guardado para auditoria.

### Critério de saída

O mesmo portátil deve apresentar exatamente o mesmo tier efetivo em todas as superfícies do sistema.

---

## Workstream 2 — Cobertura sustentável das lojas

### Estado atual

Na baseline #254 houve descoberta útil em 5/9 lojas.

Principais lacunas:

- **PCDiga** — HTTP 403 na run atual;
- **PcComponentes** — HTTP 403;
- **CHIP7** — HTTP 403;
- **Worten** — sitemap observável, mas fichas/rotas principais bloqueadas no runner.

### Estratégia

Priorizar apenas mecanismos sustentáveis e públicos:

- catálogos JSON públicos;
- sitemaps úteis;
- feeds autorizados;
- endpoints públicos de pesquisa/catalogação;
- histórico recente como fallback apenas quando corretamente marcado;
- fontes oficiais do fabricante para completar identidade/specs, nunca para inventar preço de loja.

Não introduzir brute force, bypass de CAPTCHA ou contorno agressivo de anti-bot.

### Critério de saída

A maioria das lojas-alvo deve produzir descoberta previsível sem aumento desproporcional de requests.

---

## Workstream 3 — Matching cross-store V9

### Meta

Aumentar a quantidade de ofertas comparáveis sem aumentar falsos matches.

### Prioridades

- maior cobertura de EAN/GTIN;
- maior cobertura de MPN/model code;
- normalização mais forte de CPU/GPU/display;
- EXATO por identificador forte + coerência técnica;
- FORTE quando identidade e configuração convergem;
- PROVÁVEL apenas como observação, nunca como evidência forte de preço;
- conflitos de GPU/RAM/storage/display bloqueiam fusão.

### Métricas

- percentagem de aceites com identificador forte;
- número de grupos EXATOS/FORTES;
- conflitos por 100 ofertas;
- ofertas com preço cross-store validado;
- taxa de falsos conflitos auditados.

---

## Workstream 4 — Eficiência e orçamento adaptativo

Princípio central:

> Mais mercado observado não deve significar proporcionalmente mais requests.

### Métricas V9

- candidatos descobertos / request;
- aceites / request;
- cache hit rate;
- detail fetches / candidato aceite;
- tempo por loja;
- yield por rota;
- zero-yield requests;
- requests gastos em lojas bloqueadas;
- custo marginal de descoberta por novo candidato útil.

### Melhorias candidatas

- budgets adaptativos por loja;
- redução mais rápida de rotas de yield zero;
- reserva de orçamento para lojas/rotas produtivas;
- cache TTL diferenciado entre hardware, preço e identidade;
- refresh orientado por mudança material e risco.

---

## Workstream 5 — Inteligência histórica V9

O histórico passa a ser contexto, não apenas memória.

### Capacidades alvo

- preço atual vs média 30/60/90 dias;
- mínimo histórico confiável;
- percentil do preço atual;
- tendência de preço;
- frequência observada de promoções;
- confiança baseada no tamanho e qualidade da amostra;
- distinção entre preço normal, desconto de checkout e crédito futuro.

### Regra de segurança

Nenhuma conclusão histórica forte deve ser emitida com amostra insuficiente ou identidade fraca.

---

## Workstream 6 — Explicabilidade da decisão

A V9 deve conseguir explicar por que um portátil ficou acima de outro.

### Saída desejada

Para cada oportunidade relevante:

- preço observado;
- preço efetivo confirmado;
- score técnico;
- Value;
- effective tier;
- fatores que mais contribuíram positivamente;
- principais compromissos;
- confiança do preço;
- confiança da identidade;
- contexto histórico quando disponível;
- comparação com alternativas próximas.

Objetivo: passar de “DIAMANTE 123,6” para uma decisão auditável por uma pessoa.

---

## Workstream 7 — Observabilidade e regressões

### Melhorias

- summary estruturado por run;
- reason codes estáveis;
- testes completamente independentes do relógio real, salvo testes explicitamente temporais;
- invariantes de produção para tier, preço, promoção e identidade;
- deteção de degradação de cobertura por loja;
- métricas comparáveis entre versões.

O incidente de 17/09/2026, em que fixtures promocionais expiradas bloquearam o pipeline, passa a ser uma regressão explícita a evitar.

---

## Workstream 8 — Novas lojas

Só integrar uma loja nova quando acrescentar cobertura real.

Candidatos já observados manualmente:

- Auchan
- MEO

Cada integração deve justificar:

- acesso sustentável;
- portáteis relevantes;
- preço e stock úteis;
- identidade técnica recuperável;
- custo de manutenção aceitável.

---

## Ordem de implementação

### Fase 1 — Coerência

1. effective tier como fonte de verdade;
2. métricas/run summary coerentes;
3. testes de invariantes e relógio.

### Fase 2 — Mercado

4. recuperação sustentável de cobertura das lojas bloqueadas;
5. matching cross-store V9;
6. budgets adaptativos.

### Fase 3 — Inteligência

7. contexto histórico com confiança;
8. explicabilidade da decisão;
9. avaliação de novas lojas.

### Fase 4 — Fecho V9

10. benchmark V8.8.9 vs V9;
11. documentação técnica completa;
12. apresentação final V1 → V9 com arquitetura, exemplos concretos, gráficos e resultados.

---

## KPIs para declarar V9 concluída

A V9 será considerada concluída quando, em runs reais repetidas:

- 100% das superfícies usam o mesmo effective tier;
- não existem notificações abaixo de OURO;
- promoções expiradas nunca alteram preço efetivo;
- cobertura útil é maior ou mais sustentável do que a baseline #254;
- matching forte aumenta sem crescimento relevante de conflitos falsos;
- aceites/request ou candidatos/request melhora relativamente à baseline;
- histórico só produz sinais fortes com amostra suficiente;
- existe pelo menos uma melhoria funcional claramente visível para o utilizador;
- todo o pipeline continua protegido por testes e validação end-to-end.

---

## Primeiro sprint

O primeiro sprint da V9 começa pelo problema mais estrutural e de menor risco operacional:

**V9.0 — Decision Truth Layer**

Objetivo: consolidar `base tier`, `promotion tier` e `effective tier` numa API interna única e migrar progressivamente resumo, heartbeat, logs, histórico e alertas para essa fonte.

Isto deve ser feito antes de mexer na cobertura das lojas, para que todas as melhorias posteriores sejam medidas e apresentadas com a mesma semântica.
