# Acesso às lojas

## Estado verificado

Base: `3ca7fbd`, V8.8.9. A run de produção #198 passou 187 testes.
Darty: 86 candidatos, 41 aceites, 60 pedidos (limite por loja).
CHIP7, PcComponentes e Worten: zero candidatos, HTTP 403.

O diagnóstico #34656935468 voltou a verificar as lojas no GitHub Actions.
CHIP7 e PcComponentes recusaram categoria e robots com 403. Worten recusou
a categoria, mas disponibilizou robots. O diagnóstico #34657188358 confirmou
também 403 nas homepages CHIP7/PcComponentes; o índice e um sitemap Worten
responderam 200. Um sitemap dá URLs, não confirmação atual de preços/stock.

A integração Awin existente reporta `not_configured` nas lojas bloqueadas.
Não confundir a existência do código com um feed autorizado operacional.

## Darty

O catálogo público da coleção é agora consultado primeiro, com no máximo
3 páginas de 250 produtos. O limite técnico do código é 4 páginas. URLs
repetidas são deduplicadas; páginas repetidas interrompem a paginação.

A decisão de evitar HTML/sitemap conta apenas produtos elegíveis, com preço
finito dentro do orçamento e sem indicação explícita de falta de stock.
Se a fonte falhar ou ficar abaixo do mínimo, regressa a descoberta anterior.
Um erro numa página posterior preserva os candidatos válidos já recolhidos.

O catálogo continua a produzir `catalog_json_seed`: a ficha e os guards
existentes confirmam specs e preços antes da avaliação. A alteração não cria
prova HIGH, não inventa scores e não modifica regras de alerta.

`catalog_json_exhausted=false` significa que o catálogo não foi percorrido
até ao fim. É cobertura limitada pela configuração, não cobertura completa.

## Diagnóstico reproduzível

No GitHub, executar manualmente o workflow **Diagnosticar acesso às lojas**.
Na máquina onde se pretende correr o coletor:

```bash
python -m pip install -r requirements.txt
python scripts/store_access_probe.py --stores Darty Worten CHIP7 PcComponentes PCDiga --output /tmp/store-access.json
```

O comando importa o runtime real, lê a aprendizagem e faz pedidos públicos
limitados. Não chama o motor de notificações nem escreve em `data/`.
Os hashes dos ficheiros de estado são comparados antes/depois.

`--full-run` faz uma execução completa numa cópia temporária, com NTFY e Awin
desativados; preserva o estado do checkout. O artefacto é o resumo da run.
Os diagnósticos não devem ser executados em loop para tentar vencer bloqueios.

## Ler o resultado

`run.access_health` distingue descoberta atual, apenas histórico, bloqueio e
resposta sem produtos. Mostra HTTP da categoria, estado do feed, contagens e
se o orçamento de pedidos foi atingido. CI verde prova testes, não cobertura.

## Lojas que continuam bloqueadas

- Worten e PcComponentes: configurar `AWIN_DATAFEED_API_KEY` em GitHub Actions
  apenas depois de obter acesso aos respetivos feeds. Ver `AWIN_FEEDS.md`.
- CHIP7: não há um advertiser/endpoint de feed autorizado verificado nesta
  integração. É necessário um feed fornecido pela loja ou demonstrar acesso
  normal no ambiente onde o coletor ficará instalado.
- Um coletor noutro ambiente só deve ser proposto depois de o mesmo diagnóstico
  provar que categoria e fichas funcionam aí. Não presumir que resolve 403.
- Não usar cookies de terceiros, proxies, solver de CAPTCHA ou APIs privadas.

Nenhuma destas dependências foi declarada resolvida pela alteração.
