"""Metadados públicos de versão, compatibilidade e época de estado.

`VERSION` é a única versão exposta pelo runtime e workflows. `STATE_EPOCH`
identifica a geração do estado persistente; quando muda, o runtime faz uma
migração/refresh controlado sem perder a aprendizagem de acesso às lojas.
"""

VERSION = "8.8.9"
STATE_EPOCH = "8.8.8-refresh-1"

COMPATIBLE_STATE_VERSIONS = frozenset(
    {
        "8.5",
        "8.6",
        "8.6.1",
        "8.7",
        "8.7.1",
        "8.8",
        "8.8.1",
        "8.8.2",
        "8.8.3",
        "8.8.4",
        "8.8.5",
        "8.8.6",
        "8.8.7",
        "8.8.8",
        "8.8.9",
    }
)
