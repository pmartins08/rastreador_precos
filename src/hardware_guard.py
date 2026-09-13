from __future__ import annotations

import re

from hardware_catalog import cpu_integrated_gpu, dedicated_gpu_vram_gb, gpu_capability


_CPU_PATTERNS = (
    r"core\s+ultra\s+x[79]\s+(?:processor\s+|processador\s+)?[0-9]{3,4}(?:hx|h|u|v)?(?:\s+plus)?",
    r"core\s+ultra\s+[3579]\s+(?:processor\s+|processador\s+)?[0-9]{3,4}(?:hx|h|u|v)?(?:\s+plus)?",
    r"ryzen\s+ai\s+max\+\s+(?:pro\s+)?[0-9]{3,4}",
    r"ryzen\s+ai\s+max\s+(?:pro\s+)?[0-9]{3,4}",
    r"ryzen\s+ai\s+[3579]\s+(?:hx\s+)?(?:pro\s+)?[0-9]{3,4}[a-z]*",
    r"ryzen\s+[3579]\s+(?:pro\s+)?[0-9]{3,5}[a-z]*",
)

_CATALOG_IGPUS = tuple(
    sorted(
        (
            "intel arc b390",
            "intel arc b370",
            "radeon 8060s",
            "radeon 8050s",
            "radeon 8040s",
            "radeon 890m",
            "radeon 880m",
            "radeon 860m",
            "radeon 840m",
            "radeon 820m",
            "radeon 780m",
            "radeon 760m",
            "radeon 740m",
        ),
        key=len,
        reverse=True,
    )
)

_RAM_VALUES = r"4|8|12|16|24|32|48|64|96|128"

# Algumas fichas oficiais, em particular a Radio Popular, publicam as
# características como sequência label/valor em vez de table/dl. São campos
# explícitos da própria ficha; não há inferência de hardware aqui.
_EXTRA_LINEAR_LABELS = {
    "modelo da placa grafica discreto": "gpu",
    "modelo da placa grafica discreta": "gpu",
    "capacidade da memoria incorporada": "ram",
    "slots de memoria": "ram_slots",
    "tipo de memoria interna": "ram_type",
    "capacidade total de armazenamento": "storage",
    "capacidade total de ssds": "storage",
    "capacidade da drive ssd": "storage",
    "capacidade de bateria": "battery",
    "taxa maxima de actualizacao": "refresh",
    "taxa maxima de atualizacao": "refresh",
    "tipo de painel": "panel",
    "luminosidade": "brightness",
    "tamanho do ecra na diagonal": "screen",
}


def _normalized(text: object, scraper_module) -> str:
    raw = re.sub(r"[™®©℠]", " ", str(text or ""))
    return re.sub(r"\s+", " ", scraper_module.norm(raw)).strip()


def identify_system_ram(text: object, scraper_module) -> int | None:
    """Extrai RAM explícita sem confundir VRAM/GDDR com memória do sistema."""
    value = _normalized(text, scraper_module)
    patterns = (
        rf"\b(?:ram|memoria(?:\s+ram)?|system\s+memory|memory)\s*[:=-]?\s*({_RAM_VALUES})\s*gb\b",
        rf"\b({_RAM_VALUES})\s*gb\s*(?:ram\b|(?:lp)?ddr[345x-]*\b|so-?dimm\b)",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return int(match.group(1))
    return None


def identify_explicit_vram(text: object, scraper_module) -> int | None:
    """Aceita VRAM só quando o contexto é gráfico (GDDR/VRAM/video memory)."""
    value = _normalized(text, scraper_module)
    patterns = (
        r"\b(\d{1,2})\s*gb\s*gddr[567x]*\b",
        r"\b(?:vram|video\s+memory|memoria\s+grafica)\s*[:=-]?\s*(\d{1,2})\s*gb\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return int(match.group(1))
    return None


def _canonical_cpu(model: str) -> str:
    value = re.sub(r"\b(?:processor|processador)\b", " ", model)
    return re.sub(r"\s+", " ", value).strip().lower()


def _cpu_tier(model: str) -> str | None:
    value = model.lower()
    if re.search(r"(?:ultra\s+x9|ultra\s+9|ryzen\s+ai\s+9|ryzen\s+9)", value):
        return "tier_1"
    if re.search(r"(?:ultra\s+x7|ultra\s+7|ryzen\s+ai\s+7|ryzen\s+7)", value):
        return "tier_2"
    if re.search(r"(?:ultra\s+[35]|ryzen\s+ai\s+[35]|ryzen\s+[35])", value):
        return "tier_3"
    return None


def _cpu_class(model: str) -> str | None:
    value = model.lower().strip()
    if re.search(r"(?:\shx\s+\d|\d+hx(?:\s+plus)?$)", value):
        return "hx"
    if re.search(r"\d+h(?:\s+plus)?$", value):
        return "h"
    if re.search(r"\d+[uvp](?:\s+plus)?$", value):
        return "u_ultra"
    return None


def identify_cpu(text: object, scraper_module) -> tuple[str, str | None, str | None] | None:
    value = _normalized(text, scraper_module)
    for pattern in _CPU_PATTERNS:
        match = re.search(pattern, value)
        if not match:
            continue
        model = _canonical_cpu(match.group(0))
        return model, _cpu_tier(model), _cpu_class(model)
    return None


def identify_catalog_igpu(text: object, scraper_module) -> str | None:
    value = _normalized(text, scraper_module)
    for model in _CATALOG_IGPUS:
        if re.search(scraper_module.gp(model), value):
            return model
    return None


def _extra_linear_pairs(soup, scraper_module) -> list[tuple]:
    strings = [str(value).strip() for value in soup.stripped_strings if str(value).strip()]
    normalized = [scraper_module.norm(value) for value in strings]
    out: list[tuple] = []
    values_by_label: dict[str, str] = {}

    for index, label in enumerate(normalized[:-1]):
        values_by_label.setdefault(label, strings[index + 1])
        key = _EXTRA_LINEAR_LABELS.get(label)
        if not key:
            continue
        value = strings[index + 1]
        if key == "screen":
            inch = re.search(r"\((\d{1,2}(?:[.,]\d+)?)\s*\"\)", value)
            if inch:
                value = f"{inch.group(1)} pol"
        out.append((key, strings[index], value, "label_value", 0.96))

    family = values_by_label.get("familia de processador")
    model = values_by_label.get("modelo de processador") or values_by_label.get("modelo do processador")
    if family and model:
        out.append(("cpu", "Família + modelo de processador", f"{family} {model}", "label_value", 0.97))

    vram = values_by_label.get("memoria de placa grafica discreta")
    vram_type = values_by_label.get("tipo de memoria grafica discreta")
    if vram and vram_type:
        out.append(("vram", "Memória gráfica discreta", f"{vram} {vram_type}", "label_value", 0.97))
    return out


def upgrade_spec(spec: dict, scraper_module, title: object = None) -> dict:
    """Melhora identidade de hardware e corrige cache antigo só com evidência forte."""
    if not isinstance(spec, dict):
        return spec

    explicit_ram = identify_system_ram(title, scraper_module)
    if explicit_ram is not None and spec.get("ram_gb") != explicit_ram:
        spec["ram_gb"] = explicit_ram
        spec.setdefault("fontes", {})["ram"] = "hardware_guard_explicit_ram"

    evidence = spec.get("evidencias") if isinstance(spec.get("evidencias"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            title,
            spec.get("cpu_str_original"),
            spec.get("cpu_modelo"),
            *evidence.values(),
        )
    )

    enhanced_cpu = identify_cpu(text, scraper_module)
    if enhanced_cpu:
        model, _tier, cpu_class = enhanced_cpu
        if spec.get("cpu_modelo") != model:
            spec["cpu_modelo"] = model
            spec["cpu_str_original"] = model
            spec.setdefault("fontes", {}).setdefault("cpu", "hardware_catalog")
        if cpu_class is not None:
            spec["cpu_classe"] = cpu_class

    if str(spec.get("gpu_tipo") or "").lower() != "dedicada":
        explicit = identify_catalog_igpu(text, scraper_module)
        inferred = cpu_integrated_gpu(spec.get("cpu_modelo"))
        model = explicit or inferred
        if model:
            spec["gpu_tipo"] = "integrada"
            spec["gpu_modelo"] = model
            detected = list(spec.get("gpu_modelos_detectados") or [])
            if model not in detected:
                detected.append(model)
            spec["gpu_modelos_detectados"] = detected
            source = "hardware_catalog_explicit" if explicit else "hardware_catalog_cpu_map"
            spec.setdefault("fontes", {}).setdefault("gpu_modelo", source)

    # Corrige a direção inversa do bug RAM/VRAM em caches antigos. Primeiro
    # preferimos uma quantidade gráfica explícita; só usamos o catálogo factual
    # quando o modelo Laptop tem uma única configuração publicada pelo fabricante.
    if str(spec.get("gpu_tipo") or "").lower() == "dedicada":
        explicit_vram = identify_explicit_vram(text, scraper_module)
        factual_vram = dedicated_gpu_vram_gb(spec.get("gpu_modelo"))
        target_vram = float(explicit_vram) if explicit_vram is not None else factual_vram
        if target_vram is not None:
            try:
                current_vram = float(spec.get("vram_gb")) if spec.get("vram_gb") is not None else None
            except (TypeError, ValueError):
                current_vram = None
            if current_vram is None or abs(current_vram - float(target_vram)) >= 0.01:
                spec["vram_gb"] = int(target_vram) if float(target_vram).is_integer() else float(target_vram)
                source = "hardware_guard_explicit_vram" if explicit_vram is not None else "hardware_catalog_vram"
                spec.setdefault("fontes", {})["vram"] = source

    capability = gpu_capability(spec.get("gpu_modelo"))
    if capability:
        spec["gpu_capability"] = capability
    return spec


def install(scraper_module, tracker_module) -> None:
    if getattr(tracker_module, "_HARDWARE_GUARD_INSTALLED", False):
        return

    base_cpu = scraper_module.cpu
    base_gpus = scraper_module.gpus
    base_nram = scraper_module.nram
    base_pairs = scraper_module.pairs
    base_score_allow_unknown = tracker_module.score_allow_unknown
    base_select_with_cache = tracker_module.select_with_cache

    def cpu(text: str):
        enhanced = identify_cpu(text, scraper_module)
        return enhanced if enhanced is not None else base_cpu(text)

    def gpus(text: str):
        models, gpu_type, model = base_gpus(text)
        if gpu_type == "dedicada" or model:
            return models, gpu_type, model
        mapped = identify_catalog_igpu(text, scraper_module)
        if mapped:
            return [mapped], "integrada", mapped
        return models, gpu_type, model

    def nram(text: str):
        explicit = identify_system_ram(text, scraper_module)
        return explicit if explicit is not None else base_nram(text)

    def pairs(soup):
        return [*base_pairs(soup), *_extra_linear_pairs(soup, scraper_module)]

    scraper_module.cpu = cpu
    scraper_module.gpus = gpus
    scraper_module.nram = nram
    scraper_module.pairs = pairs

    def score_allow_unknown(spec, price, weights, settings):
        upgrade_spec(spec, scraper_module)
        return base_score_allow_unknown(spec, price, weights, settings)

    def select_with_cache(items, spec_cache, max_items, weights, settings):
        for item in items:
            title = item.get("titulo")
            inline = item.get("specs")
            if isinstance(inline, dict):
                upgrade_spec(inline, scraper_module, title)
            cached = spec_cache.get(item.get("url")) if isinstance(spec_cache, dict) else None
            if isinstance(cached, dict):
                upgrade_spec(cached, scraper_module, title)
        return base_select_with_cache(items, spec_cache, max_items, weights, settings)

    tracker_module.score_allow_unknown = score_allow_unknown
    tracker_module.select_with_cache = select_with_cache
    tracker_module._HARDWARE_GUARD_INSTALLED = True
