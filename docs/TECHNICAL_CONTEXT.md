# Cérebro técnico e disponibilidade — beta.11

## Correções

- Acer/Nitro/Predator e Gigabyte/AERO/AORUS entram na descoberta, mantendo os filtros de condição e as validações de preço/identidade existentes.
- TGP, brilho e sRGB são extraídos apenas de pares de especificação de produto. Não se faz scraping indiscriminado do texto da página para estes campos.
- Duas potências no mesmo campo (por exemplo ASUS 55 W / 115 W Dynamic Boost) ficam ambíguas: não somar nem escolher a maior automaticamente.
- A potência do carregador não é TGP. Brilho HDR de pico não é brilho SDR. NTSC não é convertido em sRGB.
- Dados de família podem ser marcados `tgp_evidence_status=family_only`; não constituem confirmação do SKU exato.
- Scoring devolve `technical_context`, persiste-o nas specs e inclui ressalvas em `alertas`. Alertas individuais e resumos Top3 mostram contexto técnico.
- Fronteira Diamante corrigida para Value **>= 120**, incluindo exatamente 120.0.

## Ponderação integrada

As dimensões conservam produtividade 50%, gaming 25%, longevidade 15% e portabilidade 10%. Dentro dos 10% globais já atribuídos ao ecrã, a resolução vale 4%, brilho SDR 2%, gamut 2%, painel 1% e área útil 1%. Não se acrescentam pesos por cima dos existentes.

O TGP modula apenas a componente GPU do gaming, num multiplicador limitado entre 0,85 e 1. A curva de utilidade é não linear e satura no limite de referência por GPU: RTX 5050/5060/5070 100 W, 5070 Ti 115 W, 5080/5090 150 W, conforme os intervalos oficiais NVIDIA. Potências acima da referência não dão bónus. A amplitude máxima na pontuação global é inferior a 2,44 pontos. Isto não representa uma percentagem de FPS medida.

Brilho satura nos 500 nits SDR; pico HDR não substitui brilho normal. Dados desconhecidos recebem utilidade moderada (60/100 no ecrã), sem inventar especificações; TGP desconhecido usa multiplicador 0,9475. sRGB e DCI-P3 têm curvas próprias, sem conversão entre espaços. Campo ambíguo ou de família não constitui TGP confirmado. Uma ficha com 500 nits SDR e 1000 HDR preserva apenas os 500 SDR para scoring.

As curvas são heurísticas explícitas de decisão, não benchmarks. FPS medidos, ruído, temperaturas e autonomia medida continuam por modelar. Os dados e componentes da ponderação ficam em `brain_policy` para auditoria.

## Disponibilidade antes do Value

Stock falso ou desconhecido exclui a oferta antes do scoring económico. Na Darty, `available=true` agregado pode significar apenas levantamento numa loja distante: é exigida evidência de entrega na ficha. Oferta apenas em loja permanece `STORE_ONLY_UNVERIFIED`, sem tier ou alerta, até existir confirmação de levantamento elegível. Evidência por URL expira ao fim de seis horas e não é transferida entre lojas pelo matching técnico.

Referência de potência: https://www.nvidia.com/pt-br/geforce/laptops/compare/

## Evidência desta análise (2026-09-30)

- ASUS 90NR0KV1-M00LU0: https://estore.asus.com/pt/90nr0kv1-m00lu0-portatil-gaming-asus-tuf-gaming-a16-2025.html
- Acer NH.QW8EB.002: https://www.acer.com/pt-pt/laptops/nitro/nitro-v-14-ai-amd/pdp/NH.QW8EB.002
- Família AERO: https://www.gigabyte.com/pt/Laptop/GIGABYTE-AERO-X16-EG61H/sp

Nenhum preço destas ofertas foi embutido no código. Specs desconhecidas permanecem desconhecidas e a elegibilidade por marca não garante cobertura integral de todas as rotas de todas as lojas.
