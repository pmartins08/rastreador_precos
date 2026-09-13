# Estado operacional e próximos passos — 13/09/2026

## Trabalho realizado

- Corrigida a recursão entre confirmação de preço e decisão de refresh que interrompia as duas últimas execuções.
- Reutilização de confirmação de catálogo exige preço/hint coincidentes, confiança HIGH e TTL válido. Alterações de preço continuam a exigir confirmação e recálculo.
- Globaldata: uma rota prioritária de segmento, em vez de quatro; mantida a paginação. As outras três rotas tinham acrescentado zero candidatos nos logs analisados.
- Medição de tempo de descoberta por loja, persistida em `discovery_seconds`.
- Resumo Top 3 solicitado: uma única publicação com reserva persistida antes do POST. Uma execução futura não repete o mesmo pedido.
- 325 testes aprovados, incluindo os novos casos de recursão, cache e resumo único.

## Validação em produção

Execução 34777055233 concluída com sucesso: 297,88 s, 112 pedidos, 343 candidatos, 300 avaliados e 232 aceites. A comparação anterior foi 320,08 s / 129 pedidos / 241 aceites: menos tempo e pedidos nesta amostra, com mistura de produtos e resultados diferente; não é um benchmark controlado.

Resumo único enviado em 13/09/2026 às 19:19 UTC, comprovativo NTFY `0PTqSYrHpCYl`: Lenovo Legion 5 15AHP-682 (Diamante, 1299,99 €), ASUS TUF A16 FA608UH-R72A55CB2 (Ouro, 1049,99 €), ASUS TUF A16 FA608UM-R72A56CB1 (Diamante, 1299,99 €). Preços de checkout promocional Rádio Popular.

| Loja | Candidatos | Aceites | Observação |
|---|---:|---:|---|
| Rádio Popular | 126 | 107 | Campanha e fichas operacionais; recebeu as 12 vagas de price refresh |
| Globaldata | 66 | 50 | Descoberta com 6 pedidos, anteriormente 9; paginação mantida |
| UPTECHBOX | 59 | 38 | Catálogo ativo; 4 rejeições por falta de confirmação live |
| FNAC | 47 | 29 | Categoria, campanha e paginação ativas |
| Darty | 43 | 8 | Catálogo ativo; 20 rejeições por falta de confirmação live |
| PCDiga | 2 | 0 | Apenas histórico, sem confirmação atual; teste direto devolveu desafio HTTP 403 |
| CHIP7 | 0 | 0 | HTTP 403 |
| PcComponentes | 0 | 0 | HTTP 403 |
| Worten | 0 | 0 | HTTP 403 |

**Prioridade imediata:** distribuir as vagas de price refresh por loja e por melhoria de preço/oportunidade. Nesta run, a Rádio Popular ocupou as 12 e Darty/UPTECHBOX ficaram com zero. Testar que não reduz a cobertura da campanha nem permite alertas sem confirmação.

## Plano priorizado

1. **Medir antes de aumentar concorrência.** Comparar duração, pedidos reais, confirmações e ofertas aceites nas próximas três execuções. A última execução bem-sucedida anterior demorou 320,08 s, com 129 pedidos e 241 ofertas aceites. Não confundir variação da rede com ganho de código.
2. **Evitar fichas repetidas na mesma execução.** Introduzir cache em memória por URL para respostas públicas de produto bem-sucedidas, isolada por execução, com contagem de hits e testes de preço/variantes. Não reutilizar falhas nem respostas entre execuções sem TTL.
3. **PCDiga.** Distinguir bloqueio HTTP de HTML sem catálogo; identificar fonte pública estável ou feed autorizado antes de gastar pedidos em rotas com rendimento zero. Não aumentar tentativas contra desafios de acesso.
4. **Worten, CHIP7 e PcComponentes.** Manter sondagens limitadas e priorizar feeds oficiais/autorizados. Só ativar uma nova fonte após confirmar identidade, disponibilidade e preço numa amostra de produtos.
5. **Darty e UPTECHBOX.** Medir reutilização de confirmações HIGH e renovar primeiro produtos com alterações de preço ou potencial Ouro/Diamante. Manter testes de RAM versus VRAM e separação de SKU interno/EAN/MPN.
6. **Rádio Popular.** Manter elegibilidade da campanha, preço normal e checkout separados. Verificar expiração da campanha e impedir que descontos antigos sobrevivam no ranking atual.
7. **FNAC e Globaldata.** Ajustar paginação/rotas pelo rendimento observado, mantendo descoberta de novos modelos. Evitar paralelizar lojas enquanto os guards partilharem estado mutável.

## Critérios de sucesso

- Execuções concluídas com histórico persistido e sem recursão.
- Menos pedidos repetidos, sem perder oportunidades confirmadas nem deteção de alterações materiais de preço.
- Zero alertas de oportunidades abaixo de Ouro.
- Um único resumo Top 3 por identificador de pedido, com comprovativo NTFY persistido.
