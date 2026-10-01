"""Evidence and limitations beside Value, never a fabricated watts-to-FPS model."""
from __future__ import annotations

import math
import re


def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and low <= number <= high else None


def enrich(spec, pairs, scraper):
    """Only product spec pairs; never parse unrelated whole-page recommendations.

    Multiple power figures remain ambiguous (e.g. ASUS 55W / 115W).
    Adapter power, battery capacity and HDR peak brightness are not substitutes.
    """
    power, brightness, srgb = set(), set(), set()
    peak_brightness = False
    for key, label, raw, source, *_ in pairs:
        text = scraper.norm(raw)
        label_text = scraper.norm(label)
        if key == "tgp" or (key == "gpu" and re.search(r"\b(?:tgp|dynamic boost)\b", text)) or re.search(r"potencia grafica|max.*graphics power", label_text):
            power.update(float(v.replace(",", ".")) for v in re.findall(r"(\d{2,3}(?:[.,]\d+)?)\s*w\b", text))
        if key in {"screen", "brightness", "panel"}:
            # A combined SDR/HDR field is deliberately left for verification.
            if not re.search(r"\b(?:hdr|peak|pico)\b", text):
                brightness.update(float(v.replace(",", ".")) for v in re.findall(r"(\d{2,4}(?:[.,]\d+)?)\s*(?:nits|cd/m[²2])", text))
            elif re.search(r"nits|cd/m[²2]", text):
                peak_brightness = True
            for pattern in (r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*srgb", r"srgb\s*[:=]?\s*(\d{1,3}(?:[.,]\d+)?)\s*%"):
                srgb.update(float(v.replace(",", ".")) for v in re.findall(pattern, text))
    power = {v for v in power if _number(v, 10, 250) is not None}
    if peak_brightness and not brightness:
        spec["ecra_brightness_nits"] = None
        spec["ecra_brightness_nits_evidence_status"] = "peak_or_combined"
    if power:
        spec["tgp_candidates_w"] = sorted(power)
        spec["tgp_evidence_status"] = "explicit" if len(power) == 1 else "ambiguous"
        spec["tgp_w"] = next(iter(power)) if len(power) == 1 else None
        spec.setdefault("fontes", {})["tgp_w"] = "technical_spec_pairs"
    for field, values, bounds in (
        ("ecra_brightness_nits", brightness, (50, 2000)),
        ("ecra_srgb_percent", srgb, (1, 100)),
    ):
        values = {v for v in values if _number(v, *bounds) is not None}
        if values:
            spec[field] = next(iter(values)) if len(values) == 1 else None
            spec[field + "_evidence_status"] = "explicit" if len(values) == 1 else "ambiguous"
            spec.setdefault("fontes", {})[field] = "technical_spec_pairs"
    return spec


def technical_context(spec):
    tgp = _number(spec.get("tgp_w"), 10, 250)
    power_status = spec.get("tgp_evidence_status") or ("reported" if tgp is not None else "unknown")
    if power_status in {"ambiguous", "family_only"}:
        tgp = None
    brightness = _number(spec.get("ecra_brightness_nits"), 50, 2000)
    gamut = _number(spec.get("ecra_srgb_percent"), 1, 100)
    size = _number(spec.get("ecra_tamanho"), 8, 22)
    warnings = []
    if spec.get("gpu_tipo") == "dedicada":
        warnings.append("Gaming nominal: TGP, RAM e refrigeração não são benchmarks de FPS.")
        if tgp is None:
            warnings.append("TGP por confirmar no SKU exato; não assumir potência de outra variante.")
        elif tgp <= 60:
            warnings.append("TGP até 60 W: não equiparar automaticamente a variantes de maior potência.")
    if brightness is None or gamut is None:
        warnings.append("Brilho/gama de cores incompletos: qualidade do ecrã por confirmar.")
    if gamut is not None and gamut < 90:
        warnings.append("Cobertura sRGB inferior a 90%: compromisso de cor no ecrã integrado.")
    if brightness is not None and brightness < 350:
        warnings.append("Brilho inferior a 350 nits: menos margem em salas muito iluminadas.")
    if size is not None and size < 15:
        warnings.append("Ecrã abaixo de 15 polegadas: menos área física para trabalho sem monitor.")
    return {
        "schema": 1,
        "value_basis": "legacy_nominal_not_benchmark",
        "tgp_w": tgp,
        "tgp_status": power_status,
        "tgp_candidates_w": spec.get("tgp_candidates_w", []),
        "brightness_nits": brightness,
        "srgb_percent": gamut,
        "screen_inches": size,
        "unmodelled": ["tgp_performance", "brightness", "colour_gamut", "thermals", "noise", "measured_battery_life"],
        "warnings": warnings,
    }


def summary(spec):
    context = technical_context(spec)
    power = f"{context['tgp_w']:g} W" if context["tgp_w"] is not None else "por confirmar"
    light = f"{context['brightness_nits']:g} nits" if context["brightness_nits"] is not None else "? nits"
    gamut = f"{context['srgb_percent']:g}% sRGB" if context["srgb_percent"] is not None else "? sRGB"
    return f"TGP: {power} | Ecrã: {light}, {gamut}. Value nominal; não prevê FPS/autonomia."


def install(scraper, tracker):
    if getattr(tracker, "_TECHNICAL_CONTEXT_INSTALLED", False):
        return
    original_extract = scraper.extract
    original_score = tracker.score_allow_unknown

    def extract(title, soup):
        return enrich(original_extract(title, soup), scraper.pairs(soup), scraper)

    def score(spec, price, weights, settings):
        result = original_score(spec, price, weights, settings)
        if result.get("status") == "ACEITE":
            context = technical_context(spec)
            result["technical_context"] = context
            spec["technical_context"] = context
            result["alertas"] = list(dict.fromkeys([*result.get("alertas", []), *context["warnings"]]))
        return result

    scraper.extract = extract
    tracker.score_allow_unknown = score
    tracker._TECHNICAL_CONTEXT_INSTALLED = True
