from __future__ import annotations

import re


CPU_PATTERNS = [
    r"core\s+ultra\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"core\s+[3579]\s+[0-9]{3,5}[a-z]*",
    r"core\s+i[3579][\s-]+[0-9]{4,5}[a-z]*",
    r"i[3579]-[0-9]{4,5}[a-z]*",
    r"ryzen(?:\s+ai)?\s+[3579]\s+[0-9]{3,5}[a-z]*",
]


def cpu(text: str, normalizer) -> tuple[str | None, str | None, str | None]:
    """Classifica CPU mantendo os tiers V8, mas cobrindo grafias reais como i7-1255U."""
    normalized = normalizer(text)
    for pattern in CPU_PATTERNS:
        match = re.search(pattern, normalized)
        if not match:
            continue
        model = match.group(0)

        tier = (
            "tier_1"
            if re.search(r"(?:ultra\s+9|core\s+i9(?:[\s-]|$)|\bi9-|ryzen(?:\s+ai)?\s+9)", model)
            else "tier_2"
            if re.search(r"(?:ultra\s+7|core\s+i7(?:[\s-]|$)|\bi7-|ryzen(?:\s+ai)?\s+7)", model)
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
