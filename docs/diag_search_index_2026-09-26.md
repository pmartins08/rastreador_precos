# Diagnóstico search-index — 2026-09-26

Branch temporária: `diag-search-index-pccomponentes`.

A run `36239215974` terminou com sucesso em GitHub Actions. O objetivo foi testar descoberta pública sem API keys nem feeds autenticados, usando pesquisas `site:` contra PcComponentes e PCDiga.

## PcComponentes

- Bing respondeu HTTP 200 mas não forneceu URLs úteis do domínio no parser testado.
- DuckDuckGo HTML/Lite com `curl_cffi` conseguiu devolver 10 URLs de produto para a pesquisa genérica `site:pccomponentes.pt portatil RTX 5070 32GB`. Os snippets eram úteis para título/specs, mas não trouxeram preço de forma consistente e pesquisas mais específicas foram instáveis.
- Brave Search com `curl_cffi` foi a fonte mais rica: devolveu cerca de 20 URLs PcComponentes em pesquisas RTX 5070/5060, incluindo o HP OMEN 16-am0046np e o Lenovo LOQ 15IRX10-540. Os snippets expuseram preço em alguns resultados: HP OMEN 16-am0046np a 1.499,00 € e Lenovo LOQ 15IRX10-540 a 1.429,00 € no momento da consulta.
- Yahoo Search devolveu snippets ricos com URLs, modelos e especificações; a extração de preço foi menos limpa e os links necessitam de unwrapping/filtragem porque a página inclui muitos links internos do Yahoo.
- Mojeek devolveu 403.

Conclusão PcComponentes: a via search-index é viável para `discovery`; não deve, nesta fase, ser tratada como confirmação live do preço porque o índice pode estar desatualizado.

## PCDiga

- Brave Search com `curl_cffi` devolveu cerca de 20 URLs do domínio na pesquisa genérica RTX 5070 e mostrou snippets de produto, incluindo um Gigabyte Gaming A16 com preço indexado de 1.499,00 €.
- Yahoo também devolveu resultados PCDiga e snippets de produto/categoria.
- A pesquisa muito específica pelo Acer Nitro V14 RTX 5060 foi menos produtiva, mostrando que é necessário usar uma matriz de pesquisas por GPU/família/marca em vez de depender apenas do modelo exato.

Conclusão PCDiga: a mesma camada pode recuperar discovery parcial mesmo quando as páginas da loja devolvem Cloudflare ao GitHub Actions.

## Política recomendada

1. `search_index` entra como fonte de descoberta/fallback apenas quando a descoberta direta está bloqueada ou abaixo do limiar.
2. URLs são filtrados pelo domínio e por sinais de produto/portátil.
3. Preço de snippet recebe confiança baixa e não pode, sozinho, gerar OURO/DIAMANTE ou NTFY.
4. Quando duas fontes independentes concordarem no mesmo produto/preço, o dado pode ganhar confiança adicional, mas continua separado de `live price` até haver validação suficiente.
5. Limitar queries por run e reutilizar cache para não transformar search engines em nova origem de requests excessivos.
