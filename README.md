# Rastreador de Preços — V8.8

Motor de inteligência de mercado para portáteis ASUS, Lenovo e HP em Portugal. O sistema combina descoberta de catálogo, acesso adaptativo, extração técnica, scoring orientado ao uso FEUP + gaming, validação reforçada de preços, matching cross-store, histórico, cache e notificações ntfy.

## Estrutura

```text
scraper.py                  cérebro V8: parsing de hardware + scoring técnico
price_guard.py              V8.8: confiança de preço, quarentena e bónus de oportunidade
tracker.py                  acesso, descoberta, cache, matching, histórico, alertas e heartbeat
runner.py                   composition root V8.8
config/config.json          limites, lojas, pesos, tiers e parâmetros de segurança
tests/test_tracker.py       regressões do cérebro, acesso, matching e estado
tests/test_price_guard.py   regressões de preço e oportunidades excecionais
data/history.json           ofertas/configurações recentes e estado de alertas
data/access_learning.json   aprendizagem por loja, método e perfil
.github/workflows/tracker.yml
requirements.txt
```

A separação é intencional: `scraper.py` mede a adequação técnica, `price_guard.py` decide se o preço é confiável e como valorizar uma oportunidade excecional, e `tracker.py` decide como observar o mercado de forma eficiente. O `runner.py` apenas compõe estas camadas; não contém lógica de negócio duplicada.

## Universo

Apenas equipamento novo das famílias:

- ASUS — ROG, TUF, Vivobook, Zenbook, ExpertBook, ProArt
- Lenovo — Legion, LOQ, IdeaPad, ThinkPad, ThinkBook, Yoga
- HP — OMEN, Victus, OmniBook, EliteBook, ProBook, Envy, Pavilion

Apple, usados, recondicionados e outlet ficam excluídos.

## Cérebro e tiers

O cérebro V8 mantém as dimensões FEUP, Gaming, Longevidade e Portabilidade. O ranking técnico continua separado da oportunidade de preço.

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

Diamante deve representar uma combinação verdadeiramente excecional entre configuração e preço, não apenas hardware topo.

## V8.8 — confiança de preço

Um preço muito baixo não é rejeitado só por parecer improvável. Em vez disso, a V8.8 procura confirmação independente na ficha através de famílias de sinais como JSON-LD, metadata de produto e preço final/visível.

Além da própria ficha, a V8.8 pode confirmar o preço através do mercado quando **duas ou mais lojas independentes apresentam o mesmo EAN/GTIN ou MPN e preços concordantes**. Esta confirmação é deliberadamente conservadora: matching `FORTE` ou `PROVÁVEL` nunca é suficiente para certificar preço.

- preço normal confirmado: entra no ranking;
- preço suspeito com pelo menos duas famílias independentes concordantes na ficha: pode entrar no ranking;
- preço suspeito confirmado por pelo menos duas lojas com EAN/MPN exato: pode entrar no ranking;
- preço suspeito sem confirmação suficiente: `PRICE_UNCONFIRMED` → quarentena;
- preço do catálogo que diverge do preço confirmado da ficha: `PRICE_CONFLICT` → quarentena;
- preço que diverge de um cluster cross-store exato confirmado: `PRICE_CONFLICT` → quarentena.

Itens em quarentena não entram nos tiers nem geram alerta de oportunidade.

Abaixo do budget soft, um preço confirmado com confiança **HIGH** pode receber um bónus de oportunidade progressivo, até +15 pontos perto dos 500 €. Assim, 499 € e 1.299 € já não são tratados como equivalentes, mas o bónus nunca existe sem validação forte do preço.

A evidência de preço é **efémera por run**. CPU/GPU/RAM/ecrã podem ser reutilizados da cache, mas `price_confirmed`, confiança de página e confirmação de mercado não são tratados como specs permanentes. Isto impede que um preço confirmado ontem bloqueie legitimamente uma promoção nova hoje.

## Descoberta e capacidade

O tracker pode combinar:

1. categoria;
2. segmentos/filtros públicos;
3. paginação pública;
4. JSON-LD e cartões;
5. sitemaps quando demonstram retorno;
6. probe mode para métodos persistentemente bloqueados.

O sistema aprende o rendimento de descoberta (`novos candidatos / request`) por loja e método.

Budgets atuais da V8.8:

- até **240 avaliações** por run;
- até **90 detail fetches**;
- até **300 pedidos HTTP** globais;
- até **60 pedidos por loja**;
- deadline interno de **8 minutos**.

Estes valores são limites de segurança, não objetivos a consumir. A cache deve evitar pedidos desnecessários.

## PCDiga

A página de categoria é pouco útil para descoberta server-side, por isso a estratégia usa sitemap e fichas de produto. O preço da ficha pode aparecer como texto simples; a V8.8 usa extração contextual e a camada de confiança de preço para evitar preço antigo/PVPR, descontos, mensalidades e financiamento. Nunca escolhe simplesmente o menor valor em euros da página.

## Identidade e matching cross-store

Nunca assumimos que o nome comercial identifica uma configuração única. Um `ASUS TUF Gaming A16`, por exemplo, pode existir com GPU, RAM, SSD, ecrã e bateria diferentes.

A ordem de evidência é:

1. EAN/GTIN ou MPN/part number;
2. SKU quando acompanhado por configuração técnica completa;
3. model code + CPU + GPU + RAM + SSD;
4. assinatura técnica conservadora apenas para análise.

Níveis:

- **EXATO** — EAN/MPN idêntico;
- **FORTE** — model code/SKU + configuração principal coincidem;
- **PROVÁVEL** — apenas revisão, nunca fusão automática;
- **NÃO FUNDIR** — conflito real entre variantes da mesma família.

Só EXATO/FORTE formam grupos automáticos. Para **confirmar preço**, a regra é ainda mais rígida: apenas EAN/MPN exato pode formar um cluster de mercado. Alertas cross-store exigem que a melhor oferta cumpra o tier mínimo e que a diferença seja pelo menos 50 € ou 5%.

## Cache e identidade progressiva

Specs já conhecidas podem ser reutilizadas sem ocupar o orçamento de fichas novas. A folga de detail fetches pode refrescar gradualmente até 16 ofertas cached por run que ainda não tenham EAN/MPN. Produtos novos mantêm prioridade.

Cada URL guarda `identity_checked_at`, evitando voltar a abrir indefinidamente uma ficha já verificada sem identificador forte.

## Acesso adaptativo

O tracker aprende por loja + método + perfil de browser. Métodos persistentemente bloqueados entram em `probe mode`, recebendo tentativas baratas em vez de consumir dezenas de requests.

A aprendizagem fica em `data/access_learning.json` e é preservada quando o histórico de preços é compactado. Não existe bypass de CAPTCHA nem tentativa de contornar mecanismos anti-bot; novas integrações devem usar apenas vias públicas e legítimas.

Uma linha de investigação para lojas bloqueadas é usar **descoberta indexada legítima** como fonte de leads: pesquisar por EAN/MPN/model code através de um fornecedor de pesquisa ou feed público, e depois validar identidade/preço através das páginas de produto, fabricante ou outras lojas. Snippets de pesquisa nunca devem ser fonte única para scoring ou alertas.

## Histórico

O histórico guarda observações recentes por URL, specs necessárias à cache, IDs de configuração, estado de alertas e runs recentes. O estado é persistido com merge concorrente para impedir que uma run antiga apague aprendizagem mais recente.

## ntfy

Existem sinais independentes:

- alertas de oportunidades Ouro/Diamante e mudanças materiais;
- alertas cross-store quando existe diferença relevante;
- heartbeat de saúde em todas as runs normais;
- heartbeat de falha pelo GitHub Actions quando o pipeline termina antes do heartbeat normal.

## Testes

```bash
python -m py_compile scraper.py tracker.py price_guard.py runner.py tests/test_tracker.py tests/test_price_guard.py
python -m unittest discover -s tests -p 'test_*.py' -v
```

A suite cobre preços PT/EU, o caso 4.999 € vs 499 €, preço antigo/desconto/mensalidade, confirmação multissinal, confirmação cross-store exata, expiração da evidência de preço na cache, Diamante excecional, CPU/GPU/VRAM/TGP/M.2, JSON-LD, IDs fortes, variantes, cache, paginação, budgets, probe mode, heartbeat, matching e merge concorrente.

## Execução

O workflow corre em push para `main`, manualmente e a cada 6 horas. A ordem é testes → validação ntfy → tracker → heartbeat → merge/persistência segura.

## Caminho para V9

A V9 fica reservada para quando todas as lojas-alvo tiverem pelo menos um método público, estável e suportado de descoberta/acesso e o matching cross-store estiver maduro. Até lá, a linha V8.x continua a melhorar cobertura, identidade, segurança de preço e eficiência sem alterar arbitrariamente o cérebro técnico.
