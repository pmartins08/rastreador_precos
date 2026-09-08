# Roadmap — da V8.8.7 à próxima grande versão

Os nomes V9/V10 são provisórios. O objetivo é usar versões maiores para marcar maturidade real, não apenas quantidade de commits.

## Estado atual — V8.8.7

A linha V8 já possui:

- descoberta multi-loja;
- aprendizagem de acesso/rendimento;
- cérebro FEUP + gaming;
- guardrails de RAM, GPU e preço;
- iGPU Intelligence;
- matching cross-store conservador;
- histórico de preços a 90 dias;
- ntfy com heartbeat;
- cache e refresh progressivo;
- CI e testes de regressão.

## Critérios antes de V9

### 1. Cobertura de lojas

- cada loja-alvo deve ter pelo menos um método público com rendimento mensurável;
- reduzir lojas permanentemente a 0 candidatos;
- distinguir claramente `bloqueada`, `sem produtos elegíveis` e `parser sem rendimento`;
- continuar a melhorar Worten/CHIP7/FNAC quando a estrutura pública mudar.

### 2. Qualidade de hardware

- aumentar catálogo de GPUs/iGPUs com calibração documentada;
- reduzir `GPU_DESCONHECIDA` em produtos de topo;
- reforçar evidência de teclado PT sem criar falsos negativos excessivos;
- melhorar bateria, peso, ecrã e expansibilidade quando a ficha pública fornece dados.

### 3. Explainability

Cada produto premium deverá conseguir explicar:

- por que foi aceite;
- componentes usados no score;
- confiança dos dados;
- origem da GPU/CPU/RAM/SSD;
- razão do tier;
- validação do preço;
- histórico recente e comparação cross-store quando disponíveis.

### 4. Matching cross-store

- aumentar percentagem de ofertas com EAN/MPN forte;
- medir precisão dos matches FORTE;
- nunca fundir variantes com GPU/RAM/SSD diferentes;
- tornar comparações entre lojas mais úteis sem relaxar identidade.

### 5. Observabilidade

Guardar e comparar por release:

- candidatos descobertos;
- avaliados/aceites/rejeitados/quarentena;
- D/O/P/B;
- GPUs desconhecidas e mapeadas;
- sucesso por loja;
- candidatos por request;
- detail fetches vs cache;
- runtime;
- alertas e supressões.

## Possível V9

V9 deverá representar **maturidade operacional**, não uma reescrita total.

Candidatos a marco V9:

- cobertura estável da maioria das lojas;
- melhor confirmação de teclado;
- catálogo GPU mais completo;
- métricas por release consistentes;
- matching cross-store comprovado em dados reais;
- documentação técnica suficiente para explicar decisões do modelo.

Um refactor de packaging (`src/`, módulos internos, adapters por loja) pode ser feito nessa transição se trouxer benefício claro. Não deve acontecer só por estética enquanto a linha V8 continua a evoluir rapidamente.

## Possível V10

V10 pode ser reservada para uma mudança de produto mais visível, por exemplo:

- scoring revisto com dados históricos suficientes;
- comparação de tendências/preço justo;
- catálogo técnico versionado externamente ao código;
- adapters de lojas mais isolados;
- reporting/dashboard;
- feedback sobre qualidade das recomendações.

## Preparação da futura apresentação

Desde já, manter material para uma apresentação do projeto:

1. **Problema** — escolher portáteis bons para universidade + gaming num mercado fragmentado;
2. **Solução** — crawler + extração + cérebro + guardrails + preço + histórico;
3. **Arquitetura** — separação entre decisão e observação;
4. **Evolução** — exemplos V8.3, V8.8, V8.8.6 e V8.8.7;
5. **Casos reais** — falsos Ouros corrigidos pelo GPU Guard;
6. **Métricas** — cobertura, tiers, requests, cache, runtime;
7. **Limitações** — anti-bot, dados incompletos, teclado, identidade;
8. **Futuro** — V9/V10 e melhoria do modelo.

Cada mudança relevante deve deixar pelo menos uma destas evidências: teste, métrica, caso real, documentação ou comparação de runs.
