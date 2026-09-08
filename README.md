# Rastreador de Preços — V8.8.4

Motor de inteligência de mercado para portáteis ASUS, Lenovo e HP em Portugal. O sistema combina descoberta de catálogo, acesso adaptativo, extração técnica, scoring orientado ao uso FEUP + gaming, validação reforçada de preços, matching cross-store, histórico, cache e notificações ntfy.

A V8.x é deliberadamente uma linha de maturação. **V9 fica reservada para o momento em que todas as lojas-alvo tenham pelo menos um método público/estável de descoberta e o matching cross-store esteja suficientemente maduro.**

## Estrutura

```text
scraper.py                  cérebro V8: parsing de hardware + scoring técnico base
brain_guard.py              correções técnicas compatíveis (V8.8.3+) sem reescrever o cérebro
price_guard.py              confiança de preço, quarentena e bónus de oportunidade
market_guard.py             consenso/desacordo de mercado e proteção de promoções reais
tracker.py                  acesso, descoberta, cache, matching, histórico, alertas e heartbeat
runner.py                   composition root das camadas V8.8.x
config/config.json          lojas, limites, pesos, tiers e parâmetros de segurança
tests/test_brain_guard.py   regressões das correções técnicas
tests/test_tracker.py       regressões de acesso, matching, cache e estado
tests/test_price_guard.py   regressões de preços e oportunidades excecionais
tests/test_market_guard.py  regressões de consenso/desacordo cross-store
data/history.json           ofertas/configurações recentes e estado de alertas
data/access_learning.json   aprendizagem por loja, método e perfil
.github/workflows/tracker.yml
requirements.txt
```

A separação é intencional. `scraper.py` mede a adequação técnica; `brain_guard.py` corrige lacunas comprovadas por regressões sem alterar arbitrariamente a filosofia V8; `price_guard.py` decide se um preço individual é confiável; `market_guard.py` usa contexto cross-store sem transformar a maioria do mercado num veto a uma promoção real; `tracker.py` decide como observar o mercado. `runner.py` apenas compõe estas camadas.

## Universo

Apenas equipamento novo das famílias:

- ASUS — ROG, TUF, Vivobook, Zenbook, ExpertBook, ProArt
- Lenovo — Legion, LOQ, IdeaPad, ThinkPad, ThinkBook, Yoga
- HP — OMEN, Victus, OmniBook, EliteBook, ProBook, Envy, Pavilion

Apple, usados, recondicionados e outlet ficam excluídos.

### Lojas-alvo atuais

1. PCDiga
2. PcComponentes
3. Globaldata
4. Radio Popular
5. Darty
6. CHIP7
7. FNAC
8. Worten

A Darty entrou na V8.8.4 depois de uma auditoria externa ao tracker ter encontrado ofertas reais que o universo anterior não observava. Isto faz parte da estratégia do projeto: quando a análise independente encontra uma fonte relevante e legítima, o scanner deve ser capaz de a incorporar de forma nativa.

## Cérebro e tiers

O cérebro V8 mantém as dimensões FEUP, Gaming, Longevidade e Portabilidade. O ranking técnico continua separado da oportunidade de preço.

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

Diamante deve representar uma combinação verdadeiramente excecional entre configuração e preço, não apenas hardware topo.

### Correção de RAM intermédia

A V8.8.3 corrigiu uma lacuna do V8: capacidades entre 16 e 32 GB (sobretudo 24 GB) caíam no ramo de longevidade de 40 pontos. Agora 24 GB recebem uma classe coerente e conservadora, preservando a política já existente para 16 e 32 GB.

## V8.8 — confiança de preço

Um preço muito baixo não é rejeitado só por parecer improvável. Em vez disso, a V8.8 procura confirmação independente na ficha através de famílias de sinais como JSON-LD, metadata de produto e preço final/visível.

Além da própria ficha, a V8.8 pode usar o mercado como evidência quando **duas ou mais lojas independentes apresentam o mesmo EAN/GTIN ou MPN e preços concordantes**. Esta confirmação é deliberadamente conservadora: matching `FORTE` ou `PROVÁVEL` nunca é suficiente para certificar preço.

- preço normal confirmado: entra no ranking;
- preço suspeito com pelo menos duas famílias independentes concordantes na ficha: pode entrar no ranking;
- preço suspeito confirmado por pelo menos duas lojas com EAN/MPN exato: pode entrar no ranking;
- preço suspeito sem confirmação suficiente: `PRICE_UNCONFIRMED` → quarentena;
- preço do catálogo que diverge do preço confirmado da ficha: `PRICE_CONFLICT` → quarentena;
- preço sem evidência própria forte que diverge de um cluster cross-store exato: `PRICE_CONFLICT` → quarentena.

Itens em quarentena não entram nos tiers nem geram alerta de oportunidade.

Abaixo do budget soft, um preço confirmado com confiança **HIGH** pode receber um bónus de oportunidade progressivo, até +15 pontos perto dos 500 €. Assim, 499 € e 1.299 € já não são tratados como equivalentes, mas o bónus nunca existe sem validação forte do preço.

A evidência de preço é temporal. CPU/GPU/RAM/ecrã podem ser reutilizados da cache, mas confirmação de preço tem TTL e é refrescada quando fica antiga ou quando o preço muda.

## V8.8.4 — promoção real vs. consenso de mercado

A maioria das lojas não é uma fonte de verdade absoluta. Uma promoção genuína pode ser muito mais barata do que todas as outras ofertas do mesmo EAN/MPN.

Por isso a V8.8.4 estabelece uma hierarquia explícita de evidência:

1. **ficha do próprio comerciante com preço HIGH** (duas ou mais famílias independentes concordantes);
2. cluster cross-store exato por EAN/MPN;
3. preço de catálogo sem confirmação forte.

Se duas lojas ou um cluster de mercado discordarem de uma oferta, mas a própria ficha dessa oferta confirmar o preço com confiança HIGH, o sistema trata-a como **market outlier verificado** em vez de a rejeitar automaticamente. A referência do mercado continua guardada para contexto e auditoria.

Se a ficha não tiver confirmação HIGH, o comportamento conservador mantém-se: um desacordo extremo fica em quarentena.

Esta regra é importante para não confundir “preço demasiado bom” com “preço falso”.

## Descoberta e capacidade

O tracker pode combinar:

1. categoria;
2. segmentos/filtros públicos;
3. paginação pública;
4. JSON-LD e cartões;
5. sitemaps quando demonstram retorno;
6. probe mode para métodos persistentemente bloqueados.

O sistema aprende o rendimento de descoberta (`novos candidatos / request`) por loja e método.

Budgets atuais:

- até **240 avaliações** por run;
- até **90 detail fetches**;
- até **300 pedidos HTTP** globais;
- até **60 pedidos por loja**;
- deadline interno de **8 minutos**.

Estes valores são fusíveis de segurança, não objetivos a consumir. A cache deve evitar pedidos desnecessários.

## PCDiga

A página de categoria é pouco útil para descoberta server-side, por isso a estratégia usa sitemap e fichas de produto. O preço da ficha pode aparecer como texto simples; a V8.8 usa extração contextual e a camada de confiança de preço para evitar preço antigo/PVPR, descontos, mensalidades e financiamento. Nunca escolhe simplesmente o menor valor em euros da página.

A PCDiga já voltou a produzir candidatos reais, mas continua a ter um custo por candidato superior a Globaldata/FNAC/Radio Popular. Melhorar o seu rendimento por request continua a ser um objetivo V8.x.

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

Specs já conhecidas podem ser reutilizadas sem ocupar o orçamento de fichas novas. A folga de detail fetches pode refrescar gradualmente ofertas cached que ainda não tenham EAN/MPN ou cuja evidência de preço precise de atualização. Produtos novos mantêm prioridade.

Cada URL guarda `identity_checked_at`, evitando voltar a abrir indefinidamente uma ficha já verificada sem identificador forte.

## Acesso adaptativo

O tracker aprende por loja + método + perfil de browser. Métodos persistentemente bloqueados entram em `probe mode`, recebendo tentativas baratas em vez de consumir dezenas de requests.

A aprendizagem fica em `data/access_learning.json` e é preservada quando o histórico de preços é compactado. Não existe bypass de CAPTCHA nem tentativa de contornar mecanismos anti-bot; novas integrações devem usar apenas vias públicas e legítimas.

Para lojas bloqueadas, uma linha de investigação é usar **descoberta indexada legítima como fonte de leads**: procurar EAN/MPN/model code por uma API/fornecedor de pesquisa, feed público ou endpoint de catálogo autorizado, e depois validar identidade/preço através da ficha do comerciante, fabricante ou outras lojas. Snippets de pesquisa nunca devem ser fonte única para scoring ou alertas.

## Princípio de descoberta assistida

A auditoria externa ao tracker mostrou que uma pesquisa orientada por intenção consegue encontrar oportunidades que um crawler limitado a uma lista fixa de lojas não vê. Esse padrão pode ser transposto para o sistema de forma controlada:

- pesquisa por configuração/segmento (`RTX 5070`, `32GB`, etc.) apenas como **lead generation**;
- assim que surge um EAN/MPN, pesquisar esse ID exato no mercado;
- usar a loja para preço/stock atual;
- usar fabricante ou outra fonte exata para specs que a loja omite;
- guardar a proveniência e confiança de cada evidência;
- integrar como loja nativa uma fonte que demonstre qualidade e estabilidade.

O objetivo não é copiar um browser/serviço externo, mas reproduzir o **método de raciocínio e validação** com APIs/feeds/interfaces públicas apropriadas.

## Histórico

O histórico guarda observações recentes por URL, specs necessárias à cache, IDs de configuração, estado de alertas e runs recentes. O estado é persistido com merge concorrente para impedir que uma run antiga apague aprendizagem mais recente.

## ntfy e observabilidade

Existem sinais independentes:

- alertas de oportunidades Ouro/Diamante e mudanças materiais;
- alertas cross-store quando existe diferença relevante;
- heartbeat de saúde em todas as runs normais;
- heartbeat de falha pelo GitHub Actions quando o pipeline termina antes do heartbeat normal.

Desde a V8.8.4 existe ainda um **heartbeat redundante no workflow**. Se o tracker terminar normalmente mas a sua chamada ao ntfy falhar por uma janela de conectividade, o GitHub Actions tenta novamente por um caminho independente. Se nem o heartbeat principal nem o redundante conseguirem ser entregues, a run não é considerada totalmente saudável.

## Testes

```bash
python -m py_compile scraper.py brain_guard.py price_guard.py market_guard.py tracker.py runner.py tests/test_brain_guard.py tests/test_tracker.py tests/test_price_guard.py tests/test_market_guard.py
python -m unittest discover -s tests -p 'test_*.py' -v
```

A suite cobre preços PT/EU, o caso 4.999 € vs 499 €, preço antigo/desconto/mensalidade, confirmação multissinal, confirmação cross-store exata, promoções reais que divergem do mercado, desacordo extremo sem evidência suficiente, expiração da evidência de preço na cache, Diamante excecional, RAM intermédia, CPU/GPU/VRAM/TGP/M.2, JSON-LD, IDs fortes, variantes, cache, paginação, budgets, probe mode, heartbeat, matching e merge concorrente.

## Execução

O workflow corre em push para `main`, manualmente e a cada 6 horas. Alterações apenas em `data/**` ou `README.md` não criam runs redundantes.

A ordem operacional é:

`testes → validação ntfy → tracker → verificação/heartbeat redundante → merge/persistência segura`.

## Evolução resumida

- **V8.5** — cobertura por paginação, cache útil e primeira grande consolidação;
- **V8.6** — aprendizagem de rendimento de descoberta e fundação do matching;
- **V8.7** — identidade progressiva e maior capacidade de análise;
- **V8.8** — confiança de preço, quarentena e bónus de oportunidade;
- **V8.8.2** — desacordo de mercado por identidade exata;
- **V8.8.3** — correção comprovada para capacidades intermédias de RAM;
- **V8.8.4** — precedência de evidência HIGH da própria loja, Darty e heartbeat redundante;
- **V9** — todas as lojas-alvo com método estável + matching cross-store maduro.

Esta cronologia e as métricas das runs devem ser preservadas porque servirão de base à futura apresentação V9/V10: problema inicial, arquitetura, cérebro, segurança, cobertura, evolução medida, demonstração de matching e visão futura.
