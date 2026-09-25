"""Diagnóstico temporário das rotas públicas PCDiga/Worten no GitHub Actions.

Não grava estado, não envia NTFY e não tenta contornar autenticação/anti-bot.
Este ficheiro é deliberadamente temporário e deve ser removido antes do merge.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import requests

import runner  # noqa: F401 - instala a composição real da V9
import tracker

ROOT = Path(__file__).resolve().parents[1]
UA = "rastreador-precos/9.0 (+https://github.com/pmartins08/rastreador_precos)"


def get(url: str, timeout: int = 10):
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": UA}, allow_redirects=True)
        return response, None
    except Exception as exc:  # diagnóstico: reporta, não mascara
        return None, f"{type(exc).__name__}: {exc}"


def row_for(response, error, url: str) -> dict:
    if response is None:
        return {"url": url, "error": error}
    return {
        "url": url,
        "final_url": str(response.url),
        "status": int(response.status_code),
        "content_type": response.headers.get("Content-Type"),
        "bytes": len(response.content),
    }


def declared_sitemaps(robots_text: str) -> list[str]:
    return [
        line.split(":", 1)[1].strip()
        for line in robots_text.splitlines()
        if line.lower().startswith("sitemap:") and ":" in line
    ]


def probe_pcdiga(config: dict) -> dict:
    cat = next(item for item in config["category_urls"] if item["loja"] == "PCDiga")
    out: dict = {"store": "PCDiga", "sitemaps": [], "history_product": []}

    robots_url = "https://www.pcdiga.com/robots.txt"
    robots, error = get(robots_url)
    out["robots"] = row_for(robots, error, robots_url)
    if robots is not None and robots.status_code == 200:
        for sitemap_url in declared_sitemaps(robots.text)[:1]:
            sitemap, sitemap_error = get(sitemap_url)
            info = row_for(sitemap, sitemap_error, sitemap_url)
            if sitemap is not None and sitemap.status_code == 200:
                urls, children = tracker.sitemap_parse(sitemap.content, sitemap.text, 80)
                info.update({
                    "urls": len(urls),
                    "children": len(children),
                    "child_examples": children[:6],
                    "direct_product_urls": sum(1 for url in urls if tracker._looks_like_product_url(url, cat)),
                })
                child_rows = []
                for child in children[:3]:
                    child_response, child_error = get(child)
                    child_info = row_for(child_response, child_error, child)
                    if child_response is not None and child_response.status_code == 200:
                        child_urls, _ = tracker.sitemap_parse(child_response.content, child_response.text, 20)
                        products = [url for url in child_urls if tracker._looks_like_product_url(url, cat)]
                        child_info.update({
                            "urls": len(child_urls),
                            "product_urls": len(products),
                            "product_examples": products[:3],
                        })
                    child_rows.append(child_info)
                info["child_rows"] = child_rows
            out["sitemaps"].append(info)

    # O histórico recente serve só para descobrir uma ficha canónica que sabemos
    # ter existido. Tanto a ficha normal como o host público alternativo são
    # novamente pedidos live; nenhum preço histórico é aceite por este probe.
    history = tracker.load_json(tracker.HISTORY_PATH)
    recent = []
    for entries in history.get("offers", {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("loja") == "PCDiga" and entry.get("url"):
                recent.append(entry)
    recent.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    for entry in recent[:2]:
        canonical = str(entry["url"])
        parsed = urlparse(canonical)
        fallback = parsed._replace(netloc="publojas.pcdiga.com", query="", fragment="").geturl()
        product_row = {"timestamp": entry.get("timestamp"), "title": entry.get("titulo")}
        for label, url in (("canonical", canonical), ("publojas", fallback)):
            response, product_error = get(url)
            info = row_for(response, product_error, url)
            if response is not None and response.status_code == 200:
                soup = tracker.BeautifulSoup(response.text, "html.parser")
                evidence = tracker.page_price_evidence(soup, tracker.scraper)
                info.update({
                    "title": soup.title.get_text(" ", strip=True) if soup.title else None,
                    "jsonld": len(soup.select('script[type="application/ld+json"]')),
                    "price": evidence.get("price"),
                    "price_confidence": evidence.get("confidence"),
                })
            product_row[label] = info
        out["history_product"].append(product_row)
    return out


def probe_worten(config: dict) -> dict:
    cat = next(item for item in config["category_urls"] if item["loja"] == "Worten")
    out: dict = {"store": "Worten", "children": [], "products": []}
    robots_url = "https://www.worten.pt/robots.txt"
    robots, error = get(robots_url)
    out["robots"] = row_for(robots, error, robots_url)
    if robots is None or robots.status_code != 200:
        return out

    seeds = declared_sitemaps(robots.text)
    if not seeds:
        return out
    index, index_error = get(seeds[0])
    out["index"] = row_for(index, index_error, seeds[0])
    if index is None or index.status_code != 200:
        return out

    _urls, children = tracker.sitemap_parse(index.content, index.text, 160)
    out["index"]["children"] = len(children)
    # Dois filhos bastam para confirmar se o padrão se repete sem gastar tráfego.
    candidate_urls: list[str] = []
    for child in children[:2]:
        response, child_error = get(child)
        info = row_for(response, child_error, child)
        if response is not None and response.status_code == 200:
            urls, _ = tracker.sitemap_parse(response.content, response.text, 10)
            products = [url for url in urls if tracker._looks_like_product_url(url, cat)]
            products.sort(key=tracker._sitemap_product_score, reverse=True)
            info.update({"urls": len(urls), "products": len(products), "examples": products[:3]})
            candidate_urls.extend(products[:2])
        out["children"].append(info)

    for product_url in list(dict.fromkeys(candidate_urls))[:3]:
        response, product_error = get(product_url)
        info = row_for(response, product_error, product_url)
        if response is not None and response.status_code == 200:
            soup = tracker.BeautifulSoup(response.text, "html.parser")
            evidence = tracker.page_price_evidence(soup, tracker.scraper)
            info.update({
                "title": soup.title.get_text(" ", strip=True) if soup.title else None,
                "jsonld": len(soup.select('script[type="application/ld+json"]')),
                "price": evidence.get("price"),
                "price_confidence": evidence.get("confidence"),
            })
        out["products"].append(info)
    return out


def main() -> None:
    config = tracker.load_json(tracker.CONFIG_PATH)
    report = {
        "version": tracker.VERSION,
        "pcdiga": probe_pcdiga(config),
        "worten": probe_worten(config),
    }
    print("STORE_ACCESS_PHASE2=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
