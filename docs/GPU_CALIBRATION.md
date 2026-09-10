# Calibração de GPU — V8.8.9

## Objetivo

Evitar dois erros opostos:

1. tratar uma GPU desconhecida como se tivesse performance conhecida;
2. impor um teto artificial de tier apenas porque o modelo exato da GPU não foi reconhecido.

O cérebro V8 permanece a referência. A V8.8.9 mantém a identificação conservadora das GPUs/iGPUs e substitui o antigo hard-cap de Prata por uma influência contínua da dimensão **Gaming** na decisão final do tier.

O **Value não é alterado** por esta regra. A GPU/Gaming influencia apenas o valor usado para escolher Bronze/Prata/Ouro/Diamante.

## Fórmula de influência no tier

A regra é:

`tier_score = Value × (0,85 + 0,15 × Gaming/100)`

Consequências:

- Gaming = 100 → multiplicador 1,00;
- Gaming = 50 → multiplicador 0,925;
- Gaming = 20 → multiplicador 0,88;
- Gaming = 0 → multiplicador 0,85.

Assim, uma máquina excelente para FEUP/produtividade mas fraca em Gaming pode continuar a chegar a Ouro se o conjunto justificar isso; apenas precisa de um Value suficientemente forte. Não existe `max_tier=PRATA` para GPU desconhecida, integrada genérica ou dedicada ainda não mapeada.

A identificação GPU continua, porém, registada separadamente para explainability e para impedir que hardware desconhecido seja tratado como hardware conhecido.

## Âncoras já existentes no cérebro

- RTX 2050 Laptop: 30
- RTX 3050 Laptop: 38

A tabela de iGPU fica deliberadamente dentro desse intervalo de entrada/abaixo dele, porque TDP, largura de banda e configuração da memória afetam muito mais uma integrada do que uma GPU dedicada.

| iGPU | Classe usada |
|---|---:|
| Intel Arc Graphics 140V | 33 |
| AMD Radeon 890M | 31 |
| AMD Radeon 880M | 29 |
| Intel Arc Graphics 130V | 28 |
| AMD Radeon 780M | 27 |
| AMD Radeon 860M | 23 |
| AMD Radeon 680M | 22 |
| AMD Radeon 760M | 21 |

## Evidência usada

As classes não são uma conversão direta de um único benchmark. Foram escolhidas a partir da ordem de grandeza e posição relativa observadas em múltiplos testes agregados, mantendo margem conservadora.

Referências principais:

- Notebookcheck — Intel Lunar Lake Arc 140V analysis: https://www.notebookcheck.net/Intel-Lunar-Lake-iGPU-analysis-Arc-Graphics-140V-is-faster-and-more-efficient-than-Radeon-890M.894167.0.html
- Notebookcheck — Intel Arc Graphics 130V: https://www.notebookcheck.net/Intel-Arc-Graphics-130V-Benchmarks-and-Specs.854992.0.html
- Notebookcheck — AMD Radeon 890M: https://www.notebookcheck.net/AMD-Radeon-890M-Benchmarks-and-Specs.843536.0.html
- Notebookcheck — AMD Radeon 880M: https://www.notebookcheck.net/AMD-Radeon-880M-iGPU-Benchmarks-and-Specs.843543.0.html
- Notebookcheck — AMD Radeon 780M analysis: https://www.notebookcheck.net/AMD-Radeon-780M-iGPU-analysis-AMD-s-new-RDNA-3-GPU-takes-on-its-competitors.714019.0.html
- Notebookcheck — AMD Radeon 860M: https://www.notebookcheck.net/AMD-Radeon-860M-Benchmarks-and-Specs.949852.0.html
- Notebookcheck — AMD Radeon 760M: https://www.notebookcheck.net/AMD-Radeon-760M-GPU-Benchmarks-and-Specs.680920.0.html
- Notebookcheck — RTX 3050 Laptop: https://www.notebookcheck.net/NVIDIA-GeForce-RTX-3050-Laptop-GPU-Benchmarks-and-Specs.513790.0.html

## Estado de reconhecimento da GPU

O GPU Guard continua a produzir estados explícitos:

- `DEDICADA_MAPEADA` — modelo dedicado reconhecido e presente no catálogo do cérebro;
- `DEDICADA_NAO_MAPEADA` — dedicada detetada sem classe exata conhecida;
- `INTEGRADA_MAPEADA` — iGPU reconhecida na tabela calibrada;
- `INTEGRADA_NAO_MAPEADA` — integrada detetada sem modelo calibrado;
- `GPU_DESCONHECIDA` — evidência insuficiente para identificar o tipo/modelo.

Estes estados são evidência de confiança e observabilidade; não são um teto rígido de tier.

## Matemática do ajuste de iGPU reconhecida

No cérebro V8, a GPU representa 65% da dimensão Gaming e Gaming representa 25% do score final. Portanto, para uma iGPU mapeada:

`delta_final = (classe_iGPU - 15) × 0,65 × 0,25`

O ranking continua a aplicar o multiplicador de confiança de dados já existente. O Value é depois recalculado com a mesma função e mantém qualquer bónus de preço já validado pelo Price Guard.

Só depois desse cálculo normal é aplicado o `tier_score` contínuo para escolher o tier. O campo `value_score` mantém o Value original e o runtime guarda separadamente `gpu_tier_influence` com Value, Gaming, multiplicador e tier_score.

## Exemplos de fronteira

Com limiares ilustrativos de Ouro = 110 e Diamante = 125:

- Value 120, Gaming 50 → tier_score 111 → Ouro;
- Value 135, Gaming 20 → tier_score 118,8 → Ouro, sem hard-cap;
- Value 135, Gaming 100 → tier_score 135 → Diamante.

## Limitações

- a classe de iGPU representa uma média conservadora; não substitui benchmark do portátil exato;
- memória single/dual-channel, LPDDR, TDP e drivers podem alterar bastante a performance;
- hardware desconhecido continua desconhecido: a V8.8.9 não inventa uma classe de performance para o preencher;
- novos modelos só devem entrar após identificação inequívoca e evidência suficiente;
- a fórmula de tier deve ser revista apenas com evidência de runs reais e testes de regressão, não para forçar resultados desejados.
