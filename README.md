# Rastreador de Preços — V8.4

Rastreador de portáteis orientado a **valor real**, não apenas ao preço mais baixo. O projeto recolhe ofertas de lojas portuguesas, extrai hardware, aplica o cérebro de scoring V8, aprende quais estratégias de acesso funcionam por loja e envia alertas via ntfy apenas quando existe uma oportunidade relevante.

## Objetivo

O universo automático está limitado a portáteis novos das marcas:

- **ASUS** — ROG, TUF, Vivobook, Zenbook, ExpertBook, ProArt
- **Lenovo** — Legion, LOQ, IdeaPad, ThinkPad, ThinkBook, Yoga
- **HP** — OMEN, Victus, OmniBook, EliteBook, ProBook, Envy, Pavilion

Apple e equipamentos recondicionados/usados/outlet ficam fora do universo.

## Arquitetura

```text
GitHub Actions
    |
    v
runner.py                  # entrypoint e bootstrap
    |
    +--> brain_runtime.py  # correções de parsing compatíveis com o V8
    |      +--> brands.py
    |      +--> hardware.py
    |      +--> pricing.py
    |      +--> structured_data.py
    |      +--> catalog.py
    |
    +--> runner_v84.py     # acesso adaptativo, descoberta, prioridade e alertas
    |
    +--> scraper.py        # cérebro V8: extração estruturada + scoring

state_merge.py             # persistência segura entre runs
tests/                     # regressões do cérebro e da camada adaptativa
config/config.json         # lojas, limites, tiers e pesos
```

### 1. Cérebro V8

O scoring continua baseado nas dimensões FEUP, Gaming, Longevidade e Portabilidade. A fórmula de ranking e os pesos não são alterados pela camada V8.4.

O `brain_runtime.py` aplica apenas correções de interpretação antes da execução: formatos reais de CPU, preços PT/EU, submarcas, JSON-LD e cartões de catálogo.

### 2. Acesso adaptativo

A V8.4 aprende por **loja + método + perfil de browser**. O histórico global de cada browser também serve de prior quando um método ainda não tem dados suficientes.

Lojas persistentemente bloqueadas entram em `probe mode`: recebem uma tentativa barata por run em vez de consumir dezenas de pedidos repetindo estratégias que já provaram não funcionar.

Existem dois fusíveis:

- orçamento global de pedidos por run;
- orçamento máximo por loja.

A execução também tem deadline interno e timeout do próprio job no GitHub Actions.

### 3. Descoberta e pré-ranking

A descoberta combina, quando disponível:

1. JSON-LD / dados estruturados;
2. cartões de produto;
3. links dentro da categoria;
4. robots.txt + sitemaps como fallback.

Os produtos não são enriquecidos simplesmente do mais barato para o mais caro. Existe um **pré-ranking de potencial** baseado no hardware já visível no título e no preço, com quota por loja para evitar que uma única fonte ocupe todo o orçamento.

### 4. Fontes de preço vs. fontes de referência

As lojas de preço atuais estão em `category_urls` no `config.json`.

A página oficial ASUS está em `reference_sources`: é útil para validar modelos/especificações, mas não é tratada como loja de preço porque o catálogo português não expõe PVP de forma suficientemente fiável para o rastreador automático.

### 5. Qualidade e teclado

A extração dá prioridade a tabelas técnicas e pares label→value. O título é fallback, não uma fonte equivalente a uma ficha técnica.

Teclado explicitamente não-PT é rejeitado. Teclado desconhecido pode continuar no ranking, mas a incerteza continua refletida na qualidade/confiança dos dados.

## Value Score e tiers

Configuração atual:

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 130 |

Os alertas ntfy estão configurados para **Ouro ou Diamante**.

## Lojas

Fontes de preço configuradas:

- PCDiga
- PcComponentes
- Globaldata
- Radio Popular
- CHIP7
- FNAC
- Worten

O sistema não tenta contornar CAPTCHA ou mecanismos anti-bot. Quando uma fonte bloqueia sistematicamente os pedidos, aprende a reduzir tentativas e continua a verificar periodicamente se o acesso mudou.

## Estado persistido

`data/history.json` guarda:

- observações de preço;
- specs usadas no scoring;
- tiers e Value Score;
- estado de alertas;
- resumo das runs recentes.

`data/access_learning.json` guarda a aprendizagem de acesso por loja, browser e método.

O workflow sincroniza o `main` antes de começar e usa `state_merge.py` na persistência para evitar que uma run apague observações mais recentes.

## Testes

```bash
python -m unittest discover -s tests -v
```

A suite inclui regressões para, entre outros:

- GPU integrada vs. dedicada;
- VRAM explícita vs. RAM do sistema;
- TGP;
- CPUs Intel/Ryzen e classes U/H/HS/HX;
- preços portugueses com separador de milhares;
- prestações vs. preço real do produto;
- JSON-LD com listas de ofertas;
- submarcas sem marca-mãe no título;
- aprendizagem de browser;
- probe mode;
- budgets por loja;
- exceções de rede;
- merge seguro do histórico.

## Execução automática

O workflow corre:

- em push para `main`;
- a cada 6 horas;
- manualmente via `workflow_dispatch`.

O job instala dependências fixadas, corre toda a suite de testes, valida `NTFY_TOPIC`, executa o rastreador e só depois persiste histórico/aprendizagem.

## Princípio de evolução

A V8 permanece o cérebro estável. As versões 8.x melhoram aquisição, qualidade dos dados, observabilidade, aprendizagem e eficiência. Uma futura mudança de geração do cérebro só deve acontecer quando houver cobertura e dados suficientes para medir claramente se a nova lógica é melhor que a anterior.
