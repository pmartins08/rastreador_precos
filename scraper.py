import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

TERMOS_EXCLUSAO = [
    "recondicionado", "refurbished", "usado", "outlet", "grade a", "grade b",
    "grade c", "seminovo", "open box",
]

MARCAS_ACEITES = {
    "asus": ["rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"],
    "lenovo": ["legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"],
    "hp": ["omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"],
    "acer": ["predator", "nitro", "swift", "aspire", "travelmate"],
    "msi": ["raider", "vector", "stealth", "crosshair", "katana", "prestige", "creator"],
    "dell": ["alienware", "g-series", "g15", "g16", "xps", "inspiron", "latitude"],
}

TECLADO_PT = [
    "teclado portugues", "teclado pt", "teclado pt-pt", "keyboard portugues",
    "keyboard pt", "keyboard pt-pt", "layout pt", "layout pt-pt",
    "portuguese keyboard", "portuguese layout", "pt keyboard", "pt-pt",
]
TECLADO_NAO_PT = [
    "teclado espanhol", "keyboard espanhol", "spanish keyboard", "spanish layout",
    "teclado frances", "keyboard frances", "french keyboard", "french layout",
    "teclado alemao", "keyboard alemao", "german keyboard", "german layout",
    "teclado ingles", "keyboard ingles", "english keyboard", "keyboard us",
    "us keyboard", "us layout", "en-us keyboard", "uk keyboard", "uk layout",
    "italian keyboard", "italian layout", "swedish keyboard", "swedish layout",
    "nordic keyboard", "nordic layout", "danish keyboard", "danish layout",
    "belgian keyboard", "belgian layout", "swiss keyboard", "swiss layout",
    "azerty", "qwertz",
]

STOCK_NAO = [
    "esgotado", "fora de stock", "out of stock", "indisponivel",
    "temporariamente indisponivel", "sem stock", "sem estoque", "unavailable",
    "not available", "sold out",
]
STOCK_SIM = [
    "em stock", "em estoque", "disponivel", "disponibilidade: disponivel",
    "available", "in stock", "order now", "adicionar ao carrinho",
    "adiciona ao carrinho", "add to cart", "em stock online",
]

CPU_PATTERNS = [
    r"core\s+ultra\s+[3579]\s+\d{3,4}[a-z]*",
    r"core\s+[3579]\s+\d{3,4}[a-z]*",
    r"i[3579]-\d{4,5}[a-z]*",
    r"ryzen(?:\s+ai)?\s+[3579]\s+\d{3,4}[a-z]*",
]

GPU_MODELOS = [
    "rtx 5090", "rtx 5080", "rtx 5070 ti", "rtx 5070",
    "rtx 5060 ti", "rtx 5060", "rtx 5050",
    "rtx 4090", "rtx 4080", "rtx 4070", "rtx 4060", "rtx 4050",
]
GPU_PONTOS = {
    "rtx 5090": 100, "rtx 5080": 98, "rtx 5070 ti": 97, "rtx 5070": 95,
    "rtx 5060 ti": 90, "rtx 5060": 85, "rtx 5050": 60,
    "rtx 4090": 100, "rtx 4080": 98, "rtx 4070": 80, "rtx 4060": 65, "rtx 4050": 45,
}
GPU_PRECO_MIN = {
    "rtx 5090": 1600, "rtx 5080": 1250, "rtx 5070 ti": 1000, "rtx 5070": 850,
    "rtx 5060 ti": 700, "rtx 5060": 600, "rtx 5050": 500,
    "rtx 4090": 1400, "rtx 4080": 1200, "rtx 4070": 850, "rtx 4060": 650, "rtx 4050": 500,
}


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


def extrair_precos(texto: str) -> list[float]:
    values = []
    for raw in re.findall(r"(?<!\d)(\d{1,4}(?:[.,]\d{2})?)\s*€", texto):
        value = parse_price_value(raw)
        if value is not None and 50 <= value <= 10000:
            values.append(value)
    return values


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


def extrair_cpu(texto: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    for pattern in CPU_PATTERNS:
        match = re.search(pattern, texto)
        if not match:
            continue
        cpu = match.group(0)
        tier = (
            "tier_1" if re.search(r"ultra\s+9|core\s+i9|ryzen(?:\s+ai)?\s+9", cpu)
            else "tier_2" if re.search(r"ultra\s+7|core\s+i7|ryzen(?:\s+ai)?\s+7", cpu)
            else "tier_3"
        )
        lower = cpu.lower()
        classe = (
            "hx" if "hx" in lower else
            "hs" if "hs" in lower else
            "h" if re.search(r"\d+h\b|\bh\b", lower) else
            "u_ultra" if re.search(r"(?:\s|^)(?:u|v|p)\b", lower) else None
        )
        return cpu, tier, classe
    return None, None, None


def extrair_specs_avancadas(texto_bruto: str) -> dict:
    t = normalizar_texto(texto_bruto)
    tl = limpar_vram(t)
    s = {
        "marca": None, "submarca": None, "gpu_modelo": None, "gpu_tipo": "desconhecida",
        "cpu_modelo": None, "cpu_classe": None, "cpu_str_original": None,
        "ram_gb": None, "ram_expansivel": False, "armazenamento_tb": None,
        "ssd_expansivel": False, "bateria_wh": None, "peso_kg": None,
        "ecra_res": None, "ecra_hz": None, "teclado_pt": "desconhecido",
        "alertas": [], "fontes": {},
    }

    s["marca"], s["submarca"] = detetar_marca_submarca(t)
    if s["marca"]:
        s["fontes"]["marca"] = "titulo"

    for gpu in GPU_MODELOS:
        if gpu in t:
            s["gpu_modelo"] = gpu
            s["gpu_tipo"] = "dedicada"
            s["fontes"]["gpu"] = "modelo_exato"
            break

    if not s["gpu_modelo"]:
        if any(x in t for x in [
            "intel iris", "intel arc graphics", "intel graphics", "intel uhd", "intel xe",
            "radeon graphics", "radeon 610m", "radeon 680m", "radeon 780m", "radeon 840m",
            "radeon 890m", "qualcomm adreno", "adreno", "qualcomm gpu",
        ]):
            s["gpu_tipo"] = "integrada"
            s["fontes"]["gpu"] = "integrada"
        else:
            s["alertas"].append("GPU não identificada")

    cpu, tier, classe = extrair_cpu(t)
    if cpu:
        s["cpu_str_original"] = cpu
        s["cpu_modelo"] = tier
        s["cpu_classe"] = classe
        s["fontes"]["cpu"] = "modelo_detetado"
    else:
        s["alertas"].append("CPU não confirmada")

    m = re.search(r"(\d{1,3})\s?gb\s?(?:ram|ddr[45](?:x)?|memory|so-dimm)\b", tl)
    if m:
        s["ram_gb"] = int(m.group(1))
        s["fontes"]["ram"] = "explicita"
    else:
        for raw in re.findall(r"\b(\d{1,3})\s?gb\b", tl):
            v = int(raw)
            if v in [8, 12, 16, 24, 32, 48, 64, 96, 128]:
                s["ram_gb"] = v
                s["fontes"]["ram"] = "heuristica"
                s["alertas"].append("RAM inferida por heurística")
                break
        if s["ram_gb"] is None:
            s["alertas"].append("RAM desconhecida")

    if any(x in t for x in ["ram expansivel", "so-dimm", "slot ram", "ram upgrade", "upgradable memory", "memoria expansivel"]):
        s["ram_expansivel"] = True

    for capacity, pattern in [
        (2.0, r"2\s?tb(?:\s?(?:ssd|nvme|pcie))?"),
        (1.0, r"1\s?tb(?:\s?(?:ssd|nvme|pcie))?"),
        (0.5, r"512\s?gb(?:\s?(?:ssd|nvme|pcie))?"),
    ]:
        m = re.search(pattern, t)
        if m:
            s["armazenamento_tb"] = capacity
            s["fontes"]["armazenamento"] = "explicita" if re.search(r"ssd|nvme|pcie", m.group(0)) else "heuristica"
            break
    if s["armazenamento_tb"] is None:
        s["alertas"].append("Armazenamento não confirmado")

    if any(x in t for x in ["ssd extra", "2x m.2", "2 x m.2", "slot m.2 livre", "segundo ssd", "segundo m.2", "armazenamento expansivel"]):
        s["ssd_expansivel"] = True

    m = re.search(r"(\d{2,3})\s?wh\b", t)
    if m:
        s["bateria_wh"] = int(m.group(1))
        s["fontes"]["bateria"] = "texto"
    else:
        s["alertas"].append("Bateria (Wh) desconhecida")

    m = re.search(r"(\d[.,]\d+)\s?kg\b", t)
    if m:
        s["peso_kg"] = float(m.group(1).replace(",", "."))
        s["fontes"]["peso"] = "texto"
    else:
        s["alertas"].append("Peso desconhecido")

    if any(x in t for x in ["qhd+", "2880x1800", "2560x1600", "wqxga", "2.8k"]):
        s["ecra_res"] = "qhd+"
    elif any(x in t for x in ["qhd", "2560x1440"]):
        s["ecra_res"] = "qhd"
    elif any(x in t for x in ["1200p", "1920x1200", "wuxga"]):
        s["ecra_res"] = "fhd+"
    elif any(x in t for x in ["fhd", "1920x1080", "1080p"]):
        s["ecra_res"] = "fhd"
    else:
        s["alertas"].append("Resolução do ecrã desconhecida")

    m = re.search(r"(\d{2,3})\s?hz\b", t)
    if m:
        s["ecra_hz"] = int(m.group(1))
        s["fontes"]["ecra_hz"] = "texto"
    else:
        s["alertas"].append("Frequência do ecrã desconhecida")

    if any(x in t for x in TECLADO_NAO_PT):
        s["teclado_pt"] = "nao_pt"
        s["fontes"]["teclado"] = "texto"
        s["alertas"].append("Teclado não é PT")
    elif any(x in t for x in TECLADO_PT):
        s["teclado_pt"] = "confirmado"
        s["fontes"]["teclado"] = "texto"
    else:
        s["alertas"].append("Teclado PT não confirmado")

    return s


def calcular_qualidade_dados(s: dict) -> tuple[float, str]:
    q = 0.20 * bool(s.get("cpu_modelo")) + 0.20 * (s.get("gpu_tipo") != "desconhecida")
    if s.get("ram_gb"):
        q += 0.20 if s.get("fontes", {}).get("ram") == "explicita" else 0.14
    for campo, peso in [("bateria_wh", 0.10), ("peso_kg", 0.10), ("ecra_res", 0.10), ("ecra_hz", 0.10)]:
        if s.get(campo) is not None:
            q += peso
    return q, "ALTA" if q >= 0.85 else "MEDIA" if q >= 0.50 else "BAIXA"


def classificar_tier(value_score: float, settings: dict) -> Optional[str]:
    diamante = float(settings.get("diamante_value_min", 130))
    ouro = float(settings.get("ouro_value_min", 110))
    prata = float(settings.get("prata_value_min", 90))
    bronze = float(settings.get("bronze_value_min", 70))
    if value_score >= diamante:
        return "DIAMANTE"
    if value_score >= ouro:
        return "OURO"
    if value_score >= prata:
        return "PRATA"
    if value_score >= bronze:
        return "BRONZE"
    return None


def plausibilidade_preco(specs: dict, preco: float, settings: dict) -> tuple[bool, Optional[str]]:
    if preco <= 0:
        return False, "Preço inválido."
    if preco < float(settings.get("preco_minimo_global", 250)):
        return False, f"Preço abaixo do mínimo global ({settings.get('preco_minimo_global', 250)}€)."
    gpu = specs.get("gpu_modelo")
    if gpu:
        floor = settings.get("gpu_preco_min", {}).get(gpu, GPU_PRECO_MIN.get(gpu))
        if floor and preco < float(floor):
            return False, f"Preço suspeito para {gpu.upper()}: {preco:.2f}€ < piso {float(floor):.0f}€."
    return True, None


def calcular_scores(s: dict, preco: float, weights: dict, settings: dict) -> dict:
    if s["teclado_pt"] == "nao_pt":
        return {"status": "REJEITADO", "alertas": ["Teclado explicitamente não português."]}
    if s["ram_gb"] == 8:
        return {"status": "REJEITADO", "alertas": ["8GB RAM confirmado - insuficiente."]}
    if s["peso_kg"] and s["peso_kg"] > 2.8:
        return {"status": "REJEITADO", "alertas": ["Excede limite de peso (>2.8kg)."]}

    ram = s["ram_gb"]
    p_ram = 50 if ram is None else 100 if ram >= 32 else 80 if ram >= 16 else 40
    arm = s["armazenamento_tb"]
    p_ssd = 50 if arm is None else 100 if arm >= 2 else 85 if arm >= 1 else 65
    p_res = {"qhd+": 100, "qhd": 95, "fhd+": 85, "fhd": 75, None: 60}.get(s["ecra_res"], 60)
    p_hz = min(100, (s.get("ecra_hz") or 60) / 1.65)
    p_cpu = weights.get("cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70}).get(s["cpu_modelo"], 50)

    penal = {"u_ultra": 0, "hs": 5, "h": 10, "hx": 20, None: 10}
    auto = 50 if s["bateria_wh"] is None else max(0, min(100, s["bateria_wh"] / 90 * 100) - penal.get(s["cpu_classe"], 10))
    gpu = weights.get("gpu_base", GPU_PONTOS)
    p_gpu = gpu.get(s["gpu_modelo"], 50) if s["gpu_tipo"] == "dedicada" else 15 if s["gpu_tipo"] == "integrada" else 30
    peso = s.get("peso_kg")
    p_peso = 50 if peso is None else 100 if peso <= 1.4 else 0 if peso >= 2.8 else max(0, 100 - (peso - 1.4) * 71.4)
    p_ram_long = 50 if ram is None else 100 if ram >= 32 else 95 if ram == 16 and s["ram_expansivel"] else 75 if ram == 16 else 40
    exp = s["ssd_expansivel"]
    p_ssd_long = 50 if arm is None else 100 if arm >= 2 or (arm == 1 and exp) else 85 if arm == 1 else 75 if arm == 0.5 and exp else 65 if arm == 0.5 else 50

    feup = p_ram * 0.20 + auto * 0.30 + p_ssd * 0.15 + p_res * 0.20 + p_cpu * 0.15
    gaming = p_gpu * 0.65 + p_cpu * 0.20 + p_hz * 0.10 + p_ram * 0.05
    longevidade = p_ram_long * 0.35 + p_ssd_long * 0.25 + auto * 0.20 + p_cpu * 0.20
    final = feup * 0.50 + gaming * 0.25 + longevidade * 0.15 + p_peso * 0.10

    conf, qualidade = calcular_qualidade_dados(s)
    ranking = round(max(0, min(100, final * (0.85 + 0.15 * conf))), 1)
    value_score = round(ranking / ((preco / 1000) ** 1.2), 1) if preco > 0 else 0
    tier = classificar_tier(value_score, settings)

    alertas = list(dict.fromkeys(s.get("alertas", [])))
    if s["teclado_pt"] == "desconhecido":
        alertas.append("Teclado PT não confirmado — portátil mantido no ranking.")

    return {
        "status": "ACEITE",
        "score_final": round(final, 1),
        "score_ranking": ranking,
        "value_score": value_score,
        "oportunidade": tier,
        "qualidade_dados": qualidade,
        "confianca_percentual": f"{int(conf * 100)}%",
        "fontes_extraidas": s["fontes"],
        "alertas": list(dict.fromkeys(alertas)),
        "detalhes": {
            "marca": s.get("marca"), "submarca": s.get("submarca"),
            "gpu": s.get("gpu_modelo"), "cpu": s.get("cpu_str_original"),
            "ram_gb": s.get("ram_gb"), "armazenamento_tb": s.get("armazenamento_tb"),
            "teclado_pt": s.get("teclado_pt"), "FEUP": round(feup, 1),
            "Gaming": round(gaming, 1), "Longevidade": round(longevidade, 1),
            "Portabilidade": round(p_peso, 1),
        },
    }


def extrair_jsonld_produtos(soup: BeautifulSoup, base_url: str) -> list[dict]:
    produtos = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
            return
        if not isinstance(obj, dict):
            return
        typ = obj.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if any(str(x).lower() in {"product", "productgroup"} for x in types):
            name = obj.get("name")
            offers = obj.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers]
            offer = next((x for x in offer_list if isinstance(x, dict)), {})
            url = obj.get("url") or offer.get("url") if isinstance(offer, dict) else obj.get("url")
            price = parse_price_value((offer or {}).get("price")) if isinstance(offer, dict) else None
            if name and price:
                produtos.append({
                    "titulo": str(name).strip(),
                    "preco": price,
                    "url": urljoin(base_url, str(url)) if url else base_url,
                })
        for value in obj.values():
            if isinstance(value, (dict, list)):
                walk(value)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return produtos


def escolher_titulo(card) -> str:
    node = card.select_one(
        "h1,h2,h3,h4,[class*='title'],[class*='Title'],"
        "[class*='name'],[class*='Name'],a[title],img[alt]"
    )
    if not node:
        return ""
    title = node.get("alt") or node.get("title") or node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", title).strip()


def escolher_link(card, base_url: str, hints: list[str]) -> Optional[str]:
    anchors = card.select("a[href]")
    ranked = []
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        score = 0
        low = full.lower()
        if any(h.lower() in low for h in hints):
            score += 5
        if a.get("title"):
            score += 2
        if a.select_one("img"):
            score += 1
        ranked.append((score, full))
    return max(ranked, default=(0, None))[1]


def escolher_preco(card) -> Optional[float]:
    semantic = []
    for node in card.select("[itemprop='price'], meta[property='product:price:amount'], [data-price]"):
        raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
        value = parse_price_value(raw)
        if value is not None:
            semantic.append(value)
    if semantic:
        return min(semantic)

    current = []
    for node in card.select("[class*='price'], [class*='Price']"):
        classes = normalizar_texto(" ".join(node.get("class", [])))
        if any(x in classes for x in ["old", "oldprice", "regular", "previous", "was", "strike", "del"]):
            continue
        current.extend(extrair_precos(node.get_text(" ", strip=True)))
    if current:
        return min(current)

    values = extrair_precos(card.get_text(" ", strip=True))
    return min(values) if values else None


def extrair_candidatos_html(soup: BeautifulSoup, cfg: dict, base_url: str, limit: int) -> list[dict]:
    hints = cfg.get("product_path_hints", ["/produto/", "/product/", "/portatil/", "/portateis/"])
    selectors = cfg.get("card_selectors") or [
        "article", "li[class*='product']", "div[class*='product-card']",
        "div[class*='productCard']", "div[class*='product-item']", "[data-product-id]",
        "[data-testid*='product']",
    ]

    cards = []
    for selector in selectors:
        cards.extend(soup.select(selector))

    # Mesmo com selectors presentes, executamos o fallback por links: isto resolve páginas
    # como Globaldata/PCDIGA onde o HTML muda mas o link do produto continua consistente.
    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").lower()
        if not any(h.lower() in href for h in hints):
            continue
        parent = anchor
        best = None
        for _ in range(int(cfg.get("parent_climb", 6))):
            parent = parent.parent if parent else None
            if not parent:
                break
            text = parent.get_text(" ", strip=True)
            if 25 <= len(text) <= 2200 and extrair_precos(text):
                best = parent
                break
        if best is not None:
            cards.append(best)

    candidates = []
    seen = set()
    for card in cards:
        title = escolher_titulo(card)
        if len(title) < 10:
            continue
        price = escolher_preco(card)
        if price is None or not 100 <= price <= 10000:
            continue
        link = escolher_link(card, base_url, hints) or base_url
        key = (normalizar_texto(title), link)
        if key in seen:
            continue
        text = card.get_text(" ", strip=True)
        candidates.append({
            "titulo": title,
            "preco": price,
            "url": link,
            "stock": detetar_stock(text),
        })
        seen.add(key)

    result = []
    seen_titles = set()
    for item in candidates:
        if len(result) >= limit:
            break
        key = normalizar_texto(item["titulo"])
        if key in seen_titles:
            continue
        seen_titles.add(key)
        result.append(item)
    return result


def extrair_grelha_categoria(session: requests.Session, cfg: dict, limit: int) -> dict:
    loja = cfg["loja"]
    url = cfg["url"]
    timeout = max(5, int(cfg.get("timeout_ms", 12000)) // 1000)
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return {"loja": loja, "url": url, "produtos": [], "bloqueada": False, "erro": str(exc)}

    status = response.status_code
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body_text = normalizar_texto(soup.get_text(" ", strip=True)[:12000])
    blocked = (
        status in (401, 403, 429, 503)
        or "just a moment" in title.lower()
        or "verify you are human" in body_text
        or "access denied" in body_text
        or "cf-chl-" in response.text.lower()
    )

    print(f"   [Debug {loja}] Status: {status} | Título: '{title[:140]}'")
    if blocked:
        print(f"   ⚠️ {loja} bloqueada/CAPTCHA ({status}).")
        return {"loja": loja, "url": url, "produtos": [], "bloqueada": True, "erro": f"HTTP {status}"}

    jsonld = extrair_jsonld_produtos(soup, response.url)
    html_items = extrair_candidatos_html(soup, cfg, response.url, limit)
    merged = []
    seen = set()
    for item in jsonld + html_items:
        title_key = normalizar_texto(item.get("titulo", ""))
        if not title_key or title_key in seen:
            continue
        item["loja"] = loja
        item["url"] = item.get("url") or response.url
        item["stock"] = item.get("stock", None)
        merged.append(item)
        seen.add(title_key)
        if len(merged) >= limit:
            break

    return {"loja": loja, "url": response.url, "produtos": merged, "bloqueada": False, "erro": None}


def detetar_teclado_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    campos = []
    for node in soup.select(
        "[class*='keyboard'], [class*='Keyboard'], [class*='teclado'], "
        "[class*='Teclado'], [itemprop*='keyboard'], [data-testid*='keyboard']"
    ):
        campos.append(node.get_text(" ", strip=True))
    universo = normalizar_texto(" ".join(campos) if campos else soup.get_text(" ", strip=True)[:30000])
    if any(x in universo for x in TECLADO_NAO_PT):
        return "nao_pt"
    if any(x in universo for x in TECLADO_PT):
        return "confirmado"
    return "desconhecido"


def confirmar_teclado_produto(session: requests.Session, item: dict) -> str:
    url = item.get("url")
    if not url or url == item.get("_category_url"):
        return "desconhecido"
    try:
        response = session.get(url, timeout=9, allow_redirects=True)
        if response.status_code >= 400:
            return "desconhecido"
        return detetar_teclado_html(response.text)
    except requests.RequestException:
        return "desconhecido"


def deve_alertar(prev: Optional[dict], atual: dict) -> tuple[bool, str]:
    tier = atual.get("oportunidade")
    if not tier:
        return False, ""
    if prev is None:
        return True, f"nova oportunidade {tier.lower()}"
    old_price = prev.get("price")
    old_tier = prev.get("oportunidade")
    if isinstance(old_price, (int, float)) and atual["preco"] < old_price - 5:
        return True, "queda de preço"
    if tier != old_tier:
        return True, f"escalou para {tier.lower()}"
    return False, ""


def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC:
        print("⚠️ NTFY_TOPIC não definido; notificação ignorada.")
        return
    try:
        requests.post(
            "https://ntfy.sh",
            json={
                "topic": NTFY_TOPIC,
                "title": titulo,
                "message": mensagem,
                "tags": [t.strip() for t in tags.split(",") if t.strip()],
                "priority": 4 if prioridade == "high" else 3,
            },
            timeout=10,
        ).raise_for_status()
        print(f"📲 Notificação enviada: {titulo}")
    except requests.RequestException as exc:
        print(f"❌ Erro ao enviar ntfy: {exc}")


def formatar_alerta(tier: str, item: dict, analysis: dict, specs: dict, reason: str) -> tuple[str, str, str]:
    icons = {"DIAMANTE": "💎", "OURO": "🥇", "PRATA": "🥈", "BRONZE": "🥉"}
    icon = icons.get(tier, "💻")
    tag = {"DIAMANTE": "gem", "OURO": "trophy", "PRATA": "medal_sports", "BRONZE": "medal"}.get(tier, "computer")
    title = f"{icon} {tier} | {item['preco']:.0f}€"
    msg = (
        f"{item['titulo']}\n\n"
        f"Loja: {item['loja']}\n"
        f"Preço: {item['preco']:.2f}€\n"
        f"Ranking: {analysis['score_ranking']}/100\n"
        f"Índice de valor: {analysis['value_score']}\n"
        f"Oportunidade: {tier}\n"
        f"Dados: {analysis['qualidade_dados']} ({analysis['confianca_percentual']})\n"
        f"GPU: {specs.get('gpu_modelo') or 'não identificada'}\n"
        f"CPU: {specs.get('cpu_str_original') or 'não confirmada'}\n"
        f"RAM: {specs.get('ram_gb') or '?'}GB\n"
        f"Teclado: {specs['teclado_pt']}\n"
        f"Motivo: {reason}\n\n"
        f"🔗 Produto: {item['url']}"
    )
    return title, msg, tag


def main() -> None:
    started = datetime.now(timezone.utc)
    print("🚀 Rastreador iniciado — requests em paralelo, ranking 0–100, Bronze/Prata/Ouro/Diamante.")

    config = carregar_json(CONFIG_PATH)
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})
    settings = config.get("settings", {})
    weights = config.get("weights", {})
    categories = config.get("category_urls", [])

    budget_hard = float(settings.get("budget_hard", 1500))
    max_products = int(settings.get("max_produtos_por_categoria", 30))
    max_workers = min(len(categories), int(settings.get("max_lojas_paralelas", 6)))
    keyboard_candidates = int(settings.get("max_verificacoes_teclado", 12))

    stats = {
        "lojas": len(categories), "lojas_com_produtos": 0, "lojas_sem_resultados": 0,
        "bloqueadas": 0, "erros": 0, "encontrados": 0, "analisados": 0,
        "aceites": 0, "rejeitados": 0, "precos_suspeitos": 0, "alertas": 0,
        "diamante": 0, "ouro": 0, "prata": 0, "bronze": 0,
    }

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
    })

    with ThreadPoolExecutor(max_workers=max_workers or 1) as executor:
        future_map = {
            executor.submit(extrair_grelha_categoria, session, cfg, max_products): cfg["loja"]
            for cfg in categories
        }
        result_map = {}
        for future in as_completed(future_map):
            result = future.result()
            result_map[result["loja"]] = result

    candidates_for_keyboard = []
    per_store_keyboard_limit = max(2, keyboard_candidates // max(1, len(categories)))

    for category in categories:
        loja = category["loja"]
        result = result_map.get(loja, {"produtos": [], "bloqueada": False, "erro": "sem resultado"})
        products = result.get("produtos", [])
        print(f"\n🔍 {loja}: {len(products)} produtos candidatos.")
        stats["encontrados"] += len(products)

        if result.get("bloqueada"):
            stats["bloqueadas"] += 1
        elif result.get("erro"):
            stats["erros"] += 1
        elif products:
            stats["lojas_com_produtos"] += 1
        else:
            stats["lojas_sem_resultados"] += 1

        store_keyboard_count = 0
        for item in products:
            item["_category_url"] = result.get("url") or category["url"]
            if item["preco"] > budget_hard or not verificar_elegibilidade(item["titulo"]):
                continue

            specs = extrair_specs_avancadas(item["titulo"])
            ok_price, price_reason = plausibilidade_preco(specs, item["preco"], settings)
            if not ok_price:
                stats["precos_suspeitos"] += 1
                print(f"   [!] {item['titulo'][:68]}... | PREÇO SUSPEITO: {price_reason}")
                continue

            provisional = calcular_scores(specs, item["preco"], weights, settings)
            if provisional["status"] == "REJEITADO":
                stats["rejeitados"] += 1
                print(f"   [-] {item['titulo'][:68]}... | REJEITADO: {provisional['alertas']}")
                continue

            if specs["teclado_pt"] == "desconhecido" and store_keyboard_count < per_store_keyboard_limit:
                candidates_for_keyboard.append((item, specs))
                store_keyboard_count += 1

            item["_specs"] = specs
            stats["analisados"] += 1

    # Só valida páginas de produto num pequeno subconjunto: reduz muito o tempo sem voltar a
    # aceitar implicitamente teclados não-PT.
    def check_keyboard(entry):
        item, specs = entry
        detected = confirmar_teclado_produto(session, item) if specs["teclado_pt"] == "desconhecido" else specs["teclado_pt"]
        if detected != "desconhecido":
            specs["teclado_pt"] = detected
            specs["fontes"]["teclado"] = "pagina_produto"
            if detected == "confirmado":
                specs["alertas"] = [a for a in specs["alertas"] if a != "Teclado PT não confirmado"]
            elif "Teclado não é PT" not in specs["alertas"]:
                specs["alertas"].append("Teclado não é PT")
        return item, specs

    with ThreadPoolExecutor(max_workers=max_workers or 1) as executor:
        for future in as_completed([executor.submit(check_keyboard, x) for x in candidates_for_keyboard]):
            item, specs = future.result()
            item["_specs"] = specs

    for category in categories:
        loja = category["loja"]
        products = result_map.get(loja, {}).get("produtos", [])
        for item in products:
            specs = item.get("_specs")
            if not specs:
                continue
            analysis = calcular_scores(specs, item["preco"], weights, settings)
            if analysis["status"] == "REJEITADO":
                stats["rejeitados"] += 1
                continue

            stats["aceites"] += 1
            tier = analysis.get("oportunidade")
            if tier == "DIAMANTE": stats["diamante"] += 1
            elif tier == "OURO": stats["ouro"] += 1
            elif tier == "PRATA": stats["prata"] += 1
            elif tier == "BRONZE": stats["bronze"] += 1

            key = f"{loja}::{item['url'] or item['titulo']}"
            entries = history["offers"].setdefault(key, [])
            prev = entries[-1] if entries else None
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "price": item["preco"], "stock": item.get("stock"),
                "score_final": analysis["score_final"], "score_ranking": analysis["score_ranking"],
                "value_score": analysis["value_score"], "oportunidade": tier,
                "qualidade_dados": analysis["qualidade_dados"], "teclado_pt": specs["teclado_pt"],
                "marca": specs.get("marca"), "submarca": specs.get("submarca"),
                "gpu": specs.get("gpu_modelo"), "cpu": specs.get("cpu_str_original"),
                "url": item["url"],
            }
            entries.append(record)
            history["offers"][key] = entries[-60:]

            print(
                f"   [+] {item['titulo'][:48]}... | {item['preco']:.2f}€ | "
                f"Ranking: {analysis['score_ranking']}/100 | Valor: {analysis['value_score']}"
                f" | {tier or 'sem tier'} | Dados: {analysis['qualidade_dados']}"
            )

            should_alert, reason = deve_alertar(prev, {"preco": item["preco"], **analysis})
            if should_alert and item.get("stock") is not False and validar_url_produto(item):
                title, msg, tag = formatar_alerta(tier, item, analysis, specs, reason)
                stats["alertas"] += 1
                enviar_alerta(title, msg, "high" if tier in {"DIAMANTE", "OURO"} else "default", tag)

    guardar_json(HISTORY_PATH, history)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    resumo = (
        "📊 Resumo da run\n"
        f"Lojas: {stats['lojas']}\n"
        f"Lojas com resultados: {stats['lojas_com_produtos']}\n"
        f"Sem resultados: {stats['lojas_sem_resultados']}\n"
        f"Bloqueadas/CAPTCHA: {stats['bloqueadas']}\n"
        f"Erros de acesso: {stats['erros']}\n"
        f"Produtos encontrados: {stats['encontrados']}\n"
        f"Produtos analisados: {stats['analisados']}\n"
        f"Aceites: {stats['aceites']}\n"
        f"Rejeitados: {stats['rejeitados']}\n"
        f"Preços suspeitos descartados: {stats['precos_suspeitos']}\n"
        f"💎 Diamante: {stats['diamante']}\n"
        f"🥇 Ouro: {stats['ouro']}\n"
        f"🥈 Prata: {stats['prata']}\n"
        f"🥉 Bronze: {stats['bronze']}\n"
        f"Alertas enviados: {stats['alertas']}\n"
        f"Tempo do scraper: {elapsed:.1f}s"
    )
    print("\n" + resumo)
    enviar_alerta("🔄 Relatório de Rastreio", resumo, "default", "bar_chart")


def validar_url_produto(item: dict) -> bool:
    url = item.get("url")
    return bool(url and urlparse(url).scheme in {"http", "https"})


if __name__ == "__main__":
    main()
