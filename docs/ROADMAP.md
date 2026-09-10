# Roadmap

O projeto está na linha **V8.8.9**. A prioridade deixou de ser acrescentar camadas indiscriminadamente; o foco passa a ser cobertura real, simplificação e preparação para uma futura V9 apenas quando os dados justificarem uma mudança maior.

## Prioridade 1 — Cobertura de lojas difíceis

### Worten

O sitemap público já é descoberto, mas as fichas de produto continuam a bloquear o runner. Próximo caminho preferencial: feed Awin autorizado quando a conta tiver acesso. Evitar aumentar probes HTML que já demonstraram rendimento zero.

### CHIP7

Medir a rota pública de pesquisa no root e manter apenas estratégias que produzam candidatos reais. Rotas com rendimento zero devem regressar ao cooldown normal.

### PcComponentes

Priorizar fonte autorizada/feed quando disponível e evitar ciclos de perfis HTTP que a aprendizagem já classificou como bloqueados.

## Prioridade 2 — Eficiência

- reduzir requests repetidos por loja;
- aumentar reutilização segura de cache de hardware;
- manter preço como dado volátil com TTL próprio;
- medir candidatos novos por request antes de promover uma rota;
- rever limites por loja com base em dados, não por tentativa e erro.

## Prioridade 3 — Qualidade do matching

- aumentar cobertura de EAN/GTIN e MPN;
- melhorar matching forte sem fundir variantes diferentes;
- usar comparação cross-store para preço apenas com identidade suficiente;
- manter casos prováveis disponíveis para observabilidade, sem fusão automática.

## Prioridade 4 — Histórico de preço

- continuar a acumular a série diária de 90 dias;
- usar mudanças materiais para prioridade de avaliação;
- estudar tendência/percentil apenas quando existir amostra temporal suficiente;
- não converter histórico curto em falsa certeza sobre “bom preço”.

## Prioridade 5 — Simplificação arquitetural

A reorganização atual deixa a raiz limitada ao motor principal e move camadas especializadas para `src/`. Próximos passos de simplificação só devem acontecer quando reduzirem complexidade real.

Candidatos futuros:

- incorporar gradualmente wrappers maduros no núcleo quando já não precisarem de instalação dinâmica;
- eliminar `version_guard.py` quando os labels históricos internos de `tracker.py` forem finalmente removidos numa refatoração dedicada e testada;
- dividir `tracker.py` apenas se surgir uma fronteira funcional clara, evitando fragmentação cosmética.

## V9 — só com motivo concreto

Uma V9 deve representar mudança funcional/arquitetural relevante, não apenas um número novo. Possíveis gatilhos:

- cobertura estável da maioria das lojas através de fontes sustentáveis;
- dataset histórico suficiente para modelar contexto temporal de preço;
- separação do tracker em componentes com interfaces estáveis;
- necessidade comprovada de rever pesos/scoring do cérebro.

Até lá, a linha V8.8.x deve privilegiar estabilidade, cobertura, evidência e limpeza técnica.
