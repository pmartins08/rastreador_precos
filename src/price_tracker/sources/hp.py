from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

SOURCE_NAME = "HP Support"
SOURCE_HOST = "support.hp.com"


def normalize_product_number(value: object) -> str | None:
    raw = str(value or "").upper().strip()
    # O sufixo após # identifica frequentemente localização/teclado e não é
    # necessário para a pesquisa do produto base no suporte HP.
    raw = raw.split("#", 1)[0]
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    if not 6 <= len(raw) <= 12:
        return None
    if not re.search(r"[A-Z]", raw) or not re.search(r"\d", raw):
        return None
    return raw


def product_number(item: dict) -> str | None:
    # A referência HP só é aceite a partir de um identificador explícito.
    # Não inferimos a partir de códigos soltos do título, que podem ser apenas
    # o nome da série (ex.: 15-fc0039wm) e apontar para outra configuração.
    for field in ("mpn", "sku"):
        code = normalize_product_number(item.get(field))
        if code:
            return code
    title = str(item.get("titulo") or "").upper()
    labelled = re.search(
        r"(?:SKU|P\s*/?\s*N|PRODUCT\s*(?:NO\.?|NUMBER)|N[UÚ]MERO\s+DO\s+PRODUTO)\s*[:#-]?\s*([A-Z0-9]{6,12}(?:#[A-Z0-9]{2,5})?)",
        title,
        re.I,
    )
    return normalize_product_number(labelled.group(1)) if labelled else None


def search_url(item: dict) -> str | None:
    code = product_number(item)
    if not code:
        return None
    return f"https://{SOURCE_HOST}/pt-pt/search?q={quote(code)}"


def spec_links(html: str, base_url: str, item: dict) -> list[str]:
    code = product_number(item)
    if not code:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    links: list[tuple[int, str]] = []
    seen = set()
    for anchor in soup.select("a[href]"):
        absolute = urljoin(base_url, str(anchor.get("href") or ""))
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != SOURCE_HOST:
            continue
        if "/product/product-specs/" not in parsed.path.lower():
            continue
        marker = absolute.rstrip("/")
        if marker in seen:
            continue
        seen.add(marker)
        # Dá prioridade a resultados que já trazem o SKU na URL/texto.
        label = re.sub(r"[^A-Z0-9]", "", anchor.get_text(" ", strip=True).upper())
        query = re.sub(r"[^A-Z0-9]", "", parsed.query.upper())
        score = int(code in query) * 2 + int(code in label)
        links.append((score, marker))
    return [url for _score, url in sorted(links, key=lambda row: (-row[0], row[1]))]


def response_matches(text: object, item: dict) -> bool:
    code = product_number(item)
    if not code:
        return False
    raw = str(text or "")
    normalized = re.sub(r"[^A-Z0-9]", "", raw.upper())
    has_heading = "PRODUCTSPECIFICATIONS" in normalized or "ESPECIFICACOESDOPRODUTO" in normalized
    return has_heading and code in normalized
