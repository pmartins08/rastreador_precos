# V9 beta — análise e consolidação de 22/09/2026

## Estado e âmbito
Versão pública: **9.0.0-beta.1**. Consolida main V8.8.9 e a Fase 1 V9 desenvolvida no PR #41. Não declara concluído o roadmap completo V9. Preserva pesos, orçamento, histórico, aprendizagem, estado de alertas e STATE_EPOCH. Snapshot anterior ao deploy: run 35719795377, 22/09/2026 11:12 UTC.

## Diagnóstico
- Produção anterior: 366 candidatos, 300 avaliações (limite atingido), 187 aceites; 124 requests, 59 detalhes, 241 reutilizações de cache; 220,18 segundos; 0 alertas de oportunidade. Cinco lojas fornecem ofertas aceites, quatro continuam bloqueadas.
- Distribuição anterior: 1 Diamante, 4 Ouro, 119 Prata, 63 Bronze. Estes números não são o Top3 da nova execução.
- Darty já recebe 5 das 12 confirmações, RP 3 e UPTECHBOX 4. A distribuição entre lojas pedida anteriormente já foi implementada; não deve ser refeita.
- UPTECHBOX perde 51 ofertas por falta de confirmação live de preço. Darty perde 16 pelo mesmo motivo. Aumentar cegamente o orçamento de requests não resolve a confiança.
- Matching: 21 pares exatos e 15 pares contraditórios no resumo anterior. Mesmo EAN pode apresentar Value distinto por especificações/completude diferentes. Prioridade: reconciliação de evidência por campo, sem copiar hardware contraditório entre variantes.
- Mercado: as campanhas e Diamantes de 13/09 não são ofertas atuais. Ranking só pode usar preço elegível observado nesta execução; quatro lojas ausentes impedem afirmar que é o melhor preço de todo o mercado português.

## Cada loja
| Loja | Candidatos | Aceites | Requests | Limitação / rejeições |
|---|---:|---:|---:|---|
| CHIP7 | 0 | 0 | 2 | HTTP 403 |
| Darty | 139 | 59 | 48 | {'live_price_confirmation_required': 16, 'ram_8gb': 5, 'score_rejected_other': 19} |
| FNAC | 43 | 33 | 12 | {'ram_8gb': 5} |
| Globaldata | 84 | 66 | 13 | {'ram_8gb': 4} |
| PCDiga | 0 | 0 | 9 | HTTP 403 |
| PcComponentes | 0 | 0 | 2 | HTTP 403 |
| Radio Popular | 37 | 25 | 17 | {'ram_8gb': 6, 'score_rejected_other': 3} |
| UPTECHBOX | 63 | 4 | 19 | {'live_price_confirmation_required': 51, 'ram_8gb': 4} |
| Worten | 0 | 0 | 2 | HTTP 403 |

## Melhorias nesta beta
- Fonte comum de decisão base/promocional/efetiva em histórico, contagens, heartbeat, TOP e auditoria de alertas; promoção exige confirmação e desconto efetivo.
- Integra toda a Fase 1 existente em v9/development, incluindo testes reais de composição e normalização de scores para floats persistíveis.
- Configuração da Decision Truth lida uma vez por execução em vez de uma leitura por oferta aceite.
- Um único CI por pull request, sem repetir testes num workflow V9 separado nem simultaneamente no push da mesma branch.
- Produção mantém cron de 6 horas e validações; uma nova execução aguarda a atual terminar, evitando cancelar um processo entre envio de alertas e persistência.
- Gate de coerência V9 em produção, derivado do benchmark E2E existente.
- Retira stub de campanha antiga e configuração morta. Resumo excecional Top3 tem identificador explícito, recibo persistente e reserva antes do POST para impedir duplicados; não reutiliza ofertas antigas nem preenche com Prata.
- Histórico Git e logs de Actions preservados para diagnóstico e rollback. Não se apagam runs falhadas para esconder regressões.

## Validação e limites
- Benchmark prévio V9 35722147798: sucesso real, 333 candidatos, 272 avaliados, 153 aceites, 164 requests, 100 detalhes, 154,12 s. Não é um teste A/B: dados, cache e cobertura diferem da produção.
- Suite local após consolidação e correção do limiar: 338 testes. CI e execução de produção são os gates finais; consultar Actions para resultados efetivos.
- Esta versão mantém a política implementada: Value estritamente acima de 120 força Diamante; abaixo/equal preserva o cálculo existente. Não muda o cérebro de scoring.
- O Top3 solicitado só é enviado após uma execução fresca bem-sucedida e validação de três configurações Ouro/Diamante. Reserva sem recibo significa entrega incerta e exige revisão manual antes de qualquer reenvio.

## Próximos passos por prioridade
1. Confirmar três runs comparáveis da beta: aceites/request, tempo, cobertura por loja, divergências de tiers e alertas.
2. UPTECHBOX/Darty: medir confirmações por request, cache HIGH válida e extração estruturada de preço; evitar confundir catálogo com evidência live suficiente.
3. PCDiga/PcComponentes/CHIP7/Worten: feeds autorizados ou endpoints públicos sustentáveis. Awin já existe, mas feed não configurado não equivale a acesso resolvido.
4. Matching forte EAN/MPN com conflitos por campo e harmonização de evidência técnica; depois métricas históricas 30/60/90 dias com amostra mínima.
5. Só depois expandir Auchan/MEO e declarar V9 estável.

Rollback: reverter o commit de integração e manter data/ e STATE_EPOCH. Não restaurar ficheiros de dados antigos da branch de desenvolvimento.

## Resultado observado após publicação
PR #41 integrado; run 35726150936 concluída com sucesso: 367 candidatos, 299 avaliados, 189 aceites, 120 requests, 54 detalhes, 246 reutilizações, 177,84 s. Gate V9 validado em produção, 0 alertas normais e heartbeat confirmado. Comparação indicativa com a execução anterior, não um benchmark controlado.

A auditoria posterior encontrou `official_store_guard` a substituir 120 por uma calibração antiga de 118. PR #42 remove essa substituição: o limiar configurado passa efetivamente a ser respeitado, sem alterar pesos. Teste de composição real cobre a regressão. O resumo excecional recalcula Value e tier usando o runtime corrigido e preços recentemente observados.

O primeiro resumo foi entregue antes de a correção estar integrada (recibo OqLwMeMVsOn1); a mensagem de correção tem identificador separado e explica a divergência. Consultar `data/top3_summary_receipts.json` para confirmar a entrega; reserva não equivale a envio.

Pendência adicional: `scripts/history_audit.py` conta apenas nós com `points`; o esquema atual usa `identities` (394 séries na baseline), por isso o relatório de zero séries é um erro do auditor, não perda de histórico.

## Correção do resumo confirmada
A correção posterior permite resumir menos de três configurações elegíveis e torna os passos excecionais de notificação não bloqueantes. 339 testes locais aprovados. A mensagem corretiva foi entregue às 12:28:26 UTC de 22/09/2026, recibo ntfy `ezSaYh0fCMjO`: ASUS TUF A16 FA608UH-R72B55CS2 (1299 €, Value 116,7, Ouro) e ASUS Gaming V16 5050B (1299 €, Value 115,3, Ouro), ambos Globaldata. Eram as duas oportunidades elegíveis após recálculo no conjunto observado às 12:22 UTC; não foi inventado terceiro lugar. A run 35727351388 prossegue a validação operacional completa.
