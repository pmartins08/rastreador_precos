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

TERMOS_EXCLUSAO = [
    "recondicionado", "refurbished", "usado", "outlet",
    "grade a", "grade b", "grade c", "seminovo", "open box"
]

MARCAS_ACEITES = {
    "asus": ["rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"],
    "lenovo": ["legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"],
    "hp": ["omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"],
    "acer": ["predator", "nitro", "swift", "aspire", "travelmate"],
    "msi": ["raider", "vector", "stealth", "crosshair", "katana", "prestige", "creator"],
    "dell": ["alienware", "g-series", "g15", "g16", "xps", "inspiron", "latitude"],
}

TECLADO_PT_CONFIRMADO = [
    "teclado português", "teclado portugues", "keyboard português",
    "keyboard portugues", "layout pt", "keyboard pt", "pt-pt", "portuguese keyboard"
]
TECLADO_NAO_PT = [
    "teclado espanhol", "teclado frances", "teclado francês", "teclado alemão",
    "teclado ingles", "teclado inglês", "keyboard us", "us keyboard", "uk keyboard"
]


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
    if value is None:
        return None
    text = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return None
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


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower()).strip()


def detetar_marca_submarca(titulo: str) -> tuple[Optional[str], Optional[str]]:
    texto = normalizar_texto(titulo)
    for marca, submarcas in MARCAS_ACEITES.items():
        if re.search(rf"\b{re.escape(marca)}\b", texto):
            for submarca in submarcas:
                if re.search(rf"\b{re.escape(submarca)}\b", texto):
                    return marca, submarca
            return marca, None
    return None, None


def verificar_elegibilidade(titulo: str) -> bool:
    texto = normalizar_texto(titulo)
    if any(termo in texto for termo in TERMOS_EXCLUSAO):
        return False
    marca, _ = detetar_marca_submarca(texto)
    return marca in MARCAS_ACEITES


def limpar_vram(texto: str) -> str:
    texto = re.sub(r"\b(4|6|8|12|16|24)\s?gb\s?(gddr\d|vram)\b", "", texto)
    texto = re.sub(r"\b(rtx|rx|gtx)\s?\d{4}\s?\d{1,2}gb\b", "", texto)
    return texto


def extrair_specs_avancadas(texto_bruto: str) -> dict:
    texto = normalizar_texto(texto_bruto)
    texto_limpo = limpar_vram(texto)
    specs = {
        "marca": None, "submarca": None,
        "gpu_modelo": None, "gpu_tipo": "desconhecida",
        "cpu_modelo": None, "cpu_classe": None, "cpu_str_original": None,
        "ram_gb": None, "ram_expansivel": False,
        "armazenamento_tb": None, "ssd_expansivel": False,
        "bateria_wh": None, "peso_kg": None,
        "ecra_res": None, "ecra_hz": None,
        "teclado_pt": "desconhecido",
        "alertas": [], "fontes": {}
    }

    marca, submarca = detetar_marca_submarca(texto)
    specs["marca"], specs["submarca"] = marca, submarca
    if marca:
        specs["fontes"]["marca"] = "detetada"

    gpus = [
        "rtx 5090", "rtx 5080", "rtx 5070 ti", "rtx 5070",
        "rtx 5060 ti", "rtx 5060", "rtx 5050",
        "rtx 4090", "rtx 4080", "rtx 4070", "rtx 4060", "rtx 4050"
    ]
    for gpu in gpus:
        if gpu in texto:
            specs["gpu_modelo"] = gpu
            specs["gpu_tipo"] = "dedicada"
            specs["fontes"]["gpu"] = "modelo_exato"
            break

    if not specs["gpu_modelo"]:
        if any(x in texto for x in ["intel iris", "intel arc graphics", "radeon graphics", "radeon 780m", "radeon 890m"]):
            specs["gpu_tipo"] = "integrada"
            specs["fontes"]["gpu"] = "integrada_detetada"
        else:
            specs["alertas"].append("GPU não identificada")

    match_cpu = re.search(
        r"(core\s+ultra\s+[579]\s+\d{3}(?:hx|hs|h|u|v)?"
        r"|i[579]-\d{4,5}(?:hx|hs|h|u|p)?"
        r"|ryzen\s+[579]\s+\d{4}(?:hx|hs|h|u|s)?)",
        texto,
    )
    if match_cpu:
        cpu_str = match_cpu.group(1)
        specs["cpu_str_original"] = cpu_str
        specs["fontes"]["cpu"] = "modelo_detetado"
        if re.search(r"ultra 9|i9|ryzen 9", cpu_str):
            specs["cpu_modelo"] = "tier_1"
        elif re.search(r"ultra 7|i7|ryzen 7", cpu_str):
            specs["cpu_modelo"] = "tier_2"
        else:
            specs["cpu_modelo"] = "tier_3"

        if "hx" in cpu_str:
            specs["cpu_classe"] = "hx"
        elif "hs" in cpu_str:
            specs["cpu_classe"] = "hs"
        elif re.search(r"(?:\d)h\b", cpu_str) or re.search(r"\bh\b", cpu_str):
            specs["cpu_classe"] = "h"
        elif any(x in cpu_str for x in [" u", " v", " p"]):
            specs["cpu_classe"] = "u_ultra"
    else:
        specs["alertas"].append("CPU não confirmada")

    match_ram_exp = re.search(
        r"(\d{1,3})\s?gb\s?(ram|ddr[45](?:x)?|memory|so-dimm)\b",
        texto_limpo,
    )
    if match_ram_exp:
        specs["ram_gb"] = int(match_ram_exp.group(1))
        specs["fontes"]["ram"] = "explicita"
    else:
        matches_ram = re.findall(r"\b(\d{1,3})\s?gb\b", texto_limpo)
        for raw in matches_ram:
            val = int(raw)
            if val in [8, 12, 16, 24, 32, 48, 64, 96, 128]:
                specs["ram_gb"] = val
                specs["fontes"]["ram"] = "heuristica"
                specs["alertas"].append("RAM inferida por heurística")
                break
        if specs["ram_gb"] is None:
            specs["alertas"].append("RAM desconhecida")

    if any(x in texto for x in [
        "ram expansivel", "ram expansível", "so-dimm", "slot ram",
        "ram upgrade", "upgradable memory"
    ]):
        specs["ram_expansivel"] = True
        specs["fontes"]["ram_expansivel"] = "texto"

    storage_patterns = [
        (2.0, r"2\s?tb(?:\s?(?:ssd|nvme|pcie))?"),
        (1.0, r"1\s?tb(?:\s?(?:ssd|nvme|pcie))?"),
        (0.5, r"512\s?gb(?:\s?(?:ssd|nvme|pcie))?"),
    ]
    for value, pattern in storage_patterns:
        match = re.search(pattern, texto)
        if match:
            explicit = bool(re.search(r"(ssd|nvme|pcie)", match.group(0)))
            specs["armazenamento_tb"] = value
            specs["fontes"]["armazenamento"] = "explicita" if explicit else "heuristica"
            if not explicit:
                specs["alertas"].append("Armazenamento inferido por capacidade")
            break
    if specs["armazenamento_tb"] is None:
        specs["alertas"].append("Armazenamento não confirmado")

    if any(x in texto for x in [
        "ssd extra", "2x m.2", "2 x m.2", "slot m.2 livre",
        "segundo ssd", "segundo m.2", "armazenamento expansivel", "armazenamento expansível"
    ]):
        specs["ssd_expansivel"] = True
        specs["fontes"]["ssd_expansivel"] = "texto"

    match_bat = re.search(r"(\d{2,3})\s?wh\b", texto)
    if match_bat:
        specs["bateria_wh"] = int(match_bat.group(1))
        specs["fontes"]["bateria"] = "wh_detetado"
    else:
        specs["alertas"].append("Bateria (Wh) desconhecida")

    match_peso = re.search(r"(\d[\.,]\d+)\s?kg\b", texto)
    if match_peso:
        specs["peso_kg"] = float(match_peso.group(1).replace(",", "."))
        specs["fontes"]["peso"] = "kg_detetado"
    else:
        specs["alertas"].append("Peso desconhecido")

    if any(x in texto for x in ["qhd+", "2880x1800", "2560x1600", "wqxga"]):
        specs["ecra_res"] = "qhd+"
    elif any(x in texto for x in ["qhd", "2560x1440", "2560 x 1440"]):
        specs["ecra_res"] = "qhd"
    elif any(x in texto for x in ["1200p", "1920x1200", "1920 x 1200", "wuxga", "16:10"]):
        specs["ecra_res"] = "fhd+"
    elif any(x in texto for x in ["fhd", "1920x1080", "1920 x 1080", "1080p"]):
        specs["ecra_res"] = "fhd"

    if specs["ecra_res"]:
        specs["fontes"]["ecra_res"] = "detetada"
    else:
        specs["alertas"].append("Resolução do ecrã desconhecida")

    match_hz = re.search(r"(\d{2,3})\s?hz\b", texto)
    if match_hz:
        specs["ecra_hz"] = int(match_hz.group(1))
        specs["fontes"]["ecra_hz"] = "detetado"
    else:
        specs["alertas"].append("Frequência do ecrã desconhecida")

    if any(x in texto for x in TECLADO_PT_CONFIRMADO):
        specs["teclado_pt"] = "confirmado"
        specs["fontes"]["teclado"] = "confirmado_no_texto"
    elif any(x in texto for x in TECLADO_NAO_PT):
        specs["teclado_pt"] = "nao_pt"
        specs["fontes"]["teclado"] = "nao_pt_no_texto"
        specs["alertas"].append("Teclado não é PT")
    else:
        specs["alertas"].append("Teclado PT não confirmado")

    return specs


def calcular_qualidade_dados(specs: dict) -> tuple[float, str]:
    score = 0.0
    score += 0.20 if specs.get("cpu_modelo") else 0.0
    score += 0.20 if specs.get("gpu_tipo") != "desconhecida" else 0.0
    if specs.get("ram_gb"):
        score += 0.20 if specs["fontes"].get("ram") == "explicita" else 0.14
    for campo, peso in [("bateria_wh", 0.10), ("peso_kg", 0.10), ("ecra_res", 0.10), ("ecra_hz", 0.10)]:
        if specs.get(campo) is not None:
            score += peso
    if score >= 0.85:
        qualidade = "ALTA"
    elif score >= 0.50:
        qualidade = "MEDIA"
    else:
        qualidade = "BAIXA"
    return score, qualidade


def calcular_scores(specs: dict, preco: float, weights: dict) -> dict:
    if specs["teclado_pt"] == "nao_pt":
        return {"status": "REJEITADO", "alertas": ["Teclado não é português."]}
    if specs["teclado_pt"] != "confirmado":
        return {"status": "REJEITADO", "alertas": ["Teclado PT não confirmado — fora do ranking automático."]}
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

    conf_valor, qualidade = calcular_qualidade_dados(specs)
    score_ranking = round(score_final * (0.85 + 0.15 * conf_valor), 1)
    value_score = round(score_ranking / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0

    return {
        "status": "ACEITE",
        "score_final": round(score_final, 1),
        "score_ranking": score_ranking,
        "value_score": value_score,
        "qualidade_dados": qualidade,
        "confianca_percentual": f"{int(conf_valor * 100)}%",
        "fontes_extraidas": specs["fontes"],
        "alertas": specs["alertas"],
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


async def extrair_preco_e_stock(page: Page, loja: str) -> tuple[Optional[float], Optional[bool]]:
    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")
    product_json = soup.find("script", type="application/ld+json")
    if product_json:
        try:
            data = json.loads(product_json.string or product_json.get_text())
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                offers = item.get("offers")
                if isinstance(offers, dict):
                    price = parse_price_value(offers.get("price"))
                    availability = str(offers.get("availability", "")).lower()
                    if price is not None:
                        return price, "instock" in availability or "preorder" in availability
        except (json.JSONDecodeError, TypeError):
            pass

    price_selectors = ["[itemprop='price']", "meta[property='product:price:amount']", "[class*='price']", "[class*='Price']", "[data-price]"]
    for selector in price_selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
        price = parse_price_value(raw)
        if price is not None and 200 <= price <= 4500:
            stock_text = soup.get_text(" ", strip=True).lower()
            stock = not any(x in stock_text for x in ["esgotado", "out of stock", "indisponível"])
            return price, stock
    return None, None


async def extrair_grelha_categoria(page: Page, cat_config: dict, limit: int = 30) -> list[dict]:
    loja = cat_config["loja"]
    url = cat_config["url"]
    produtos: list[dict] = []
    timeout_ms = int(cat_config.get("timeout_ms", 45000))

    try:
        response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        status_code = response.status if response else "N/A"
        page_title = await page.title()
        print(f"   [Debug {loja}] Status: {status_code} | Título: '{page_title}'")
        if status_code in [403, 429] or "just a moment" in page_title.lower():
            print(f"   ⚠️ {loja} bloqueada ou requer CAPTCHA.")
            return []
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            print(f"   ⚠️ {loja}: networkidle não atingido; continuo com o conteúdo disponível.")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        await page.wait_for_timeout(int(cat_config.get("scroll_wait_ms", 2500)))
    except PlaywrightTimeout:
        print(f"   ⚠️ Timeout em {loja}; a extrair o que carregou até agora...")
    except Exception as e:
        print(f"   ❌ Erro de navegação em {loja}: {e}")
        return []

    soup = BeautifulSoup(await page.content(), "html.parser")
    selectors = cat_config.get("card_selectors") or [
        "article", "div[class*='product-card']", "div[class*='productCard']",
        "div[class*='product-item']", "div[class*='ProductItem']",
        "div[data-name='product']", "li[class*='product']"
    ]
    cards = soup.select(", ".join(selectors))

    if not cards:
        for tag in soup.find_all(["div", "li"]):
            txt = tag.get_text(" ", strip=True)
            if 20 < len(txt) < 500 and tag.find("a") and re.search(r"\d{2,4}[.,]\d{2}\s?€?", txt):
                cards.append(tag)

    for card in cards:
        if len(produtos) >= limit:
            break
        title_node = card.select_one("h1, h2, h3, h4, [class*='title'], [class*='name'], a[title]")
        title = ""
        if title_node:
            title = title_node.get("title") or title_node.get_text(" ", strip=True)
        if not title or len(title) < 10:
            continue

        price = None
        price_selectors = cat_config.get("price_selectors") or [
            "[itemprop='price']", "[class*='price']", ".price", "span[class*='Price']"
        ]
        for selector in price_selectors:
            node = card.select_one(selector)
            if node:
                raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
                price = parse_price_value(raw)
                if price is not None and 200 <= price <= 4500:
                    break
        if price is None:
            match_p = re.search(r"(\d{2,4}[.,]\d{2})\s?€?", card.get_text(" ", strip=True))
            if match_p:
                price = parse_price_value(match_p.group(1))
        if price is None or price < 200 or price > 4500:
            continue

        link_node = card.select_one("a[href]")
        link = urljoin(url, link_node["href"]) if link_node else url
        card_text = card.get_text(" ", strip=True).lower()
        stock = not any(x in card_text for x in ["esgotado", "out of stock", "indisponível"])
        produtos.append({"loja": loja, "titulo": title.strip(), "preco": price, "url": link, "stock": stock})

    return list({f"{p['loja']}::{p['titulo']}": p for p in produtos}.values())


def extrair_teclado_do_html(html: str) -> str:
    texto = normalizar_texto(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    if any(x in texto for x in TECLADO_NAO_PT):
        return "nao_pt"
    if any(x in texto for x in TECLADO_PT_CONFIRMADO):
        return "confirmado"
    return "desconhecido"


async def confirmar_teclado_produto(page: Page, url: str) -> str:
    try:
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if response and response.status >= 400:
            return "desconhecido"
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeout:
            pass
        return extrair_teclado_do_html(await page.content())
    except Exception:
        return "desconhecido"


def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC:
        print("⚠️ NTFY_TOPIC não definido.")
        return
    try:
        payload = {
            "topic": NTFY_TOPIC,
            "title": titulo,
            "message": mensagem,
            "tags": [t.strip() for t in tags.split(",")],
            "priority": 4 if prioridade == "high" else 3,
        }
        res = requests.post("https://ntfy.sh", json=payload, timeout=15)
        res.raise_for_status()
        print(f"📲 Notificação enviada! ({titulo})")
    except Exception as e:
        print(f"❌ Erro ao enviar JSON para o ntfy: {e}")


async def main() -> None:
    print("🚀 A iniciar Rastreador V5 — marcas + CHIP7 + teclado PT...")
    config = carregar_json(CONFIG_PATH)
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})
    settings = config.get("settings", {})
    weights = config.get("weights", {})
    min_value = settings.get("min_value_score_alerta", 45.0)
    budget_hard = settings.get("budget_hard", 1500.0)
    require_pt_keyboard = bool(settings.get("require_pt_keyboard", True))
    alertas, analisados = 0, 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT",
        )

        for cat in config.get("category_urls", []):
            loja = cat["loja"]
            print(f"\n🔍 A varrer categoria: {loja}...")
            page = await context.new_page()
            produtos = await extrair_grelha_categoria(page, cat, limit=settings.get("max_produtos_por_categoria", 30))
            await page.close()
            print(f"   => Encontrados {len(produtos)} itens na grelha da {loja}.")

            for item in produtos:
                if not verificar_elegibilidade(item["titulo"]) or item["preco"] > budget_hard:
                    continue

                specs = extrair_specs_avancadas(item["titulo"])
                analisados += 1

                if require_pt_keyboard and specs["teclado_pt"] == "desconhecido":
                    detail_page = await context.new_page()
                    detected_keyboard = await confirmar_teclado_produto(detail_page, item["url"])
                    await detail_page.close()
                    specs["teclado_pt"] = detected_keyboard
                    if detected_keyboard == "confirmado":
                        specs["fontes"]["teclado"] = "pagina_produto"
                        specs["alertas"] = [a for a in specs["alertas"] if a != "Teclado PT não confirmado"]
                    elif detected_keyboard == "nao_pt":
                        specs["fontes"]["teclado"] = "pagina_produto"
                        if "Teclado não é PT" not in specs["alertas"]:
                            specs["alertas"].append("Teclado não é PT")

                av = calcular_scores(specs, item["preco"], weights)
                if av.get("status") == "REJEITADO":
                    print(f"   [-] {item['titulo'][:55]}... | REJEITADO: {av.get('alertas')}")
                    continue

                key = f"{item['loja']}::{item['titulo']}"
                entries = history["offers"].setdefault(key, [])
                prev = entries[-1] if entries else None
                entries.append({
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "price": item["preco"], "stock": item["stock"],
                    "score_final": av["score_final"], "score_ranking": av["score_ranking"],
                    "value_score": av["value_score"], "qualidade_dados": av["qualidade_dados"],
                    "teclado_pt": specs["teclado_pt"], "marca": specs.get("marca"),
                    "submarca": specs.get("submarca"),
                })
                history["offers"][key] = entries[-60:]

                print(
                    f"   [+] {item['titulo'][:45]}... | {item['preco']:.2f}€ | "
                    f"Rank: {av['score_ranking']} | Value: {av['value_score']} | Dados: {av['qualidade_dados']}"
                )

                e_oport = av["value_score"] >= min_value
                baixou = bool(prev and prev["price"] - item["preco"] > 5.0)
                if (e_oport or baixou) and item["stock"]:
                    alertas += 1
                    prefixo = "🌟 OPORTUNIDADE" if e_oport else "📉 QUEDA PREÇO"
                    msg = (
                        f"{item['titulo']}\n\nLoja: {item['loja']}\n"
                        f"Preço: {item['preco']:.2f}€\nRank: {av['score_ranking']}/100\n"
                        f"Value: {av['value_score']}\nDados: {av['qualidade_dados']} ({av['confianca_percentual']})\n"
                        f"Teclado: PT confirmado\n🔗 {item['url']}"
                    )
                    enviar_alerta(
                        f"{prefixo}: {item['preco']:.0f}€", msg,
                        prioridade="high",
                        tags="star2" if e_oport else "chart_with_downwards_trend",
                    )

        await browser.close()

    guardar_json(HISTORY_PATH, history)
    enviar_alerta(
        "🔄 Relatório de Rastreio V5",
        f"Rastreio concluído.\nPortáteis considerados: {analisados}\nAlertas: {alertas}",
        "default",
        "white_check_mark",
    )
    print(f"\n✅ Concluído ({analisados} portáteis considerados).")


if __name__ == "__main__":
    asyncio.run(main())
