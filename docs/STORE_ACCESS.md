# Acesso às lojas

## Estado verificado

Base: `9.0.0-beta.12` / preparação para versão final estável `9.0.0`.
Lojas ativas com recolha live e cache operacional:
- `FNAC`, `Globaldata`, `MEO`, `UPTECHBOX`, `Tek4life`, `Auchan`, `Clickfiel`, `Radio Popular` e `Darty`.

Lojas bloqueadas por WAF/Cloudflare no GitHub Actions:
- `PCDiga`, `PcComponentes`, `CHIP7`, `Worten` e `You Get` (esta última com 100% de bloqueio Cloudflare na categoria e paginação).

O suporte a feeds de afiliados Awin permanece implementado e preparado para ativação automática assim que a variável de ambiente `AWIN_DATAFEED_API_KEY` for fornecida.

### Resolução de gargalos de disponibilidade e cache (9.0.0)

1. **TTL de Disponibilidade (6h) vs. Cache de Hardware (24h)**:
   - Em lojas onde os cartões de listagem não trazem texto explícito de stock (`Auchan`, `Clickfiel`, `Radio Popular`) e em `Darty`, a expiração de 6h do registo de disponibilidade em `access_learning.json` causava a rejeição por `availability_not_eligible` de ofertas servidas da cache de hardware.
   - O `availability_guard.py` passou a forçar revalidação live quando a disponibilidade de 6h expira para estas lojas, sem consumir slots desnecessários em lojas que já trazem stock explícito no cartão (`FNAC`, `Globaldata`).
2. **Quota de Refreshes de Preço**:
   - `max_price_refreshes_per_run` aumentado de 12 para 48 em `config/config.json`, permitindo refrescar até 48 ofertas voláteis em cada run e desbloqueando ofertas que exigiam confirmação de preço live em `Tek4life` e `UPTECHBOX`.
3. **Reabertura Gradual de Fichas sem `os_status`**:
   - `needs_identity_refresh` reabre gradualmente entradas da cache anteriores a `9.0.0-beta.12` que ainda não tenham `os_status` verificado, usando a quota existente de refreshes de identidade (`12`/run).
4. **Enriquecimento Oficial de Fabricante**:
   - Ativado o enriquecimento oficial via `Lenovo PSREF` e `HP Support` (`manufacturer_enrichment_enabled: true`, máx. 8/run, máx. 4/marca) para preencher metadados técnicos de hardware com base em identificadores exatos (EAN/MPN).

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


## Auditoria das ofertas antigas

A auditoria #34657917070 encontrou as 41 ofertas Darty aceites na run #198:
40 já tinham `stock=false`, confirmado pelo catálogo; apenas 1 tinha stock.
As 750 entradas consultadas resultaram em 463 URLs elegíveis distintas,
402 sem stock e 61 com stock (incluindo preços fora do orçamento).
A queda da contagem bruta não representava a perda de 22 ofertas disponíveis.

O catálogo também conserva preços base quando a ficha tem uma promoção.
Os seeds passam a obter o preço da evidência atual da ficha, conservando
a indicação original em `specs.catalog_price_hint`. Não há promoção de
confiança MEDIUM para HIGH. Preços suspeitos continuam a exigir a confirmação
forte definida no Price Guard, e conflitos reais continuam em quarentena.

Nas runs seguintes, a mesma URL pode reutilizar o preço confirmado da ficha
durante o TTL já configurado (24h), desde que o preço indicativo do catálogo
não tenha mudado. Quando muda ou expira, a Coverage Guard exige refresh live.
Sem refresh, o candidato cached fica em quarentena.

A quota máxima de refresh de preços sobe de 12 para 48 para permitir renovar
os portáteis ativos da Darty; mantém os limites globais de 90 detalhes,
300 pedidos e 60 pedidos por loja. A quota é um máximo, não uma meta.
