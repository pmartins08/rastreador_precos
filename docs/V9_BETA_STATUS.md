# Estado atual — beta.12 em manutenção silenciosa

Ciclo de desenvolvimento concluído. NTFY apenas Diamante; heartbeat desligado. Monitorização a cada seis horas. Ver [fecho e pendências](CLOSEOUT.md) para mudanças e limitações desta revisão.

As métricas abaixo são **referências históricas**, não resultados da beta.12 nem prova de stock atual.

---

# V9 beta — expansão de cobertura em 01/10/2026

## Versão e política

Versão desta revisão: **9.0.0-beta.11**. Preserva os pesos das quatro dimensões e `STATE_EPOCH`; integra TGP e qualidade do ecrã no cérebro. Disponibilidade elegível passa a requisito antes do Value: sem stock confirmado não existe tier nem alerta de oportunidade. Diamante usa Value >= 120. Detalhes e limitações em [TECHNICAL_CONTEXT.md](TECHNICAL_CONTEXT.md).

## Validação beta.11

PR [#65](https://github.com/pmartins08/rastreador_precos/pull/65) integrada no commit `827ff76a`. CI: **421 testes**, sintaxe, configuração e auditorias passaram. Run [36842551276](https://github.com/pmartins08/rastreador_precos/actions/runs/36842551276), concluída com sucesso: 358 candidatos, 300 avaliações, 130 aceites no pipeline, 161 requests, 60 detalhes e 213,45 segundos. E2E passou; a publicação e heartbeat NTFY foram confirmados.

Darty: 65 candidatos, 47 avaliações, **zero aceites**; as 47 rejeições registam `availability_not_eligible`. O Acer ANV15-52-923W não aparece no ranking nem no snapshot de oportunidades desta run, nem recebeu nova notificação. Isto não declara todo o catálogo sem stock: a ficha pública não confirmou disponibilidade elegível, e o stock agregado não substitui essa confirmação. Onze probes persistiram sete estados por confirmar e quatro sem stock; o Acer ficou por confirmar, sem nova prova de entrega.

A auditoria após a run removeu quatro registos por conflito de preço, incluindo o AERO X16 da Globaldata, deixando 126 entradas económicas novas. Todas as 126 têm `offer_availability.eligible=true` e `brain_policy` preenchido. O snapshot anterior à auditoria (130 aceites, um Ouro) não deve servir isoladamente como recomendação de compra do AERO; esse conflito necessita de confirmação live de preço.

Orçamento soft 1.400 € / hard 1.600 €, integrado pela PR #61. A PR #62 acrescenta You Get, Tek4life, Auchan, MEO, Clickfiel e Novo Atalho: 15 lojas configuradas. CI da expansão: 405 testes passaram.

## Validação live da expansão

Run [36836800757](https://github.com/pmartins08/rastreador_precos/actions/runs/36836800757), commit `e8767bb9`, concluída com sucesso em 01/10/2026. Consulta: 518,14 s; 334 candidatos, 300 avaliados, 194 aceites, 254 requests, 137 detalhes live e 165 reutilizações de cache. E2E passou. Distribuição: 1 Diamante, 9 Ouros, 124 Pratas e 59 Bronzes; um aceite ficou sem tier, produzindo aviso de contagem (194 vs. 193), que não deve ser confundido com falha de execução.

| Nova loja | Candidatos | Avaliados | Aceites | Estado nesta run |
|---|---:|---:|---:|---|
| You Get | 0 | 0 | 0 | bloqueada |
| Tek4life | 37 | 31 | 25 | catálogo público e fichas live |
| Auchan | 11 | 11 | 9 | discovery e fichas live |
| Clickfiel | 23 | 21 | 15 | categoria e fichas live |
| MEO | 18 | 14 | 13 | categoria e fichas live |
| Novo Atalho | 2 | 2 | 2 | sitemap e fichas live; cobertura estreita |

As novas fontes acrescentaram 91 candidatos e 64 aceites. Todas as 15 lojas foram consultadas, incluindo as fontes anteriores; o limite de 300 avaliações deixou 34 candidatos por avaliar. Não se trata de cobertura integral dos catálogos. NTFY: 5 oportunidades e 1 heartbeat; confirmação de publicação após deploy também respondeu HTTP 200.

PCDiga, PcComponentes, CHIP7 e Worten continuaram sem candidatos elegíveis. A expansão compensou parcialmente estes bloqueios; não os resolveu. A RP caiu de 4 para 2 candidatos nesta comparação após a exclusão de artigos de exposição; esta run isolada não permite atribuir toda a diferença a esse filtro. Resultados de uma execução não certificam acesso futuro, stock no checkout nem todas as variantes.

Última execução anterior à expansão: `36829492861`, beta.9, sucesso em 223,62 s; 220 candidatos, 220 avaliados, 112 aceites, 141 requests, 64 detalhes live; 0 Diamantes / 4 Ouros. Auditoria NTFY: 1 oportunidade e 1 heartbeat. PCDIGA, PcComponentes, CHIP7 e Worten sem candidatos elegíveis nessa execução.

As métricas da tabela abaixo são históricas de 26/09. Os testes locais não certificam acesso live às lojas. A expansão aumenta os limites para 420 requests e 140 detalhes, preserva 10 minutos e dá espaço de avaliação aos novos candidatos por loja.

O princípio operacional desta fase é simples: **discovery não é confirmação**. URLs ou preços encontrados por índices públicos podem ajudar a localizar produtos, mas ficam `INDEX_ONLY` até uma fonte suficientemente forte confirmar identidade e preço.

## Última run completa de referência (beta.5)

Run de produção `36264887615`, concluída com sucesso:

| Métrica | Resultado |
|---|---:|
| Lojas configuradas | 9 |
| Candidatos descobertos | 234 |
| Avaliados | 234 |
| Aceites | 115 |
| Requests | 140 |
| Detalhes live | 62 |
| Cache reutilizada | 172 |
| Runtime | 280,6 s |
| Diamante | 0 |
| Ouro | 0 |
| Prata | 80 |
| Bronze | 35 |
| Alertas de oportunidade | 0 |

O silêncio do NTFY nesta execução é esperado: não existiam oportunidades Ouro/Diamante confirmadas pelo runtime.

## Estado por loja

| Loja | Estado operacional | Observação |
|---|---|---|
| Globaldata | **live útil** | cobertura e preços produtivos; 58 candidatos / 44 aceites na referência beta.5 |
| Radio Popular | **live útil** | 35 candidatos / 23 aceites; promoções só têm efeito económico quando confirmadas |
| Darty | **live útil** | 36 candidatos / 14 aceites; catálogo público complementa HTML |
| UPTECHBOX | **live útil** | 61 candidatos; confirmação de preço continua conservadora |
| FNAC | **live útil** | 44 candidatos / 33 aceites |
| PCDiga | **discovery útil, ficha bloqueada** | search-index encontrou 24 URLs e 16 preços; 3 tentativas live receberam HTTP 403 |
| PcComponentes | **discovery útil** | search-index encontrou 43 URLs e 26 preços; ainda sem identidade forte suficiente para promoção automática; Awin opcional preparado |
| CHIP7 | **discovery útil** | beta.5 encontrou 27 URLs e 17 preços com 4 pedidos; beta.6 acrescenta identidade forte por MPN em formatos restritos |
| Worten | **bloqueada / discovery improdutivo** | sitemap anterior gastava requests sem candidatos; search-index genérico beta.5 devolveu zero URLs úteis |

## Search-index e validação live

A sequência atual é:

`Search Index -> INDEX_ONLY -> identidade forte -> ficha live -> preço HIGH -> candidato`

Regras:

- `price_hint` de snippet nunca entra sozinho no scoring, tier, histórico económico ou NTFY;
- PCDiga pode obter EAN forte diretamente de URLs que o runtime valida;
- CHIP7 pode obter MPN forte apenas em padrões de referência Lenovo/ASUS muito restritos;
- PcComponentes não recebe identificadores inventados a partir de slugs descritivos;
- a ficha live tem de confirmar o mesmo EAN/MPN;
- o `price_guard` exige confiança HIGH por pelo menos duas famílias independentes de sinais;
- se existir hint indexado, o preço live tem de concordar dentro da tolerância;
- HTTP 403/429, identidade divergente, preço MEDIUM/UNKNOWN ou conflito mantêm o produto em quarentena.

## Matching e histórico

Na referência beta.5 existiam 19 grupos cross-store, 23 pares exatos e 6 conflitos explícitos. Conflitos não são fundidos. O histórico é auditado antes das runs; observações recentes com preço/specs contraditórios são removidas em vez de contaminarem ranking e alertas.

Os melhores Values históricos não devem ser tratados como ofertas atuais. Incluem campanhas já terminadas, produtos descontinuados e preços que deixaram de existir. A decisão atual exige preço recente e elegível.

## Dívida/limitações conhecidas

1. **PCDiga**: bom discovery, mas Cloudflare continua a bloquear a confirmação direta no GitHub runner.
2. **PcComponentes**: discovery amplo; feed Awin oficial está preparado mas depende de `AWIN_DATAFEED_API_KEY` autorizada.
3. **CHIP7**: discovery já funciona; a beta.6 tenta converter referências MPN fortes em validações live sem baixar a fasquia de confiança.
4. **Worten**: é a principal loja ainda sem discovery produtivo na estratégia atual.
5. O ranking técnico pode colocar ultrabooks baratos com iGPU acima de máquinas gaming quando o Value económico domina; a análise de compra deve considerar explicitamente o objetivo gaming além do ranking bruto.

## Gates para V9 estável

- manter CI e regressões verdes;
- aumentar cobertura útil sem permitir `INDEX_ONLY` no cérebro;
- estabilizar pelo menos uma rota sustentável adicional para lojas atualmente bloqueadas;
- continuar a reduzir conflitos de identidade/matching sem falsos merges;
- validar comportamento por várias runs comparáveis, não por um único snapshot;
- manter documentação, versão pública e runtime sincronizados.

O histórico detalhado das fases anteriores permanece no Git e em `CHANGELOG.md`; este ficheiro é deliberadamente um snapshot operacional e não um diário de desenvolvimento.
