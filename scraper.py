import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

# ==========================================
# UTILITÁRIOS & I/O
# ==========================================

def carregar_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"⚠️ Erro ao ler {path.name} ({e}). A criar novo histórico limpo.")
        return {}

def guardar_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)

def parse_price_value(value: Any) -> Optional[float]:
    if value is None: return None
    if isinstance(value, (int, float)): return float(value)
    text = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not text: return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                return float(text.replace(".", "").replace(",", "."))
            return float(text.replace(",", ""))
        if "," in text:
            return float(text.replace(".", "").replace(",", "."))
        return float(text)
    except ValueError:
        return None

# ==========================================
# MOTOR DE AVALIAÇÃO
# ==========================================

TERMOS_EXCLUSAO = [
    "recondicionado", "refurbished", "usado", "outlet",
    "grade a", "grade b", "grade c", "seminovo", "open box"
]

def verificar_elegibilidade(titulo: str) -> bool:
    return not any(termo in titulo.lower() for termo in TERMOS_EXCLUSAO)

def limpar_vram(texto: str) -> str:
    texto = re.sub(r'\b(4|6|8|12|16|24)\s?gb\s?(gddr\d|vram)\b', '', texto)
    texto = re.sub(r'\b(rtx|rx|gtx)\s?\d{4}\s?\d{1,2}gb\b', '', texto)
    return texto

def extrair_specs_avancadas(texto_bruto: str) -> dict:
    texto = texto_bruto.lower()
    texto_limpo = limpar_vram(texto)

    specs = {
        "gpu_modelo": None, "gpu_tipo": "desconhecida",
        "cpu_modelo": None, "cpu_classe": None,
        "ram_gb": None, "armazenamento_tb": None
    }

    gpus = ["rtx 5070", "rtx 5060", "rtx 5050", "rtx 4090", "rtx 4080", "rtx 4070", "rtx 4060", "rtx 4050"]
    for gpu in gpus:
        if gpu in texto:
            specs["gpu_modelo"], specs["gpu_tipo"] = gpu, "dedicada"
            break

    if not specs["gpu_modelo"]:
        if any(x in texto for x in ["intel iris", "radeon graphics", "arc graphics", "780m"]):
            specs["gpu_tipo"] = "integrada"

    match_cpu = re.search(r'(core\s+ultra\s+[579]\s+\d{3}(?:h|u|v)?|i[579]-\d{4,5}(?:hx|hs|h|u|p)?|ryzen\s+[579]\s+\d{4}(?:hx|hs|h|u|s)?)', texto)
    if match_cpu:
        cpu_str = match_cpu.group(1)
        if re.search(r'ultra 9|i9|ryzen 9', cpu_str): specs["cpu_modelo"] = "tier_1"
        elif re.search(r'ultra 7|i7|ryzen 7', cpu_str): specs["cpu_modelo"] = "tier_2"
        else: specs["cpu_modelo"] = "tier_3"

    match_ram = re.search(r'(\d{2,3})\s?gb\b', texto_limpo)
    if match_ram and int(match_ram.group(1)) in [8, 16, 24, 32, 48, 64]:
        specs["ram_gb"] = int(match_ram.group(1))

    if re.search(r'2\s?tb', texto): specs["armazenamento_tb"] = 2.0
    elif re.search(r'1\s?tb', texto): specs["armazenamento_tb"] = 1.0
    elif re.search(r'512\s?gb', texto): specs["armazenamento_tb"] = 0.5

    return specs

def calcular_scores(specs: dict, preco: float, weights: dict) -> dict:
    if specs.get("ram_gb") is not None and specs["ram_gb"] <= 8:
        return {"status": "REJEITADO", "reason": "RAM <= 8GB"}

    p_ram = 100 if specs["ram_gb"] and specs["ram_gb"] >= 32 else (80 if specs["ram_gb"] and specs["ram_gb"] >= 16 else 40)
    p_ssd = 100 if specs["armazenamento_tb"] and specs["armazenamento_tb"] >= 2.0 else (85 if specs["armazenamento_tb"] and specs["armazenamento_tb"] >= 1.0 else 65)
    
    p_cpu = weights.get("cpu_base", {}).get(specs["cpu_modelo"], 50)
    p_gpu = weights.get("gpu_base", {}).get(specs["gpu_modelo"], 30 if specs["gpu_tipo"] == "integrada" else 50)

    score_feup = (p_ram * 0.25) + (p_ssd * 0.25) + (p_cpu * 0.50)
    score_gaming = (p_gpu * 0.70) + (p_cpu * 0.30)
    score_final = (score_feup * 0.50) + (score_gaming * 0.50)
    
    value_score = round(score_final / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0

    return {
        "status": "ACEITE",
        "score_final": round(score_final, 1),
        "value_score": value_score
    }

# ==========================================
# EXTRAÇÃO DE GRELHA MELHORADA (COM SCROLL)
# ==========================================

async def extrair_grelha_categoria(page: Page, cat_config: dict, limit: int = 30) -> list[dict]:
    loja = cat_config["loja"]
    url = cat_config["url"]
    produtos = []

    try:
        response = await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page_title = await page.title()
        print(f"   [Debug {loja}] Status: {response.status if response else 'N/A'} | Título: '{page_title}'")

        # Verificação de bloqueio Cloudflare / Bot
        if "just a moment" in page_title.lower() or "attention required" in page_title.lower():
            print(f"   ⚠️ {loja} bloqueada por proteção Cloudflare/Bot Check.")
            return []

        # Scroll para forçar carregamento dinâmico
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3);")
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, (document.body.scrollHeight / 3) * 2);")
        await page.wait_for_timeout(1500)

    except Exception as e:
        print(f"   ❌ Erro de navegação em {loja}: {e}")
        return []

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    # Mapeamento de selectores abrangentes por loja
    selectors = [
        "article", 
        "div[class*='product-card']", 
        "div[class*='productCard']", 
        "div[class*='product_card']",
        "div[class*='product-item']", 
        "div[class*='ProductItem']", 
        "li[class*='product']",
        "[data-testid*='product']"
    ]
    
    cards = soup.select(", ".join(selectors))
    
    # Fallback genérico se a estrutura for baseada apenas em links de produto
    if not cards:
        cards = soup.find_all(lambda tag: tag.name in ['div', 'li', 'article'] and tag.find('a') and re.search(r'\d+[\.,]\d{2}\s?€?', tag.get_text()))

    for card in cards:
        if len(produtos) >= limit: break

        # Procura título
        title_node = card.select_one("h1, h2, h3, h4, [class*='title'], [class*='name'], a[title]")
        title = ""
        if title_node:
            title = title_node.get("title") or title_node.get_text(strip=True)
        if not title or len(title) < 12:
            continue

        # Procura preço no cartão
        price_text = ""
        price_node = card.select_one("[class*='price'], .price, span[class*='Price']")
        if price_node:
            price_text = price_node.get_text(strip=True)
        else:
            # Procural padrão de preço por RegEx no texto do cartão
            match_p = re.search(r'(\d{3,4}[\.,]\d{2})\s?€?', card.get_text())
            if match_p: price_text = match_p.group(1)

        price = parse_price_value(price_text)
        if not price or price < 200 or price > 4500: 
            continue

        # Procura URL
        link_node = card.select_one("a[href]")
        link = urljoin(url, link_node["href"]) if link_node else url

        # Stock
        stock_text = card.get_text().lower()
        stock = not any(x in stock_text for x in ["esgotado", "out of stock", "indisponível", "sem stock"])

        produtos.append({
            "loja": loja,
            "titulo": title,
            "preco": price,
            "url": link,
            "stock": stock
        })

    # Filtrar duplicados na mesma página
    vistos = set()
    unicos = []
    for p in produtos:
        chave = f"{p['titulo']}::{p['preco']}"
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(p)

    return unicos

# ==========================================
# NOTIFICAÇÕES
# ==========================================

def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC: return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=mensagem.encode("utf-8"),
            headers={"Title": titulo.encode("ascii", "ignore").decode("ascii"), "Tags": tags, "Priority": prioridade},
            timeout=15,
        ).raise_for_status()
    except requests.RequestException: pass

# ==========================================
# FLUXO PRINCIPAL
# ==========================================

async def main() -> None:
    print("🚀 A iniciar Rastreador V3 (Com Debug & Auto-Scroll)...")
    config = carregar_json(CONFIG_PATH)
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})

    settings = config.get("settings", {})
    weights = config.get("weights", {})
    
    min_value_alerta = settings.get("min_value_score_alerta", 45.0)
    max_prods = settings.get("max_produtos_por_categoria", 30)
    budget_hard = settings.get("budget_hard", 1500.0)

    alertas_disparados = 0
    total_analisados = 0

    async with async_playwright() as p:
        # Chromium com argumentos para mitigar deteção de automação
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT"
        )

        for cat in config.get("category_urls", []):
            print(f"\n🔍 A varrer categoria: {cat['loja']}...")
            page = await context.new_page()
            
            # Bloquear imagens e CSS desnecessários para acelerar e poupar tráfego
            await page.route("**/*.{png,jpg,jpeg,svg,webp,css,woff,woff2}", lambda route: route.abort())

            produtos = await extrair_grelha_categoria(page, cat, limit=max_prods)
            await page.close()

            print(f"   => Encontrados {len(produtos)} produtos válidos na {cat['loja']}.")

            for item in produtos:
                titulo = item["titulo"]
                preco = item["preco"]
                loja = item["loja"]
                key = f"{loja}::{titulo}"

                if preco > budget_hard:
                    continue

                total_analisados += 1

                if not verificar_elegibilidade(titulo):
                    continue

                specs = extrair_specs_avancadas(titulo)
                avaliacao = calcular_scores(specs, preco, weights)

                if avaliacao["status"] == "REJEITADO":
                    continue

                entries = history["offers"].setdefault(key, [])
                previous = entries[-1] if entries else None

                current = {
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "price": preco,
                    "stock": item["stock"],
                    "score_final": avaliacao["score_final"],
                    "value_score": avaliacao["value_score"]
                }
                entries.append(current)
                history["offers"][key] = entries[-60:]

                print(f"   [+] {titulo[:45]}... | {preco:.2f}€ | Score: {avaliacao['score_final']} | Value: {avaliacao['value_score']}")

                e_oportunidade = avaliacao["value_score"] >= min_value_alerta
                baixou_preco = previous and (previous["price"] - preco > 5.0)

                if (e_oportunidade or baixou_preco) and item["stock"]:
                    alertas_disparados += 1
                    tag_emoji = "star2" if e_oportunidade else "chart_with_downwards_trend"
                    titulo_alerta = f"🌟 OPORTUNIDADE DE OURO: {preco:.0f}€" if e_oportunidade else f"📉 QUEDA DE PREÇO: {preco:.0f}€"
                    
                    msg = (
                        f"{titulo}\n\n"
                        f"🏬 Loja: {loja}\n"
                        f"💶 Preço: {preco:.2f} €\n"
                        f"🏆 Performance Score: {avaliacao['score_final']} / 100\n"
                        f"💎 Value Score: {avaliacao['value_score']}\n\n"
                        f"🔗 {item['url']}"
                    )
                    enviar_alerta(titulo_alerta, msg, prioridade="high", tags=tag_emoji)

        await browser.close()

    guardar_json(HISTORY_PATH, history)
    print(f"\n✅ Rastreamento concluído ({total_analisados} portáteis analisados dentro do budget de {budget_hard}€).")

if __name__ == "__main__":
    asyncio.run(main())
