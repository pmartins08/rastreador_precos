from __future__ import annotations


_INSTALLED = False


def install(tracker_module) -> None:
    """Guarantee that raw Value above the diamond threshold is DIAMANTE.

    Below that threshold, preserve the existing GPU-aware tier logic unchanged.
    This keeps the continuous GPU influence for OURO/PRATA/BRONZE while making
    the requested policy absolute at the top end: raw ``Value > 120`` cannot be
    downgraded from DIAMANTE by an auxiliary tier score.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_tier_from_value = tracker_module.scraper.tier_from_value

    def tier_with_diamond_floor(value, settings):
        raw_value = float(value)
        diamond_min = float(settings.get("diamante_value_min", 120.0))
        if raw_value > diamond_min:
            return "DIAMANTE"
        return previous_tier_from_value(value, settings)

    tracker_module.scraper.tier_from_value = tier_with_diamond_floor
    _INSTALLED = True
