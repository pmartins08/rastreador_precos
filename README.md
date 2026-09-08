# Rastreador de Preços — V8.8.5

Motor de inteligência de mercado para portáteis ASUS, Lenovo e HP em Portugal. O sistema combina descoberta adaptativa, campanhas promocionais como fonte de leads, extração técnica, scoring orientado ao uso FEUP + gaming, validação reforçada de preços, matching cross-store, histórico de preços, cache e notificações ntfy.

A V8.x continua deliberadamente uma linha de maturação. **V9 fica reservada para o momento em que todas as lojas-alvo tenham pelo menos um método público/estável de descoberta e o matching cross-store esteja suficientemente maduro.**

## Estrutura

```text
version.py                    versão pública única do runtime
version_guard.py              compatibilidade de labels/estado de versões anteriores
scraper.py                    cérebro V8: parsing de hardware + scoring técnico base
brain_guard.py                correções técnicas comprovadas sem reescrever o cérebro
price_guard.py                confiança de preço, quarentena e bónus de oportunidade
market_guard.py               consenso/desacordo cross-store e proteção de promoções reais
promotion_guard.py            campanhas públicas como leads e prioridade de pré-ranking
historical_guard.py           histórico compacto de preços a 90 dias
tracker.py                    acesso, descoberta, cache, matching, histórico e alertas
runner.py                     composition root das camadas V8.8.x
config/config.json            lojas, limites, pesos, tiers e parâmetros de segurança
data/history.json             ofertas/configurações recentes e estado de alertas
data/access_learning.json     aprendizagem por loja, método e perfil
data/price_history.json       histórico diário compacto (criado/atualizado pelo runtime)
tests/                        regressões do cérebro, guards, tracker e histórico
.github/workflows/ci.yml      validação de pull requests/branch de desenvolvimento
.github/workflows/tracker.yml execução periódica e persistência segura
requirements.txt
```

A separação é intencional. `scraper.py` mede a adequação técnica; `brain_guard.py` corrige lacunas comprovadas; `price_guard.py` decide se um preço individual é confiável; `market_guard.py` usa contexto cross-store; `promotion_guard.py` decide onde vale a pena procurar primeiro; `historical_guard.py` acrescenta contexto temporal. `tracker.py` continua responsável pela observação do mercado e `runner.py` apenas compõe as camadas.

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

A Darty entrou na V8.8.4 depois de uma auditoria externa ter encontrado ofertas reais que o universo anterior não observava. A estratégia permanece aberta a novas fontes relevantes, desde que possam ser integradas através de interfaces públicas e legítimas.

## Cérebro e tiers

O cérebro V8 mantém quatro dimensões principais: **FEUP, Gaming, Longevidade e Portabilidade**. O ranking técnico continua separado da oportunidade de preço.

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

Diamante deve representar uma combinação verdadeiramente excecional entre configuração e preço, não apenas hardware topo.

### Correção de RAM intermédia

A V8.8.3 corrigiu uma lacuna comprovada do V8: capacidades entre 16 e 32 GB, sobretudo 24 GB, caíam no ramo de longevidade de 40 pontos. `brain_guard.py` corrige apenas esse caso sem alterar arbitrariamente a restante filosofia do cérebro.

## V8.8 — confiança de preço

Um preço muito baixo não é rejeitado apenas por parecer improvável. A V8.8 procura confirmação independente na própria ficha através de famílias de sinais como JSON-LD, metadata de produto e preço final/visível.

Além da ficha, o sistema pode usar o mercado como evidência quando **duas ou mais lojas independentes apresentam o mesmo EAN/GTIN ou MPN e preços concordantes**. Matching `FORTE` ou `PROVÁVEL` nunca é suficiente para certificar preço.

- preço normal confirmado: entra no ranking;
- preço suspeito com múltiplas famílias independentes concordantes: pode entrar;
- preço suspeito confirmado por lojas independentes com EAN/MPN exato: pode entrar;
- preço suspeito sem confirmação suficiente: `PRICE_UNCONFIRMED` → quarentena;
- catálogo vs ficha em conflito: `PRICE_CONFLICT` → quarentena;
- oferta sem evidência própria forte que diverge de cluster exato: `PRICE_CONFLICT` → quarentena.

Itens em quarentena não entram nos tiers nem geram alerta de oportunidade.

Abaixo do budget soft, um preço confirmado com confiança **HIGH** pode receber um bónus de oportunidade progressivo, até +15 pontos perto dos 500 €. O bónus nunca existe sem validação forte do preço.

A evidência de preço é temporal. CPU/GPU/RAM/ecrã podem ser reutilizados da cache, mas confirmação de preço tem TTL e é refrescada quando envelhece ou quando o preço muda.

## V8.8.4 — promoção real vs. consenso de mercado

A maioria das lojas não é uma fonte de verdade absoluta. Uma promoção genuína pode ser muito mais barata que as restantes ofertas do mesmo EAN/MPN.

A hierarquia de evidência é:

1. **ficha do próprio comerciante com preço HIGH**;
2. cluster cross-store exato por EAN/MPN;
3. preço de catálogo sem confirmação forte.

Se o mercado discordar de uma oferta mas a própria ficha confirmar o preço com confiança HIGH, o sistema trata-a como **market outlier verificado** em vez de a rejeitar automaticamente. Sem confirmação HIGH, um desacordo extremo mantém o comportamento conservador e pode levar a quarentena.

## V8.8.5 — Promo Intelligence

A V8.8.5 acrescenta uma ideia diferente: **campanhas promocionais são uma fonte prioritária de descoberta, não uma fonte de verdade**.

Quando existe uma campanha pública ativa — por exemplo Regresso às Aulas — `promotion_guard.py` pode colocá-la à frente de segmentos genéricos. Rotas com datas conhecidas deixam automaticamente de estar ativas quando expiram.

Produtos encontrados numa campanha recebem apenas:

- proveniência `promocao`;
- prioridade adicional no **pré-ranking**, para merecerem análise mais cedo;
- métricas próprias de rendimento (`novos candidatos / request`).

A promoção **não altera** diretamente:

- score técnico;
- Value;
- tier;
- confiança de preço;
- regras de quarentena.

Assim, um banner “-40%” nunca consegue criar um Ouro/Diamante. O produto continua obrigatoriamente a passar pelo Brain Guard, Price Guard e Market Guard.

## V8.8.5 — histórico de preços a 90 dias

`historical_guard.py` cria uma segunda dimensão temporal: o preço atual passa a poder ser comparado com observações anteriores do próprio sistema.

A identidade histórica segue uma política conservadora:

1. EAN/GTIN → histórico `EXATO` partilhável entre lojas;
2. MPN → histórico `EXATO` partilhável entre lojas;
3. sem ID forte → histórico `LOCAL` da própria URL, nunca fundido entre comerciantes.

Para evitar crescimento desnecessário, não são guardadas todas as observações completas. Por identidade e por dia são compactados:

- mínimo;
- máximo;
- último preço;
- soma e número de amostras;
- lojas observadas.

A janela ativa é de **90 dias**. O contexto pode indicar mínimo, média, mediana dos mínimos diários e se o preço atual representa um **novo mínimo** ou está perto do mínimo observado.

O histórico é deliberadamente informativo nesta versão: **não altera sozinho o Value, o tier ou a confiança de preço**. Serve para melhorar a explicação da oportunidade e os alertas ntfy.

Importante: a comparação de uma run usa como baseline apenas o estado anterior à própria run. Duas lojas observadas segundos uma da outra não são confundidas com “histórico passado”.

### Referências históricas externas

Comparadores como KuantoKusta são uma linha de investigação útil porque podem oferecer histórico adicional e identificadores fortes. A integração externa não faz ainda parte do runtime V8.8.5. Quando existir uma interface pública suficientemente estável, a regra prevista é conservadora: usar EAN/MPN para matching e tratar a fonte externa apenas como **contexto secundário**, nunca como certificação autónoma de preço ou atalho para Diamante.

## Descoberta e capacidade

O tracker pode combinar:

1. campanhas públicas ativas;
2. categoria;
3. segmentos/filtros públicos;
4. paginação pública;
5. JSON-LD e cartões;
6. sitemaps quando demonstram retorno;
7. probe mode para métodos persistentemente bloqueados.

O sistema aprende o rendimento de descoberta (`novos candidatos / request`) por loja e método.

Budgets atuais:

- até **240 avaliações** por run;
- até **90 detail fetches**;
- até **300 pedidos HTTP** globais;
- até **60 pedidos por loja**;
- deadline interno de **8 minutos**.

Estes valores são fusíveis de segurança, não objetivos a consumir. A cache deve evitar pedidos desnecessários.

## PCDiga

A página de categoria é pouco útil para descoberta server-side, por isso a estratégia pode usar sitemap e fichas de produto. O preço da ficha pode aparecer como texto simples; a camada de confiança evita preço antigo/PVPR, descontos, mensalidades e financiamento. Nunca se escolhe simplesmente o menor valor em euros da página.

A PCDiga já produz candidatos reais, mas continua a ter custo por candidato superior às melhores fontes. Melhorar o rendimento por request permanece objetivo da linha V8.x.

## Identidade e matching cross-store

Nunca assumimos que o nome comercial identifica uma configuração única. Um `ASUS TUF Gaming A16`, por exemplo, pode existir com GPU, RAM, SSD, ecrã e bateria diferentes.

Ordem de evidência:

1. EAN/GTIN ou MPN/part number;
2. SKU quando acompanhado por configuração técnica completa;
3. model code + CPU + GPU + RAM + SSD;
4. assinatura técnica conservadora apenas para análise.

Níveis:

- **EXATO** — EAN/MPN idêntico;
- **FORTE** — model code/SKU + configuração principal coincidem;
- **PROVÁVEL** — apenas revisão, nunca fusão automática;
- **NÃO FUNDIR** — conflito real entre variantes da mesma família.

Só EXATO/FORTE formam grupos automáticos. Para **confirmar preço**, apenas EAN/MPN exato pode formar um cluster de mercado. Alertas cross-store exigem que a melhor oferta cumpra o tier mínimo e que a diferença seja pelo menos 50 € ou 5%.

## Cache e identidade progressiva

Specs já conhecidas podem ser reutilizadas sem ocupar o orçamento de fichas novas. A folga de detail fetches pode refrescar gradualmente ofertas cached que ainda não tenham EAN/MPN ou cuja evidência de preço precise de atualização. Produtos novos mantêm prioridade.

Cada URL guarda `identity_checked_at`, evitando voltar a abrir indefinidamente uma ficha já verificada sem identificador forte.

## Acesso adaptativo

O tracker aprende por loja + método + perfil de browser. Métodos persistentemente bloqueados entram em `probe mode`, recebendo tentativas baratas em vez de consumir dezenas de requests.

A aprendizagem fica em `data/access_learning.json`. Não existe bypass de CAPTCHA nem tentativa de contornar mecanismos anti-bot; novas integrações devem usar apenas vias públicas e legítimas.

Para lojas bloqueadas, uma linha de investigação é usar descoberta indexada legítima apenas como **lead generation**: encontrar EAN/MPN/model code por API, feed público ou endpoint autorizado e depois validar identidade/preço através do comerciante, fabricante ou outras lojas. Snippets nunca devem ser fonte única para scoring ou alertas.

## Histórico e estado

Existem agora três estados persistentes com objetivos diferentes:

- `data/history.json` — ofertas/configurações recentes, cache, alertas e métricas de runs;
- `data/access_learning.json` — aprendizagem de acesso e rendimento por método;
- `data/price_history.json` — séries diárias compactas de preço até 90 dias.

A persistência no GitHub Actions faz merge seguro após sincronizar com `main`, para uma run antiga não apagar estado mais recente.

Referências a versões V8.5–V8.8.x mantidas na compatibilidade de estado **não são resíduos**: permitem reutilizar cache válida e preservar a evolução medida do sistema.

## ntfy e observabilidade

Existem sinais independentes:

- alertas de oportunidades Ouro/Diamante e mudanças materiais;
- contexto histórico quando disponível;
- alertas cross-store quando existe diferença relevante;
- heartbeat de saúde em todas as runs normais;
- heartbeat redundante pelo GitHub Actions;
- heartbeat de falha quando o pipeline termina prematuramente.

A versão pública do runtime está centralizada em `version.py`, evitando manter `v884`, `v881`, etc. espalhados pelo workflow atual.

## Testes e CI

```bash
python -m py_compile version.py version_guard.py scraper.py brain_guard.py price_guard.py market_guard.py promotion_guard.py historical_guard.py tracker.py runner.py
python -m unittest discover -s tests -p 'test_*.py' -v
```

A suite cobre, entre outros casos:

- preços PT/EU e o bug 4.999 € vs 499 €;
- preço antigo, desconto, mensalidade e financiamento;
- confirmação multissinal e cross-store exata;
- promoções reais que divergem do mercado;
- quarentena por evidência insuficiente;
- expiração da confiança de preço na cache;
- RAM intermédia;
- CPU/GPU/VRAM/TGP/M.2;
- JSON-LD e IDs fortes;
- variantes e matching;
- cache, paginação, budgets e probe mode;
- prioridade/expiração de campanhas;
- histórico de 90 dias, novo mínimo, compactação e merge idempotente;
- heartbeat e merge concorrente.

`.github/workflows/ci.yml` valida alterações antes da integração. O workflow de produção corre em push para `main`, manualmente e a cada 6 horas.

A ordem operacional é aproximadamente:

`testes → validação ntfy → tracker → heartbeat → merge/persistência de estado`.

## Evolução resumida

- **V8.5** — cobertura por paginação, cache útil e primeira grande consolidação;
- **V8.6** — aprendizagem de rendimento de descoberta e fundação do matching;
- **V8.7** — identidade progressiva e maior capacidade de análise;
- **V8.8** — confiança de preço, quarentena e bónus de oportunidade;
- **V8.8.2** — desacordo de mercado por identidade exata;
- **V8.8.3** — correção comprovada para capacidades intermédias de RAM;
- **V8.8.4** — precedência de evidência HIGH da própria loja, Darty e heartbeat redundante;
- **V8.8.5** — Promo Intelligence, histórico compacto de 90 dias, CI dedicada e limpeza do versionamento operacional;
- **V9** — todas as lojas-alvo com método estável + matching cross-store maduro.

## Caminho para V9

As prioridades da linha atual são:

1. estabilizar descoberta em PcComponentes, CHIP7 e Worten;
2. melhorar rendimento da PCDiga;
3. aumentar cobertura de EAN/MPN;
4. amadurecer grupos EXATO/FORTE e reduzir PROVÁVEIS ambíguos;
5. medir o valor real das campanhas por candidatos úteis/request;
6. acumular histórico suficiente para avaliar a qualidade da nova camada temporal.

Esta cronologia, as métricas das runs e os casos reais de falhas/correções devem ser preservados porque servirão de base à futura apresentação V9/V10: problema inicial, arquitetura, cérebro, segurança, cobertura, evolução medida, matching, inteligência histórica e visão futura.
