"""Smoke live das fontes oficiais Lenovo/HP, sem notificações nem estado."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import scraper
from price_tracker.sources import hp, lenovo

UA = "rastreador-precos-source-probe/1.0 (+https://github.com/pmartins08/rastreador_precos)"


def fetch(url: str) -> requests.Response:
    response = requests.get(url, timeout=10, headers={"User-Agent": UA})
    response.raise_for_status()
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report: dict[str, dict] = {}

    lenovo_item = {
        "titulo": "Lenovo IdeaPad Slim 3 15ARP10",
        "mpn": "83K700U6SP",
    }
    lenovo_url = lenovo.detail_urls(lenovo_item)[0]
    lenovo_response = fetch(lenovo_url)
    lenovo_ok = lenovo.response_matches(lenovo_response.text, lenovo_item)
    lenovo_spec = scraper.extract(
        lenovo_item["titulo"], BeautifulSoup(lenovo_response.text, "html.parser")
    )
    report["lenovo"] = {
        "url": str(lenovo_response.url),
        "status": lenovo_response.status_code,
        "identity_ok": lenovo_ok,
        "cpu": lenovo_spec.get("cpu_modelo"),
        "ram_gb": lenovo_spec.get("ram_gb"),
        "storage_tb": lenovo_spec.get("armazenamento_tb"),
        "battery_wh": lenovo_spec.get("bateria_wh"),
    }

    hp_item = {"titulo": "HP Laptop 15-fc0039wm", "mpn": "7W6H7UA"}
    hp_url = (
        "https://support.hp.com/us-en/product/product-specs/"
        "hp-15.6-inch-laptop-pc-15-fc0000/model/2101497693?sku=7W6H7UA"
    )
    hp_response = fetch(hp_url)
    hp_ok = hp.response_matches(hp_response.text, hp_item)
    hp_spec = scraper.extract(
        hp_item["titulo"], BeautifulSoup(hp_response.text, "html.parser")
    )
    report["hp"] = {
        "url": str(hp_response.url),
        "status": hp_response.status_code,
        "identity_ok": hp_ok,
        "cpu": hp_spec.get("cpu_modelo"),
        "ram_gb": hp_spec.get("ram_gb"),
        "storage_tb": hp_spec.get("armazenamento_tb"),
        "battery_wh": hp_spec.get("bateria_wh"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("MANUFACTURER_SOURCE_PROBE " + json.dumps(report, ensure_ascii=False), flush=True)

    failures = []
    if not lenovo_ok or not lenovo_spec.get("cpu_modelo") or not lenovo_spec.get("ram_gb"):
        failures.append("Lenovo PSREF não confirmou identidade/specs")
    if not hp_ok or not hp_spec.get("cpu_modelo") or not hp_spec.get("ram_gb"):
        failures.append("HP Support não confirmou identidade/specs")
    if failures:
        raise RuntimeError("; ".join(failures))


if __name__ == "__main__":
    main()
