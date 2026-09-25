"""Diagnóstico temporário CHIP7/PcComponentes no GitHub Actions.

Só testa páginas e ficheiros públicos oficiais. Não grava estado, não envia NTFY,
não usa endpoints privados e não tenta contornar proteções anti-bot. O ficheiro é
temporário e será removido antes do merge da fase de acesso.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from bs4 import BeautifulSoup

import runner  # noqa: F401 - instala a composição real da V9
import tracker

UA = "rastreador-precos/9.0 (+https://github.com/pmartins08/rastreador_precos)"


def get(url: str, timeout: int = 10):
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.6"},
            allow_redirects=True,
        )
        return response, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def summarize(response, error, url: str) -> dict:
    if response is None:
        return {"url": url, "error": error}
    row = {
        "url": url,
        "final_url": str(response.url),
        "status": int(response.status_code),
        "content_type": response.headers.get("Content-Type"),
        "server": response.headers.get("Server"),
        "bytes": len(response.content),
    }
    if response.status_code == 200 and "html" in str(response.headers.get("Content-Type", "")).lower():
        soup = BeautifulSoup(response.text, "html.parser")
        row["title"] = soup.title.get_text(" ", strip=True) if soup.title else None
        row["jsonld"] = len(soup.select('script[type="application/ld+json"]'))
        evidence = tracker.page_price_evidence(soup, tracker.scraper)
        row["price"] = evidence.get("price")
        row["price_confidence"] = evidence.get("confidence")
        script_sources = [str(tag.get("src")) for tag in soup.select("script[src]") if tag.get("src")]
        row["script_hosts"] = sorted({urlparse(src).netloc for src in script_sources if urlparse(src).netloc})[:12]
        lowered = response.text.lower()
        row["frontend_markers"] = {
            "algolia": "algolia" in lowered,
            "instantsearch": "instantsearch" in lowered,
            "meilisearch": "meilisearch" in lowered,
            "typesense": "typesense" in lowered,
        }
    return row


def probe_store(name: str, urls: list[tuple[str, str]]) -> dict:
    rows = []
    for label, url in urls:
        response, error = get(url)
        row = summarize(response, error, url)
        row["label"] = label
        rows.append(row)
    return {"store": name, "routes": rows}


def main() -> None:
    chip7 = probe_store(
        "CHIP7",
        [
            ("category_bare", "https://chip7.pt/computadores/portateis"),
            ("category_www", "https://www.chip7.pt/computadores/portateis"),
            ("sitemap_bare", "https://chip7.pt/sitemap.xml"),
            ("sitemap_www", "https://www.chip7.pt/sitemap.xml"),
            ("known_product_bare", "https://chip7.pt/computadores/portateis/portateis-gaming/lenovo/83q7003vpg"),
            ("known_product_www", "https://www.chip7.pt/computadores/portateis/portateis-gaming/lenovo/83q7003vpg"),
            ("legacy_index_category", "https://chip7.pt/index.php/computadores/portateis"),
        ],
    )
    pccomponentes = probe_store(
        "PcComponentes",
        [
            ("category_www", "https://www.pccomponentes.pt/categorias/computadores-portateis"),
            ("category_bare", "https://pccomponentes.pt/categorias/computadores-portateis"),
            ("sitemap_www", "https://www.pccomponentes.pt/sitemap.xml"),
            ("sitemap_bare", "https://pccomponentes.pt/sitemap.xml"),
            (
                "known_product_pt",
                "https://www.pccomponentes.pt/portatil-asus-tuf-gaming-a16-fa608up-r72b57cs2-16-amd-ryzen-7-260-32gb-1tb-ssd-rtx-5060-pt",
            ),
            # Controlo apenas diagnóstico: a loja ES nunca será usada para preço PT.
            ("es_home_control", "https://www.pccomponentes.com/"),
            ("es_category_control", "https://www.pccomponentes.com/portatiles"),
        ],
    )
    print(
        "STORE_ACCESS_PHASE2="
        + json.dumps(
            {"version": tracker.VERSION, "chip7": chip7, "pccomponentes": pccomponentes},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
