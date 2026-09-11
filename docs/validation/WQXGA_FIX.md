# Validação WQXGA

Casos cobertos pela correção:

- `WQXGA OLED 165Hz` com referência secundária `FHD` -> `qhd+`.
- `FHD 1920x1080` sem WQXGA -> mantém `fhd`.
- cache antiga `fhd` + título atual WQXGA -> promove para `qhd+` com auditoria.
- WQXGA presente em evidência técnica -> corrige antes do scoring.
- resolução não relacionada, como `qhd`, não é alterada sem WQXGA explícito.

A correção é deliberadamente estreita e não altera regras de CPU, GPU, RAM, SSD, refresh, matching ou preço.
