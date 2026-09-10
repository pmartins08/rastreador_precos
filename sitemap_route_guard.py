from __future__ import annotations

from contextvars import ContextVar


_CURRENT_CAT: ContextVar[dict | None] = ContextVar("sitemap_route_cat", default=None)


def _child_priority(url: str, cat: dict) -> tuple[int, int, str]:
    text = str(url or "").lower()
    configured = [str(value).lower() for value in cat.get("sitemap_child_hints", []) if value]
    generic = ("product", "produto", "catalog", "portatil", "laptop")
    configured_hits = sum(1 for marker in configured if marker in text)
    generic_hits = sum(1 for marker in generic if marker in text)
    return (-configured_hits, -generic_hits, text)


def install(tracker_module) -> None:
    """Melhora a seleção de filhos de sitemap sem criar novos pedidos por si só."""
    if getattr(tracker_module, "_SITEMAP_ROUTE_GUARD_INSTALLED", False):
        return

    base_parse = tracker_module.sitemap_parse
    base_discover = tracker_module.discover_sitemap_urls

    def sitemap_parse(content: bytes, text: str, max_children: int = 10):
        cat = _CURRENT_CAT.get()
        if not isinstance(cat, dict) or not cat.get("sitemap_child_hints"):
            return base_parse(content, text, max_children)

        # Ler mais <loc> do índice é trabalho local. O número de sitemaps realmente
        # pedidos continua limitado pelo `max_sitemaps` da descoberta base.
        scan_limit = max(
            int(max_children),
            int(cat.get("sitemap_index_scan_limit", max(40, int(max_children) * 8))),
        )
        urls, children = base_parse(content, text, scan_limit)
        if children:
            children = sorted(children, key=lambda url: _child_priority(url, cat))
            children = children[: int(max_children)]
        return urls, children

    def discover_sitemap_urls(cat: dict, config: dict, **kwargs):
        token = _CURRENT_CAT.set(cat)
        try:
            return base_discover(cat, config, **kwargs)
        finally:
            _CURRENT_CAT.reset(token)

    tracker_module.sitemap_parse = sitemap_parse
    tracker_module.discover_sitemap_urls = discover_sitemap_urls
    tracker_module._SITEMAP_ROUTE_GUARD_INSTALLED = True
