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
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

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
        print(f"⚠️ Erro ao ler {path.name} ({e}). A criar novo histórico.")
        return {}

def guardar_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)

def parse_price_value(value: Any) -> Optional[float]:
    if value is None: return None
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
# MOTOR DE FILTRAGEM
# ==========================================

TERMOS_EXCLUSAO = [
    "recondicionado", "refurbished", "usado", "outlet",
    "grade a", "grade b", "grade c", "seminovo", "open box"
]

TERMOS_OBRIGATORIOS = ["portátil", "portatil", "laptop", "macbook", "notebook"]

def verificar_elegibilidade(titulo: str) -> bool:
    t_lower = titulo.lower()
    e_portatil = any(termo in t_lower for termo in TERMOS_OBRIGATORIOS)
    if not e_portatil:
        return False
    contem_exclusao = any(termo in t_lower for termo in TERMOS_EXCLUSAO)
    return not contem_exclusao

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
        return {"status": "REJEITADO"}

    p_ram = 100 if specs["ram_gb"] and specs["ram_gb"] >= 32 else (80 if specs["ram_gb"] and specs["ram_gb"] >= 16 else 40)
    p_ssd = 100 if specs["armazenamento_tb"] and specs["armazenamento_tb"] >= 2.0 else (85 if specs["armazenamento_tb"] and specs["armazenamento_tb"] >= 1.0 else 65)
    
    p_cpu = weights.get("cpu_base", {}).get(specs["cpu_modelo"], 50)
    p_gpu = weights.get("gpu_base", {}).get(specs["gpu_modelo"], 30 if specs["gpu_tipo"] == "integrada" else 50)

    score_feup = (p_ram * 0.25) + (p_ssd * 0.25) + (p_cpu * 0.50)
    score_gaming = (p_gpu * 0.70) + (p_cpu * 0.30)
    score_final = (score_feup * 0.50) + (score_gaming * 0.50)
    
    value_score = round(score_final / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0

    return {"status": "ACEITE", "score_final": round(score_final, 1), "value_score": value_score}

# ==========================================
# EXTRAÇÃO DE GRELHA E NAVEGAÇÃO
# ==========================================

async def extrair_grelha_categoria(page: Page, cat_config: dict, limit: int = 30) -> list[dict]:
    loja = cat_config["loja"]
    url = cat_config["url"]
    produtos = []

    try:
        # Espera que os pedidos de rede parem (permite carregar produtos via JS)
        response = await page.goto(url, timeout=45000, wait_until="networkidle")
        page_title = await page.title()
        status_code = response.status if response else 'N/A'
        print(f"   [Debug {loja}] Status: {status_code} | Título: '{page_title}'")
        
        if "just a moment" in page_title.lower() or status_code in [403, 429]:
            print(f"   ⚠️ {loja} bloqueada ou requer CAPTCHA.")
            return []

        # Interação para forçar lazy loading
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight / 2);")
        await page.wait_for_timeout(3000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        await page.wait_for_timeout(2000)

    except PlaywrightTimeout:
        print(f"   ⚠️ Aviso: Timeout em {loja}, a extrair o que carregou até agora...")
    except Exception as e:
        print(f"   ❌ Erro de navegação em {loja}: {e}")
        return []

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        "article", 
        "div[class*='product-card']", "div[class*='productCard']", 
        "div[class*='product-item']", "div[class*='ProductItem']", 
        "div[data-name='product']", "li[class*='product']"
    ]
    
    cards = soup.select(", ".join(selectors))
    
    # Fallback mais inteligente caso as classes acima não existam
    if not cards:
        tags = soup.find_all(['div', 'li'])
        for tag in tags:
            texto = tag.get_text(strip=True)
            # Se for uma caixa com tamanho razoável, tiver um link e um preço
            if 20 < len(texto) < 400 and tag.find('a') and re.search(r'\d{3,4}[\.,]\d{2}\s?€?', texto):
                cards.append(tag)

    for card in cards:
        if len(produtos) >= limit: break

        title_node = card.select_one("h1, h2, h3, h4, [class*='title'], [class*='name'], a[title]")
        title = title_node.get("title") or title_node.get_text(strip=True) if title_node else ""
        if not title or len(title) < 10: continue

        price_text = ""
        price_node = card.select_one("[class*='price'], .price, span[class*='Price']")
        if price_node:
            price_text = price_node.get_text(strip=True)
        else:
            match_p = re.search(r'(\d{3,4}[\.,]\d{2})\s?€?', card.get_text(separator=" "))
            if match_p: price_text = match_p.group(1)

        price = parse_price_value(price_text)
        if not price or price < 200 or price > 4500: 
            continue

        link_node = card.select_one("a[href]")
        link = urljoin(url, link_node["href"]) if link_node else url
        stock = not any(x in card.get_text().lower() for x in ["esgotado", "out of stock", "indisponível"])

        produtos.append({"loja": loja, "titulo": title, "preco": price, "url": link, "stock": stock})

    # Remover duplicados
    unicos = {f"{p['titulo']}::{p['preco']}": p for p in produtos}.values()
    return list(unicos)

# ==========================================
# NOTIFICAÇÕES (NTFY via JSON Payload)
# ==========================================

def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC:
        print(f"⚠️ NTFY_TOPIC não definido.")
        return
    try:
        # Enviar em JSON resolve 100% os problemas de formatação, emojis e cabeçalhos HTTP
        payload = {
            "topic": NTFY_TOPIC,
            "title": titulo,
            "message": mensagem,
            "tags": [t.strip() for t in tags.split(",")],
            "priority": 4 if prioridade == "high" else 3
        }
        res = requests.post("https://ntfy.sh", json=payload, timeout=15)
        res.raise_for_status()
        print(f"📲 Notificação enviada! ({titulo})")
    except Exception as e:
        print(f"❌ Erro ao enviar JSON para o ntfy: {e}")

# ==========================================
# FLUXO PRINCIPAL
# ==========================================

async def main() -> None:
    print("🚀 A iniciar Rastreador V4 (Wait for Network + Ntfy JSON Fix)...")
    config = carregar_json(CONFIG_PATH)
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})

    settings = config.get("settings", {})
    weights = config.get("weights", {})
    min_value = settings.get("min_value_score_alerta", 45.0)
    budget_hard = settings.get("budget_hard", 1500.0)

    alertas, analisados = 0, 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT"
        )

        for cat in config.get("category_urls", []):
            print(f"\n🔍 A varrer categoria: {cat['loja']}...")
            page = await context.new_page()
            produtos = await extrair_grelha_categoria(page, cat, limit=settings.get("max_produtos_por_categoria", 30))
            await page.close()

            print(f"   => Encontrados {len(produtos)} itens na grelha da {cat['loja']}.")

            for item in produtos:
                if not verificar_elegibilidade(item["titulo"]) or item["preco"] > budget_hard:
                    continue

                analisados += 1
                specs = extrair_specs_avancadas(item["titulo"])
                av = calcular_scores(specs, item["preco"], weights)

                if av.get("status") == "REJEITADO": continue

                key = f"{item['loja']}::{item['titulo']}"
                entries = history["offers"].setdefault(key, [])
                prev = entries[-1] if entries else None

                entries.append({
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "price": item["preco"],
                    "stock": item["stock"],
                    "score_final": av["score_final"],
                    "value_score": av["value_score"]
                })
                history["offers"][key] = entries[-60:]

                print(f"   [+] {item['titulo'][:45]}... | {item['preco']:.2f}€ | Score: {av['score_final']} | Value: {av['value_score']}")

                e_oport = av["value_score"] >= min_value
                baixou = prev and (prev["price"] - item["preco"] > 5.0)

                if (e_oport or baixou) and item["stock"]:
                    alertas += 1
                    t = f"🌟 OPORTUNIDADE: {item['preco']:.0f}€" if e_oport else f"📉 QUEDA PREÇO: {item['preco']:.0f}€"
                    m = f"{item['titulo']}\n\nLoja: {item['loja']}\nScore: {av['score_final']}/100\n🔗 {item['url']}"
                    enviar_alerta(t, m, prioridade="high", tags="star2" if e_oport else "chart_with_downwards_trend")

        await browser.close()

    enviar_alerta("🔄 Relatório de Rastreio V4", f"Rastreio concluído.\nPortáteis válidos: {analisados}\nAlertas: {alertas}", "default", "white_check_mark")
    guardar_json(HISTORY_PATH, history)
    print(f"\n✅ Concluído ({analisados} portáteis analisados).")

if __name__ == "__main__":
    asyncio.run(main())
