# Display Guard

## Objetivo

Corrigir resolução de ecrã quando a própria oferta identifica explicitamente um painel `WQXGA`, evitando que referências secundárias a `FHD` existentes na mesma página (por exemplo webcam, vídeo, conteúdo editorial ou acessórios) contaminem `ecra_res`.

## Regra atual

- `WQXGA` explícito -> `qhd+`.
- A regra tem precedência apenas quando a nomenclatura `WQXGA` está presente no título ou nas evidências técnicas do produto.
- Não são feitas inferências por família, modelo, preço ou marca.
- Resoluções sem esta evidência explícita continuam a usar o parser base.
- CPU, GPU, RAM, armazenamento e refresh não são alterados por esta camada.

## Cache

O guard também corrige specs antigas reutilizadas da cache quando o título atual contém `WQXGA`. A alteração fica auditável em `display_resolution_guard`, incluindo a resolução anterior, a nova resolução e a fonte que justificou a correção.

## Motivação observada em produção

Duas ofertas Lenovo IdeaPad Slim 5x com o mesmo EAN e 165 Hz estavam a divergir apenas porque uma fonte tinha sido guardada como `fhd` apesar de o título indicar `WQXGA OLED`. Isso fazia o Matching Guard bloquear corretamente uma identidade cuja spec de ecrã estava, na realidade, mal extraída.
