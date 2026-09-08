# Changelog

Este ficheiro resume alterações de produto e arquitetura relevantes. O detalhe histórico continua preservado no Git, nas validações e nas métricas das runs.

## 8.8.7 — iGPU Intelligence

- GPU Guard passa a reconhecer modelos integrados explícitos em vez de reduzir todas as iGPUs ao fallback genérico de 15 pontos.
- Primeira tabela conservadora: Intel Arc Graphics 140V/130V e AMD Radeon 890M/880M/860M/780M/760M/680M.
- A escala é ancorada ao mapa já existente: RTX 2050 = 30 e RTX 3050 = 38; nenhuma iGPU desta primeira tabela ultrapassa a classe RTX 3050.
- iGPU mapeada passa a contar como GPU confirmada para o gate de Ouro/Diamante; iGPU genérica continua limitada a Prata.
- O ajuste recalcula apenas a componente Gaming correspondente ao delta entre o fallback integrado=15 e a nova classe explícita.
- Cache V8.8.6 é migrada progressivamente por título/evidência técnica sem invalidar CPU, RAM, ecrã ou voltar a abrir a ficha desnecessariamente.
- Parser passa a reconhecer nomenclaturas reais como `Intel® Arc™ de 140 V`.

### Consolidação pós-release

- README reescrito para refletir o estado real da V8.8.7 e deixar histórico detalhado no changelog/docs.
- Documentação separada em arquitetura, operação, roadmap, calibração e validações de release.
- Compatibilidade de versões/estado centralizada em `version.py`; `version_guard.py` passa a consumir essa fonte única.
- CI deixa de manter listas manuais de ficheiros Python e valida automaticamente branches `feature/**`, `fix/**`, `chore/**` e `refactor/**`.
- Workflow de produção usa `compileall`, valida `config.json` e deixa de executar scraping quando o commit altera apenas documentação/estado.
- `.gitignore` e documentação de `data/` foram completados.

## 8.8.6 — GPU confidence & coverage efficiency

- Ouro e Diamante passam a exigir GPU confirmada por modelo e por uma classe conhecida pelo sistema.
- GPUs desconhecidas, dedicadas não mapeadas e integradas sem classe explícita mantêm o Value bruto, mas ficam limitadas a Prata.
- Promo Intelligence passa a aprender rendimento e perde prioridade quando uma rota promocional demonstra baixa eficiência.
- Worten passa a reconhecer o padrão atual `/produtos/` nas URLs descobertas via sitemap.
- CI cobre isolamento do GPU Guard para garantir que o cérebro base mantém os tiers originais fora da avaliação contextual.

## 8.8.5 — Promo Intelligence & 90-day history

- Campanhas públicas configuráveis como lead generation.
- Histórico compacto de preços a 90 dias por EAN/MPN, com fallback local por URL.
- Versão pública centralizada e workflow/CI consolidados.

## 8.8.4

- Evidência HIGH da própria ficha passa a poder validar promoções reais que divergem do mercado.
- Darty adicionada ao universo de lojas.
- Heartbeat redundante no workflow.

## 8.8.3

- Correção de longevidade para capacidades intermédias de RAM, sobretudo 24 GB.

## 8.8

- Price Guard: confiança de preço, quarentena e bónus de oportunidade validado.

## 8.7

- Identidade progressiva e aumento de cobertura por cache/detail refresh.

## 8.6

- Aprendizagem de rendimento de descoberta e fundação do matching cross-store.

## 8.5

- Paginação, cache útil e primeira consolidação da linha V8.
