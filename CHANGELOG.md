# Changelog

Este ficheiro concentra o histórico funcional e arquitetural relevante. Detalhes de implementação continuam preservados no histórico Git e nas métricas das runs; relatórios temporários de validação não são mantidos indefinidamente no repositório.

## 8.8.9 — Market intelligence, coverage sources & repository cleanup

- GPU/iGPU deixa de impor um hard-cap artificial de Prata: a dimensão Gaming passa a influenciar o tier de forma contínua sem alterar o `value_score` bruto.
- Reconhecimento de hardware moderno foi reforçado com catálogo factual e aliases conservadores, incluindo famílias recentes de CPU/iGPU.
- Darty ganha fallback de catálogo JSON público, aumentando significativamente a cobertura sem depender apenas das fichas HTML.
- Integração Awin opcional preparada para Darty, PcComponentes e Worten; sem `AWIN_DATAFEED_API_KEY` é um no-op e não altera o comportamento normal.
- Feed Awin usa apenas feeds autorizados devolvidos à conta e exige deep link direto do merchant; preço de feed conta como evidência MEDIUM, nunca como confirmação HIGH isolada.
- Parser de feeds passa a escolher o delimitador pelo cabeçalho para não confundir vírgula decimal portuguesa com separador CSV.
- Matching de categoria de feeds tolera singular/plural português (`portátil` / `portáteis`) sem afrouxar o filtro para produtos não relevantes.
- Worten passa a versionar a estratégia de sitemap: quando a estratégia muda, apenas a aprendizagem antiga desse método é arquivada/reaberta, sem apagar aprendizagem das restantes fontes.
- A estratégia nova confirmou que o sitemap da Worten é acessível, mas as fichas de produto continuam bloqueadas no runner; a limitação fica classificada como acesso a produto, não descoberta de sitemap.
- CHIP7 recebe um probe controlado da pesquisa pública no root como alternativa à categoria bloqueada; o método continua sujeito à aprendizagem/cooldown normal.
- Alterações materiais de preço em ofertas históricas recebem prioridade explícita de avaliação. Quedas de pelo menos `alerta_queda_preco_eur` têm prioridade superior a subidas, garantindo que o recálculo de Value/tier não perde um slot do pré-ranking.
- O mecanismo de alerta mantém como baseline o último preço que efetivamente gerou alerta, reduzindo spam por pequenas oscilações.
- Repositório reorganizado: raiz reservada a `runner.py`, `tracker.py`, `scraper.py` e `version.py`; camadas auxiliares de produção movidas para `src/`; configuração, estado, docs, testes e workflows permanecem isolados nas respetivas pastas.
- `version.py` passa a expor 8.8.9 como versão pública sem alterar `STATE_EPOCH`, preservando o histórico e a aprendizagem já válidos.
- Workflow `v888-smoke.yml` e relatórios de validação antigos V8.8.6/V8.8.7 removidos por serem artefactos de release já substituídos pelo CI, changelog e histórico Git.
- README, arquitetura, operações, roadmap e documentação de `data/` atualizados para refletir a estrutura e comportamento atuais.

## 8.8.8 — Coverage resilience, state refresh & current Top 5

- `coverage_guard.py` reduz I/O repetido, coloca rotas improdutivas em cooldown temporário e permite fallback histórico apenas como lead sujeito a confirmação live.
- PCDiga passa a recuperar uma pequena amostra de ofertas conhecidas quando a descoberta pública colapsa; no smoke de release os 6 leads recuperados foram reabertos live e os 6 foram aceites.
- URLs equivalentes de sitemap/cache deixam de depender de igualdade textual estrita, reduzindo duplicação e desperdício de requests.
- A ASUS Store deixa de fazer parte do scan ativo: mantém-se como fonte oficial útil para enriquecimento futuro, mas não conta como 9.ª loja enquanto não tiver descoberta pública estável e produtiva.
- Darty mantém descoberta live via sitemap; cobertura abaixo do histórico recente permanece uma limitação conhecida para refinamento pós-release.
- `state_refresh_guard.py` introduz um `state_epoch` para impedir que merges concorrentes reintroduzam análises de versões anteriores depois do refresh V8.8.8.
- No primeiro refresh V8.8.8, o histórico antigo pode servir apenas como bootstrap transitório de cache/specs; no estado persistente ficam apenas observações recalculadas pela V8.8.8.
- `price_history.json` é reiniciado no novo epoch para evitar séries históricas cuja origem/versionamento não era suficientemente auditável.
- `access_learning.json` é preservado porque contém aprendizagem operacional de acesso/descoberta e não avaliações de portáteis.
- `top5_guard.py` passa a persistir `data/top5_current.json`: Top 5 agregado do estado atual do mercado conhecido, não simplesmente Top 5 da última run.
- Configurações iguais são deduplicadas no Top 5 e representadas pela melhor oferta atual conhecida.
- A release inclui uma campanha ntfy one-shot que envia uma notificação separada para cada posição do Top 5 atual, com proteção contra reenvio de itens já enviados.
- Durante o refresh inicial, alertas normais de oportunidade podem ser silenciados para evitar duplicados enquanto a campanha Top 5 é emitida.
- O workflow de estado passa a persistir também `data/top5_current.json` e respeita o novo epoch durante merges concorrentes.
- Smoke de release: 128 testes, 166 candidatos, 166 avaliados, 120 aceites, 101 requests, 60 detalhe, 106 cache, 8 lojas, 4 grupos cross-store exatos e Top 5 construído com 5 posições.

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
