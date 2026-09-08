# Rastreador de Preços — V8.6.1

Motor de inteligência de mercado para portáteis ASUS, Lenovo e HP em Portugal. O sistema combina descoberta de catálogo, acesso adaptativo, extração técnica, scoring orientado ao uso FEUP + gaming, histórico, cache e notificações ntfy.

## Estrutura

```text
scraper.py                  cérebro V8: parsing de hardware + scoring
tracker.py                  acesso, descoberta, cache, histórico, alertas e heartbeat
config/config.json          limites, lojas, pesos e tiers
tests/test_tracker.py       regressões do cérebro e do tracker
data/history.json           preços/configurações recentes e estado de alertas
data/access_learning.json   aprendizagem de acesso por loja/método/browser
.github/workflows/tracker.yml
requirements.txt
```

A divisão é intencional: `scraper.py` decide **o que vale a pena**; `tracker.py` decide **como observar o mercado de forma eficiente**.

## Universo

Apenas equipamento novo das famílias:

- ASUS — ROG, TUF, Vivobook, Zenbook, ExpertBook, ProArt
- Lenovo — Legion, LOQ, IdeaPad, ThinkPad, ThinkBook, Yoga
- HP — OMEN, Victus, OmniBook, EliteBook, ProBook, Envy, Pavilion

Apple, usados, recondicionados e outlet ficam excluídos.

## Scoring

O cérebro V8 mantém as dimensões FEUP, Gaming, Longevidade e Portabilidade. O Value Score combina ranking técnico/adequação com preço.

Tiers atuais:

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

Diamante é deliberadamente raro: representa uma combinação excecional de adequação e preço, sem exigir quase perfeição matemática como acontecia com 130.

## Descoberta e cobertura

O tracker pode combinar:

1. categoria;
2. paginação pública confirmada;
3. JSON-LD e cartões de produto;
4. sitemaps quando demonstram retorno útil;
5. probe mode para lojas persistentemente bloqueadas.

Cada loja tem orçamento próprio e existe também orçamento global/deadline. O sistema não tenta contornar CAPTCHA ou mecanismos anti-bot.

A cache de especificações é independente do orçamento de fichas novas: produtos descobertos novamente podem reutilizar CPU/GPU/RAM/ecrã já confirmados, libertando acessos de detalhe para SKUs novos.

## Identidade de configurações

Nunca assumimos que o nome comercial identifica uma configuração única. `ASUS TUF Gaming A16`, por exemplo, pode existir com GPUs, RAM e SSD diferentes.

A ordem de confiança é:

1. SKU / part number / EAN quando disponível;
2. caso contrário, uma assinatura conservadora que inclui título + CPU + GPU + RAM + SSD + ecrã.

A V8.6.1 executa matching cross-store conservador em quatro níveis: **EXATO** (EAN/MPN), **FORTE** (model code + CPU/GPU/RAM/SSD), **PROVÁVEL** (apenas para revisão) e **NÃO FUNDIR** quando existe conflito técnico. Só EXATO/FORTE formam grupos automáticos de ofertas e nunca alteram o histórico individual de cada loja.

## Acesso adaptativo

O tracker aprende por loja + método + perfil de browser. Fontes persistentemente bloqueadas entram em `probe mode`, recebendo uma tentativa barata em vez de desperdiçar dezenas de requests.

A aprendizagem de acesso é persistida em `data/access_learning.json` e não é apagada quando o histórico de preços é compactado. A V8.6.1 aprende também o **rendimento de descoberta** (novos candidatos por request) por método/segmento e usa esse histórico para ordenar rotas alternativas mais produtivas.

## Histórico

O histórico V8.6.1 é automaticamente compactado:

- remove formatos e observações pré-V8.6.1;
- normaliza chaves por URL;
- mantém apenas observações recentes necessárias para preço/cache;
- preserva estado de alertas válido;
- mantém apenas as runs V8.6.1 recentes.

## ntfy

Existem dois sinais independentes:

- alertas de oportunidade (Ouro/Diamante, upgrades de tier ou quedas de preço);
- heartbeat de saúde em todas as runs normais.

Se o pipeline falhar antes de o Python terminar, o GitHub Actions envia um heartbeat de falha separado.

## Testes

```bash
python -m py_compile scraper.py tracker.py tests/test_tracker.py
python -m unittest discover -s tests -p 'test_tracker.py' -v
```

A suite cobre preços PT/EU, CPU/GPU, VRAM, TGP, M.2, JSON-LD, IDs fortes, variantes de configuração, cache, paginação, budgets, probe mode, heartbeat, histórico e merge concorrente.

## Execução

O workflow corre em push para `main`, manualmente e a cada 6 horas. A ordem é testes → validação ntfy → tracker → heartbeat → merge/persistência segura.


## Refinamentos V8.6.1

- O matching distingue produtos não relacionados de conflitos reais de variante.
- Comparações cross-store só notificam quando a melhor oferta cumpre o tier mínimo e a diferença é pelo menos 50 € ou 5%.
- A PCDiga prioriza famílias de maior interesse no sitemap e pode usar o host público `publojas.pcdiga.com` como fallback de ficha, mantendo a URL canónica da oferta.
