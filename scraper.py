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
from playwright.async_api import async_playwright, Page, BrowserContext

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
# MOTOR DE AVALIAÇÃO (V1)
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
        "cpu_modelo": None, "cpu_classe": None, "cpu_str_original": None,
        "ram_gb": None, "ram_expansivel": False,
        "armazenamento_tb": None, "ssd_expansivel": False,
        "bateria_wh": None, "peso_kg": None,
        "ecra_res": None, "ecra_hz": None,
        "alertas": [], "fontes": {}
    }

    gpus = ["rtx 5070", "rtx 5060", "rtx 5050", "rtx 4090", "rtx 4080", "rtx 4070", "rtx 4060", "rtx 4050"]
    for gpu in gpus:
        if gpu in texto:
            specs["gpu_modelo"], specs["gpu_tipo"], specs["fontes"]["gpu"] = gpu, "dedicada", "modelo_exato"
            break

    if not specs["gpu_modelo"]:
        if any(x in texto for x in ["intel iris", "radeon graphics", "arc graphics", "780m"]):
            specs["gpu_tipo"], specs["fontes"]["gpu"] = "integrada", "integrada_detetada"

    match_cpu = re.search(r'(core\s+ultra\s+[579]\s+\d{3}(?:h|u|v)?|i[579]-\d{4,5}(?:hx|hs|h|u|p)?|ryzen\s+[579]\s+\d{4}(?:hx|hs|h|u|s)?)', texto)
    if match_cpu:
        cpu_str = match_cpu.group(1)
        specs["cpu_str_original"], specs["fontes"]["cpu"] = cpu_str, "modelo_detetado"
        if re.search(r'ultra 9|i9|ryzen 9', cpu_str): specs["cpu_modelo"] = "tier_1"
        elif re.search(r'ultra 7|i7|ryzen 7', cpu_str): specs["cpu_modelo"] = "tier_2"
        else: specs["cpu_modelo"] = "tier_3"

        if 'hx' in cpu_str: specs["cpu_classe"] = "hx"
        elif 'hs' in cpu_str: specs["cpu_classe"] = "hs"
        elif 'h' in cpu_str: specs["cpu_classe"] = "h"
        elif 'u' in cpu_str or 'v' in cpu_str or 'p' in cpu_str: specs["cpu_classe"] = "u_ultra"

    match_ram_exp = re.search(r'(\d{2,3})\s?gb\s?(ram|ddr[45]|memory|so-dimm)\b', texto_limpo)
    if match_ram_exp:
        specs["ram_gb"], specs["fontes"]["ram"] = int(match_ram_exp.group(1)), "explicita"
    else:
        match_ram_heur = re.search(r'\b(\d{2,3})\s?gb\b', texto_limpo)
        if match_ram_heur and int(match_ram_heur.group(1)) in [8, 16, 24, 32, 48, 64]:
            specs["ram_gb"], specs["fontes"]["ram"] = int(match_ram_heur.group(1)), "heuristica"

    if re.search(r'2\s?tb', texto): specs["armazenamento_tb"] = 2.0
    elif re.search(r'1\s?tb', texto): specs["armazenamento_tb"] = 1.0
    elif re.search(r'512\s?gb', texto): specs["armazenamento_tb"] = 0.5

    match_hz = re.search(r'(\d{2,3})\s?hz', texto)
    if match_hz: specs["ecra_hz"] = int(match_hz.group(1))

    return specs

def calcular_scores(specs: dict, preco: float, weights: dict) -> dict:
    if specs.get("ram_gb") is not None and specs["ram_gb"] <= 8:
        return {"status": "REJEITADO", "alertas": [f"{specs['ram_gb']}GB RAM - Insuficiente"]}

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
        "value_score": value_score,
        "alertas": specs["alertas"]
    }

# ==========================================
# PARSER DE GRELHA (GRID EXTRACTION)
# ==========================================

async def extrair_grelha_categoria(page: Page, cat_config: dict, limit: int = 30) -> list[dict]:
    loja = cat_config["loja"]
    url = cat_config["url"]
    produtos = []

    try:
        await page.goto(url, timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"❌ Erro ao abrir página da categoria {loja}: {e}")
        return []

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    # Estratégia de extração genérica adaptada aos cartões de produto das lojas
    cards = []
    if "pcdiga" in loja.lower():
        cards = soup.select("article, div[class*='product-card'], div[class*='grid'] > div")
    elif "pccomponentes" in loja.lower():
        cards = soup.select("article.product-card, div.product-card__content")
    else:
        cards = soup.select("article, .product-card, .product-item, .item-card, [class*='product']")

    for card in cards:
        if len(produtos) >= limit: break

        # Extrair Título
        title_node = card.select_one("h2, h3, .product-title, [class*='title'], [class*='name']")
        title = title_node.get_text(strip=True) if title_node else ""
        if not title or len(title) < 10: continue

        # Extrair Preço
        price_node = card.select_one("[class*='price'], .price, span.price-value, .p")
        price_text = price_node.get_text(strip=True) if price_node else ""
        price = parse_price_value(price_text)
        if not price or price < 250 or price > 4500: continue

        # Extrair Link
        link_node = card.select_one("a[href]")
        link = urljoin(url, link_node["href"]) if link_node else url

        # Extrair Stock (Se não diz que está esgotado, assumimos stock na página de categoria)
        stock_text = card.get_text().lower()
        stock = not any(x in stock_text for x in ["esgotado", "out of stock", "indisponível", "sem stock"])

        produtos.append({
            "loja": loja,
            "titulo": title,
            "preco": price,
            "url": link,
            "stock": stock
        })

    # Remover duplicados da página
    vistos = set()
    unicos = []
    for p in produtos:
        if p["url"] not in vistos:
            vistos.add(p["url"])
            unicos.append(p)

    return unicos

# ==========================================
# NOTIFICAÇÕES & ALERTAS
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
    print("🚀 A iniciar Rastreador V3 (Pesquisa em Grelha + Oportunidades de Ouro)...")
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
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT"
        )

        for cat in config.get("category_urls", []):
            print(f"\n🔍 A varrer categoria: {cat['loja']}...")
            page = await context.new_page()
            produtos = await extrair_grelha_categoria(page, cat, limit=max_prods)
            await page.close()

            print(f"   => Encontrados {len(produtos)} produtos na grelha da {cat['loja']}.")

            for item in produtos:
                titulo = item["titulo"]
                preco = item["preco"]
                loja = item["loja"]
                key = f"{loja}::{titulo}"

                # --- BLOQUEIO POR ORÇAMENTO MÁXIMO ---
                if preco > budget_hard:
                    continue

                total_analisados += 1

                if not verificar_elegibilidade(titulo):
                    continue

                specs = extrair_specs_avancadas(titulo)
                avaliacao = calcular_scores(specs, preco, weights)

                if avaliacao["status"] == "REJEITADO":
                    continue

                # Histórico
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

                # Regra de Alerta: Oportunidade de Ouro (Value Score alto) ou Queda de Preço
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

    if alertas_disparados == 0 and total_analisados > 0:
        enviar_alerta("Rastreio Concluído", f"✅ {total_analisados} portáteis (abaixo de {budget_hard}€) analisados em massa.\nNenhuma oportunidade de ouro ou queda detetada neste ciclo.", "min", "mag")

    guardar_json(HISTORY_PATH, history)
    print(f"\n✅ Rastreamento em massa concluído ({total_analisados} produtos dentro do budget).")

if __name__ == "__main__":
    asyncio.run(main())
