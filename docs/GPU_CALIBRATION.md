# Calibração de GPU — V8.8.7

## Objetivo

Evitar dois erros opostos:

1. dar Ouro/Diamante a uma GPU desconhecida só porque CPU/RAM/preço compensam a incerteza;
2. tratar uma iGPU moderna identificada (ex.: Arc 140V) como se tivesse a mesma performance de qualquer integrada genérica.

O cérebro V8 permanece a referência. A V8.8.7 só substitui o fallback `integrada = 15` quando o **modelo exato** é reconhecido.

## Âncoras já existentes no cérebro

- RTX 2050 Laptop: 30
- RTX 3050 Laptop: 38

A primeira tabela de iGPU fica deliberadamente dentro desse intervalo de entrada/abaixo dele, porque TDP, largura de banda e configuração da memória afetam muito mais uma integrada do que uma GPU dedicada.

| iGPU | Classe V8.8.7 |
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

## Regra de tier

- modelo dedicado presente em `gpu_base` → GPU confirmada;
- modelo integrado presente na tabela acima → GPU confirmada;
- dedicada sem modelo, integrada genérica ou GPU desconhecida → no máximo Prata;
- confirmação de GPU não garante Ouro: o Value continua a resultar do cérebro completo e das validações de preço.

## Matemática do ajuste integrado

No cérebro V8, a GPU representa 65% da dimensão Gaming e Gaming representa 25% do score final. Portanto, para uma iGPU mapeada:

`delta_final = (classe_iGPU - 15) × 0.65 × 0.25`

O ranking continua a aplicar o multiplicador de confiança de dados já existente. O Value é depois recalculado com a mesma função e mantém qualquer bónus de preço já validado pelo Price Guard.

## Limitações

- a classe representa uma média conservadora; não substitui benchmark do portátil exato;
- memória single/dual-channel, LPDDR, TDP e drivers podem alterar bastante a performance;
- novos modelos só devem entrar após identificação inequívoca e evidência suficiente;
- a tabela deve ser revista quando dados reais do tracker mostrarem incoerências ou quando o universo de hardware evoluir.
