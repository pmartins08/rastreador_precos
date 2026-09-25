"""Compatibilidade temporária para o antigo nome da camada de acesso.

A implementação vive agora em ``store_access_guard``. Este shim mantém o
composition root estável nesta beta e pode desaparecer quando o import de
``runner.py`` for consolidado numa próxima limpeza estrutural.
"""
from store_access_guard import (  # noqa: F401
    _RECOVERY,
    _archive_and_reset_sitemap_access,
    _recovery_cat,
    _worten_sitemap_product_url,
    install,
)
