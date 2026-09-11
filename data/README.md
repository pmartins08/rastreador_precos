# Estado gerado pelo runtime

Esta pasta contém **dados operacionais persistentes**, não fixtures de teste nem ficheiros para edição manual.

## Ficheiros

### `history.json`

Ofertas recentes, specs extraídas, scores, tiers, estado de alertas e métricas de runs. O tracker compacta entradas antigas para limitar crescimento.

### `access_learning.json`

Aprendizagem por loja, método e perfil de acesso: tentativas, sucessos, bloqueios, erros e rendimento de descoberta.

### `price_history.json`

Histórico diário compacto a 90 dias por identidade forte (EAN/MPN) ou, quando isso não existe, por URL local.

### `matching_state.json`

Estado **derivado** do matching da run atual. Guarda as identidades observadas, grupos cross-store EXATO/FORTE, casos PROVÁVEL para revisão e conflitos que impedem fusão. É reconstruído a partir dos registos realmente avaliados; nunca substitui `history.json` nem é fonte de verdade para preços/specs.

Um EAN/MPN repetido não pode fundir nem confirmar preços entre ofertas quando CPU, GPU, RAM, armazenamento, resolução ou refresh conhecidos se contradizem.

### `top5_current.json`

Snapshot agregado das cinco melhores configurações atuais conhecidas dentro do TTL configurado, deduplicadas por identidade/configuração.

### `state_epoch.json`

Identifica a geração do estado persistente. Só muda quando existe uma migração/refresh deliberado; uma simples atualização de versão ou reorganização de código não deve reiniciar o histórico.

## Regras

- não editar manualmente durante desenvolvimento normal;
- alterações são produzidas pelo runtime e persistidas pelo GitHub Actions;
- commits automáticos usam `[skip ci]` para não criar ciclos;
- o workflow faz merge concorrente antes do push final;
- `matching_state.json` pode ser regenerado sem apagar ou reescrever o histórico bruto;
- mudanças de schema/epoch exigem migração ou compatibilidade explícita;
- nunca apagar os ficheiros de histórico/aprendizagem apenas por parecerem “dados antigos”: são parte funcional do monitor de preços.
