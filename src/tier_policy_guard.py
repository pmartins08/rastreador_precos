from __future__ import annotations

from decision_truth_runtime_guard import install as install_decision_truth_runtime_guard


_INSTALLED = False


def install(tracker_module) -> None:
    """Guarantee that raw Value above the diamond threshold is DIAMANTE.

    Below that threshold, preserve the existing GPU-aware tier logic unchanged.
    This keeps the continuous GPU influence for OURO/PRATA/BRONZE while making
    the requested policy absolute at the top end: raw ``Value > 120`` cannot be
    downgraded from DIAMANTE by an auxiliary tier score.

    Na V9, quando o tracker completo está disponível, esta mesma composição
    instala também a Decision Truth Layer de runtime. Testes unitários mínimos
    que só expõem ``scraper.tier_from_value`` continuam independentes.
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

    runtime_contract = (
        "record_offer",
        "send_heartbeat",
        "main",
        "LOGGER",
        "load_json",
        "CONFIG_PATH",
    )
    if all(hasattr(tracker_module, name) for name in runtime_contract):
        install_decision_truth_runtime_guard(tracker_module)

    _INSTALLED = True
