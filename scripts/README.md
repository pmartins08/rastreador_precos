# Scripts operacionais

Esta pasta contém ferramentas de diagnóstico e auditoria que não fazem parte do caminho principal de execução do LapIntel PT.

- `history_audit.py` — auditoria de histórico, matching e distribuição de Value (usada no CI);
- `tier_threshold_audit.py` — verificação de thresholds/tier policy (usada no CI);
- `system_guardian_audit.py` — auditoria programática da baseline e dos 8 pilares inegociáveis (Agente 4 / CI);
- `store_access_probe.py` — diagnóstico controlado das rotas públicas por loja;
- `validate_decision_run.py` — invariantes V9 de histórico, contagens e decisões efetivas (usada após cada run);
- `v10_agent_prototype.py` — protótipo multi-agente autónomo LapIntel V10 com Google Antigravity SDK (`--dry-run` e modo SDK).

Scripts one-shot concluídos e respetivo estado de replay foram removidos do repositório após a conclusão do ciclo de desenvolvimento.
