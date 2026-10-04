"""Explicit purchase constraints; never infer an OS or keyboard from a SKU."""
import re


def enrich_purchase_specs(spec, title, pairs, norm):
    os_evidence = [norm(title)]
    keyboard_evidence = [norm(title)]
    for key, label, value, *_ in pairs:
        if key == 'os':
            os_evidence.append(norm(value))
        if key == 'keyboard':
            keyboard_evidence.append(norm(value))
    missing = any(re.search(r'\b(?:sem (?:sistema operativo|sistema operacional|s[ .]?o)|no os|without os|freedos|free dos|dos)\b', text) for text in os_evidence)
    windows = any(re.search(r'\bwindows\s*(?:10|11)?\b', text) for text in os_evidence)
    spec['os_status'] = 'conflict' if missing and windows else 'none' if missing else 'windows' if windows else 'unknown'
    # Explicit Spanish only: English/unknown/PT are not excluded.
    if any(re.search(r'\b(?:espanhol|espanol|spanish)\b', text) for text in keyboard_evidence):
        spec['keyboard_layout'] = 'es'
    return spec


def installation_cost(spec, settings):
    return max(0.0, float(settings.get('windows_installation_cost_eur', 110.0))) if spec.get('os_status') == 'none' else 0.0


def total_cost(price, installation):
    return round(float(price) + float(installation), 2)
