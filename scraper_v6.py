import asyncio
import re
import unicodedata
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

import scraper as base

# Guardar referências originais antes de instalar os overrides.
_ORIGINAL_CALCULAR_SCORES = base.calcular_scores
_ORIGINAL_GRELHA = base.extrair_grelha_categoria
_ORIGINAL_PRECO_STOCK = base.extrair_preco_e_stock

TECLADO_PT_CONFIRMADO_V6 = [
    "teclado portugues", "teclado pt", "teclado pt-pt",
    "keyboard portugues", "keyboard pt", "keyboard pt-pt",
    "layout pt", "layout pt-pt", "portuguese keyboard",
    "portuguese layout", "pt keyboard", "pt-pt"
]

TECLADO_NAO_PT_V6 = [
    "teclado espanhol", "keyboard espanhol", "spanish keyboard", "spanish layout",
    "teclado frances", "keyboard frances", "french keyboard", "french layout",
    "teclado alemao", "keyboard alemao", "german keyboard", "german layout",
    "teclado ingles", "keyboard ingles", "english keyboard",
    "keyboard us", "us keyboard", "us layout", "en-us keyboard",
    "uk keyboard", "uk layout", "italian keyboard", "italian layout",
    "swedish keyboard", "swedish layout", "nordic keyboard", "nordic layout",
    "danish keyboard", "danish layout", "belgian keyboard", "swiss keyboard",
    "azerty", "qwertz"
]

STOCK_INDISPONIVEL = [
    "esgotado", "fora de stock", "out of stock", "indisponivel",
    "temporariamente indisponivel", "sem stock", "sem estoque",
    "unavailable", "not available"
]
STOCK_DISPONIVEL = [
    "em stock", "em estoque", "disponivel", "disponibilidade: disponivel",
    "available", "in stock", "order now", "adicionar ao carrinho",
    "adiciona ao carrinho", "add to cart"
]


def normalizar_v6(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def detetar_stock_v6(texto: str) -> Optional[bool]:
    texto = normalizar_v6(texto)
    if any(x in texto for x in STOCK_INDISPONIVEL):
        return False
    if any(x in texto for x in STOCK_DISPONIVEL):
        return True
    return None


def extrair_teclado_do_html_v6(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    texto = normalizar_v6(soup.get_text(" ", strip=True))
    html_normalizado = normalizar_v6(str(soup))
    universo = f"{texto} {html_normalizado}"

    # A ausência de informação não é motivo de rejeição.
    if any(x in universo for x in TECLADO_NAO_PT_V6):
        return "nao_pt"
    if any(x in universo for x in TECLADO_PT_CONFIRMADO_V6):
        return "confirmado"
    return "desconhecido"


async def confirmar_teclado_produto_v6(page: Page, url: str) -> str:
    try:
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if response and response.status >= 400:
            return "desconhecido"
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeout:
            pass
        return extrair_teclado_do_html_v6(await page.content())
    except Exception:
        return "desconhecido"


def calcular_scores_v6(specs: dict, preco: float, weights: dict) -> dict:
    # Rejeitar somente quando existe indicação explícita de teclado não-PT.
    if specs["teclado_pt"] == "nao_pt":
        return {"status": "REJEITADO", "alertas": ["Teclado explicitamente não português."]}

    teclado_original = specs["teclado_pt"]
    # Reutilizamos toda a fórmula oficial do scraper, apenas bypassando o gate
    # do teclado quando o estado é desconhecido.
    if teclado_original == "desconhecido":
        specs["teclado_pt"] = "confirmado"
        try:
            resultado = _ORIGINAL_CALCULAR_SCORES(specs, preco, weights)
        finally:
            specs["teclado_pt"] = teclado_original
        if resultado.get("status") == "ACEITE":
            alertas = list(resultado.get("alertas", []))
            aviso = "Teclado PT não confirmado — portátil mantido no ranking."
            if aviso not in alertas:
                alertas.append(aviso)
            resultado["alertas"] = alertas
            resultado.setdefault("detalhes", {})["teclado_pt"] = "desconhecido"
        return resultado

    return _ORIGINAL_CALCULAR_SCORES(specs, preco, weights)


async def extrair_grelha_categoria_v6(page: Page, cat_config: dict, limit: int = 30) -> list[dict]:
    produtos = await _ORIGINAL_GRELHA(page, cat_config, limit=limit)
    if produtos:
        return produtos

    # Fallback para grelhas sem classes de cartão estáveis.
    soup = BeautifulSoup(await page.content(), "html.parser")
    result = []
    seen = set()
    hints = cat_config.get("product_path_hints", [
        "/produto/", "/product/", "/produtos/",
        "/computadores-portateis/", "/portateis/", "/laptop/"
    ])

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if not any(hint in href.lower() for hint in hints):
            continue
        absolute_url = urljoin(cat_config["url"], href)
        parent = anchor
        for _ in range(6):
            parent = parent.parent if parent else None
            if not parent:
                break
            text = parent.get_text(" ", strip=True)
            if not (20 <= len(text) <= 1200):
                continue
            match_price = re.search(r"(\d{2,4}(?:[.,]\d{2})?)\s*€", text)
            if not match_price:
                continue

            title_node = parent.select_one(
                "h1, h2, h3, h4, [class*='title'], [class*='Title'], "
                "[class*='name'], [class*='Name'], img[alt]"
            )
            title = ""
            if title_node:
                title = (
                    title_node.get("alt")
                    or title_node.get("title")
                    or title_node.get_text(" ", strip=True)
                )
            if not title:
                title = anchor.get("title") or anchor.get_text(" ", strip=True)
            title = re.sub(r"\s+", " ", title).strip()
            price = base.parse_price_value(match_price.group(1))

            if len(title) < 10 or title in seen or price is None or not 200 <= price <= 4500:
                continue

            seen.add(title)
            result.append({
                "loja": cat_config["loja"],
                "titulo": title,
                "preco": price,
                "url": absolute_url,
                "stock": detetar_stock_v6(text),
            })
            break

        if len(result) >= limit:
            break

    return result


async def extrair_preco_e_stock_v6(page: Page, loja: str):
    # Preservar o parser atual; o estado explícito de stock é tratado no runner
    # e esta função fica disponível para futuras lojas que usem detalhe de produto.
    return await _ORIGINAL_PRECO_STOCK(page, loja)


base.normalizar_texto = normalizar_v6
base.extrair_teclado_do_html = extrair_teclado_do_html_v6
base.confirmar_teclado_produto = confirmar_teclado_produto_v6
base.calcular_scores = calcular_scores_v6
base.extrair_grelha_categoria = extrair_grelha_categoria_v6
base.extrair_preco_e_stock = extrair_preco_e_stock_v6


async def main() -> None:
    print("🚀 A iniciar Rastreador V6 — teclado tolerante + fallback de scraping...")
    await base.main()


if __name__ == "__main__":
    asyncio.run(main())
