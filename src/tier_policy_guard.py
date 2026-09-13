from __future__ import annotations


_INSTALLED = False


def install(tracker_module) -> None:
    """Enforce tier thresholds from the raw Value, never an adjusted tier score.

    Other guards may attach metadata (for example GPU-aware ``tier_score``) to a
    float-like Value. That metadata can remain useful for diagnostics/ranking,
    but the commercial tier policy is intentionally simple and global:
    ``Value > 120`` is DIAMANTE according to the configured tier thresholds.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    previous_tier_from_value = tracker_module.scraper.tier_from_value

    def tier_from_raw_value(value, settings):
        # float(...) deliberately strips TierAwareValue/other float subclasses
        # and therefore prevents auxiliary scores from changing the tier.
        return previous_tier_from_value(float(value), settings)

    tracker_module.scraper.tier_from_value = tier_from_raw_value
    _INSTALLED = True
