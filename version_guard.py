from __future__ import annotations

import logging

from version import VERSION


LEGACY_RUNTIME_LABELS = ("V8.8.1", "V8.8.4")


class RuntimeVersionFilter(logging.Filter):
    """Normaliza apenas mensagens operacionais antigas do tracker base.

    O histórico continua a preservar a versão em que cada observação foi criada;
    este filtro serve apenas para o texto emitido pelo runtime atual.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for legacy in LEGACY_RUNTIME_LABELS:
                record.msg = record.msg.replace(legacy, f"V{VERSION}")
        return True


def install(tracker_module) -> None:
    if getattr(tracker_module, "_VERSION_GUARD_INSTALLED", False):
        return
    tracker_module.VERSION = VERSION
    tracker_module.COMPATIBLE_STATE_VERSIONS.add(VERSION)
    tracker_module.LOGGER.addFilter(RuntimeVersionFilter())
    tracker_module._VERSION_GUARD_INSTALLED = True
