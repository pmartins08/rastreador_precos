import asyncio
import json
import os
import re
import unicodedata
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

TERMOS_EXCLUSAO = ["recondicionado", "refurbished", "usado", "outlet", "grade a", "grade b", "grade c", "seminovo", "open box"]
MARCAS_ACEITES = {
    "asus": ["rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"],
    "lenovo": ["legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"],
    "hp": ["omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"],
    "acer": ["predator", "nitro", "swift", "aspire", "travelmate"],
    "msi": ["raider", "vector", "stealth", "crosshair", "katana", "prestige", "creator"],
    "dell": ["alienware", "g-series", "g15", "g16", "xps", "inspiron", "latitude"],
}
TECLADO_PT = ["teclado portugues", "teclado pt", "teclado pt-pt", "keyboard portugues", "keyboard pt", "keyboard pt-pt", "layout pt", "layout pt-pt", "portuguese keyboard", "portuguese layout", "pt keyboard", "pt-pt"]
TECLADO_NAO_PT = ["teclado espanhol", "keyboard espanhol", "spanish keyboard", "spanish layout", "teclado frances", "keyboard frances", "french keyboard", "french layout", "teclado alemao", "keyboard alemao", "german keyboard", "german layout", "teclado ingles", "keyboard ingles", "english keyboard", "keyboard us", "us keyboard", "us layout", "en-us keyboard", "uk keyboard", "uk layout", "italian keyboard", "italian layout", "swedish keyboard", "swedish layout", "nordic keyboard", "nordic layout", "danish keyboard", "danish layout", "belgian keyboard", "swiss keyboard", "azerty", "qwertz"]
STOCK_NAO = ["esgotado", "fora de stock", "out of stock", "indisponivel", "temporariamente indisponivel", "sem stock", "sem estoque", "unavailable", "not available", "sold out"]
STOCK_SIM = ["em stock", "em estoque", "disponivel", "disponibilidade: disponivel", "available", "in stock", "order now", "adicionar ao carrinho", "adiciona ao carrinho", "add to cart", "em stock online"]
CPU_PATTERNS = [r"core\s+ultra\s+[3579]\s+\d{3,4}[a-z]*", r"core\s+[3579]\s+\d{3,4}[a-z]*", r"i[3579]-\d{4,5}[a-z]*", r"ryzen(?:\s+ai)?\s+[3579]\s+\d{3,4}[a-z]*"]
GPU_MODELOS = ["rtx 5090", "rtx 5080", "rtx 5070 ti", "rtx 5070", "rtx 5060 ti", "rtx 5060", "rtx 5050", "rtx 4090", "rtx 4080", "rtx 4070", "rtx 4060", "rtx 4050"]
GPU_PONTOS = {"rtx 5090": 100, "rtx 5080": 98, "rtx 5070 ti": 97, "rtx 5070": 95, "rtx 5060 ti": 90, "rtx 5060": 85, "rtx 5050": 60, "rtx 4090": 100, "rtx 4080": 98, "rtx 4070": 80, "rtx 4060": 65, "rtx 4050": 45}


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def carregar_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️ Erro ao ler {path.name}: {exc}")
        return {}


def guardar_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def parse_price_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    try:
        if "," in text and "." in text:
            return float(text.replace(".", "").replace(",", ".")) if text.rfind(",") > text.rfind(".") else float(text.replace(",", ""))
        return float(text.replace(",", "."))
    except ValueError:
        return None


def detetar_stock(texto: str) -> Optional[bool]:
    t = normalizar_texto(texto)
    if any(x in t for x in STOCK_NAO):
        return False
    if any(x in t for x in STOCK_SIM):
        return True
    return None


def detetar_marca_submarca(titulo: str) -> tuple[Optional[str], Optional[str]]:
    t = normalizar_texto(titulo)
    for marca, subs in MARCAS_ACEITES.items():
        if re.search(rf"\b{re.escape(marca)}\b", t):
            for sub in subs:
                if re.search(rf"\b{re.escape(sub)}\b", t):
                    return marca, sub
            return marca, None
    return None, None


def verificar_elegibilidade(titulo: str) -> bool:
    t = normalizar_texto(titulo)
    if any(x in t for x in TERMOS_EXCLUSAO):
        return False
    marca, _ = detetar_marca_submarca(t)
    return marca in MARCAS_ACEITES


def limpar_vram(texto: str) -> str:
    texto = re.sub(r"\b(4|6|8|12|16|24)\s?gb\s?(gddr\d|vram)\b", "", texto)
    return re.sub(r"\b(rtx|rx|gtx)\s?\d{4}\s?\d{1,2}gb\b", "", texto)


def extrair_teclado_do_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    texto = normalizar_texto(soup.get_text(" ", strip=True))
    universo = f"{texto} {normalizar_texto(str(soup))}"
    if any(x in universo for x in TECLADO_NAO_PT):
        return "nao_pt"
    if any(x in universo for x in TECLADO_PT):
        return "confirmado"
    return "desconhecido"


def extrair_cpu(texto: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    for pattern in CPU_PATTERNS:
        match = re.search(pattern, texto)
        if not match:
            continue
        cpu = match.group(0)
        tier = "tier_1" if re.search(r"ultra\s+9|core\s+i9|ryzen(?:\s+ai)?\s+9", cpu) else "tier_2" if re.search(r"ultra\s+7|core\s+i7|ryzen(?:\s+ai)?\s+7", cpu) else "tier_3"
        lower = cpu.lower()
        classe = "hx" if "hx" in lower else "hs" if "hs" in lower else "h" if re.search(r"\d+h\b|\bh\b", lower) else "u_ultra" if any(x in lower for x in (" u", " v", " p")) else None
        return cpu, tier, classe
    return None, None, None


def extrair_specs_avancadas(texto_bruto: str) -> dict:
    t = normalizar_texto(texto_bruto)
    tl = limpar_vram(t)
    s = {"marca": None, "submarca": None, "gpu_modelo": None, "gpu_tipo": "desconhecida", "cpu_modelo": None, "cpu_classe": None, "cpu_str_original": None, "ram_gb": None, "ram_expansivel": False, "armazenamento_tb": None, "ssd_expansivel": False, "bateria_wh": None, "peso_kg": None, "ecra_res": None, "ecra_hz": None, "teclado_pt": "desconhecido", "alertas": [], "fontes": {}}
    s["marca"], s["submarca"] = detetar_marca_submarca(t)
    if s["marca"]: s["fontes"]["marca"] = "titulo"
    for gpu in GPU_MODELOS:
        if gpu in t:
            s["gpu_modelo"] = gpu; s["gpu_tipo"] = "dedicada"; s["fontes"]["gpu"] = "modelo_exato"; break
    if not s["gpu_modelo"]:
        if any(x in t for x in ["intel iris", "intel arc graphics", "intel graphics", "intel uhd", "radeon graphics", "radeon 610m", "radeon 680m", "radeon 780m", "radeon 840m", "radeon 890m", "qualcomm adreno"]):
            s["gpu_tipo"] = "integrada"; s["fontes"]["gpu"] = "integrada"
        else: s["alertas"].append("GPU não identificada")
    cpu, tier, classe = extrair_cpu(t)
    if cpu:
        s["cpu_str_original"] = cpu; s["cpu_modelo"] = tier; s["cpu_classe"] = classe; s["fontes"]["cpu"] = "modelo_detetado"
    else: s["alertas"].append("CPU não confirmada")
    m = re.search(r"(\d{1,3})\s?gb\s?(?:ram|ddr[45](?:x)?|memory|so-dimm)\b", tl)
    if m:
        s["ram_gb"] = int(m.group(1)); s["fontes"]["ram"] = "explicita"
    else:
        for raw in re.findall(r"\b(\d{1,3})\s?gb\b", tl):
            v = int(raw)
            if v in [8, 12, 16, 24, 32, 48, 64, 96, 128]:
                s["ram_gb"] = v; s["fontes"]["ram"] = "heuristica"; s["alertas"].append("RAM inferida por heurística"); break
        if s["ram_gb"] is None: s["alertas"].append("RAM desconhecida")
    if any(x in t for x in ["ram expansivel", "so-dimm", "slot ram", "ram upgrade", "upgradable memory", "memoria expansivel"]): s["ram_expansivel"] = True
    for capacity, pattern in [(2.0, r"2\s?tb(?:\s?(?:ssd|nvme|pcie))?"), (1.0, r"1\s?tb(?:\s?(?:ssd|nvme|pcie))?"), (0.5, r"512\s?gb(?:\s?(?:ssd|nvme|pcie))?")]:
        m = re.search(pattern, t)
        if m:
            s["armazenamento_tb"] = capacity; s["fontes"]["armazenamento"] = "explicita" if re.search(r"ssd|nvme|pcie", m.group(0)) else "heuristica"; break
    if s["armazenamento_tb"] is None: s["alertas"].append("Armazenamento não confirmado")
    if any(x in t for x in ["ssd extra", "2x m.2", "2 x m.2", "slot m.2 livre", "segundo ssd", "segundo m.2", "armazenamento expansivel", "armazenamento expansível"]): s["ssd_expansivel"] = True
    m = re.search(r"(\d{2,3})\s?wh\b", t)
    if m: s["bateria_wh"] = int(m.group(1)); s["fontes"]["bateria"] = "texto"
    else: s["alertas"].append("Bateria (Wh) desconhecida")
    m = re.search(r"(\d[\.,]\d+)\s?kg\b", t)
    if m: s["peso_kg"] = float(m.group(1).replace(",", ".")); s["fontes"]["peso"] = "texto"
    else: s["alertas"].append("Peso desconhecido")
    if any(x in t for x in ["qhd+", "2880x1800", "2560x1600", "wqxga", "2.8k"]): s["ecra_res"] = "qhd+"
    elif any(x in t for x in ["qhd", "2560x1440"]): s["ecra_res"] = "qhd"
    elif any(x in t for x in ["1200p", "1920x1200", "wuxga"]): s["ecra_res"] = "fhd+"
    elif any(x in t for x in ["fhd", "1920x1080", "1080p"]): s["ecra_res"] = "fhd"
    else: s["alertas"].append("Resolução do ecrã desconhecida")
    m = re.search(r"(\d{2,3})\s?hz\b", t)
    if m: s["ecra_hz"] = int(m.group(1)); s["fontes"]["ecra_hz"] = "texto"
    else: s["alertas"].append("Frequência do ecrã desconhecida")
    if any(x in t for x in TECLADO_NAO_PT): s["teclado_pt"] = "nao_pt"; s["fontes"]["teclado"] = "texto"; s["alertas"].append("Teclado não é PT")
    elif any(x in t for x in TECLADO_PT): s["teclado_pt"] = "confirmado"; s["fontes"]["teclado"] = "texto"
    else: s["alertas"].append("Teclado PT não confirmado")
    return s


def calcular_qualidade_dados(s: dict) -> tuple[float, str]:
    q = 0.20 * bool(s.get("cpu_modelo")) + 0.20 * (s.get("gpu_tipo") != "desconhecida")
    if s.get("ram_gb"): q += 0.20 if s.get("fontes", {}).get("ram") == "explicita" else 0.14
    for campo, peso in [("bateria_wh", 0.10), ("peso_kg", 0.10), ("ecra_res", 0.10), ("ecra_hz", 0.10)]:
        if s.get(campo) is not None: q += peso
    return q, "ALTA" if q >= 0.85 else "MEDIA" if q >= 0.50 else "BAIXA"


def calcular_tier_oportunidade(value_score: float) -> Optional[str]:
    if value_score >= 100: return "OURO"
    if value_score >= 70: return "PRATA"
    if value_score >= 45: return "BRONZE"
    return None


def calcular_scores(s: dict, preco: float, weights: dict) -> dict:
    if s["teclado_pt"] == "nao_pt": return {"status": "REJEITADO", "alertas": ["Teclado explicitamente não português."]}
    if s["ram_gb"] == 8: return {"status": "REJEITADO", "alertas": ["8GB RAM confirmado - insuficiente."]}
    if s["peso_kg"] and s["peso_kg"] > 2.8: return {"status": "REJEITADO", "alertas": ["Excede limite de peso (>2.8kg)."]}
    ram = s["ram_gb"]; p_ram = 50 if ram is None else 100 if ram >= 32 else 80 if ram >= 16 else 40
    arm = s["armazenamento_tb"]; p_ssd = 50 if arm is None else 100 if arm >= 2 else 85 if arm >= 1 else 65
    p_res = {"qhd+": 100, "qhd": 95, "fhd+": 85, "fhd": 75, None: 60}.get(s["ecra_res"], 60)
    p_hz = min(100, (s.get("ecra_hz") or 60) / 1.65)
    p_cpu = weights.get("cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70}).get(s["cpu_modelo"], 50)
    penal = {"u_ultra": 0, "hs": 5, "h": 10, "hx": 20, None: 10}; auto = 50 if s["bateria_wh"] is None else max(0, min(100, s["bateria_wh"] / 90 * 100) - penal.get(s["cpu_classe"], 10))
    gpu = weights.get("gpu_base", GPU_PONTOS); p_gpu = gpu.get(s["gpu_modelo"], 50) if s["gpu_tipo"] == "dedicada" else 15 if s["gpu_tipo"] == "integrada" else 30
    peso = s.get("peso_kg"); p_peso = 50 if peso is None else 100 if peso <= 1.4 else 0 if peso >= 2.8 else max(0, 100 - (peso - 1.4) * 71.4)
    p_ram_long = 50 if ram is None else 100 if ram >= 32 else 95 if ram == 16 and s["ram_expansivel"] else 75 if ram == 16 else 40
    exp = s["ssd_expansivel"]; p_ssd_long = 50 if arm is None else 100 if arm >= 2 or (arm == 1 and exp) else 85 if arm == 1 else 75 if arm == 0.5 and exp else 65 if arm == 0.5 else 50
    feup = p_ram * .20 + auto * .30 + p_ssd * .15 + p_res * .20 + p_cpu * .15
    gaming = p_gpu * .65 + p_cpu * .20 + p_hz * .10 + p_ram * .05
    longevidade = p_ram_long * .35 + p_ssd_long * .25 + auto * .20 + p_cpu * .20
    final = feup * .50 + gaming * .25 + longevidade * .15 + p_peso * .10
    conf, qualidade = calcular_qualidade_dados(s)
    ranking = round(max(0, min(100, final * (.85 + .15 * conf))), 1)
    value_score = round(ranking / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0
    tier = calcular_tier_oportunidade(value_score)
    alertas = list(dict.fromkeys(s.get("alertas", [])))
    if s["teclado_pt"] == "desconhecido": alertas.append("Teclado PT não confirmado — portátil mantido no ranking.")
    return {"status": "ACEITE", "score_final": round(final, 1), "score_ranking": ranking, "value_score": value_score, "oportunidade": tier, "qualidade_dados": qualidade, "confianca_percentual": f"{int(conf * 100)}%", "fontes_extraidas": s["fontes"], "alertas": list(dict.fromkeys(alertas)), "detalhes": {"marca": s.get("marca"), "submarca": s.get("submarca"), "teclado_pt": s.get("teclado_pt"), "FEUP": round(feup, 1), "Gaming": round(gaming, 1), "Longevidade": round(longevidade, 1), "Portabilidade": round(p_peso, 1)}}


async def confirmar_teclado_produto(page: Page, url: str) -> str:
    try:
        response = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if response and response.status >= 400: return "desconhecido"
        try: await page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeout: pass
        return extrair_teclado_do_html(await page.content())
    except Exception: return "desconhecido"


async def extrair_grelha_categoria(page: Page, cfg: dict, limit: int = 30) -> list[dict]:
    loja, url = cfg["loja"], cfg["url"]
    try:
        response = await page.goto(url, timeout=int(cfg.get("timeout_ms", 45000)), wait_until="domcontentloaded")
        status = response.status if response else "N/A"; title = await page.title(); body_text = normalizar_texto(await page.locator("body").inner_text(timeout=5000))
        print(f"   [Debug {loja}] Status: {status} | Título: '{title}'")
        if status in (401, 403, 429) or "just a moment" in title.lower() or "verify you are human" in body_text or "access denied" in body_text:
            print(f"   ⚠️ {loja} bloqueada ou requer CAPTCHA."); return []
        try: await page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout: print(f"   ⚠️ {loja}: networkidle não atingido; continuo com o conteúdo disponível.")
        for _ in range(int(cfg.get("scroll_passes", 3))):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); await page.wait_for_timeout(int(cfg.get("scroll_wait_ms", 1500)))
    except PlaywrightTimeout: print(f"   ⚠️ Timeout em {loja}; a extrair o que carregou...")
    except Exception as exc: print(f"   ❌ Erro de navegação em {loja}: {exc}"); return []

    soup = BeautifulSoup(await page.content(), "html.parser")
    selectors = cfg.get("card_selectors") or ["article", "li[class*='product']", "div[class*='product-card']", "div[class*='productCard']", "div[class*='product-item']", "[data-product-id]", "[data-testid*='product']"]
    cards = []
    for selector in selectors:
        found = soup.select(selector)
        if len(found) > len(cards): cards = found

    hints = cfg.get("product_path_hints", ["/produto/", "/product/", "/portateis/", "/computadores-portateis/"])
    if not cards:
        for anchor in soup.select("a[href]"):
            if not any(h in anchor.get("href", "").lower() for h in hints): continue
            parent = anchor
            for _ in range(7):
                parent = parent.parent if parent else None
                if not parent: break
                text = parent.get_text(" ", strip=True)
                if 25 <= len(text) <= 1800 and re.search(r"\d{2,4}(?:[.,]\d{2})\s*€", text): cards.append(parent); break

    result, seen = [], set()
    for card in cards:
        if len(result) >= limit: break
        node = card.select_one("h1,h2,h3,h4,[class*='title'],[class*='Title'],[class*='name'],[class*='Name'],a[title],img[alt]")
        title = (node.get("alt") or node.get("title") or node.get_text(" ", strip=True)) if node else ""
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 10 or title in seen: continue

        price = None
        for selector in cfg.get("price_selectors") or ["[itemprop='price']", "meta[property='product:price:amount']", "[class*='price']", "[class*='Price']", "[data-price]"]:
            node = card.select_one(selector)
            if not node: continue
            raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            price = parse_price_value(raw)
            if price is not None and 200 <= price <= 4500: break
        if price is None:
            m = re.search(r"(\d{2,4}(?:[.,]\d{2}))\s*€", card.get_text(" ", strip=True)); price = parse_price_value(m.group(1)) if m else None
        if price is None or not 200 <= price <= 4500: continue
        anchor = card.select_one("a[href]"); link = urljoin(url, anchor["href"]) if anchor else url
        result.append({"loja": loja, "titulo": title, "preco": price, "url": link, "stock": detetar_stock(card.get_text(" ", strip=True))}); seen.add(title)
    return result


def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC:
        print("⚠️ NTFY_TOPIC não definido; notificação ignorada."); return
    try:
        requests.post("https://ntfy.sh", json={"topic": NTFY_TOPIC, "title": titulo, "message": mensagem, "tags": [t.strip() for t in tags.split(",")], "priority": 4 if prioridade == "high" else 3}, timeout=15).raise_for_status()
        print(f"📲 Notificação enviada: {titulo}")
    except Exception as exc: print(f"❌ Erro ao enviar ntfy: {exc}")


def deve_alertar(prev: Optional[dict], atual: dict) -> tuple[bool, str]:
    tier = atual.get("oportunidade")
    if tier is None: return False, ""
    if prev is None: return True, f"nova oportunidade {tier.lower()}"
    old_price = prev.get("price"); old_tier = prev.get("oportunidade")
    if isinstance(old_price, (int, float)) and atual["preco"] < old_price - 5: return True, "queda de preço"
    if tier != old_tier: return True, f"escalou para {tier.lower()}"
    return False, ""


async def main() -> None:
    print("🚀 A iniciar Rastreador — multi-loja + ranking 0–100 + alertas Ouro/Prata/Bronze...")
    config = carregar_json(CONFIG_PATH); history = carregar_json(HISTORY_PATH); history.setdefault("offers", {})
    settings = config.get("settings", {}); weights = config.get("weights", {}); budget_hard = float(settings.get("budget_hard", 1500.0)); max_products = int(settings.get("max_produtos_por_categoria", 30))
    stats = {"lojas": 0, "lojas_com_produtos": 0, "lojas_sem_resultados": 0, "bloqueadas": 0, "encontrados": 0, "analisados": 0, "aceites": 0, "rejeitados": 0, "alertas": 0, "ouro": 0, "prata": 0, "bronze": 0}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36", viewport={"width": 1920, "height": 1080}, locale="pt-PT")
        for category in config.get("category_urls", []):
            loja = category["loja"]; stats["lojas"] += 1; print(f"\n🔍 A varrer categoria: {loja}...")
            page = await context.new_page(); products = await extrair_grelha_categoria(page, category, limit=max_products); await page.close()
            print(f"   => Encontrados {len(products)} itens na grelha da {loja}."); stats["encontrados"] += len(products)
            if products: stats["lojas_com_produtos"] += 1
            else: stats["lojas_sem_resultados"] += 1
            for item in products:
                if item["preco"] > budget_hard or not verificar_elegibilidade(item["titulo"]): continue
                specs = extrair_specs_avancadas(item["titulo"]); stats["analisados"] += 1
                if specs["teclado_pt"] == "desconhecido":
                    detail = await context.new_page(); detected = await confirmar_teclado_produto(detail, item["url"]); await detail.close(); specs["teclado_pt"] = detected
                    if detected != "desconhecido": specs["fontes"]["teclado"] = "pagina_produto"
                    if detected == "confirmado": specs["alertas"] = [a for a in specs["alertas"] if a != "Teclado PT não confirmado"]
                    elif detected == "nao_pt" and "Teclado não é PT" not in specs["alertas"]: specs["alertas"].append("Teclado não é PT")
                analysis = calcular_scores(specs, item["preco"], weights)
                if analysis["status"] == "REJEITADO": stats["rejeitados"] += 1; print(f"   [-] {item['titulo'][:60]}... | REJEITADO: {analysis['alertas']}"); continue
                stats["aceites"] += 1; tier = analysis.get("oportunidade")
                if tier == "OURO": stats["ouro"] += 1
                elif tier == "PRATA": stats["prata"] += 1
                elif tier == "BRONZE": stats["bronze"] += 1
                key = f"{loja}::{item['titulo']}"; entries = history["offers"].setdefault(key, []); prev = entries[-1] if entries else None
                record = {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "price": item["preco"], "stock": item["stock"], "score_final": analysis["score_final"], "score_ranking": analysis["score_ranking"], "value_score": analysis["value_score"], "oportunidade": tier, "qualidade_dados": analysis["qualidade_dados"], "teclado_pt": specs["teclado_pt"], "marca": specs.get("marca"), "submarca": specs.get("submarca")}
                entries.append(record); history["offers"][key] = entries[-60:]
                stock_label = "stock confirmado" if item["stock"] is True else "stock desconhecido" if item["stock"] is None else "ESGOTADO"; tier_label = f" | {tier}" if tier else ""
                print(f"   [+] {item['titulo'][:48]}... | {item['preco']:.2f}€ | Ranking: {analysis['score_ranking']}/100 | Valor: {analysis['value_score']}{tier_label} | Dados: {analysis['qualidade_dados']} | {stock_label}")
                should_alert, reason = deve_alertar(prev, {"preco": item["preco"], **analysis})
                if should_alert and item["stock"] is not False:
                    stats["alertas"] += 1
                    tag = "trophy" if tier == "OURO" else "medal_sports" if tier == "PRATA" else "medal"
                    title = f"🥇 OURO | {item['preco']:.0f}€" if tier == "OURO" else f"🥈 PRATA | {item['preco']:.0f}€" if tier == "PRATA" else f"🥉 BRONZE | {item['preco']:.0f}€"
                    msg = (f"{item['titulo']}\n\nLoja: {loja}\nPreço: {item['preco']:.2f}€\nRanking: {analysis['score_ranking']}/100\nÍndice de valor: {analysis['value_score']}\nOportunidade: {tier}\nDados: {analysis['qualidade_dados']} ({analysis['confianca_percentual']})\nTeclado: {specs['teclado_pt']}\nMotivo: {reason}\n🔗 {item['url']}")
                    enviar_alerta(title, msg, "high" if tier == "OURO" else "default", tag)
        await browser.close()

    guardar_json(HISTORY_PATH, history)
    resumo = ("📊 Resumo da run\n" f"Lojas: {stats['lojas']}\n" f"Lojas com resultados: {stats['lojas_com_produtos']}\n" f"Lojas sem resultados/bloqueadas: {stats['lojas_sem_resultados']}\n" f"Produtos encontrados: {stats['encontrados']}\n" f"Produtos analisados: {stats['analisados']}\n" f"Aceites: {stats['aceites']}\n" f"Rejeitados: {stats['rejeitados']}\n" f"🥇 Ouro: {stats['ouro']}\n" f"🥈 Prata: {stats['prata']}\n" f"🥉 Bronze: {stats['bronze']}\n" f"Alertas enviados: {stats['alertas']}")
    print("\n" + resumo); enviar_alerta("🔄 Relatório de Rastreio", resumo, "default", "bar_chart")


if __name__ == "__main__":
    asyncio.run(main())
