# LapIntel PT

**Inteligência de mercado para escolher um portátil em Portugal.**

[![CI](https://github.com/pmartins08/rastreador_precos/actions/workflows/ci.yml/badge.svg)](https://github.com/pmartins08/rastreador_precos/actions/workflows/ci.yml)
[![Monitorização](https://github.com/pmartins08/rastreador_precos/actions/workflows/tracker.yml/badge.svg)](https://github.com/pmartins08/rastreador_precos/actions/workflows/tracker.yml)

Descobre ofertas, confirma preço e disponibilidade, identifica configurações entre lojas e calcula um Value adaptado a universidade, engenharia e gaming.

**Objetivo de compra concluído · 9.0.0-beta.12 · manutenção silenciosa**

O objetivo inicial desta fase está concluído. O projeto fica preparado para manutenção e futura retoma; resultados históricos não constituem recomendações ou promoções atuais.

A monitorização continua **a cada seis horas**, com notificações **apenas Diamante**. Heartbeats, avisos de deploy/falha no NTFY e resumos extraordinários estão desligados/removidos. Falhas continuam visíveis no GitHub Actions. O desenvolvimento ativo fica em pausa; as limitações de cobertura mantêm a designação beta.

## Como decide

1. **Descobrir** — categorias, catálogos públicos, sitemaps e feeds autorizados opcionais.
2. **Confirmar** — identidade EAN/MPN, preço live, condição nova e disponibilidade elegível.
3. **Avaliar** — produtividade, gaming, longevidade, portabilidade e custo total.
4. **Comparar** — Value unificado, campanhas confirmadas e histórico verificável.
5. **Notificar** — oportunidades Diamante novas ou com alterações materiais, com deduplicação.

| Política | Regra atual |
|---|---|
| Orçamento | 1.400 € preferencial; 1.600 € máximo, incluindo instalação quando aplicável |
| Sem SO / FreeDOS explícito | +110 € no custo usado pelo Value e no limite de compra |
| SO desconhecido | Não presumir Windows nem custo zero confirmado; sinalizar incerteza |
| Teclado | PT não obrigatório; espanhol explicitamente identificado é excluído |
| Disponibilidade | Sem stock ou por confirmar: sem tier, ranking ou alerta |
| Marcas | ASUS, Lenovo, HP, Acer e Gigabyte; incluindo submarcas reconhecidas |
| Condição | Apenas novos; exclui usados, recondicionados e exposição |

O Value unifica o anterior Opportunity Rank: **0,80 × Value base + 0,30 × Gaming + histórico**, limitado a 150. O preço melhora progressivamente abaixo do orçamento preferencial, com contribuição limitada. O antigo bónus duplicado por preço baixo está desligado. O histórico só pode contribuir quando há pelo menos três dias observados; o bónus máximo é cinco pontos.

TGP, brilho SDR, gamut, painel, área útil, bateria e peso fazem parte da avaliação técnica. Dados desconhecidos não são substituídos por especificações de outra variante. Estas pontuações são utilidade de decisão, não previsões de FPS ou autonomia.

| Tier | Value mínimo | NTFY |
|---|---:|:---:|
| Bronze | 70 | — |
| Prata | 90 | — |
| Ouro | 110 | — |
| **Diamante** | **120, inclusive** | **Sim** |

## Cobertura e limites

Quinze lojas configuradas: **PCDiga, PcComponentes, Globaldata, Rádio Popular, Darty, UPTECHBOX, CHIP7, FNAC, Worten, You Get, Tek4life, Auchan, MEO, Clickfiel e Novo Atalho**.

Configuração não equivale a cobertura integral. PCDiga, PcComponentes, CHIP7, Worten e You Get tiveram acesso bloqueado ou improdutivo nas últimas validações documentadas. A ASUS eStore tem adaptador, mas não é anunciada como fonte live ativa. Snippets de pesquisa servem apenas para descoberta: nunca bastam para preço, Value ou alertas.

Por execução: até **420 requests, 140 fichas, 300 avaliações e 10 minutos**. Não há garantia de observar todos os produtos ou todas as campanhas. Consultar o [estado operacional](docs/V9_BETA_STATUS.md).

## Executar e validar

Python 3.11; o workflow usa o secret `NTFY_TOPIC`. `AWIN_DATAFEED_API_KEY` é opcional.

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m compileall -q runner.py tracker.py scraper.py version.py src tests scripts
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
python runner.py
```

`runner.py` compõe o pipeline; `scraper.py` extrai e pontua; `tracker.py` orquestra. `src/` contém validações e integrações, `config/` a política, `tests/` regressões e `data/` o estado persistente. Executar o runner com NTFY configurado pode enviar oportunidades.

## Documentação

- [Fecho e revisão das pendências](docs/CLOSEOUT.md)
- [Operação e retoma](docs/OPERATIONS.md)
- [Arquitetura](docs/ARCHITECTURE.md) · [Cérebro técnico](docs/TECHNICAL_CONTEXT.md)
- [Acesso às lojas](docs/STORE_ACCESS.md) · [Estado da V9](docs/V9_BETA_STATUS.md)
- [História](docs/PROJECT_STORY.md) · [Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md)

## Créditos

**Pedro Martins** — ideia, requisitos, decisões de produto, validação e desenvolvimento.

**ChatGPT (OpenAI)** — co-desenvolvimento técnico assistido: arquitetura, implementação, testes, análise e documentação.
