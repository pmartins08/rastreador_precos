import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "products.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

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
        else: specs["alertas"].append("GPU não identificada")

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
    else: specs["alertas"].append("CPU não confirmada")

    match_ram_exp = re.search(r'(\d{2,3})\s?gb\s?(ram|ddr[45]|memory|so-dimm)\b', texto_limpo)
    if match_ram_exp:
        specs["ram_gb"], specs["fontes"]["ram"] = int(match_ram_exp.group(1)), "explicita"
    else:
        match_ram_heur = re.search(r'\b(\d{2,3})\s?gb\b', texto_limpo)
        if match_ram_heur and int(match_ram_heur.group(1)) in [8, 16, 24, 32, 48, 64]:
            specs["ram_gb"], specs["fontes"]["ram"] = int(match_ram_heur.group(1)), "heuristica"
            specs["alertas"].append("RAM inferida por heurística")
        else: specs["alertas"].append("RAM desconhecida")
            
    if any(x in texto for x in ["ram expansivel", "so-dimm", "slot ram", "upgradable memory"]):
        specs["ram_expansivel"], specs["fontes"]["ram_expansivel"] = True, "texto_explicito"

    if re.search(r'2\s?tb\s?(ssd|nvme|pcie)', texto): specs["armazenamento_tb"], specs["fontes"]["armazenamento"] = 2.0, "explicita"
    elif re.search(r'2\s?tb', texto): specs["armazenamento_tb"], specs["fontes"]["armazenamento"] = 2.0, "heuristica"
    elif re.search(r'1\s?tb\s?(ssd|nvme|pcie)', texto): specs["armazenamento_tb"], specs["fontes"]["armazenamento"] = 1.0, "explicita"
    elif re.search(r'1\s?tb', texto): specs["armazenamento_tb"], specs["fontes"]["armazenamento"] = 1.0, "heuristica"
    elif re.search(r'512\s?gb\s?(ssd|nvme|pcie)', texto): specs["armazenamento_tb"], specs["fontes"]["armazenamento"] = 0.5, "explicita"
    elif re.search(r'512\s?gb', texto): specs["armazenamento_tb"], specs["fontes"]["armazenamento"] = 0.5, "heuristica"
    else: specs["alertas"].append("Armazenamento não confirmado")

    if any(x in texto for x in ["ssd extra", "2x m.2", "slot m.2 livre", "armazenamento expansivel"]):
        specs["ssd_expansivel"], specs["fontes"]["ssd_expansivel"] = True, "texto_explicito"

    match_bat = re.search(r'(\d{2,3})\s?wh', texto)
    if match_bat: specs["bateria_wh"], specs["fontes"]["bateria"] = int(match_bat.group(1)), "wh_detetado"
    else: specs["alertas"].append("Bateria (Wh) desconhecida")

    match_peso = re.search(r'(\d[\.,]\d+)\s?kg', texto)
    if match_peso: specs["peso_kg"], specs["fontes"]["peso"] = float(match_peso.group(1).replace(',', '.')), "kg_detetado"
    else: specs["alertas"].append("Peso desconhecido")

    if any(x in texto for x in ["qhd+", "2560x1600", "wqxga"]): specs["ecra_res"], specs["fontes"]["ecra_res"] = "qhd+", "resolucao_detetada"
    elif any(x in texto for x in ["qhd", "2560x1440"]): specs["ecra_res"], specs["fontes"]["ecra_res"] = "qhd", "resolucao_detetada"
    elif any(x in texto for x in ["1200p", "1920x1200", "wuxga", "16:10"]): specs["ecra_res"], specs["fontes"]["ecra_res"] = "fhd+", "resolucao_detetada"
    elif any(x in texto for x in ["fhd", "1920x1080", "1080p"]): specs["ecra_res"], specs["fontes"]["ecra_res"] = "fhd", "resolucao_detetada"

    match_hz = re.search(r'(\d{2,3})\s?hz', texto)
    if match_hz: specs["ecra_hz"], specs["fontes"]["ecra_hz"] = int(match_hz.group(1)), "hz_detetado"

    return specs

def calcular_qualidade_dados(specs: dict) -> tuple:
    score_confianca = 0
    if specs.get("cpu_modelo"): score_confianca += 0.20
    if specs.get("gpu_tipo") != "desconhecida": score_confianca += 0.20
    if specs.get("ram_gb"): score_confianca += 0.20 if specs["fontes"].get("ram") == "explicita" else 0.14
    if specs.get("bateria_wh"): score_confianca += 0.10
    if specs.get("peso_kg"): score_confianca += 0.10
    if specs.get("ecra_res"): score_confianca += 0.10
    if specs.get("ecra_hz"): score_confianca += 0.10
    
    if score_confianca >= 0.85: qualidade = "ALTA"
    elif score_confianca >= 0.50: qualidade = "MEDIA"
    else: qualidade = "BAIXA"
    return score_confianca, qualidade

def calcular_scores(specs: dict, preco: float) -> dict:
    if specs.get("ram_gb") is not None and specs["ram_gb"] <= 8:
        return {"status": "REJEITADO", "alertas": [f"{specs['ram_gb']}GB RAM Confirmado - Insuficiente"]}
    if specs.get("peso_kg") is not None and specs["peso_kg"] > 2.8:
        return {"status": "REJEITADO", "alertas": ["Excede limite de peso (>2.8kg)"]}

    p_ram = 100 if specs["ram_gb"] and specs["ram_gb"] >= 32 else (80 if specs["ram_gb"] and specs["ram_gb"] >= 16 else (40 if specs["ram_gb"] else 50))
    p_ssd = 100 if specs["armazenamento_tb"] and specs["armazenamento_tb"] >= 2.0 else (85 if specs["armazenamento_tb"] and specs["armazenamento_tb"] >= 1.0 else (65 if specs["armazenamento_tb"] else 50))
    
    p_ecra_res = {"qhd+": 100, "qhd": 95, "fhd+": 85, "fhd": 75, None: 60}.get(specs["ecra_res"], 60)
    p_ecra_hz = min(100, (specs.get("ecra_hz") or 60) / 1.65)
    p_cpu = {"tier_1": 100, "tier_2": 85, "tier_3": 70, None: 50}.get(specs["cpu_modelo"], 50)
    
    penalizacao_consumo = {"u_ultra": 0, "hs": 5, "h": 10, "hx": 20, None: 10}
    score_autonomia = 50 if specs["bateria_wh"] is None else max(0, min(100, (specs["bateria_wh"] / 90) * 100) - penalizacao_consumo.get(specs["cpu_classe"], 10))

    tabela_gpu = {"rtx 5070": 95, "rtx 4080": 100, "rtx 5060": 85, "rtx 4070": 80, "rtx 4060": 65, "rtx 5050": 60, "rtx 4050": 45}
    if specs["gpu_tipo"] == "dedicada": p_gpu = tabela_gpu.get(specs["gpu_modelo"], 50)
    elif specs["gpu_tipo"] == "integrada": p_gpu = 15
    else: p_gpu = 30 

    peso = specs.get("peso_kg")
    p_peso = 50 if peso is None else (100 if peso <= 1.4 else (0 if peso >= 2.8 else max(0, 100 - ((peso - 1.4) * 71.4))))

    if specs["ram_gb"] is None: p_ram_long = 50
    elif specs["ram_gb"] >= 32: p_ram_long = 100
    elif specs["ram_gb"] == 16 and specs["ram_expansivel"]: p_ram_long = 95
    elif specs["ram_gb"] == 16: p_ram_long = 75
    else: p_ram_long = 40
    
    arm, exp = specs.get("armazenamento_tb"), specs.get("ssd_expansivel")
    if arm is None: p_ssd_long = 50
    elif arm >= 2.0 or (arm == 1.0 and exp): p_ssd_long = 100
    elif arm == 1.0: p_ssd_long = 85
    elif arm == 0.5 and exp: p_ssd_long = 75
    elif arm == 0.5: p_ssd_long = 65
    else: p_ssd_long = 50

    score_feup = (p_ram * 0.20) + (score_autonomia * 0.30) + (p_ssd * 0.15) + (p_ecra_res * 0.20) + (p_cpu * 0.15)
    score_gaming = (p_gpu * 0.65) + (p_cpu * 0.20) + (p_ecra_hz * 0.10) + (p_ram * 0.05)
    score_longevidade = (p_ram_long * 0.35) + (p_ssd_long * 0.25) + (score_autonomia * 0.20) + (p_cpu * 0.20)
    score_final = (score_feup * 0.50) + (score_gaming * 0.25) + (score_longevidade * 0.15) + (p_peso * 0.10)
    
    conf_valor, qualidade = calcular_qualidade_dados(specs)
    score_ranking = round(score_final * (0.85 + 0.15 * conf_valor), 1)
    value_score = round(score_ranking / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0

    return {
        "status": "ACEITE",
        "score_final": round(score_final, 1),
        "value_score": value_score,
        "qualidade_dados": qualidade,
        "alertas": specs["alertas"]
    }


# ==========================================
# UTILITÁRIOS ORIGINAIS (I/O, Parse, HTML)
# ==========================================

def carregar_json(path: Path) -> dict:
    if not path.exists(): return {}
    with path.open("r", encoding="utf-8") as f: return json.load(f)

def guardar_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)

def parse_price_value(value: Any) -> Optional[float]:
    if value is None: return None
    if isinstance(value, (int, float)): return float(value)
    text = str(value).strip().replace("€", "").replace(" ", "")
    if not text: return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."): return float(text.replace(".", "").replace(",", "."))
            return float(text.replace(",", ""))
        if "," in text: return float(text.replace(".", "").replace(",", "."))
        return float(text)
    except ValueError: return None

def availability_to_bool(value: Any) -> Optional[bool]:
    if value is None: return None
    text = str(value).lower()
    positive = ["instock", "in stock", "available", "disponivel", "disponível"]
    negative = ["outofstock", "out of stock", "soldout", "sold out", "indisponivel", "indisponível", "esgotado"]
    if any(x in text for x in positive): return True
    if any(x in text for x in negative): return False
    return None

def _walk_jsonld(obj: Any, result: dict) -> None:
    if isinstance(obj, dict):
        obj_type = obj.get("@type")
        types = set(str(x).lower() for x in obj_type) if isinstance(obj_type, list) else ({str(obj_type).lower()} if obj_type else set())

        if "offer" in types or "aggregateoffer" in types or "product" in types:
            if result["price"] is None and obj.get("price") is not None: result["price"] = parse_price_value(obj.get("price"))
            if result["stock"] is None and obj.get("availability") is not None: result["stock"] = availability_to_bool(obj.get("availability"))

        for key in ("offers", "itemOffered", "item", "mainEntity"):
            if key in obj: _walk_jsonld(obj[key], result)
        for value in obj.values():
            if isinstance(value, (dict, list)): _walk_jsonld(value, result)
    elif isinstance(obj, list):
        for item in obj: _walk_jsonld(item, result)

def extrair_preco_e_stock(html_content: str) -> tuple[Optional[float], Optional[bool]]:
    soup = BeautifulSoup(html_content, "html.parser")
    result = {"price": None, "stock": None}

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw: continue
        try:
            _walk_jsonld(json.loads(raw), result)
            if result["price"] is not None and result["stock"] is not None: return result["price"], result["stock"]
        except (json.JSONDecodeError, TypeError): continue

    if result["price"] is None:
        for attrs in [{"itemprop": "price"}, {"property": "product:price:amount"}, {"name": "price"}]:
            node = soup.find("meta", attrs)
            if node and node.get("content"):
                result["price"] = parse_price_value(node.get("content"))
                if result["price"] is not None: break

    if result["stock"] is None:
        for attrs in [{"itemprop": "availability"}, {"property": "product:availability"}]:
            node = soup.find("meta", attrs)
            if node and node.get("content"):
                result["stock"] = availability_to_bool(node.get("content"))
                if result["stock"] is not None: break

    if result["price"] is None:
        matches = re.findall(r"(?:€\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})|\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d{3,5}(?:,\d{2}))\s*€?", html_content)
        valid = [p for p in (parse_price_value(m) for m in matches) if p is not None and 300 <= p <= 4000]
        if valid: result["price"] = min(valid)

    if result["stock"] is None:
        text = soup.get_text(" ", strip=True).lower()
        if any(x in text for x in ["esgotado", "indisponível", "out of stock", "sem stock"]): result["stock"] = False
        elif any(x in text for x in ["em stock", "adicionar", "comprar", "available"]): result["stock"] = True
        elif result["price"] is not None: result["stock"] = True

    return result["price"], result["stock"]

def calcular_categoria(preco: float, rules: dict) -> tuple[str, str, str]:
    if preco <= rules.get("excellent_max", 0): return "COMPRA_EXCELENTE", "high", "star"
    if preco <= rules.get("very_good_max", 0): return "COMPRA_MUITO_BOA", "high", "white_check_mark"
    if preco <= rules.get("acceptable_max", 0): return "PRECO_ACEITAVEL", "default", "information_source"
    if preco <= rules.get("wait_max", 0): return "ESPERAR", "default", "hourglass_flowing_sand"
    return "EVITAR", "low", "warning"

def get_recent_prices(entries: list[dict], days: int = 30) -> list[float]:
    now = datetime.now(timezone.utc)
    result = []
    for entry in entries:
        try:
            dt = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if (now - dt).days <= days and entry.get("price") is not None: result.append(float(entry["price"]))
        except (KeyError, ValueError, TypeError): continue
    return result

def analisar_historico(entries: list[dict], preco_atual: float) -> dict:
    prices_30 = get_recent_prices(entries, 30)
    all_prices = [float(e["price"]) for e in entries if e.get("price") is not None]
    base = prices_30 or all_prices
    return {
        "media_30d": round(sum(base) / len(base), 2) if base else None,
        "min_30d": round(min(prices_30), 2) if prices_30 else None,
        "min_historico": round(min(all_prices), 2) if all_prices else None,
    }

def should_alert(previous: Optional[dict], current: dict) -> bool:
    if previous is None: return current["stock"] is True and current["category"] in {"COMPRA_EXCELENTE", "COMPRA_MUITO_BOA"}
    if previous.get("stock") is False and current["stock"] is True: return True
    if previous.get("price") is not None and current["price"] < previous["price"] - 1.0: return True
    if previous.get("category") != current["category"]: return True
    return False

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
# FLUXO ASSÍNCRONO COM PLAYWRIGHT E MOTOR V1
# ==========================================

async def consultar_oferta(page: Page, oferta: dict) -> tuple[Optional[float], Optional[bool], str, str]:
    try:
        await page.goto(oferta["url"], timeout=40000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception: pass
    
    try:
        html = await page.content()
        title = (await page.title()).lower()
    except Exception:
        return None, None, "DOM_ERROR", ""

    if "404" in title or "not found" in title: return None, None, "NOT_FOUND", ""
    if "just a moment" in title or "um momento" in title: return None, None, "BLOCKED", ""

    price, stock = extrair_preco_e_stock(html)
    return price, stock, "OK", title

async def processar_produto(context: BrowserContext, sem: asyncio.Semaphore, product: dict, offer: dict, rules: dict, history: dict) -> int:
    key = f"{product['product_id']}::{offer['loja']}"
    
    async with sem:
        page = await context.new_page()
        price, stock, status, page_title = await consultar_oferta(page, offer)
        await page.close()

    if status != "OK" or price is None:
        print(f"   => ❌ Falha: {product['nome']} ({offer['loja']}) - Status: {status}")
        return 0

    # -------- INJEÇÃO DO MOTOR V1 --------
    texto_analise = f"{product.get('nome', '')} {page_title}"
    
    if not verificar_elegibilidade(texto_analise):
        print(f"   => ⚠️ Rejeitado (Não elegível): {product['nome']} ({offer['loja']})")
        return 0

    specs = extrair_specs_avancadas(texto_analise)
    avaliacao = calcular_scores(specs, price)

    if avaliacao["status"] == "REJEITADO":
        print(f"   => ⚠️ Rejeitado ({avaliacao['alertas'][0]}): {product['nome']} ({offer['loja']})")
        return 0
    # ---------------------------------------

    entries = history["offers"].setdefault(key, [])
    previous = entries[-1] if entries else None
    category, priority, tag = calcular_categoria(price, rules)
    metrics = analisar_historico(entries, price)

    current = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "price": round(price, 2),
        "stock": stock,
        "category": category,
        "score_final": avaliacao["score_final"],
        "value_score": avaliacao["value_score"]
    }
    entries.append(current)
    history["offers"][key] = entries[-180:]

    print(f"   => ✅ Lido: {product['nome']} ({offer['loja']}) | {price:.2f} € | Score: {avaliacao['score_final']} | Value: {avaliacao['value_score']}")

    if should_alert(previous, current) and stock is not False:
        msg = (f"{product['nome']} — {offer['loja']}\n\n💶 Preço: {price:.2f} €\n"
               f"📦 Stock: {'🟢 Em stock' if stock else '🔴 Indisponível'}\n"
               f"🏷️ Classificação: {category.replace('_', ' ')}\n\n"
               f"🏆 Score Final: {avaliacao['score_final']} / 100\n"
               f"💎 Value Score: {avaliacao['value_score']}\n")
        
        if metrics.get("media_30d"): msg += f"\n📊 Média 30d: {metrics['media_30d']:.2f} €"
        if metrics.get("min_historico"): msg += f"\n📉 Mín. Histórico: {metrics['min_historico']:.2f} €"
        
        if avaliacao["alertas"]:
            msg += f"\n\n⚠️ Alertas Deteção:\n- " + "\n- ".join(avaliacao["alertas"])
            
        msg += f"\n\n🔗 {offer['url']}"
        enviar_alerta(f"{category.replace('_', ' ')} — {price:.0f} EUR", msg, priority, f"{tag},computer")
        return 1
    return 0

async def main() -> None:
    print("🚀 A iniciar Rastreador V2 (Concorrente + Algoritmo V1)...")
    config = carregar_json(CONFIG_PATH)
    if not config: return
        
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})
    rules = config.get("alert_rules", {})

    total_ofertas = sum(len(p.get("offers", [])) for p in config.get("products", []))
    sem = asyncio.Semaphore(5)

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT"
        )

        tasks = [processar_produto(context, sem, product, offer, rules, history) 
                 for product in config.get("products", []) 
                 for offer in product.get("offers", [])]
        
        resultados = await asyncio.gather(*tasks)
        alertas_disparados = sum(resultados)
        await browser.close()

    if alertas_disparados == 0 and total_ofertas > 0:
        enviar_alerta("Rastreio Concluído", f"✅ {total_ofertas} ofertas verificadas.\nSem novas descidas de preço ou alterações de stock.", "min", "mag")
        print("   => ℹ️ Heartbeat enviado (Nenhuma alteração detetada).")

    guardar_json(HISTORY_PATH, history)
    print("\n✅ Rastreamento concluído.")

if __name__ == "__main__":
    asyncio.run(main())
