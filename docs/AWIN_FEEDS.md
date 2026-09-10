# Feeds Awin — fonte autorizada opcional

## Objetivo

Dar ao rastreador uma via estável para lojas cujo HTML público bloqueia ou limita o GitHub Actions, sem recorrer a proxies, CAPTCHA bypass, sessões privadas ou endpoints não autorizados.

A integração é **opt-in**. Sem a variável `AWIN_DATAFEED_API_KEY`, o guard não faz qualquer pedido à Awin e o comportamento normal do rastreador mantém-se.

## Lojas preparadas

O código conhece os IDs públicos dos programas portugueses:

- Darty PT — `120908`
- PcComponentes PT — `20983`
- Worten PT — `99897`

A existência de um programa Awin não garante, por si só, que um feed esteja visível para a conta. O guard consulta a lista de feeds a que a chave tem acesso e usa apenas feeds realmente devolvidos por essa lista.

## Ativação

1. Criar/usar uma conta Publisher Awin.
2. Solicitar adesão aos programas pretendidos e respeitar os termos de cada anunciante.
3. Obter a **Data Feed API Key** da Awin.
4. No repositório GitHub, criar o secret `AWIN_DATAFEED_API_KEY` com essa chave.

O workflow `tracker.yml` já expõe esse secret apenas ao processo `runner.py`. A chave não é escrita em configuração, histórico, logs ou métricas do rastreador.

## Comportamento

Quando uma das lojas preparadas fica abaixo do limiar de cobertura:

1. a primeira loja que precisar do fallback consulta uma vez a lista de feeds Awin;
2. a lista é mantida apenas em memória durante a run;
3. o guard escolhe por advertiser o feed mais adequado, preferindo membership `Joined` e idioma português;
4. descarrega o feed do anunciante;
5. aceita apenas ASUS/Lenovo/HP, produtos identificados como portáteis e não recondicionados/usados/outlet;
6. exige um `merchant_deep_link` direto para o domínio da própria loja — links de tracking Awin não são usados pelo scraper;
7. usa EAN e MPN apenas quando os campos correspondentes existem explicitamente;
8. IDs internos do merchant não são promovidos a MPN/SKU cross-store.

## Preço e hardware

O preço do feed autorizado conta como **uma fonte MEDIUM**, nunca HIGH. Isto significa que:

- preços normais podem ser avaliados mesmo que a ficha HTML esteja bloqueada;
- preços extraordinariamente baixos continuam sujeitos ao Price Guard e ficam em quarentena sem confirmação HIGH ou confirmação cross-store exata;
- não é atribuído o bónus de negócio excecional apenas com o feed.

Se `product_name + specifications + model` contiverem pelo menos dois sinais técnicos úteis entre CPU, GPU, RAM e armazenamento, o guard cria specs estruturadas de confiança conservadora. Caso contrário, o produto fica apenas como seed e continua a tentar enriquecimento pela ficha/cache normal.

## Fontes de referência

- Awin Product Feed List / Data Feed API: documentação Awin Publisher/Help.
- Darty PT Affiliate Programme: programa Awin e condições do anunciante.
- PcComponentes PT Affiliate Programme: programa Awin e catálogo otimizado para afiliados/comparadores.
- Worten PT Affiliate Programme: programa Awin PT.

Este ficheiro documenta a integração técnica; os termos atuais de cada programa devem ser consultados na Awin antes de ativar os respetivos feeds.
