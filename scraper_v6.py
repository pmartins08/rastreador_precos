import asyncio
import re
import unicodedata
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

import scraper as base


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

    # Rejeitar apenas quando houver evidência explícita de layout estrangeiro.
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
    # A única condição de rejeição relacionada com teclado é evidência explícita
    # de que o layout não é PT. 'desconhecido' segue para o ranking.
    if specs["teclado_pt"] == "nao_pt":
        return {"status": "REJEITADO", "alertas": ["Teclado explicitamente não português."]}

    resultado = base.calcular_scores.__wrapped__(specs, preco, weights) if hasattr(base.calcular_scores, "__wrapped__") else None
    if resultado is None:
        resultado = _calcular_scores_base_sem_teclado(specs, preco, weights)
    return resultado


def _calcular_scores_base_sem_teclado(specs: dict, preco: float, weights: dict) -> dict:
    # Copia a lógica base, removendo apenas o bloqueio do teclado desconhecido.
    if specs["ram_gb"] == 8:
        return {"status": "REJEITADO", "alertas": ["8GB RAM confirmado - insuficiente."]}
    if specs["peso_kg"] and specs["peso_kg"] > 2.8:
        return {"status": "REJEITADO", "alertas": ["Excede limite de peso (>2.8kg)."]}

    ram = specs["ram_gb"]
    p_ram = 50 if ram is None else 100 if ram >= 32 else 80 if ram >= 16 else 40
    arm = specs["armazenamento_tb"]
    p_ssd = 50 if arm is None else 100 if arm >= 2.0 else 85 if arm >= 1.0 else 65
    tabela_ecra = {"qhd+": 100, "qhd": 95, "fhd+": 85, "fhd": 75, None: 60}
    p_ecra_res = tabela_ecra.get(specs["ecra_res"], 60)
    p_ecra_hz = min(100, (specs.get("ecra_hz") or 60) / 1.65)
    tabela_cpu = weights.get("cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70})
    p_cpu = tabela_cpu.get(specs["cpu_modelo"], 50)

    penalizacao_consumo = {"u_ultra": 0, "hs": 5, "h": 10, "hx": 20, None: 10}
    if specs["bateria_wh"] is None:
        score_autonomia = 50
    else:
        p_bat_base = min(100, (specs["bateria_wh"] / 90) * 100)
        score_autonomia = max(0, p_bat_base - penalizacao_consumo.get(specs["cpu_classe"], 10))

    tabela_gpu = weights.get("gpu_base", {
        "rtx 5090": 100, "rtx 5080": 98, "rtx 5070 ti": 97, "rtx 5070": 95,
        "rtx 5060 ti": 90, "rtx 5060": 85, "rtx 5050": 60,
        "rtx 4090": 100, "rtx 4080": 100, "rtx 4070": 80, "rtx 4060": 65, "rtx 4050": 45,
    })
    if specs["gpu_tipo"] == "dedicada":
        p_gpu = tabela_gpu.get(specs["gpu_modelo"], 50)
    elif specs["gpu_tipo"] == "integrada":
        p_gpu = 15
    else:
        p_gpu = 30

    peso = specs.get("peso_kg")
    if peso is None:
        p_peso = 50
    elif peso <= 1.4:
        p_peso = 100
    elif peso >= 2.8:
        p_peso = 0
    else:
        p_peso = max(0, 100 - ((peso - 1.4) * 71.4))

    if ram is None:
        p_ram_long = 50
    elif ram >= 32:
        p_ram_long = 100
    elif ram == 16 and specs["ram_expansivel"]:
        p_ram_long = 95
    elif ram == 16:
        p_ram_long = 75
    else:
        p_ram_long = 40

    exp = specs.get("ssd_expansivel")
    if arm is None:
        p_ssd_long = 50
    elif arm >= 2.0 or (arm == 1.0 and exp):
        p_ssd_long = 100
    elif arm == 1.0:
        p_ssd_long = 85
    elif arm == 0.5 and exp:
        p_ssd_long = 75
    elif arm == 0.5:
        p_ssd_long = 65
    else:
        p_ssd_long = 50

    score_feup = p_ram * 0.20 + score_autonomia * 0.30 + p_ssd * 0.15 + p_ecra_res * 0.20 + p_cpu * 0.15
    score_gaming = p_gpu * 0.65 + p_cpu * 0.20 + p_ecra_hz * 0.10 + p_ram * 0.05
    score_longevidade = p_ram_long * 0.35 + p_ssd_long * 0.25 + score_autonomia * 0.20 + p_cpu * 0.20
    score_final = score_feup * 0.50 + score_gaming * 0.25 + score_longevidade * 0.15 + p_peso * 0.10
    conf_valor, qualidade = base.calcular_qualidade_dados(specs)
    score_ranking = round(score_final * (0.85 + 0.15 * conf_valor), 1)
    value_score = round(score_ranking / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0

    alertas = list(specs.get("alertas", []))
    if specs["teclado_pt"] == "desconhecido":
        msg = "Teclado PT não confirmado — portátil mantido no ranking."
        if msg not in alertas:
            alertas.append(msg)

    return {
        "status": "ACEITE",
        "score_final": round(score_final, 1),
        "score_ranking": score_ranking,
        "value_score": value_score,
        "qualidade_dados": qualidade,
        "confianca_percentual": f"{int(conf_valor * 100)}%",
        "fontes_extraidas": specs["fontes"],
        "alertas": alertas,
        "detalhes": {
            "marca": specs.get("marca"),
            "submarca": specs.get("submarca"),
            "teclado_pt": specs.get("teclado_pt"),
            "FEUP": round(score_feup, 1),
            "Gaming": round(score_gaming, 1),
            "Longevidade": round(score_longevidade, 1),
            "Portabilidade": round(p_peso, 1),
        },
    }


async def extrair_grelha_categoria_v6(page: Page, cat_config: dict, limit: int = 30) -> list[dict]:
    # Primeiro tenta o parser existente, para preservar compatibilidade por loja.
    produtos = await base.extrair_grelha_categoria(page, cat_config, limit=limit)
    if produtos:
        # Corrige a inferência excessivamente otimista de stock usada pelo parser antigo.
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        texto_pagina = soup.get_text(" ", strip=True)
        stock_global = detetar_stock_v6(texto_pagina)
        if stock_global is False:
            for item in produtos:
                item["stock"] = False
        return produtos

    # Fallback de segunda camada para lojas em que o DOM não segue os selectors habituais.
    soup = BeautifulSoup(await page.content(), "html.parser")
    urls_produto = set()
    hints = cat_config.get("product_path_hints", [
        "/produto/", "/product/", "/produtos/",
        "/computadores-portateis/", "/portateis/", "/laptop/"
    ])
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        href_low = href.lower()
        if any(hint in href_low for hint in hints):
            urls_produto.add(urljoin(cat_config["url"], href))

    result = []
    seen = set()
    for link in urls_produto:
        if len(result) >= limit:
            break
        anchor = soup.find("a", href=lambda value: value == link or value == href)
        if anchor is None:
            continue
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
            title_node = parent.select_one("h1, h2, h3, h4, [class*='title'], [class*='Title'], [class*='name'], [class*='Name'], img[alt]")
            title = ""
            if title_node:
                title = title_node.get("alt") or title_node.get("title") or title_node.get_text(" ", strip=True)
            if not title:
                title = anchor.get("title") or anchor.get_text(" ", strip=True)
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) < 10 or title in seen:
                continue
            price = base.parse_price_value(match_price.group(1))
            if price is None or not 200 <= price <= 4500:
                continue
            seen.add(title)
            result.append({
                "loja": cat_config["loja"],
                "titulo": title,
                "preco": price,
                "url": urljoin(cat_config["url"], anchor.get("href", "")),
                "stock": detetar_stock_v6(text),
            })
            break
    return result


async def extrair_preco_e_stock_v6(page: Page, loja: str):
    return await base.extrair_preco_e_stock(page, loja)


# Aplicar overrides no módulo que contém main(); o main continua a ser o mesmo,
# mas usa as implementações V6 acima.
base.normalizar_texto = normalizar_v6
base.extrair_teclado_do_html = extrair_teclado_do_html_v6
base.confirmar_teclado_produto = confirmar_teclado_produto_v6
base.calcular_scores = calcular_scores_v6
base.extrair_grelha_categoria = extrair_grelha_categoria_v6
base.extrair_preco_e_stock = extrair_preco_e_stock_v6


async def main() -> None:
    print("🚀 A iniciar Rastreador V6 — teclado tolerante + scraping robusto...")
    await base.main()


if __name__ == "__main__":
    asyncio.run(main())
