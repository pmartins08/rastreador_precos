# Contexto técnico — beta.10

## Correções

- Acer/Nitro/Predator e Gigabyte/AERO/AORUS entram na descoberta, mantendo os filtros de condição e as validações de preço/identidade existentes.
- TGP, brilho e sRGB são extraídos apenas de pares de especificação de produto. Não se faz scraping indiscriminado do texto da página para estes campos.
- Duas potências no mesmo campo (por exemplo ASUS 55 W / 115 W Dynamic Boost) ficam ambíguas: não somar nem escolher a maior automaticamente.
- A potência do carregador não é TGP. Brilho HDR de pico não é brilho SDR. NTSC não é convertido em sRGB.
- Dados de família podem ser marcados `tgp_evidence_status=family_only`; não constituem confirmação do SKU exato.
- Scoring devolve `technical_context`, persiste-o nas specs e inclui ressalvas em `alertas`. Alertas individuais e resumos Top3 mostram contexto técnico.
- Fronteira Diamante corrigida para Value **>= 120**, incluindo exatamente 120.0.

## O que não mudou

O cérebro e os pesos históricos de Value foram preservados. A GPU nominal ainda não é corrigida numericamente por TGP; brilho/gama de cores não têm pesos numéricos novos. Esta camada corrige extração e apresentação, **não é uma recalibração de performance**.

Converter 60/85/115 W em percentagens de FPS exigiria benchmarks comparáveis por GPU, modo de energia, memória e chassis. Uma curva arbitrária faria parecer que esse trabalho já foi realizado. Não foi.

Os avisos abaixo de 350 nits, 90% sRGB ou 15 polegadas são critérios de utilização autónoma, não testes eliminatórios nem alterações de tier. Não tornam uma oferta rejeitada aceite, não promovem INDEX_ONLY e não enfraquecem verificações de stock/preço.

## Evidência desta análise (2026-09-30)

- ASUS 90NR0KV1-M00LU0: https://estore.asus.com/pt/90nr0kv1-m00lu0-portatil-gaming-asus-tuf-gaming-a16-2025.html
- Acer NH.QW8EB.002: https://www.acer.com/pt-pt/laptops/nitro/nitro-v-14-ai-amd/pdp/NH.QW8EB.002
- Família AERO: https://www.gigabyte.com/pt/Laptop/GIGABYTE-AERO-X16-EG61H/sp

Nenhum preço destas ofertas foi embutido no código. Specs desconhecidas permanecem desconhecidas e a elegibilidade por marca não garante cobertura integral de todas as rotas de todas as lojas.
