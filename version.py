"""Metadados públicos de versão e compatibilidade de estado.

`VERSION` é a única versão exposta pelo runtime e workflows. A lista de estados
compatíveis fica no mesmo módulo para evitar lógica de compatibilidade dispersa.
"""

VERSION = "8.8.8"

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
    }
)
