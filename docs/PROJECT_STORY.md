# LapIntel PT — A história do projeto

**V1 → V8.8.9 → V9**

> Começou com uma pergunta: “Onde consigo comprar este ASUS TUF ao melhor preço?”  
> Terminou, nesta primeira grande etapa, com o próprio sistema a descobrir que o melhor candidato era um Lenovo Legion 5.

## 1. O início: um portátil, várias lojas

A V1 não tentava descobrir qual era o melhor portátil. Essa decisão já tinha sido tomada manualmente: o alvo era um ASUS TUF específico.

O programa tinha uma missão simples:

**ASUS TUF escolhido → procurar em várias lojas → extrair preços → comparar → notificar**

Parecia um problema pequeno. Na prática, foi suficiente para abrir quase todos os problemas que definiriam as versões seguintes: HTML inconsistente, páginas com JavaScript, preços promocionais, anti-bot, produtos com nomes semelhantes e dados técnicos incompletos.

## 2. V2–V4: aprender a observar o mercado

A V2 transformou a extração no problema principal. O mesmo preço podia estar em HTML, metadata, JSON estruturado ou ser carregado apenas depois de JavaScript.

Na V3, o projeto saiu temporariamente do GitHub e passou pelo Apify para experimentar infraestrutura mais orientada a scraping e browser automation.

A V4 marcou a primeira prova de conceito real: o sistema já conseguia obter preços do ASUS TUF em praticamente todas as lojas pretendidas. A Worten continuava a ser a exceção mais difícil.

Quando esse objetivo foi demonstrado, o projeto regressou ao GitHub.

## 3. V5: a pergunta que mudou tudo

A grande viragem não foi técnica. Foi conceptual:

> “Se conseguimos comparar este portátil, porque estamos nós a escolher manualmente todos os modelos que o sistema deve analisar?”

A arquitetura deixou de ser:

**Nós escolhemos → sistema compara**

E passou a ser:

**Sistema procura → sistema analisa → sistema escolhe**

Foi aqui que o projeto deixou de ser apenas um rastreador de preços.

## 4. V6: nasce o cérebro

Para escolher sozinho, o sistema precisava de responder a uma pergunta difícil: **o que significa um portátil ser bom para este utilizador?**

O cérebro passou a decompor a decisão em quatro dimensões:

- 🎓 **FEUP** — produtividade, engenharia, programação e utilização académica;
- 🎮 **Gaming** — desempenho gráfico e adequação a jogos;
- ⏳ **Longevidade** — margem para a configuração continuar relevante;
- 🎒 **Portabilidade** — peso, autonomia e adequação ao dia a dia.

CPU, GPU, RAM, SSD, VRAM, ecrã e outros atributos deixaram de ser simples texto extraído. Passaram a ser variáveis de decisão.

## 5. V7: qualidade não chega — nasce o Value

Um portátil excelente por 3.000 € não é automaticamente uma boa compra.

O projeto introduziu então o **Value Score**, combinando capacidade técnica, adequação ao utilizador e preço.

Surgiram os tiers:

**Bronze → Prata → Ouro → Diamante**

Na política final da V8.8.9, qualquer **Value bruto/efetivo superior a 120 é Diamante**. Abaixo desse limite, a dimensão Gaming continua a influenciar o tier sem alterar artificialmente o Value bruto.

## 6. V8: transformar experiências num sistema

A V8 consolidou anos de decisões incrementais numa arquitetura mais modular:

**Mercado → descoberta → extração → identidade → validação → cérebro → Value → decisão → ntfy**

A partir daqui, cada problema importante passou a ter uma camada responsável por o conter em vez de contaminar o sistema inteiro.

### V8.1–V8.3 — adaptação, budgets e segurança

O crawler começou a aprender quais métodos funcionavam melhor por loja e a gastar menos recursos em estratégias improdutivas.

Foram formalizados budgets de:

- pedidos;
- tempo;
- páginas;
- detalhe;
- esforço por loja.

A filosofia tornou-se: **nenhuma loja pode comprometer a run inteira**.

### V8.5 — cache, paginação e histórico

A observação do mercado cresceu sem obrigar a abrir repetidamente a mesma ficha.

Especificações relativamente estáveis passaram a ser reutilizadas por cache, enquanto o preço manteve tratamento mais volátil.

### V8.6–V8.7 — matching e identidade progressiva

O sistema começou a reconhecer que duas URLs diferentes podiam representar a mesma configuração.

EAN/GTIN, MPN, SKU, model code, CPU, GPU, RAM e SSD passaram a contribuir para níveis de matching:

**EXATO · FORTE · PROVÁVEL · NÃO FUNDIR**

A identidade deixou também de ter de nascer completa. Um produto podia ganhar EAN, MPN, TGP ou outros detalhes em runs posteriores.

## 7. V8.8: aprender a desconfiar dos próprios dados

Um dos bugs mais importantes do projeto foi um portátil próximo de **4.999 €** ser interpretado como **499 €**.

O cérebro fez exatamente o que lhe pedimos: viu um portátil poderoso a um preço absurdo e classificou-o como oportunidade extraordinária.

O problema estava antes do cérebro.

Nasceu o **Price Guard**: preço deixou de ser apenas um número extraído e passou a precisar de evidência.

JSON-LD, metadata, preço visível, checkout e informação estruturada começaram a ser comparados. Sem suporte suficiente, a oferta entra em quarentena e não pode gerar um falso Diamante.

### V8.8.2 — o mercado como segunda opinião

O matching cross-store passou a ajudar a perceber se um preço era plausível.

Se três lojas observam a mesma configuração perto de 1.500 € e uma diz 499 €, o sistema ganha um forte motivo para investigar antes de confiar.

### V8.8.3 — Brain Guard

Pequenas lacunas técnicas, como capacidades intermédias de RAM, passaram a ser corrigidas por uma camada de regressão testada sem reescrever arbitrariamente a filosofia original do cérebro.

### V8.8.4 — Market Guard

O sistema aprendeu o inverso do problema anterior: **um preço muito abaixo do mercado pode estar certo**.

Se a própria loja consegue provar o preço com evidência HIGH, uma discrepância deixa de ser automaticamente rejeitada e pode tornar-se um **Verified Market Outlier**.

## 8. V8.8.5–V8.8.9: a maturidade que faltava

As versões finais da linha V8.8.x transformaram os conceitos anteriores num sistema muito mais operacional.

### V8.8.5 — Promo Intelligence e histórico de 90 dias

Campanhas deixaram de ser apenas páginas promocionais e passaram a ser fontes económicas capazes de alterar o preço efetivo e o Value. O histórico de preços ganhou uma janela diária compacta de 90 dias.

### V8.8.6 — confiança GPU e eficiência de cobertura

A qualidade da identificação da GPU passou a ter impacto explícito na confiança da classificação. Rotas promocionais e métodos de descoberta começaram a ser avaliados também pelo seu rendimento.

### V8.8.7 — iGPU Intelligence

GPUs integradas deixaram de cair todas no mesmo fallback genérico. Modelos como Intel Arc 140V/130V e Radeon 890M/880M/860M/780M passaram a ser reconhecidos com classes próprias e conservadoras.

### V8.8.8 — cobertura resiliente e refresh de estado

Entraram mecanismos mais fortes de `state_epoch`, Top 5 agregado, reutilização segura do histórico e recuperação de cobertura quando uma loja perde temporariamente uma rota de descoberta.

### V8.8.9 — final desta etapa

A V8.8.9 consolidou:

- novos fallbacks de catálogo público;
- melhor uso de feeds autorizados opcionais;
- prioridade a alterações materiais de preço;
- maior integridade histórica;
- política final de tiers;
- auditoria das notificações;
- melhor isolamento entre preço, identidade, hardware e decisão.

A regra que encerrou a calibração superior ficou simples:

> **Value > 120 ⇒ DIAMANTE**

## 9. A run que fechou o ciclo

A run operacional final validada da V8.8.9 passou **325 testes** e apresentou:

| Métrica | Resultado |
|---|---:|
| Lojas configuradas | 9 |
| Candidatos descobertos | **356** |
| Avaliados | **300** |
| Aceites | **230** |
| Requests | **128** |
| Detail fetches | **40** |
| Cache reutilizada | **266** |
| Runtime | **341,6 s** |
| Lojas com acesso útil | **6 / 9** |

Isto significa que, em menos de seis minutos, o sistema observou centenas de candidatos mantendo o número de requests muito abaixo do volume de informação efetivamente processado.

### Cobertura nessa run

**Acesso útil:** PCDiga, Globaldata, Radio Popular, Darty, UPTECHBOX e FNAC.

**Bloqueadas nas rotas testadas:** PcComponentes, CHIP7 e Worten, todas com HTTP 403.

A limitação é intencionalmente tratada como um problema de cobertura — não como autorização para contornar CAPTCHA ou mecanismos anti-bot.

## 10. A promoção que mudou a decisão

A campanha da Radio Popular foi um teste perfeito à evolução do projeto.

O sistema percorreu **13 páginas** da campanha, viu **154 itens de listagem**, confirmou **142 candidatos** e encontrou **10 portáteis acima do budget bruto** que voltavam a entrar no limite depois do desconto.

Na V1, uma promoção desta natureza teria sido apenas um preço a extrair.

Na V8.8.9, passou a ser uma alteração económica real:

**preço live → desconto aplicável → checkout efetivo → novo Value → novo tier → nova decisão**

## 11. Os três Diamantes finais

No momento da decisão, três configurações ficaram acima de Value 120:

| # | Modelo | Loja | Value |
|---|---|---|---:|
| 🥇 | **Lenovo Legion 5 15AHP-682** | Radio Popular | **123,6** |
| 🥈 | ASUS TUF A16 FA608UH-R72A55CB2 | Radio Popular | **123,3** |
| 🥉 | ASUS TUF A16 FA608UM-R72A56CB1 | Radio Popular | **121,9** |

O detalhe importante é que o sistema não se limitou a escolher o maior número. Os três finalistas foram depois comparados como produtos reais: CPU, GPU, potência, ecrã, peso, bateria, utilização na FEUP e longevidade.

## 12. O portátil escolhido

### 🏆 Lenovo Legion 5 15AHP-682

A escolha final foi o **Lenovo Legion 5 15AHP-682**.

Configuração usada na decisão:

- AMD Ryzen 7 250;
- NVIDIA GeForce RTX 5060 8 GB;
- 32 GB DDR5;
- SSD 1 TB;
- ecrã OLED 15,3" 2560×1600, 165 Hz;
- peso aproximado de 1,87 kg;
- Windows 11;
- Value efetivo do tracker: **123,6 — DIAMANTE**.

Com a campanha analisada, o custo económico considerado pelo projeto ficou em aproximadamente **1.299,99 €**.

O ASUS TUF com RTX 5050 era a opção de maior poupança. O TUF com RTX 5060 era competitivo em performance. Mas, ao mesmo nível de preço efetivo, o Legion combinava RTX 5060 com um ecrã OLED muito superior e menor peso — uma combinação especialmente forte para o objetivo misto **FEUP + gaming + vários anos de utilização**.

## 13. Fechar o círculo

É aqui que a história do projeto fica mais interessante.

### V1

> “Quero este ASUS TUF. Descobre onde está mais barato.”

O ser humano escolhia. O sistema procurava.

### V8.8.9

> “Quero o melhor portátil para mim dentro destas condições.”

O sistema:

**observou o mercado → descobriu candidatos → interpretou hardware → validou preços → reconheceu promoções → calculou Value → encontrou Diamantes → apoiou a decisão final**

E o portátil escolhido já nem sequer era o ASUS TUF que deu origem ao projeto.

Foi um **Lenovo Legion 5** que o próprio processo ajudou a descobrir.

Por isso, a V8.8.9 pode ser considerada um sucesso mesmo que a V9 venha a ser concluída mais tarde. O projeto fez aquilo para que foi construído — e produziu uma decisão real.

## 14. Porque passa a chamar-se LapIntel PT

“Rastreador de preços” já descrevia apenas uma pequena parte do sistema.

O nome **LapIntel PT — Laptop Market Intelligence Engine** representa melhor aquilo em que o projeto se transformou:

- descobre mercado;
- compreende configurações;
- mede adequação;
- valida evidência;
- compara economia real;
- preserva histórico;
- aprende a observar melhor;
- explica decisões.

O repositório nasceu como `rastreador_precos`; a identidade do produto passa a ser **LapIntel PT**.

## 15. V9 — o próximo capítulo, não uma condição de sucesso

A V9 fica deliberadamente em aberto para uma fase posterior.

Os principais candidatos são:

1. **Cobertura sustentável das lojas difíceis** — sobretudo PcComponentes, CHIP7 e Worten, privilegiando fontes públicas ou autorizadas.
2. **Matching cross-store mais maduro** — mais EAN/MPN e menos dependência de heurísticas.
3. **Tier efetivo unificado em toda a observabilidade** — logs, heartbeat e ranking devem contar promoções exatamente com a mesma lógica usada na decisão.
4. **Mais inteligência histórica** — só quando a amostra temporal justificar percentis, tendência e mínimo histórico com confiança.
5. **Maior eficiência** — mais candidatos relevantes por request e menos detail fetches desnecessários.
6. **Expansão de cobertura** — novas lojas só entram quando acrescentarem valor real e acesso sustentável; Auchan e MEO são candidatos naturais a estudar depois de terem surgido na verificação manual do Lenovo escolhido.

A V9 deverá ser uma versão de maturidade, não apenas um número maior.

## Créditos

### Pedro Martins

Conceção do problema, requisitos, critérios reais de compra, decisões de produto, validação dos resultados, testes no mercado e desenvolvimento iterativo do projeto.

### ChatGPT (OpenAI)

Co-desenvolvimento técnico assistido: arquitetura, implementação, debugging, testes, análise de logs e runs, guardrails, documentação, comparação das oportunidades e apoio à decisão final.

---

**LapIntel PT não nasceu como um exercício abstrato. Nasceu para responder a uma compra real. O melhor sinal de sucesso é simples: o sistema encontrou uma resposta e o portátil vai ser comprado.**
