# Estado gerado pelo runtime

Esta pasta contém dados operacionais persistidos pelo GitHub Actions. Não são fixtures nem ficheiros para edição manual.

## `history.json`

Guarda ofertas recentes, specs extraídas, scores, tiers, estado de alertas e métricas de runs. O tracker compacta entradas antigas para limitar crescimento.

## `access_learning.json`

Guarda aprendizagem por loja, método e perfil de acesso: tentativas, sucessos, bloqueios, erros e rendimento de descoberta.

## `price_history.json`

Guarda histórico diário compacto de preços por identidade forte (EAN/MPN) ou, quando isso não existe, por URL local.

## Regras

- não editar manualmente durante desenvolvimento normal;
- alterações destes ficheiros são feitas pelo workflow de produção;
- commits automáticos usam `[skip ci]` para não criar ciclos;
- o workflow faz merge concorrente antes do push final;
- mudanças de schema devem ser acompanhadas por migração/compatibilidade explícita.
