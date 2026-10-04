# Fecho do ciclo de compra — 4 de outubro de 2026

Estado: **compra concluída; desenvolvimento ativo em pausa; monitorização silenciosa**.
Versão: **9.0.0-beta.12**. O histórico e a aprendizagem existentes são preservados; o state epoch não muda.

## Pendências revistas contra o código

| Decisão | Resultado |
|---|---|
| NTFY apenas Diamante | Configuração passa a DIAMANTE e mínimo 120; aplica-se também a promoções e alterações de preço |
| Heartbeats desligados | Flag false; removidos fallback, deploy e aviso de falha do workflow; diagnóstico permanece no Actions |
| Resumos extraordinários antigos | Removidos passos de Top 3, script, testes desse script e recibos de replay concluídos |
| Value e Opportunity unificados | Ativado schema 2; a fórmula é aplicada uma vez, antes de tier e alertas; campo Opportunity fica como compatibilidade |
| Preço abaixo do orçamento | Incorporada a melhoria que estava numa branch por integrar: curva contínua e limitada |
| Bónus duplicado de preço baixo | Desligado na configuração; guard conserva compatibilidade histórica |
| Diamante ≥120 | Já existia no runtime; auditoria E2E alinhada com o limiar configurado e com a igualdade |
| Resumos D/O/P/B | Finalização independente do heartbeat; ofertas aceites abaixo de Bronze são contabilizadas como sem tier |
| Instalação de Windows | +110 € para sem SO/FreeDOS explícito; entra em Value e limite, também após desconto confirmado |
| Teclado | Espanhol confirmado rejeitado; inglês, desconhecido e PT não exigem o antigo gate PT |
| TGP/ecrã/bateria/peso no cérebro | Ponderação da beta.11 preservada; adicionada curva própria para NTSC explícito, sem conversão fictícia em sRGB |
| Sem stock nunca Ouro/Diamante | Gate da beta.11 preservado e coberto por testes |
| Novas lojas | As seis integrações da beta.10 já estavam em main; mantidas as 15 fontes configuradas |
| Darty/carrinho/campanhas | Discovery e confirmação já implementados; preservados guards de datas, elegibilidade e entrega |
| Histórico e matching | EAN/MPN, veto de conflitos e deduplicação mantidos; acrescentados resumos de 30/60/90 dias |
| GitHub/documentação | README, roadmap, operação, história e versão alinhados com o fecho real |

## Contrato económico

O preço do comerciante continua intacto para confirmação live e histórico de preços. O custo de instalação é separado (`installation_cost_eur`); `purchase_total_eur` inclui o checkout e essa instalação. Não se desconta a instalação nas campanhas.

O Value base técnico/económico usa o custo total. O Value unificado usa 80% desse Value base, 30% da pontuação Gaming na escala 0–100 (equivalente à ponderação 20% numa escala 0–150), mais até cinco pontos de histórico. Há no mínimo três dias observados para bónus histórico. Dados desconhecidos não geram bónus de mínimo histórico.

Os scores históricos não são reescritos com a nova fórmula. Cada nova observação é recalculada e marcada com o schema correspondente. Comparações entre versões devem reconhecer esta mudança de política.

## Limitações que permanecem

- Bloqueios externos em PCDiga, PcComponentes, CHIP7, Worten e You Get não se resolvem apenas reorganizando código. Não há garantia de cobertura integral nem bypass de proteções.
- Awin precisa de credencial autorizada; sem ela é um no-op. ASUS eStore não está certificada como fonte live ativa.
- Ausência/conflito de informação de SO não prova Windows incluído: o motor explicita a incerteza. Cache antiga pode precisar de nova ficha para preencher este campo.
- Confirmação de stock/preço expira; a loja e o checkout continuam a ser a confirmação final da compra.
- FPS, ruído, temperaturas e autonomia medida não são estimados como se fossem benchmarks.

Estas limitações justificam manter a versão beta.12. Fechar a compra não certifica uma release estável com cobertura total.

## Verificação

A suite unitária inclui regressões de Value contínuo/idempotente, custo total, promoção com instalação, limite do orçamento, espanhol, Diamante exato, ausência de NTFY Ouro e finalização de métricas sem heartbeat. Os envios destes testes são simulados.

O CI valida código, configuração, testes e auditorias históricas antes da integração. A primeira run de produção após a integração confirma a operação live; os testes locais não certificam acesso às lojas.
