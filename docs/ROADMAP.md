# Roadmap — LapIntel PT

A linha atual é a **V8.8.9** e a missão principal do projeto está cumprida: o sistema percorreu o mercado, produziu três oportunidades Diamante e ajudou a escolher o **Lenovo Legion 5 15AHP-682**.

A V9 fica como próximo capítulo opcional. Não deve existir apenas porque há trabalho que ainda pode ser feito; deve representar um novo patamar de maturidade.

## O que falta para justificar uma V9

### 1. Cobertura sustentável das lojas difíceis

Na run final validada, seis das nove lojas configuradas deram acesso útil. As três limitações mais claras continuam a ser:

- **PcComponentes** — HTTP 403 nas rotas testadas;
- **CHIP7** — HTTP 403 nas rotas testadas;
- **Worten** — sitemap acessível, mas fichas de produto bloqueadas no runner.

Prioridade: fontes públicas, catálogos ou feeds autorizados. Não aumentar brute force nem tentar contornar CAPTCHA/anti-bot.

### 2. Matching cross-store mais maduro

Objetivos:

- aumentar cobertura de EAN/GTIN e MPN;
- reforçar matching EXATO/FORTE;
- evitar fusões de variantes com specs incompatíveis;
- manter casos PROVÁVEIS observáveis sem os promover automaticamente;
- usar preço cross-store apenas quando a identidade tiver evidência suficiente.

### 3. Uma única noção de tier efetivo

A lógica de decisão já considera promoções e garante **Value > 120 ⇒ DIAMANTE**.

O próximo passo é garantir que a mesma definição aparece de forma idêntica em:

- ranking;
- resumo D/O/P/B;
- heartbeat;
- logs;
- dashboards/snapshots futuros;
- notificações.

A run final mostrou que a decisão económica estava correta, mas a contagem interna de tiers ainda podia refletir o tier base em vez do tier promocional efetivo. É um bom candidato para ser o primeiro acabamento de uma V9.

### 4. Eficiência baseada em dados

Continuar a perseguir a regra:

> **mais mercado observado não deve significar proporcionalmente mais requests.**

Indicadores úteis:

- candidatos novos por request;
- candidatos aceites por request;
- percentagem de cache reutilizada;
- detail fetches por candidato relevante;
- rendimento por rota e por loja;
- tempo consumido por loja.

A run final da V8.8.9 já mostrou a direção: **356 descobertos, 300 avaliados e 230 aceites com 128 requests e 266 reutilizações de cache**.

### 5. Inteligência histórica — quando houver amostra suficiente

O histórico de preços deve amadurecer antes de ser transformado em sinal forte.

Possíveis capacidades futuras:

- preço atual vs. média 30/60/90 dias;
- percentil do preço atual;
- mínimo histórico confiável;
- tendência;
- frequência real de promoções;
- confiança da conclusão em função da amostra.

Evitar conclusões fortes a partir de históricos curtos.

### 6. Novas lojas, apenas quando acrescentarem cobertura real

A escolha final do Lenovo mostrou que ainda existe mercado fora do universo atual. Na verificação manual surgiram **Auchan** e **MEO** para o mesmo modelo.

Uma V9 pode estudar novas lojas, mas cada integração deve passar pelos mesmos critérios das atuais:

- acesso sustentável;
- informação suficiente;
- baixo desperdício de requests;
- identidade técnica útil;
- manutenção razoável.

## O que não precisa de mudar

A V9 não deve reescrever o cérebro só para parecer nova.

Continuam válidos os princípios:

- FEUP, Gaming, Longevidade e Portabilidade permanecem dimensões separadas;
- preço e qualidade técnica não são a mesma coisa;
- preço excecional exige evidência proporcional ao risco;
- matching forte exige coerência técnica;
- bloqueios de lojas não justificam bypass de proteções;
- alterações relevantes devem ficar protegidas por testes.

## Critério de saída para V9

A V9 fará sentido quando pelo menos três condições forem verdadeiras:

1. a maioria das lojas-alvo tem descoberta sustentável e previsível;
2. ranking, promoções, tier efetivo e observabilidade usam a mesma fonte de verdade;
3. matching e histórico conseguem acrescentar contexto sem aumentar falsos positivos;
4. a eficiência melhora de forma mensurável em relação à V8.8.9;
5. existe uma melhoria funcional que seja visível para o utilizador e não apenas reorganização interna.

## Depois da V9

A ambição de longo prazo continua a ser um sistema capaz de receber apenas condições de compra e tratar autonomamente de:

**observar → descobrir → identificar → validar → comparar → contextualizar → escolher → explicar**

Mas essa ambição já não é necessária para provar o valor do projeto. A V8.8.9 fechou a primeira grande história do **LapIntel PT** com uma decisão real: **Lenovo Legion 5 15AHP-682**.
