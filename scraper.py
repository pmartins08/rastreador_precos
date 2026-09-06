from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config" / "config.json"
HISTORY_PATH = BASE / "data" / "history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

EXCLUDE = [
    "recondicionado", "refurbished", "usado", "outlet",
    "grade a", "grade b", "grade c", "seminovo", "open box",
]
BRANDS = {
    "asus": {"rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"},
    "lenovo": {"legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"},
    "hp": {"omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"},
}
KPT = [
    "teclado portugues", "teclado pt", "teclado pt-pt", "keyboard portugues",
    "keyboard pt", "keyboard pt-pt", "layout pt", "layout pt-pt",
    "portuguese keyboard", "portuguese layout", "pt keyboard", "pt-pt",
]
KNPT = [
    "teclado espanhol", "spanish keyboard", "spanish layout",
    "teclado frances", "french keyboard", "french layout",
    "teclado alemao", "german keyboard", "german layout",
    "teclado ingles", "english keyboard", "keyboard us", "us keyboard",
    "us layout", "en-us keyboard", "uk keyboard", "uk layout",
    "italian keyboard", "italian layout", "azerty", "qwertz",
]
SNO = [
    "esgotado", "fora de stock", "out of stock", "indisponivel",
    "temporariamente indisponivel", "sem stock", "unavailable",
    "not available", "sold out",
]
SSI = [
    "em stock", "em estoque", "disponivel", "disponibilidade: disponivel",
    "available", "in stock", "order now", "adicionar ao carrinho",
    "adiciona ao carrinho", "add to cart", "em stock online",
]
GPU_MODELOS = sorted(
    [
        "rtx 5090", "rtx 5080", "rtx 5070 ti", "rtx 5070", "rtx 5060 ti",
        "rtx 5060", "rtx 5050", "rtx 4090", "rtx 4080", "rtx 4070",
        "rtx 4060", "rtx 4050", "rtx a5500", "rtx a5000", "rtx a4500",
        "rtx a3000", "rtx a2000", "radeon rx 7900m", "radeon rx 7800m",
        "radeon rx 7700s", "radeon rx 7600s", "radeon rx 7600m xt",
        "radeon rx 7600m", "radeon rx 6850m xt", "radeon rx 6800m",
        "radeon rx 6650m", "radeon rx 6600m", "radeon rx 6550m", "radeon rx 6500m",
    ],
    key=len,
    reverse=True,
)
IGPU = [
    "intel iris", "intel arc graphics", "intel graphics", "intel uhd",
    "intel xe", "intel xe graphics", "intel arc integrated", "radeon graphics",
    "radeon 610m", "radeon 680m", "radeon 780m", "radeon 840m", "radeon 890m",
    "radeon 760m", "amd radeon graphics", "amd integrated graphics",
    "qualcomm adreno", "adreno",
]
GPU_GEN = ["rtx graphics", "rtx discrete", "geforce rtx", "geforce mx", "radeon rx", "radeon pro"]
CPU_PAT = [
    r"core\s+ultra\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"core\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"core\s+i[3579]\s+[0-9]{4,5}[a-z]*",
    r"i[3579]-[0-9]{4,5}[a-z]*",
    r"ryzen(?:\s+ai)?\s+[3579]\s+[0-9]{3,5}[a-z]*",
]

ALIASES = {
    "gpu": ["gpu", "placa grafica", "graphics card", "graphic card", "graphic processor",
            "processador grafico", "video card", "vga", "placa grafica discreta",
            "placa grafica dedicada"],
    "igpu": ["placa grafica integrada", "onboard graphics", "integrated graphics", "integrated gpu"],
    "vram": ["memoria grafica", "graphics memory", "video memory", "vram"],
    "tgp": ["tgp", "total graphics power", "potencia grafica"],
    "cpu": ["processador", "cpu", "processor", "modelo do processador"],
    "ram": ["memoria ram", "ram", "system memory", "memory", "memoria instalada"],
    "ram_type": ["tipo de memoria", "memory type", "tipo ram", "ram type"],
    "storage": ["disco ssd", "ssd", "armazenamento", "storage", "capacidade ssd"],
    "screen": ["ecra", "display", "screen", "painel", "tipo de ecra"],
    "resolution": ["resolucao", "resolution"],
    "refresh": ["refresh rate", "frequencia", "taxa de atualizacao", "hz"],
    "brightness": ["brilho", "brightness", "nits", "cd/m2"],
    "panel": ["tipo de painel", "panel type", "panel", "technology"],
    "battery": ["bateria", "battery", "capacidade da bateria", "battery capacity"],
    "weight": ["peso", "weight", "peso do produto"],
    "keyboard": ["teclado", "keyboard", "layout"],
    "ram_slots": ["slots ram", "ram slots", "so-dimm", "memoria expansivel"],
    "m2": ["m.2", "slot m.2", "slots m.2"],
}

def norm(x: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        "".join(c for c in unicodedata.normalize("NFKD", str(x or "")) if not unicodedata.combining(c)),
    ).lower().strip()

def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}

def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def parse_price_value(value: object) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    try:
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                return float(s.replace(".", "").replace(",", "."))
            return float(s.replace(",", ""))
        if "," in s:
            return float(s.replace(".", "").replace(",", "."))
        return float(s)
    except ValueError:
        return None

def prices(text: str) -> list[float]:
    out = []
    for raw in re.findall(r"(?<!\d)(\d{1,4}(?:[.,]\d{2})?)\s*€", text or ""):
        p = parse_price_value(raw)
        if p is not None and 50 <= p <= 10000:
            out.append(p)
    return out

def stock(text: str) -> bool | None:
    t = norm(text)
    if any(x in t for x in SNO):
        return False
    if any(x in t for x in SSI):
        return True
    return None

def brand(text: str) -> tuple[str | None, str | None]:
    t = norm(text)
    for b, subs in BRANDS.items():
        if re.search(rf"\b{re.escape(b)}\b", t):
            for s in sorted(subs, key=len, reverse=True):
                if re.search(rf"\b{re.escape(s)}\b", t):
                    return b, s
            return b, None
    return None, None

def eligible(text: str) -> bool:
    return not any(x in norm(text) for x in EXCLUDE) and brand(text)[0] in BRANDS

def gp(model: str) -> str:
    return r"(?<![a-z0-9])" + r"[\s._-]*".join(re.escape(x) for x in model.split()) + r"(?![a-z0-9])"

def gpus(text: str) -> tuple[list[str], str, str | None]:
    t = norm(text)
    models = [x for x in GPU_MODELOS if re.search(gp(x), t)]
    if models:
        return models, "dedicada", models[0]
    if any(re.search(gp(x), t) for x in GPU_GEN):
        return [], "dedicada", None
    if any(re.search(gp(x), t) for x in IGPU):
        return [], "integrada", None
    return [], "desconhecida", None

def cpu(text: str) -> tuple[str | None, str | None, str | None]:
    t = norm(text)
    for pat in CPU_PAT:
        m = re.search(pat, t)
        if not m:
            continue
        s = m.group(0)
        tier = (
            "tier_1"
            if re.search(r"ultra\s+9|core\s+i9|ryzen(?:\s+ai)?\s+9", s)
            else "tier_2"
            if re.search(r"ultra\s+7|core\s+i7|ryzen(?:\s+ai)?\s+7", s)
            else "tier_3"
        )
        cls = (
            "hx" if "hx" in s else
            "hs" if "hs" in s else
            "h" if re.search(r"\d+h\b", s) else
            "u_ultra" if re.search(r"\b[uvp]\b", s) else None
        )
        return s, tier, cls
    return None, None, None

def _key(label: str) -> str | None:
    n = norm(label)
    for key, aliases in ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", n) for a in aliases):
            return key
    return None

def pairs(soup: BeautifulSoup) -> list[tuple]:
    out: list[tuple] = []
    for tr in soup.select("table tr"):
        cells = [x for x in tr.find_all(["th", "td"]) if x.get_text(" ", strip=True)]
        if len(cells) >= 2:
            k = _key(cells[0].get_text(" ", strip=True))
            if k:
                out.append((k, cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True), "table", 0.98))
    for dt in soup.select("dl dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            k = _key(dt.get_text(" ", strip=True))
            if k:
                out.append((k, dt.get_text(" ", strip=True), dd.get_text(" ", strip=True), "dl", 0.98))
    for node in soup.find_all(["li", "div", "p"]):
        label = node.select_one("[class*='label'],[class*='name'],[class*='key']")
        value = node.select_one("[class*='value'],[class*='detail'],[class*='spec-value']")
        if label and value and label is not value:
            k = _key(label.get_text(" ", strip=True))
            if k:
                out.append((k, label.get_text(" ", strip=True), value.get_text(" ", strip=True), "label_value", 0.92))
    return out

def best(values: list[tuple]) -> tuple | None:
    return max(values, key=lambda x: x[4]) if values else None

def nram(text: str) -> int | None:
    t = norm(text)
    if re.search(r"vram|memoria grafica|graphics memory|video memory", t):
        return None
    m = re.search(r"\b(4|8|12|16|24|32|48|64|96|128)\s*gb\b", t)
    return int(m.group(1)) if m else None

def nstorage(text: str) -> float | None:
    vals = []
    for m in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", norm(text)):
        v = float(m.group(1).replace(",", "."))
        gb = v * 1024 if m.group(2) == "tb" else v
        if 128 <= gb <= 8192:
            vals.append(gb)
    return round(max(vals) / 1024, 2) if vals else None

def specs(text: str) -> dict:
    t = norm(text)
    o = {
        "fontes": {}, "evidencias": {}, "conflitos": [], "alertas": [],
        "marca": None, "submarca": None, "gpu_tipo": "desconhecida",
        "gpu_modelo": None, "gpu_modelos_detectados": [],
        "cpu_modelo": None, "cpu_str_original": None, "cpu_classe": None,
        "ram_gb": None, "ram_type": None, "ram_expansivel": False,
        "armazenamento_tb": None, "ssd_expansivel": False, "vram_gb": None,
        "tgp_w": None, "bateria_wh": None, "peso_kg": None,
        "ecra_tamanho": None, "ecra_res": None, "ecra_painel": None,
        "ecra_hz": None, "ecra_brightness_nits": None, "teclado_pt": "desconhecido",
    }
    o["marca"], o["submarca"] = brand(t)
    detected, gtype, gmodel = gpus(t)
    o["gpu_tipo"], o["gpu_modelo"], o["gpu_modelos_detectados"] = gtype, gmodel, detected
    cmodel, _ctier, cclass = cpu(t)
    o["cpu_modelo"], o["cpu_str_original"], o["cpu_classe"] = cmodel, cmodel, cclass
    o["ram_gb"] = nram(t)
    o["armazenamento_tb"] = nstorage(t)
    m = re.search(r"(\d{1,2})\s*gb\s*gddr\d+", t)
    o["vram_gb"] = int(m.group(1)) if m else None
    m = re.search(r"(\d{2,3})\s*w\b", t)
    o["tgp_w"] = int(m.group(1)) if m else None
    m = re.search(r"(\d{2,3})\s*wh\b", t)
    o["bateria_wh"] = int(m.group(1)) if m else None
    m = re.search(r"(\d[.,]\d+)\s*kg\b", t)
    o["peso_kg"] = float(m.group(1).replace(",", ".")) if m else None
    m = re.search(r'(\d{1,2}(?:[.,]\d)?)\s*(?:"|pol|poles|polegadas)\b', t)
    o["ecra_tamanho"] = float(m.group(1).replace(",", ".")) if m else None
    m = re.search(r"(\d{2,3})\s*hz\b", t)
    o["ecra_hz"] = int(m.group(1)) if m else None
    o["ecra_res"] = (
        "qhd+" if re.search(r"2560\s*x\s*1600|qhd\+", t) else
        "fhd+" if re.search(r"1920\s*x\s*1200|wuxga", t) else
        "fhd" if re.search(r"1920\s*x\s*1080|1080p|fhd", t) else None
    )
    o["teclado_pt"] = (
        "nao_pt" if any(x in t for x in KNPT)
        else "confirmado" if any(x in t for x in KPT)
        else "desconhecido"
    )
    return o

def apply_pair(o: dict, key: str, value: str, source: str) -> None:
    t = norm(value)
    if key == "gpu":
        detected, gt, gm = gpus(value)
        if detected:
            o["gpu_modelos_detectados"] = detected
            o["gpu_modelo"] = gm
            o["gpu_tipo"] = gt
    elif key == "igpu":
        if not o.get("gpu_modelo"):
            o["gpu_tipo"] = "integrada"
    elif key == "cpu":
        c, _tier, cls = cpu(value)
        if c:
            o["cpu_modelo"], o["cpu_str_original"], o["cpu_classe"] = c, c, cls
    elif key == "ram":
        n = nram(value)
        if n is not None:
            o["ram_gb"] = n
    elif key == "ram_type":
        o["ram_type"] = value.strip()
    elif key == "ram_slots":
        o["ram_expansivel"] = True
    elif key == "storage":
        n = nstorage(value)
        if n is not None:
            o["armazenamento_tb"] = n
        if re.search(r"\b(2\s*x|segundo|extra|expansivel|m\.2\s+livre)\b", t):
            o["ssd_expansivel"] = True
    elif key == "vram":
        m = re.search(r"(\d{1,2})\s*gb", t)
        if m:
            o["vram_gb"] = int(m.group(1))
    elif key == "tgp":
        m = re.search(r"(\d{2,3})\s*w", t)
        if m:
            o["tgp_w"] = int(m.group(1))
    elif key == "battery":
        m = re.search(r"(\d{2,3})\s*wh", t)
        if m:
            o["bateria_wh"] = int(m.group(1))
    elif key == "weight":
        m = re.search(r"(\d[.,]\d+)\s*kg", t)
        if m:
            o["peso_kg"] = float(m.group(1).replace(",", "."))
    elif key == "resolution":
        if re.search(r"2560\s*x\s*1600|qhd\+", t):
            o["ecra_res"] = "qhd+"
        elif re.search(r"1920\s*x\s*1200|wuxga", t):
            o["ecra_res"] = "fhd+"
        elif re.search(r"1920\s*x\s*1080|1080p|fhd", t):
            o["ecra_res"] = "fhd"
    elif key == "refresh":
        m = re.search(r"(\d{2,3})\s*hz", t)
        if m:
            o["ecra_hz"] = int(m.group(1))
    elif key == "screen":
        m = re.search(r'(\d{1,2}(?:[.,]\d)?)\s*(?:"|pol|poles|polegadas)\b', t)
        if m:
            o["ecra_tamanho"] = float(m.group(1).replace(",", "."))
    elif key == "panel":
        o["ecra_painel"] = value.strip()
    elif key == "brightness":
        m = re.search(r"(\d{2,4})\s*(?:nits|cd/m2)", t)
        if m:
            o["ecra_brightness_nits"] = int(m.group(1))
    elif key == "keyboard":
        kt = norm(value)
        o["teclado_pt"] = (
            "nao_pt" if any(x in kt for x in KNPT)
            else "confirmado" if any(x in kt for x in KPT)
            else o["teclado_pt"]
        )
    o["evidencias"][key] = value
    o["fontes"][key] = source

def extract(title: str, soup: BeautifulSoup) -> dict:
    o = specs(title)
    ps = pairs(soup)
    by: dict[str, list[tuple]] = {}
    for item in ps:
        by.setdefault(item[0], []).append(item)
    for key in ["gpu", "igpu", "cpu", "ram", "storage", "vram", "tgp", "battery",
                "weight", "resolution", "screen", "refresh", "brightness", "panel",
                "keyboard", "ram_type", "ram_slots", "m2"]:
        z = best(by.get(key, []))
        if z:
            apply_pair(o, key, z[2], z[3])
            if key == "m2":
                o["ssd_expansivel"] = True
    page_text = soup.get_text(" ", strip=True)
    fallback = specs(title + " " + page_text[:20000])
    for k in ["gpu_modelo", "gpu_tipo", "cpu_modelo", "cpu_str_original", "cpu_classe",
              "ram_gb", "armazenamento_tb", "vram_gb", "tgp_w", "bateria_wh", "peso_kg",
              "ecra_tamanho", "ecra_res", "ecra_hz", "teclado_pt"]:
        if o.get(k) in (None, "desconhecida", "desconhecido") and fallback.get(k) not in (None, "desconhecida", "desconhecido"):
            o[k] = fallback[k]
            o["fontes"][k] = "titulo_texto_fallback"
    return o

def quality(s: dict) -> tuple[float, str]:
    q = 0.0
    q += 0.20 if s.get("cpu_modelo") else 0.0
    q += 0.20 if s.get("gpu_tipo") != "desconhecida" else 0.0
    if s.get("ram_gb"):
        q += 0.20 if s["fontes"].get("ram") in {"table", "dl", "label_value"} else 0.14
    for field, weight in [("bateria_wh", 0.10), ("peso_kg", 0.10), ("ecra_res", 0.10), ("ecra_hz", 0.10)]:
        if s.get(field) is not None:
            q += weight
    return q, "ALTA" if q >= 0.85 else "MEDIA" if q >= 0.50 else "BAIXA"

def price_score(price_value: float, settings: dict) -> float:
    soft = float(settings.get("budget_soft", 1300.0))
    hard = float(settings.get("budget_hard", 1500.0))
    if price_value <= soft:
        return 150.0
    if price_value <= hard:
        return 150.0 - 50.0 * ((price_value - soft) / max(1.0, hard - soft))
    penalty = min(30.0, (price_value - hard) / max(1.0, hard) * 100.0)
    return max(70.0, 100.0 - penalty)

def value_score(ranking: float, price_value: float, settings: dict) -> float:
    raw = (1.30 * ranking) * 0.70 + price_score(price_value, settings) * 0.30
    return round(max(0.0, min(150.0, raw)), 1)


def score(spec: dict, price_value: float, weights: dict, settings: dict) -> dict:
    if spec.get("teclado_pt") == "nao_pt":
        return {"status": "REJEITADO", "alertas": ["Teclado não é português."]}
    if spec.get("teclado_pt") != "confirmado":
        return {"status": "REJEITADO", "alertas": ["Teclado PT não confirmado — fora do ranking automático."]}
    if spec.get("ram_gb") == 8:
        return {"status": "REJEITADO", "alertas": ["8GB RAM confirmado - insuficiente."]}
    if spec.get("peso_kg") and spec["peso_kg"] > 2.8:
        return {"status": "REJEITADO", "alertas": ["Excede limite de peso (>2.8kg)."]}
    ram = spec.get("ram_gb")
    p_ram = 50 if ram is None else 100 if ram >= 32 else 80 if ram >= 16 else 40
    arm = spec.get("armazenamento_tb")
    p_ssd = 50 if arm is None else 100 if arm >= 2 else 85 if arm >= 1 else 65
    p_res = {"qhd+": 100, "qhd": 95, "fhd+": 85, "fhd": 75, None: 60}.get(spec.get("ecra_res"), 60)
    p_hz = min(100, (spec.get("ecra_hz") or 60) / 1.65)
    _cpu_model, cpu_tier, _cpu_class = cpu(spec.get("cpu_modelo", ""))
    p_cpu = weights.get("cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70}).get(cpu_tier, 50)
    penalty = {"u_ultra": 0, "hs": 5, "h": 10, "hx": 20, None: 10}
    autonomy = 50 if spec.get("bateria_wh") is None else max(0, min(100, spec["bateria_wh"] / 90 * 100) - penalty.get(spec.get("cpu_classe"), 10))
    gpu_base = weights.get("gpu_base", {})
    if spec.get("gpu_tipo") == "dedicada":
        p_gpu = gpu_base.get(spec.get("gpu_modelo"), 50)
    elif spec.get("gpu_tipo") == "integrada":
        p_gpu = 15
    else:
        p_gpu = 30
    peso = spec.get("peso_kg")
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
    elif ram == 16 and spec.get("ram_expansivel"):
        p_ram_long = 95
    elif ram == 16:
        p_ram_long = 75
    else:
        p_ram_long = 40
    exp = spec.get("ssd_expansivel")
    if arm is None:
        p_ssd_long = 50
    elif arm >= 2 or (arm == 1 and exp):
        p_ssd_long = 100
    elif arm == 1:
        p_ssd_long = 85
    elif arm == 0.5 and exp:
        p_ssd_long = 75
    elif arm == 0.5:
        p_ssd_long = 65
    else:
        p_ssd_long = 50
    feup = p_ram * 0.20 + autonomy * 0.30 + p_ssd * 0.15 + p_res * 0.20 + p_cpu * 0.15
    gaming = p_gpu * 0.65 + p_cpu * 0.20 + p_hz * 0.10 + p_ram * 0.05
    longevity = p_ram_long * 0.35 + p_ssd_long * 0.25 + autonomy * 0.20 + p_cpu * 0.20
    final = feup * 0.50 + gaming * 0.25 + longevity * 0.15 + p_peso * 0.10
    conf, quality_label = quality(spec)
    ranking = round(final * (0.85 + 0.15 * conf), 1)
    value = value_score(ranking, price_value, settings)
    return {
        "status": "ACEITE", "score_final": round(final, 1), "score_ranking": ranking,
        "value_score": value, "qualidade_dados": quality_label,
        "confianca_percentual": f"{int(conf * 100)}%",
        "fontes_extraidas": spec.get("fontes", {}), "alertas": spec.get("alertas", []),
        "detalhes": {
            "marca": spec.get("marca"), "submarca": spec.get("submarca"),
            "teclado_pt": spec.get("teclado_pt"), "FEUP": round(feup, 1),
            "Gaming": round(gaming, 1), "Longevidade": round(longevity, 1),
            "Portabilidade": round(p_peso, 1),
        },
    }

def blocked(r: requests.Response) -> tuple[bool, str | None]:
    if r.status_code in {401, 403, 429}:
        return True, f"HTTP {r.status_code}"
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        title = norm(soup.title.get_text(" ", strip=True) if soup.title else "")
        for n in soup(["script", "style", "noscript"]):
            n.decompose()
        visible = norm(" ".join(soup.stripped_strings))[:20000]
        challenge = (
            "cf-chl-" in title or "cf-chl-" in visible or
            "just a moment" in title or "checking your browser" in visible or
            "verify you are human" in visible or "access denied" in visible or
            "robot check" in visible or "are you a robot" in visible or
            "captcha" in title
        )
        return (True, "challenge") if challenge else (False, None)
    except Exception:
        return False, None

def fetch(url: str, timeout_s: float = 15.0) -> requests.Response | None:
    last = None
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=timeout_s, allow_redirects=True)
            last = r
            is_blocked, why = blocked(r)
            if is_blocked:
                r._v8_block_reason = why
                return r
            if r.status_code < 500:
                return r
        except requests.RequestException as e:
            if attempt == 2:
                print(f"   ❌ {url}: {e}")
        if attempt < 2:
            time.sleep(1 + attempt)
    return last

def same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc

def product_path_ok(url: str, hints: list[str]) -> bool:
    path = urlparse(url).path.lower()
    return any(h.lower() in path for h in hints)

def jsonld_products(soup: BeautifulSoup) -> list[dict]:
    out = []
    for node in soup.find_all("script", type="application/ld+json"):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                typ = item.get("@type")
                if typ in {"Product", "Offer"} or "offers" in item:
                    name = item.get("name")
                    url = item.get("url")
                    offers = item.get("offers")
                    price_value = None
                    available = None
                    if isinstance(offers, dict):
                        price_value = parse_price_value(offers.get("price"))
                        available = norm(offers.get("availability"))
                    else:
                        price_value = parse_price_value(item.get("price"))
                    if name and url:
                        out.append({"titulo": str(name).strip(), "url": str(url), "preco": price_value, "stock": "instock" in (available or "")})
                for v in item.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
    return out

def candidate_from_card(card: BeautifulSoup, base_url: str, cat: dict) -> dict | None:
    text = card.get_text(" ", strip=True)
    title_node = card.select_one("h1,h2,h3,h4,[class*='title'],[class*='name'],a[title]")
    title = (title_node.get("title") or title_node.get_text(" ", strip=True)) if title_node else ""
    if not title or len(title) < 10:
        a = card.select_one("a[href]")
        title = (a.get("title") or a.get_text(" ", strip=True)) if a else ""
    if not title or not eligible(title):
        return None
    p = None
    for selector in cat.get("price_selectors", []) + ["[itemprop='price']", "[data-price]", "[class*='price']", "[class*='Price']"]:
        node = card.select_one(selector)
        if node:
            raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            p = parse_price_value(raw)
            if p is not None:
                break
    if p is None:
        ps = prices(text)
        if ps:
            p = min(ps)
    if p is None or not 200 <= p <= 4500:
        return None
    a = card.select_one("a[href]")
    if not a or not a.get("href"):
        return None
    url = urljoin(base_url, a["href"])
    return {"loja": cat["loja"], "titulo": title.strip(), "preco": p, "url": url, "stock": stock(text) if stock(text) is not None else True}

def discover_category(html: str, cat: dict, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    products = jsonld_products(soup)
    converted = []
    for x in products:
        if eligible(x["titulo"]):
            p = x.get("preco")
            if p and 200 <= p <= 4500:
                converted.append({"loja": cat["loja"], "titulo": x["titulo"], "preco": p, "url": urljoin(cat["url"], x["url"]), "stock": True if x.get("stock") is None else x["stock"]})
    if converted:
        return list({f"{p['loja']}::{p['titulo']}": p for p in converted}.values())[:limit]

    selectors = cat.get("card_selectors") or [
        "article", "li[class*='product']", "div[class*='product-card']", "div[class*='productCard']",
        "div[class*='product-item']", "div[class*='ProductItem']", "div[data-name='product']",
        "div[class*='item-product']", "div[class*='productTile']",
    ]
    cards = soup.select(",".join(selectors))
    seen = set()
    out = []
    for card in cards:
        p = candidate_from_card(card, cat["url"], cat)
        if p:
            key = f"{p['titulo']}::{p['url']}"
            if key not in seen:
                seen.add(key); out.append(p)
                if len(out) >= limit:
                    break

    if len(out) < limit:
        for a in soup.find_all("a", href=True):
            title = a.get("title") or a.get_text(" ", strip=True)
            full_url = urljoin(cat["url"], a["href"])
            if not title or not product_path_ok(full_url, cat.get("product_path_hints", [])) or not eligible(title):
                continue
            parent = a
            for _ in range(int(cat.get("parent_climb", 7))):
                parent = parent.parent
                if parent is None:
                    break
                text = parent.get_text(" ", strip=True)
                ps = prices(text)
                p = min(ps) if ps else None
                if p is not None and 200 <= p <= 4500:
                    item = {"loja": cat["loja"], "titulo": title.strip(), "preco": p, "url": full_url, "stock": stock(text)}
                    key = f"{item['titulo']}::{item['url']}"
                    if key not in seen:
                        seen.add(key); out.append(item)
                    break
            if len(out) >= limit:
                break
    return out[:limit]

def robots_sitemaps(base_url: str) -> list[str]:
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    r = fetch(urljoin(origin, "/robots.txt"), timeout_s=10)
    if not r or r.status_code >= 400:
        return []
    return [line.split(":", 1)[1].strip() for line in r.text.splitlines() if line.lower().startswith("sitemap:")]

def parse_sitemap(url: str, max_children: int = 30) -> list[str]:
    r = fetch(url, timeout_s=12)
    if not r or r.status_code >= 400:
        return []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text, flags=re.I)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    if root.tag.lower().endswith("sitemapindex"):
        return [x.text.strip() for x in root.findall("sm:sitemap/sm:loc", ns)[:max_children] if x.text]
    return [x.text.strip() for x in root.findall("sm:url/sm:loc", ns) if x.text]

def discover_sitemap_products(cat: dict, max_urls: int) -> list[str]:
    candidates = []
    for sm in robots_sitemaps(cat["url"]):
        candidates.extend(parse_sitemap(sm, max_children=25))
        if len(candidates) >= max_urls * 3:
            break
    hints = cat.get("product_path_hints", [])
    filtered = []
    seen = set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        if same_host(u, cat["url"]) and product_path_ok(u, hints):
            filtered.append(u)
            if len(filtered) >= max_urls:
                break
    return filtered

def enrich_product(item: dict) -> tuple[dict, dict]:
    r = fetch(item["url"], timeout_s=14)
    if not r or r.status_code >= 400:
        return item, {"error": f"HTTP {getattr(r, 'status_code', 'ERR')}"}
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    ld = jsonld_products(soup)
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    real_title = (h1.get_text(" ", strip=True) if h1 else "") or page_title
    if ld and ld[0].get("titulo"):
        real_title = ld[0]["titulo"]
    if real_title and len(real_title) >= 8:
        item["titulo"] = real_title
    extracted = extract(item["titulo"], soup)
    p = item.get("preco")
    for x in ld:
        if x.get("preco"):
            p = x["preco"]; break
    if p is None:
        ps = prices(text)
        if ps: p = min(ps)
    item = dict(item)
    if p is not None and 200 <= p <= 4500:
        item["preco"] = p
    st = stock(text)
    if st is not None:
        item["stock"] = st
    extracted["page_url"] = r.url
    return {**item, "specs": extracted, "html_text": text[:50000]}, {"error": None}

def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer,rotating_light") -> None:
    if not NTFY_TOPIC:
        print("⚠️ NTFY_TOPIC não definido.")
        return
    payload = {"topic": NTFY_TOPIC, "title": titulo[:180], "message": mensagem, "tags": [x.strip() for x in tags.split(",") if x.strip()], "priority": 4 if prioridade == "high" else 3}
    try:
        r = requests.post("https://ntfy.sh", json=payload, timeout=15)
        r.raise_for_status()
        print(f"📲 Notificação enviada: {titulo}")
    except requests.RequestException as e:
        print(f"❌ Erro ntfy: {e}")

def tier_from_value(value: float, settings: dict) -> str | None:
    if value >= float(settings.get("diamante_value_min", 130)):
        return "DIAMANTE"
    if value >= float(settings.get("ouro_value_min", 110)):
        return "OURO"
    if value >= float(settings.get("prata_value_min", 90)):
        return "PRATA"
    if value >= float(settings.get("bronze_value_min", 70)):
        return "BRONZE"
    return None

def main() -> None:
    if os.getenv("SMOKE_TEST") == "1":
        assert parse_price_value("1.199,90 €") == 1199.90
        assert gpus("ASUS TUF RTX-5070 Laptop GPU 32GB")[-1] == "rtx 5070"
        assert specs("ASUS TUF F16 RTX 5070 32GB DDR5 1TB SSD 240Hz 90Wh").get("vram_gb") is None
        assert specs("ASUS TUF RTX 5070 8 GB GDDR7").get("vram_gb") == 8
        test_settings = load(CONFIG_PATH).get("settings", {})
        assert value_score(100, 1300, test_settings) == 136.0
        assert tier_from_value(136.0, test_settings) == "DIAMANTE"
        assert value_score(75, 1300, test_settings) == 113.2
        assert tier_from_value(113.2, test_settings) == "OURO"
        assert tier_from_value(69.9, test_settings) is None
        assert tier_from_value(70.0, test_settings) == "BRONZE"
        assert tier_from_value(90.0, test_settings) == "PRATA"
        assert tier_from_value(110.0, test_settings) == "OURO"
        assert tier_from_value(130.0, test_settings) == "DIAMANTE"
        print("OK: V8 estruturada, GPU/RAM/VRAM/TGP/ecrã/bateria, scoring e histórico.")
        return

    config = load(CONFIG_PATH); settings = config.get("settings", {}); weights = config.get("weights", {})
    max_cat = int(settings.get("max_produtos_por_categoria", 30)); max_enrich = int(settings.get("max_enriquecimentos_detalhe", 48))
    max_sitemap = min(80, max(20, max_cat * 2)); require_pt = bool(settings.get("require_pt_keyboard", True))
    budget_hard = float(settings.get("budget_hard", 1500)); min_value = float(settings.get("min_value_score_alerta", 70))
    history = load(HISTORY_PATH); history.setdefault("offers", {})
    all_items: list[dict] = []; loja_stats: dict[str, dict] = {}; errors: dict[str, str | None] = {}

    for cat in config.get("category_urls", []):
        loja = cat["loja"]; stat = {"encontrados": 0, "candidatos": 0, "aceites": 0, "rejeitados": 0, "bloqueada": False}; loja_stats[loja] = stat
        response = fetch(cat["url"], timeout_s=float(cat.get("timeout_ms", 12000)) / 1000); candidates: list[dict] = []
        if response is not None:
            is_blocked, reason = blocked(response)
            if is_blocked:
                stat["bloqueada"] = True; errors[loja] = reason
            elif response.status_code < 400:
                candidates = discover_category(response.text, cat, max_cat)
            else:
                errors[loja] = f"HTTP {response.status_code}"
        else:
            errors[loja] = "sem_resposta"

        if not candidates:
            sitemap_urls = discover_sitemap_products(cat, max_sitemap)
            if sitemap_urls:
                sitemap_candidates = [{"loja": loja, "titulo": url.split("/")[-1].replace("-", " "), "preco": None, "url": url, "stock": None} for url in sitemap_urls]
                with ThreadPoolExecutor(max_workers=min(6, len(sitemap_candidates))) as ex:
                    futures = {ex.submit(enrich_product, x): x for x in sitemap_candidates[:max_enrich]}
                    for fut in as_completed(futures):
                        item, err = fut.result()
                        if not err.get("error") and item.get("preco") and eligible(item.get("titulo", "")):
                            candidates.append(item)
                if candidates:
                    stat["bloqueada"] = False; errors[loja] = None
                elif errors.get(loja) is None:
                    errors[loja] = "sitemap_sem_produtos"

        clean = []; seen = set()
        for item in candidates:
            if item.get("preco") is None or item["preco"] > budget_hard or not item.get("url"):
                continue
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            if eligible(item.get("titulo", "")):
                clean.append(item)
        stat["encontrados"] = len(clean); stat["candidatos"] = len(clean); all_items.extend(clean)

    unique_items = {}
    for item in all_items:
        unique_items.setdefault(f"{item['loja']}::{item['url']}", item)
    enriched: list[dict] = []
    work = list(unique_items.values())[:max_enrich]
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(enrich_product, item): item for item in work}
        for fut in as_completed(futures):
            item, _err = fut.result(); enriched.append(item)

    alerts = 0; tiers = {"DIAMANTE": 0, "OURO": 0, "PRATA": 0, "BRONZE": 0}
    for item in enriched:
        loja = item["loja"]
        if item.get("preco") is None:
            continue
        s = item.get("specs") or specs(item["titulo"])
        if require_pt and s.get("teclado_pt") == "desconhecido":
            continue
        av = score(s, item["preco"], weights, settings)
        if av.get("status") != "ACEITE":
            loja_stats[loja]["rejeitados"] += 1; continue
        loja_stats[loja]["aceites"] += 1
        tier = tier_from_value(av["value_score"], settings)
        if tier: tiers[tier] += 1
        key = f"{loja}::{item['titulo']}"; entries = history["offers"].setdefault(key, []); prev = entries[-1] if entries else None
        entry = {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "price": item["preco"], "stock": item.get("stock"), "score_final": av["score_final"], "score_ranking": av["score_ranking"], "value_score": av["value_score"], "tier": tier, "specs": s, "url": item["url"]}
        entries.append(entry)
        if len(entries) > 30: del entries[:-30]
        if tier and av["value_score"] >= min_value:
            previous_price = prev.get("price") if prev else None
            price_drop = previous_price is not None and item["preco"] <= previous_price - float(settings.get("alerta_queda_preco_eur", 5))
            if previous_price is None or price_drop:
                alerts += 1
                msg = f"{item['titulo']}\nPreço: {item['preco']:.2f}€\nValue: {av['value_score']:.1f} | Rank: {av['score_ranking']:.1f}\nTier: {tier}\n{item['url']}"
                enviar_alerta(f"{tier}: {item['titulo']}", msg, "high" if tier in {"DIAMANTE", "OURO"} else "default")

    save(HISTORY_PATH, history)
    top = sorted(((entries[-1], k) for k, entries in history["offers"].items() if entries), key=lambda x: x[0].get("value_score", 0), reverse=True)[:8]
    print("🔎 TOP oportunidades:")
    for entry, key in top:
        sp = entry.get("specs", {})
        print(f"   {key.split('::',1)[0]} | {entry.get('price', 0):.2f}€ | Rank {entry.get('score_ranking', 0):.1f} | Value {entry.get('value_score', 0):.1f} | {entry.get('tier') or '—'} | {sp.get('gpu_modelo') or sp.get('gpu_tipo')} | {key.split('::',1)[1]}")
    blocked_count = sum(1 for x in loja_stats.values() if x["bloqueada"])
    print(f"📊 V8 | Lojas: {len(loja_stats)} | Bloqueadas: {blocked_count} | Encontrados: {sum(x['encontrados'] for x in loja_stats.values())} | Candidatos: {sum(x['candidatos'] for x in loja_stats.values())} | Enriquecidos: {len(enriched)} | Aceites: {sum(x['aceites'] for x in loja_stats.values())} | Alertas: {alerts} | Diamante: {tiers['DIAMANTE']} | Ouro: {tiers['OURO']} | Prata: {tiers['PRATA']} | Bronze: {tiers['BRONZE']}")
    for k, v in loja_stats.items():
        print(f"🏪 {k}: encontrados={v['encontrados']} candidatos={v['candidatos']} aceites={v['aceites']} rejeitados={v['rejeitados']} bloqueada={v['bloqueada']} erro={errors.get(k)}")

if __name__ == "__main__":
    main()
