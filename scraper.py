from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Universo de produto
# ---------------------------------------------------------------------------

EXCLUDE = {
    "recondicionado",
    "refurbished",
    "usado",
    "outlet",
    "grade a",
    "grade b",
    "grade c",
    "seminovo",
    "open box",
}

BRANDS = {
    "asus": {"rog", "tuf", "vivobook", "zenbook", "expertbook", "proart"},
    "lenovo": {"legion", "loq", "ideapad", "thinkpad", "thinkbook", "yoga"},
    "hp": {"omen", "victus", "omnibook", "elitebook", "probook", "envy", "pavilion"},
}

KPT = [
    "teclado portugues",
    "teclado pt",
    "teclado pt-pt",
    "keyboard portugues",
    "keyboard pt",
    "keyboard pt-pt",
    "layout pt",
    "layout pt-pt",
    "portuguese keyboard",
    "portuguese layout",
    "pt keyboard",
    "pt-pt",
]

KNPT = [
    "teclado espanhol",
    "spanish keyboard",
    "spanish layout",
    "teclado frances",
    "french keyboard",
    "french layout",
    "teclado alemao",
    "german keyboard",
    "german layout",
    "teclado ingles",
    "english keyboard",
    "keyboard us",
    "us keyboard",
    "us layout",
    "en-us keyboard",
    "uk keyboard",
    "uk layout",
    "italian keyboard",
    "italian layout",
    "azerty",
    "qwertz",
]

SNO = [
    "esgotado",
    "fora de stock",
    "out of stock",
    "indisponivel",
    "temporariamente indisponivel",
    "sem stock",
    "unavailable",
    "not available",
    "sold out",
]

SSI = [
    "em stock",
    "em estoque",
    "disponivel",
    "disponibilidade: disponivel",
    "available",
    "in stock",
    "order now",
    "adicionar ao carrinho",
    "adiciona ao carrinho",
    "add to cart",
    "em stock online",
]


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------

GPU_MODELOS = sorted(
    [
        "rtx 5090",
        "rtx 5080",
        "rtx 5070 ti",
        "rtx 5070",
        "rtx 5060 ti",
        "rtx 5060",
        "rtx 5050",
        "rtx 4090",
        "rtx 4080",
        "rtx 4070",
        "rtx 4060",
        "rtx 4050",
        "rtx 3080 ti",
        "rtx 3080",
        "rtx 3070 ti",
        "rtx 3070",
        "rtx 3060",
        "rtx 3050 ti",
        "rtx 3050",
        "rtx 2050",
        "rtx a5500",
        "rtx a5000",
        "rtx a4500",
        "rtx a3000",
        "rtx a2000",
        "radeon rx 7900m",
        "radeon rx 7800m",
        "radeon rx 7700s",
        "radeon rx 7600s",
        "radeon rx 7600m xt",
        "radeon rx 7600m",
        "radeon rx 6850m xt",
        "radeon rx 6800m",
        "radeon rx 6650m",
        "radeon rx 6600m",
        "radeon rx 6550m",
        "radeon rx 6500m",
    ],
    key=len,
    reverse=True,
)

IGPU = [
    "intel iris",
    "intel arc graphics",
    "intel graphics",
    "intel uhd",
    "intel xe",
    "intel xe graphics",
    "intel arc integrated",
    "radeon graphics",
    "radeon 610m",
    "radeon 660m",
    "radeon 680m",
    "radeon 740m",
    "radeon 760m",
    "radeon 780m",
    "radeon 840m",
    "radeon 860m",
    "radeon 880m",
    "radeon 890m",
    "amd radeon graphics",
    "amd integrated graphics",
    "qualcomm adreno",
    "adreno",
]

GPU_GEN = [
    "rtx graphics",
    "rtx discrete",
    "geforce rtx",
    "geforce mx",
    "radeon rx",
    "radeon pro",
]

CPU_PAT = [
    r"core\s+ultra\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"ultra\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"core\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"core\s+i[3579][\s-]+[0-9]{4,5}[a-z]*",
    r"i[3579]-[0-9]{4,5}[a-z]*",
    r"ryzen\s+ai\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"ryzen\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"r[3579]\s+[0-9]{4,5}[a-z]*",
]

ALIASES = {
    "gpu": [
        "gpu",
        "placa grafica",
        "graphics card",
        "graphic card",
        "graphic processor",
        "processador grafico",
        "video card",
        "vga",
        "placa grafica discreta",
        "placa grafica dedicada",
    ],
    "igpu": [
        "placa grafica integrada",
        "onboard graphics",
        "integrated graphics",
        "integrated gpu",
    ],
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


# ---------------------------------------------------------------------------
# Normalização e preços
# ---------------------------------------------------------------------------

_GROUPED_DOT = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_GROUPED_COMMA = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def norm(value: object) -> str:
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", text).lower().strip()


def parse_price_value(value: object) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not raw:
        return None
    try:
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                return float(raw.replace(".", "").replace(",", "."))
            return float(raw.replace(",", ""))
        if _GROUPED_DOT.fullmatch(raw):
            return float(raw.replace(".", ""))
        if _GROUPED_COMMA.fullmatch(raw):
            return float(raw.replace(",", ""))
        if "," in raw:
            return float(raw.replace(".", "").replace(",", "."))
        return float(raw)
    except ValueError:
        return None


def prices(text: str) -> list[float]:
    pattern = re.compile(
        r"(?<!\d)(\d{1,3}(?:[.\s\u00a0]\d{3})+(?:,\d{2})?|\d{1,4}(?:[.,]\d{2})?)\s*€"
    )
    out: list[float] = []
    for raw in pattern.findall(text or ""):
        value = parse_price_value(raw)
        if value is not None and 50 <= value <= 10000:
            out.append(value)
    return out


def best_product_price(
    values: list[float], minimum: float = 200.0, maximum: float = 4500.0
) -> float | None:
    valid = [float(value) for value in values if minimum <= float(value) <= maximum]
    return min(valid) if valid else None


# Guardrail de ingestao: impede que mensalidades/descontos absurdamente baixos
# entrem no ranking como se fossem o preco total do portatil. Nao altera scoring.
GPU_PRICE_SANITY_MIN = {
    "rtx 5090": 1500.0,
    "rtx 5080": 1000.0,
    "rtx 5070 ti": 800.0,
    "rtx 5070": 650.0,
    "rtx 5060 ti": 550.0,
    "rtx 5060": 450.0,
    "rtx 5050": 400.0,
    "rtx 4090": 1200.0,
    "rtx 4080": 900.0,
    "rtx 4070": 600.0,
    "rtx 4060": 450.0,
}


def price_is_plausible_for_title(title: str, price: float) -> bool:
    value = float(price)
    _models, _kind, model = gpus(title)
    floor = GPU_PRICE_SANITY_MIN.get(model)
    return floor is None or value >= floor


# ---------------------------------------------------------------------------
# Elegibilidade e componentes
# ---------------------------------------------------------------------------


def stock(text: str) -> bool | None:
    value = norm(text)
    if any(marker in value for marker in SNO):
        return False
    if any(marker in value for marker in SSI):
        return True
    return None


def brand(text: str) -> tuple[str | None, str | None]:
    value = norm(text)
    for parent, children in BRANDS.items():
        if re.search(rf"\b{re.escape(parent)}\b", value):
            for child in sorted(children, key=len, reverse=True):
                if re.search(rf"\b{re.escape(child)}\b", value):
                    return parent, child
            return parent, None

    for parent, children in BRANDS.items():
        for child in sorted(children, key=len, reverse=True):
            if re.search(rf"\b{re.escape(child)}\b", value):
                return parent, child
    return None, None


def eligible(text: str) -> bool:
    value = norm(text)
    return not any(marker in value for marker in EXCLUDE) and brand(value)[0] in BRANDS


def gp(model: str) -> str:
    return (
        r"(?<![a-z0-9])"
        + r"[\s._-]*".join(re.escape(part) for part in model.split())
        + r"(?![a-z0-9])"
    )


def gpus(text: str) -> tuple[list[str], str, str | None]:
    value = norm(text)
    models = [model for model in GPU_MODELOS if re.search(gp(model), value)]
    if models:
        return models, "dedicada", models[0]
    if any(re.search(gp(marker), value) for marker in GPU_GEN):
        return [], "dedicada", None
    if any(re.search(gp(marker), value) for marker in IGPU):
        return [], "integrada", None
    return [], "desconhecida", None


def cpu(text: str) -> tuple[str | None, str | None, str | None]:
    value = norm(text)
    for pattern in CPU_PAT:
        match = re.search(pattern, value)
        if not match:
            continue
        model = match.group(0)
        tier = (
            "tier_1"
            if re.search(
                r"(?:ultra\s+9|core\s+9(?:\s|$)|core\s+i9(?:[\s-]|$)|\bi9-|ryzen(?:\s+ai)?\s+9|\br9\s)",
                model,
            )
            else "tier_2"
            if re.search(
                r"(?:ultra\s+7|core\s+7(?:\s|$)|core\s+i7(?:[\s-]|$)|\bi7-|ryzen(?:\s+ai)?\s+7|\br7\s)",
                model,
            )
            else "tier_3"
        )
        cpu_class = (
            "hx"
            if model.endswith("hx")
            else "hs"
            if model.endswith("hs")
            else "h"
            if re.search(r"\d+h$", model)
            else "u_ultra"
            if re.search(r"\d+[uvp]$", model)
            else None
        )
        return model, tier, cpu_class
    return None, None, None


def _key(label: str) -> str | None:
    value = norm(label)
    for key, aliases in ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", value) for alias in aliases):
            return key
    return None


def pairs(soup: BeautifulSoup) -> list[tuple]:
    out: list[tuple] = []
    for row in soup.select("table tr"):
        cells = [node for node in row.find_all(["th", "td"]) if node.get_text(" ", strip=True)]
        if len(cells) >= 2:
            label = cells[0].get_text(" ", strip=True)
            key = _key(label)
            if key:
                out.append((key, label, cells[1].get_text(" ", strip=True), "table", 0.98))

    for dt in soup.select("dl dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            label = dt.get_text(" ", strip=True)
            key = _key(label)
            if key:
                out.append((key, label, dd.get_text(" ", strip=True), "dl", 0.98))

    for node in soup.find_all(["li", "div", "p"]):
        label_node = node.select_one("[class*='label'],[class*='name'],[class*='key']")
        value_node = node.select_one("[class*='value'],[class*='detail'],[class*='spec-value']")
        if label_node and value_node and label_node is not value_node:
            label = label_node.get_text(" ", strip=True)
            key = _key(label)
            if key:
                out.append(
                    (
                        key,
                        label,
                        value_node.get_text(" ", strip=True),
                        "label_value",
                        0.92,
                    )
                )
    return out


def best(values: list[tuple]) -> tuple | None:
    return max(values, key=lambda item: item[4]) if values else None


def nram(text: str) -> int | None:
    value = norm(text)
    if re.search(r"vram|memoria grafica|graphics memory|video memory", value):
        return None
    match = re.search(r"\b(4|8|12|16|24|32|48|64|96|128)\s*gb\b", value)
    return int(match.group(1)) if match else None


def nstorage(text: str) -> float | None:
    values = []
    for match in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", norm(text)):
        raw = float(match.group(1).replace(",", "."))
        gb = raw * 1024 if match.group(2) == "tb" else raw
        if 128 <= gb <= 8192:
            values.append(gb)
    return round(max(values) / 1024, 2) if values else None


def _resolution(text: str) -> str | None:
    value = norm(text)
    if re.search(r"2880\s*x\s*1800|3200\s*x\s*2000|2560\s*x\s*1600|qhd\+|2\.8k|3\.2k", value):
        return "qhd+"
    if re.search(r"2560\s*x\s*1440|qhd\b|1440p", value):
        return "qhd"
    if re.search(r"1920\s*x\s*1200|wuxga|fhd\+", value):
        return "fhd+"
    if re.search(r"1920\s*x\s*1080|1080p|full[ -]?hd|\bfhd\b", value):
        return "fhd"
    return None


def specs(text: str) -> dict:
    value = norm(text)
    out = {
        "fontes": {},
        "evidencias": {},
        "conflitos": [],
        "alertas": [],
        "marca": None,
        "submarca": None,
        "gpu_tipo": "desconhecida",
        "gpu_modelo": None,
        "gpu_modelos_detectados": [],
        "cpu_modelo": None,
        "cpu_str_original": None,
        "cpu_classe": None,
        "ram_gb": None,
        "ram_type": None,
        "ram_expansivel": False,
        "armazenamento_tb": None,
        "ssd_expansivel": False,
        "vram_gb": None,
        "tgp_w": None,
        "bateria_wh": None,
        "peso_kg": None,
        "ecra_tamanho": None,
        "ecra_res": None,
        "ecra_painel": None,
        "ecra_hz": None,
        "ecra_brightness_nits": None,
        "teclado_pt": "desconhecido",
    }
    out["marca"], out["submarca"] = brand(value)
    detected, gpu_type, gpu_model = gpus(value)
    out["gpu_tipo"] = gpu_type
    out["gpu_modelo"] = gpu_model
    out["gpu_modelos_detectados"] = detected
    cpu_model, _tier, cpu_class = cpu(value)
    out["cpu_modelo"] = cpu_model
    out["cpu_str_original"] = cpu_model
    out["cpu_classe"] = cpu_class
    out["ram_gb"] = nram(value)
    out["armazenamento_tb"] = nstorage(value)

    match = re.search(r"(\d{1,2})\s*gb\s*gddr\d+", value)
    out["vram_gb"] = int(match.group(1)) if match else None
    match = re.search(r"(?:tgp\s*[:=-]?\s*)?(\d{2,3})\s*w\b", value)
    if match and "tgp" in value[max(0, match.start() - 12) : match.end() + 3]:
        out["tgp_w"] = int(match.group(1))
    match = re.search(r"(\d{2,3})\s*wh\b", value)
    out["bateria_wh"] = int(match.group(1)) if match else None
    match = re.search(r"(\d[.,]\d+)\s*kg\b", value)
    out["peso_kg"] = float(match.group(1).replace(",", ".")) if match else None
    match = re.search(r'(\d{1,2}(?:[.,]\d)?)\s*(?:"|pol|poles|polegadas)\b', value)
    out["ecra_tamanho"] = float(match.group(1).replace(",", ".")) if match else None
    match = re.search(r"(\d{2,3})\s*hz\b", value)
    out["ecra_hz"] = int(match.group(1)) if match else None
    out["ecra_res"] = _resolution(value)
    out["teclado_pt"] = (
        "nao_pt"
        if any(marker in value for marker in KNPT)
        else "confirmado"
        if any(marker in value for marker in KPT)
        else "desconhecido"
    )
    return out


def apply_pair(out: dict, key: str, value: str, source: str) -> None:
    text = norm(value)
    if key == "gpu":
        detected, gpu_type, gpu_model = gpus(value)
        if detected:
            out["gpu_modelos_detectados"] = detected
            out["gpu_modelo"] = gpu_model
            out["gpu_tipo"] = gpu_type
        elif gpu_type == "integrada" and not out.get("gpu_modelo"):
            out["gpu_tipo"] = "integrada"
        elif gpu_type == "dedicada" and not out.get("gpu_modelo"):
            out["gpu_tipo"] = "dedicada"
    elif key == "igpu":
        if not out.get("gpu_modelo"):
            out["gpu_tipo"] = "integrada"
    elif key == "cpu":
        cpu_model, _tier, cpu_class = cpu(value)
        if cpu_model:
            out["cpu_modelo"] = cpu_model
            out["cpu_str_original"] = cpu_model
            out["cpu_classe"] = cpu_class
    elif key == "ram":
        ram = nram(value)
        if ram is not None:
            out["ram_gb"] = ram
    elif key == "ram_type":
        out["ram_type"] = value.strip()
    elif key == "ram_slots":
        out["ram_expansivel"] = True
    elif key == "storage":
        storage = nstorage(value)
        if storage is not None:
            out["armazenamento_tb"] = storage
        if re.search(r"\b(2\s*x|segundo|extra|expansivel|m\.2\s+livre|slot\s+livre)\b", text):
            out["ssd_expansivel"] = True
    elif key == "vram":
        match = re.search(r"(\d{1,2})\s*gb\s*gddr\d+\b", text)
        if match:
            out["vram_gb"] = int(match.group(1))
    elif key == "tgp":
        match = re.search(r"(\d{2,3})\s*w", text)
        if match:
            out["tgp_w"] = int(match.group(1))
    elif key == "battery":
        match = re.search(r"(\d{2,3})\s*wh", text)
        if match:
            out["bateria_wh"] = int(match.group(1))
    elif key == "weight":
        match = re.search(r"(\d[.,]\d+)\s*kg", text)
        if match:
            out["peso_kg"] = float(match.group(1).replace(",", "."))
    elif key in {"resolution", "screen"}:
        resolution = _resolution(text)
        if resolution:
            out["ecra_res"] = resolution
        match = re.search(r'(\d{1,2}(?:[.,]\d)?)\s*(?:"|pol|poles|polegadas)\b', text)
        if match:
            out["ecra_tamanho"] = float(match.group(1).replace(",", "."))
        match = re.search(r"(\d{2,3})\s*hz\b", text)
        if match:
            out["ecra_hz"] = int(match.group(1))
    elif key == "refresh":
        match = re.search(r"(\d{2,3})\s*hz", text)
        if match:
            out["ecra_hz"] = int(match.group(1))
    elif key == "panel":
        out["ecra_painel"] = value.strip()
    elif key == "brightness":
        match = re.search(r"(\d{2,4})\s*(?:nits|cd/m2)", text)
        if match:
            out["ecra_brightness_nits"] = int(match.group(1))
    elif key == "keyboard":
        exact_pt = {
            "pt",
            "pt-pt",
            "portugues",
            "portuguese",
            "portugal",
            "portugues portugal",
            "portuguese portugal",
        }
        out["teclado_pt"] = (
            "nao_pt"
            if any(marker in text for marker in KNPT)
            else "confirmado"
            if text in exact_pt or bool(re.search(r"\b(?:pt|pt-pt)\b", text))
            else out["teclado_pt"]
        )
    out["evidencias"][key] = value
    out["fontes"][key] = source


def extract(title: str, soup: BeautifulSoup) -> dict:
    out = specs(title)
    by: dict[str, list[tuple]] = {}
    for item in pairs(soup):
        by.setdefault(item[0], []).append(item)

    for key in [
        "gpu",
        "igpu",
        "cpu",
        "ram",
        "storage",
        "vram",
        "tgp",
        "battery",
        "weight",
        "resolution",
        "screen",
        "refresh",
        "brightness",
        "panel",
        "keyboard",
        "ram_type",
        "ram_slots",
        "m2",
    ]:
        chosen = best(by.get(key, []))
        if not chosen:
            continue
        apply_pair(out, key, chosen[2], chosen[3])
        if key == "m2":
            evidence = norm(f"{chosen[1]} {chosen[2]}")
            if re.search(
                r"(?:2\s*x\s*m\.2|2\s+slots?\s+m\.2|slot\s+m\.2\s+livre|m\.2\s+livre|segundo\s+m\.2|extra)",
                evidence,
            ):
                out["ssd_expansivel"] = True

    page_text = soup.get_text(" ", strip=True)
    fallback = specs(title)
    for field in [
        "gpu_modelo",
        "gpu_tipo",
        "cpu_modelo",
        "cpu_str_original",
        "cpu_classe",
        "ram_gb",
        "armazenamento_tb",
        "vram_gb",
        "tgp_w",
        "bateria_wh",
        "peso_kg",
        "ecra_tamanho",
        "ecra_res",
        "ecra_hz",
        "teclado_pt",
    ]:
        if out.get(field) in (None, "desconhecida", "desconhecido") and fallback.get(field) not in (
            None,
            "desconhecida",
            "desconhecido",
        ):
            out[field] = fallback[field]
            out["fontes"][field] = "titulo_fallback"

    if out.get("teclado_pt") == "desconhecido":
        text = norm(page_text)
        if re.search(r"teclado.{0,80}\b(?:pt|pt-pt|portugues|portuguese|portugal)\b", text):
            out["teclado_pt"] = "confirmado"
            out["fontes"]["teclado_pt"] = "contexto_texto"
        elif re.search(
            r"teclado.{0,80}\b(?:espanhol|spanish|frances|french|alemao|german|ingles|english|azerty|qwertz)\b",
            text,
        ):
            out["teclado_pt"] = "nao_pt"
            out["fontes"]["teclado_pt"] = "contexto_texto"
    return out


# ---------------------------------------------------------------------------
# Cérebro V8: scoring preservado
# ---------------------------------------------------------------------------


def quality(spec: dict) -> tuple[float, str]:
    score_value = 0.0
    score_value += 0.20 if spec.get("cpu_modelo") else 0.0
    score_value += 0.20 if spec.get("gpu_tipo") != "desconhecida" else 0.0
    if spec.get("ram_gb"):
        score_value += (
            0.20
            if spec.get("fontes", {}).get("ram") in {"table", "dl", "label_value"}
            else 0.14
        )
    for field, weight in [
        ("bateria_wh", 0.10),
        ("peso_kg", 0.10),
        ("ecra_res", 0.10),
        ("ecra_hz", 0.10),
    ]:
        if spec.get(field) is not None:
            score_value += weight
    return (
        score_value,
        "ALTA" if score_value >= 0.85 else "MEDIA" if score_value >= 0.50 else "BAIXA",
    )


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
    # Layout do teclado é apenas informativo; preservar a evidência do parser.
    if spec.get("ram_gb") == 8:
        return {"status": "REJEITADO", "alertas": ["8GB RAM confirmado - insuficiente."]}
    if spec.get("peso_kg") and spec["peso_kg"] > 2.8:
        return {"status": "REJEITADO", "alertas": ["Excede limite de peso (>2.8kg)."]}

    ram = spec.get("ram_gb")
    p_ram = 50 if ram is None else 100 if ram >= 32 else 80 if ram >= 16 else 40
    storage = spec.get("armazenamento_tb")
    p_ssd = 50 if storage is None else 100 if storage >= 2 else 85 if storage >= 1 else 65
    p_res = {"qhd+": 100, "qhd": 95, "fhd+": 85, "fhd": 75, None: 60}.get(
        spec.get("ecra_res"), 60
    )
    p_hz = min(100, (spec.get("ecra_hz") or 60) / 1.65)
    _cpu_model, cpu_tier, _cpu_class = cpu(spec.get("cpu_modelo", ""))
    p_cpu = weights.get(
        "cpu_base", {"tier_1": 100, "tier_2": 85, "tier_3": 70}
    ).get(cpu_tier, 50)
    penalty = {"u_ultra": 0, "hs": 5, "h": 10, "hx": 20, None: 10}
    autonomy = (
        50
        if spec.get("bateria_wh") is None
        else max(
            0,
            min(100, spec["bateria_wh"] / 90 * 100)
            - penalty.get(spec.get("cpu_classe"), 10),
        )
    )

    gpu_base = weights.get("gpu_base", {})
    if spec.get("gpu_tipo") == "dedicada":
        p_gpu = gpu_base.get(spec.get("gpu_modelo"), 50)
    elif spec.get("gpu_tipo") == "integrada":
        p_gpu = 15
    else:
        p_gpu = 30

    weight = spec.get("peso_kg")
    if weight is None:
        p_weight = 50
    elif weight <= 1.4:
        p_weight = 100
    elif weight >= 2.8:
        p_weight = 0
    else:
        p_weight = max(0, 100 - ((weight - 1.4) * 71.4))

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

    expandable = spec.get("ssd_expansivel")
    if storage is None:
        p_ssd_long = 50
    elif storage >= 2 or (storage == 1 and expandable):
        p_ssd_long = 100
    elif storage == 1:
        p_ssd_long = 85
    elif storage == 0.5 and expandable:
        p_ssd_long = 75
    elif storage == 0.5:
        p_ssd_long = 65
    else:
        p_ssd_long = 50

    feup = p_ram * 0.20 + autonomy * 0.30 + p_ssd * 0.15 + p_res * 0.20 + p_cpu * 0.15
    gaming = p_gpu * 0.65 + p_cpu * 0.20 + p_hz * 0.10 + p_ram * 0.05
    longevity = p_ram_long * 0.35 + p_ssd_long * 0.25 + autonomy * 0.20 + p_cpu * 0.20
    final = feup * 0.50 + gaming * 0.25 + longevity * 0.15 + p_weight * 0.10
    confidence, quality_label = quality(spec)
    ranking = round(final * (0.85 + 0.15 * confidence), 1)
    value = value_score(ranking, price_value, settings)

    return {
        "status": "ACEITE",
        "score_final": round(final, 1),
        "score_ranking": ranking,
        "value_score": value,
        "qualidade_dados": quality_label,
        "confianca_percentual": f"{int(confidence * 100)}%",
        "fontes_extraidas": spec.get("fontes", {}),
        "alertas": spec.get("alertas", []),
        "detalhes": {
            "marca": spec.get("marca"),
            "submarca": spec.get("submarca"),
            "teclado_pt": spec.get("teclado_pt"),
            "FEUP": round(feup, 1),
            "Gaming": round(gaming, 1),
            "Longevidade": round(longevity, 1),
            "Portabilidade": round(p_weight, 1),
        },
    }


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


# ---------------------------------------------------------------------------
# Structured data e descoberta de catálogo
# ---------------------------------------------------------------------------


def same_host(a: str, b: str) -> bool:
    def host(value: str) -> str:
        return urlparse(value).netloc.lower().removeprefix("www.")

    return host(a) == host(b)


def product_path_ok(url: str, hints: list[str]) -> bool:
    path = urlparse(url).path.lower()
    return any(str(hint).lower() in path for hint in hints)


def _types(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item).lower() for item in value}
    return {str(value).lower()} if value is not None else set()


def _offer_candidates(offers: object) -> list[dict]:
    if isinstance(offers, dict):
        if isinstance(offers.get("@graph"), list):
            return [item for item in offers["@graph"] if isinstance(item, dict)]
        return [offers]
    if isinstance(offers, list):
        return [item for item in offers if isinstance(item, dict)]
    return []


def _availability(value: object) -> bool | None:
    text = str(value or "").lower()
    if not text:
        return None
    if any(marker in text for marker in ("outofstock", "soldout", "discontinued")):
        return False
    if any(marker in text for marker in ("instock", "limitedavailability", "preorder")):
        return True
    return None


def jsonld_products(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str, float | None]] = set()
    for node in soup.find_all("script", type="application/ld+json"):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_types = _types(item.get("@type"))
            is_product = "product" in item_types or "offers" in item
            is_offer = "offer" in item_types
            if is_product or is_offer:
                name = item.get("name")
                item_url = item.get("url")
                price = parse_price_value(item.get("price"))
                available = _availability(item.get("availability"))
                for offer in _offer_candidates(item.get("offers")):
                    offer_price = parse_price_value(
                        offer.get("price") or offer.get("lowPrice") or offer.get("highPrice")
                    )
                    if offer_price is not None:
                        price = offer_price
                    if not item_url and offer.get("url"):
                        item_url = offer.get("url")
                    offer_stock = _availability(offer.get("availability"))
                    if offer_stock is not None:
                        available = offer_stock
                    if not name and offer.get("name"):
                        name = offer.get("name")
                    if price is not None:
                        break

                if name and item_url:
                    record = {
                        "titulo": str(name).strip(),
                        "url": str(item_url).strip(),
                        "preco": price,
                        "stock": available,
                        "sku": item.get("sku") or item.get("productID"),
                        "mpn": item.get("mpn"),
                        "ean": (
                            item.get("gtin13")
                            or item.get("gtin14")
                            or item.get("gtin12")
                            or item.get("gtin")
                        ),
                    }
                    marker = (record["titulo"], record["url"], record["preco"])
                    if marker not in seen:
                        seen.add(marker)
                        out.append(record)

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            for key, child in item.items():
                if key != "@graph" and isinstance(child, (dict, list)):
                    stack.append(child)
    return out


DEFAULT_CARD_SELECTORS = [
    "article",
    "li[class*='product']",
    "div[class*='product-card']",
    "div[class*='productCard']",
    "div[class*='product-item']",
    "div[class*='ProductItem']",
    "div[data-name='product']",
    "div[class*='item-product']",
    "div[class*='productTile']",
]


def _product_link(card: BeautifulSoup, base_url: str, cat: dict):
    hints = cat.get("product_path_hints", [])
    fallback = None
    for anchor in card.find_all("a", href=True):
        full_url = urljoin(base_url, anchor["href"])
        if fallback is None and same_host(full_url, base_url):
            fallback = (anchor, full_url)
        if same_host(full_url, base_url) and product_path_ok(full_url, hints):
            return anchor, full_url
    return fallback or (None, None)


def _title(card: BeautifulSoup, anchor) -> str:
    node = card.select_one("h1,h2,h3,h4,[class*='title'],[class*='name'],a[title]")
    if node:
        title = node.get("title") or node.get_text(" ", strip=True)
        if title and len(title.strip()) >= 6:
            return title.strip()
    if anchor:
        title = anchor.get("title") or anchor.get_text(" ", strip=True)
        if title:
            return title.strip()
    return ""


def _card_prices(card: BeautifulSoup, cat: dict) -> list[float]:
    values: list[float] = []
    selectors = cat.get("price_selectors", []) + [
        "[itemprop='price']",
        "[data-price]",
        "[class*='price']",
        "[class*='Price']",
    ]
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in card.select(selector):
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            raw_text = norm(raw)
            class_text = norm(" ".join(node.get("class", [])))
            if any(
                marker in f"{class_text} {raw_text}"
                for marker in ("month", "mensal", "prestacao", "/ mes", "/mes", "por mes")
            ):
                continue
            direct = parse_price_value(raw)
            if direct is not None:
                values.append(direct)
            values.extend(prices(str(raw)))
    if not values:
        values.extend(prices(card.get_text(" ", strip=True)))
    return values


def candidate_from_card(card: BeautifulSoup, base_url: str, cat: dict) -> dict | None:
    anchor, url = _product_link(card, base_url, cat)
    title = _title(card, anchor)
    if not url or not title or not eligible(title):
        return None
    price = best_product_price(_card_prices(card, cat))
    if price is None or not price_is_plausible_for_title(title, price):
        return None
    text = card.get_text(" ", strip=True)
    return {
        "loja": cat["loja"],
        "titulo": title,
        "preco": price,
        "url": url,
        "stock": stock(text),
    }


def _add_candidate(out: list[dict], seen: set[str], item: dict, limit: int) -> None:
    url = item.get("url")
    if not url or url in seen or len(out) >= limit:
        return
    seen.add(url)
    out.append(item)


def discover_category(html: str, cat: dict, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()

    for record in jsonld_products(soup):
        if len(out) >= limit:
            break
        title = record.get("titulo") or ""
        price = record.get("preco")
        url = urljoin(cat["url"], record.get("url") or "")
        if (
            eligible(title)
            and price is not None
            and 200 <= float(price) <= 4500
            and same_host(url, cat["url"])
        ):
            _add_candidate(
                out,
                seen,
                {
                    "loja": cat["loja"],
                    "titulo": title.strip(),
                    "preco": float(price),
                    "url": url,
                    "stock": record.get("stock"),
                },
                limit,
            )

    selectors = cat.get("card_selectors") or DEFAULT_CARD_SELECTORS
    for card in soup.select(",".join(selectors)):
        if len(out) >= limit:
            break
        item = candidate_from_card(card, cat["url"], cat)
        if item:
            _add_candidate(out, seen, item, limit)

    if len(out) < limit:
        hints = cat.get("product_path_hints", [])
        for anchor in soup.find_all("a", href=True):
            if len(out) >= limit:
                break
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            full_url = urljoin(cat["url"], anchor["href"])
            if (
                not title
                or not same_host(full_url, cat["url"])
                or not product_path_ok(full_url, hints)
                or not eligible(title)
                or full_url in seen
            ):
                continue
            parent = anchor
            for _ in range(int(cat.get("parent_climb", 7))):
                parent = parent.parent
                if parent is None:
                    break
                price = best_product_price(prices(parent.get_text(" ", strip=True)))
                if price is None:
                    continue
                _add_candidate(
                    out,
                    seen,
                    {
                        "loja": cat["loja"],
                        "titulo": title.strip(),
                        "preco": price,
                        "url": full_url,
                        "stock": stock(parent.get_text(" ", strip=True)),
                    },
                    limit,
                )
                break
    return out[:limit]
