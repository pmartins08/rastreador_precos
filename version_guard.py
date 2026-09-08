from __future__ import annotations

import logging

from version import COMPATIBLE_STATE_VERSIONS, VERSION


# O tracker base ainda contém alguns labels históricos no texto de log. Esta
# camada normaliza apenas a apresentação; não altera versões gravadas no estado.
LEGACY_RUNTIME_LABELS = ("V8.8.1", "V8.8.4")


class RuntimeVersionFilter(logging.Filter):
    """Normaliza labels operacionais antigos para a versão pública atual."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for legacy in LEGACY_RUNTIME_LABELS:
                record.msg = record.msg.replace(legacy, f"V{VERSION}")
        return True


def install(tracker_module) -> None:
    """Aplica versão pública e compatibilidade sem reescrever o tracker base."""
    if getattr(tracker_module, "_VERSION_GUARD_INSTALLED", False):
        return

    tracker_module.VERSION = VERSION
    tracker_module.COMPATIBLE_STATE_VERSIONS.update(COMPATIBLE_STATE_VERSIONS)
    tracker_module.LOGGER.addFilter(RuntimeVersionFilter())
    tracker_module._VERSION_GUARD_INSTALLED = True
