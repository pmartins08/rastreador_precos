# Módulos auxiliares

Esta pasta contém as camadas especializadas que complementam o motor principal da raiz sem esconder o fluxo central do projeto.

- `*_guard.py` — validação, cobertura, histórico, matching, scoring contextual e observabilidade.
- `matching_guard.py` — impede que EAN/MPN contraditórios fundam configurações ou confirmem preços e gera `data/matching_state.json` como estado derivado auditável.
- `hardware_catalog.py` — catálogo factual usado pelo reconhecimento de CPU/iGPU.
- `awin_feed_guard.py` e `catalog_guard.py` — fontes públicas/autorizadas alternativas para descoberta.

Os entrypoints e o núcleo permanecem na raiz:

- `runner.py` — composition root e entrypoint de produção;
- `tracker.py` — motor de descoberta, avaliação, estado e alertas;
- `scraper.py` — parsing e cérebro técnico base;
- `version.py` — versão pública e compatibilidade de estado.

Os módulos desta pasta são código de produção. Os testes correspondentes vivem exclusivamente em `tests/`.
