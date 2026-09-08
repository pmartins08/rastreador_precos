# Arquitetura do Rastreador

## Objetivo

O projeto separa **decisão técnica**, **observação do mercado** e **guardrails operacionais**. A intenção é permitir melhorar scrapers, confiança de preço e cobertura sem reescrever silenciosamente o cérebro V8.

## Fluxo principal

```text
configuração de lojas
        ↓
descoberta de candidatos
        ↓
enriquecimento de ficha
        ↓
extração de hardware / identidade
        ↓
scoring técnico base
        ↓
guards de qualidade e mercado
        ↓
Value + tier
        ↓
matching + histórico
        ↓
ntfy + persistência
```

## Fronteiras dos módulos

### `scraper.py`

É o núcleo técnico base. Responsabilidades principais:

- normalização de texto e preços;
- deteção de marca/família;
- extração de CPU, GPU, RAM, SSD, ecrã, bateria, peso e teclado;
- scoring FEUP, Gaming, Longevidade e Portabilidade;
- cálculo do ranking e Value base;
- thresholds de tier.

Alterações aqui têm impacto direto no cérebro e devem exigir regressões explícitas.

### `tracker.py`

É o motor de observação do mercado. Trata de:

- budgets globais e por loja;
- perfis de acesso e aprendizagem de sucesso/bloqueio;
- descoberta por categoria, segmento, paginação e sitemap;
- cache e refresh progressivo de identidade/preço;
- matching cross-store;
- persistência de estado;
- alertas ntfy;
- métricas de cada run.

O ficheiro contém ainda alguns labels históricos do desenvolvimento V8. O runtime público é normalizado por `version_guard.py`; estes labels não representam a versão real atual.

### `runner.py`

É o **composition root**. Instala as camadas sobre o cérebro/tracker base e expõe os entrypoints de execução e merge de estado.

A ordem é intencional:

1. fallback linear de specs;
2. Brain Guard;
3. Price Guard;
4. import do tracker;
5. identidade adicional;
6. Version Guard;
7. Promotion Guard;
8. GPU Guard;
9. Market Guard;
10. Historical Guard.

Mudanças de ordem devem ser tratadas como alteração arquitetural, porque os wrappers podem depender do comportamento já instalado.

## Guards

### `brain_guard.py`

Corrige lacunas técnicas comprovadas sem redesenhar o cérebro. Exemplo: capacidades intermédias de RAM como 24 GB.

### `gpu_guard.py`

Resolve duas classes de problema:

- impede Ouro/Diamante quando a GPU não é conhecida com confiança;
- atribui classes explícitas e conservadoras a iGPUs modernas conhecidas.

O Value bruto não é destruído só porque o tier é limitado.

### `price_guard.py`

Separa oportunidade real de preço suspeito. Usa evidência da ficha, quarentena e bónus apenas quando a confiança é suficiente.

### `market_guard.py`

Compara ofertas com identidade forte e impede que consenso cross-store invalide automaticamente uma promoção confirmada pela própria ficha.

### `promotion_guard.py`

Campanhas são **lead generation**, não prova de preço. Podem alterar prioridade de descoberta, nunca score/tier diretamente.

### `historical_guard.py`

Mantém contexto temporal compacto a 90 dias por EAN/MPN, com fallback local por URL quando falta identidade forte.

### `version_guard.py`

É uma camada de compatibilidade do tracker base. A versão pública e o conjunto de estados compatíveis vivem em `version.py`.

## Identidade e matching

Hierarquia conservadora:

1. EAN/GTIN;
2. MPN/part number;
3. SKU/model code + configuração principal;
4. assinatura técnica apenas para revisão.

Só matches fortes devem ser fundidos automaticamente. Confirmação de preço cross-store exige identidade exata.

## Estado

- `data/history.json` — ofertas, specs, alertas e runs recentes;
- `data/access_learning.json` — aprendizagem de acesso e rendimento;
- `data/price_history.json` — histórico diário compacto.

O workflow faz merge concorrente antes de persistir para reduzir perdas quando duas execuções se aproximam.

## Regra de evolução

Antes de alterar o cérebro base, preferir uma destas opções:

1. melhorar extração/evidência;
2. adicionar guard pequeno e testável;
3. acrescentar configuração;
4. adicionar métricas para provar o problema.

Uma alteração do scoring base só deve acontecer quando existe um caso real reproduzível, impacto quantificado e testes que protegem o comportamento pretendido.
