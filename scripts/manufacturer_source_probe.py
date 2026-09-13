"""Smoke live das fontes oficiais Lenovo/HP, sem notificações nem estado."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Carrega exatamente a mesma composição/adaptive_fetch usada pela produção.
import runner  # noqa: F401
import scraper
import tracker
from price_tracker.sources import hp, lenovo


def fetch_live(url: str, config: dict, *, source: str, method: str, timeout_s: float = 10.0):
    response, profile, outcome = tracker.adaptive_fetch(
        url,
        config,
        timeout_s,
        store=source,
        method=method,
    )
    if response is None or response.status_code >= 400 or outcome != "http_success":
        raise RuntimeError(
            f"{source}: acesso falhou | outcome={outcome} | profile={profile} | "
            f"status={getattr(response, 'status_code', None)}"
        )
    return response, profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tracker.LEARNING = tracker.load_learning()
    tracker.REQUESTS_USED = 0
    tracker.REQUESTS_BY_STORE.clear()
    tracker.DETAIL_FETCHES_USED = 0
    tracker.RUN_DEADLINE = 0.0
    config = tracker.load_json(tracker.CONFIG_PATH)

    report: dict[str, dict] = {}

    lenovo_item = {
        "titulo": "Lenovo IdeaPad Slim 3 15ARP10",
        "mpn": "83K700U6SP",
    }
    lenovo_url = lenovo.detail_urls(lenovo_item)[0]
    lenovo_response, lenovo_profile = fetch_live(
        lenovo_url,
        config,
        source=lenovo.SOURCE_NAME,
        method="manufacturer_probe:psref",
        timeout_s=10.0,
    )
    lenovo_ok = lenovo.response_matches(lenovo_response.text, lenovo_item)
    lenovo_spec = scraper.extract(
        lenovo_item["titulo"], BeautifulSoup(lenovo_response.text, "html.parser")
    )
    report["lenovo"] = {
        "url": str(lenovo_response.url),
        "status": lenovo_response.status_code,
        "profile": lenovo_profile,
        "response_length": len(lenovo_response.text or ""),
        "identity_ok": lenovo_ok,
        "cpu": lenovo_spec.get("cpu_modelo"),
        "gpu": lenovo_spec.get("gpu_modelo"),
        "ram_gb": lenovo_spec.get("ram_gb"),
        "storage_tb": lenovo_spec.get("armazenamento_tb"),
        "battery_wh": lenovo_spec.get("bateria_wh"),
    }

    hp_item = {"titulo": "HP Laptop 15-fc0039wm", "mpn": "7W6H7UA"}
    hp_search_url = hp.search_url(hp_item)
    if not hp_search_url:
        raise RuntimeError("HP: não foi possível construir URL typeahead")
    hp_search_response, hp_search_profile = fetch_live(
        hp_search_url,
        config,
        source=hp.SOURCE_NAME,
        method="manufacturer_probe:typeahead",
        timeout_s=8.0,
    )
    hp_matches = hp.typeahead_matches(hp_search_response.text, hp_item)
    print("HP_MATCHES " + json.dumps(hp_matches[:5], ensure_ascii=False), flush=True)
    if not hp_matches:
        raise RuntimeError("HP: typeahead oficial não resolveu o SKU")

    match = hp_matches[0]
    series_oid = match.get("series_oid")
    model_oid = match.get("model_oid")
    spec_urls = hp.spec_urls(hp_search_response.text, hp_item)
    if not series_oid or not model_oid or not spec_urls:
        raise RuntimeError("HP: typeahead sem série/modelo/ficha exata")

    hp_response, hp_detail_profile = fetch_live(
        spec_urls[0],
        config,
        source=hp.SOURCE_NAME,
        method="manufacturer_probe:product_specs",
        timeout_s=12.0,
    )
    hp_ok = hp.response_matches(hp_response.text, hp_item)
    hp_spec = scraper.extract(
        hp_item["titulo"], BeautifulSoup(hp_response.text, "html.parser")
    )
    report["hp"] = {
        "typeahead_url": str(hp_search_response.url),
        "typeahead_status": hp_search_response.status_code,
        "typeahead_profile": hp_search_profile,
        "matches": len(hp_matches),
        "series_oid": series_oid,
        "model_oid": model_oid,
        "url": str(hp_response.url),
        "status": hp_response.status_code,
        "profile": hp_detail_profile,
        "response_length": len(hp_response.text or ""),
        "identity_ok": hp_ok,
        "cpu": hp_spec.get("cpu_modelo"),
        "gpu": hp_spec.get("gpu_modelo"),
        "ram_gb": hp_spec.get("ram_gb"),
        "storage_tb": hp_spec.get("armazenamento_tb"),
        "battery_wh": hp_spec.get("bateria_wh"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("MANUFACTURER_SOURCE_PROBE " + json.dumps(report, ensure_ascii=False), flush=True)

    failures = []
    if not lenovo_ok or not lenovo_spec.get("cpu_modelo") or not lenovo_spec.get("ram_gb"):
        failures.append("Lenovo PSREF não confirmou identidade/specs pelo acesso de produção")
    if not hp_ok or not hp_spec.get("cpu_modelo") or not hp_spec.get("ram_gb"):
        failures.append("HP Support não confirmou identidade/specs pelo acesso de produção")
    if failures:
        raise RuntimeError("; ".join(failures))


if __name__ == "__main__":
    main()
