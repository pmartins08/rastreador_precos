"""Bounded decision utilities, not measured FPS or battery predictions."""
import math
import re


def number(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def curve(value, anchors, unknown=60.0):
    if value is None:
        return unknown
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return anchors[-1][1]


def factors(spec, resolution_score):
    light = number(spec.get('ecra_brightness_nits'), 50, 2000)
    if spec.get('ecra_brightness_nits_evidence_status') in {'ambiguous', 'peak_or_combined', 'family_only'}:
        light = None
    brightness = curve(light, [(150, 20), (250, 45), (300, 60), (350, 75), (400, 85), (500, 100)])
    srgb = number(spec.get('ecra_srgb_percent'), 1, 100)
    dci = number(spec.get('ecra_dci_p3_percent'), 1, 100)
    gamut = curve(srgb, [(45, 25), (65, 50), (80, 70), (90, 85), (100, 100)])
    if srgb is None and dci is not None:
        # Separate DCI-P3 utility; never pretend this is an sRGB conversion.
        gamut = curve(dci, [(50, 45), (75, 75), (90, 95), (100, 100)])
    panel_text = str(spec.get('ecra_painel') or '').lower()
    panel = 100 if re.search(r'\boled\b', panel_text) else 85 if re.search(r'\bips\b', panel_text) else 70 if re.search(r'\bva\b', panel_text) else 40 if re.search(r'\btn\b', panel_text) else 60
    size = curve(number(spec.get('ecra_tamanho'), 8, 22), [(10, 30), (13.3, 55), (14, 70), (15, 85), (16, 100), (17, 90), (18, 80)])
    display = resolution_score * .4 + brightness * .2 + gamut * .2 + panel * .1 + size * .1
    tgp = number(spec.get('tgp_w'), 10, 250)
    if spec.get('tgp_evidence_status') in {'ambiguous', 'family_only'}:
        tgp = None
    # Official NVIDIA subsystem power ceilings. Above the reference does not
    # gain extra points; boost/adapter watts cannot inflate the score.
    reference = {'rtx 5050':100, 'rtx 5060':100, 'rtx 5070':100,
                 'rtx 5070 ti':115, 'rtx 5080':150, 'rtx 5090':150}.get(str(spec.get('gpu_modelo') or '').lower())
    utility = .65
    if tgp is not None and reference is not None:
        utility = curve(tgp / reference, [(.3, .15), (.45, .25), (.6, .4), (.8, .75), (1, 1)])
    multiplier = .85 + .15 * utility if spec.get('gpu_tipo') == 'dedicada' else 1.0
    return {'schema':1, 'display_score':round(display, 3), 'resolution':resolution_score,
            'brightness':round(brightness, 3), 'gamut':round(gamut, 3),
            'panel':panel, 'size':round(size, 3), 'tgp_multiplier':round(multiplier, 5),
            'tgp_known':tgp is not None and reference is not None,
            'basis':'decision_utility_not_benchmark',
            'display_total_weights':{'resolution':.04, 'brightness':.02, 'gamut':.02, 'panel':.01, 'size':.01}}
