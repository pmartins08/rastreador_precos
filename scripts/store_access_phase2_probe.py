"""Diagnóstico temporário CHIP7/PcComponentes no GitHub Actions.

Só testa páginas públicas e, para PcComponentes, uma configuração Algolia de
pesquisa-only publicada historicamente no frontend/código público. Não grava
estado, não envia NTFY, não usa endpoints privados e não tenta contornar
proteções anti-bot. O ficheiro é temporário e será removido antes do merge.
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


def probe_pccomponentes_algolia() -> dict:
    """Testa apenas se a antiga chave pública de pesquisa continua viva.

    A configuração foi publicada em código de demonstração de 2021 e corresponde
    a uma chave de search-only usada pelo InstantSearch do site. Não é aceite como
    fonte permanente sem confirmação de que o índice PT devolve dados atuais.
    """
    endpoint = "https://bewoyx1cf1-dsn.algolia.net/1/indexes/*/queries"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "X-Algolia-Application-Id": "BEWOYX1CF1",
        "X-Algolia-API-Key": "47978d8b445ceaceb718dd842d434099",
    }
    output: dict = {"endpoint": endpoint, "indexes": []}
    for index_name in ("pccomponentes:pt", "pccomponentes:es"):
        payload = {
            "requests": [
                {
                    "indexName": index_name,
                    "params": "query=portatil&hitsPerPage=3&page=0&facets=[]",
                }
            ]
        }
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
            row: dict = {
                "index": index_name,
                "status": int(response.status_code),
                "content_type": response.headers.get("Content-Type"),
                "bytes": len(response.content),
            }
            try:
                data = response.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                if isinstance(data.get("message"), str):
                    row["message"] = data["message"][:200]
                results = data.get("results")
                if isinstance(results, list) and results and isinstance(results[0], dict):
                    result = results[0]
                    row["nb_hits"] = result.get("nbHits")
                    hits = []
                    for hit in result.get("hits", [])[:3]:
                        if not isinstance(hit, dict):
                            continue
                        price = hit.get("price")
                        if isinstance(price, dict):
                            price = price.get("amount")
                        hits.append(
                            {
                                "title": hit.get("title") or hit.get("name"),
                                "price": price,
                                "url": hit.get("url") or hit.get("productUrl") or hit.get("link"),
                                "object_id": hit.get("objectID"),
                            }
                        )
                    row["hits"] = hits
            output["indexes"].append(row)
        except Exception as exc:
            output["indexes"].append({"index": index_name, "error": f"{type(exc).__name__}: {exc}"})
    return output


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
        ],
    )
    pccomponentes["historical_public_algolia"] = probe_pccomponentes_algolia()
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
