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
    response = requests.get(url, timeout=12, headers={"User-Agent": UA})
    response.raise_for_status()
    return response


def post(url: str, payload: dict) -> requests.Response:
    response = requests.post(
        url,
        json=payload,
        timeout=12,
        headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"},
    )
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
    hp_search_url = hp.search_url(hp_item)
    if not hp_search_url:
        raise RuntimeError("HP: não foi possível construir URL typeahead")
    hp_search_response = fetch(hp_search_url)
    hp_matches = hp.typeahead_matches(hp_search_response.text, hp_item)
    print("HP_MATCHES " + json.dumps(hp_matches[:5], ensure_ascii=False), flush=True)
    if not hp_matches:
        raise RuntimeError("HP: typeahead oficial não resolveu o SKU")

    match = hp_matches[0]
    series_oid = match.get("series_oid") or match.get("product_id")
    model_oid = match.get("product_id")
    if not series_oid:
        raise RuntimeError("HP: typeahead sem OID de série/modelo")

    category_response = post(
        "https://support.hp.com/wcc-services/pdp/category?type=all",
        {
            "seriesOid": str(series_oid),
            "modelOid": str(model_oid) if model_oid else None,
            "isMobile": False,
            "cc": "us",
            "lc": "en",
            "productAttributes": [],
        },
    )
    category_json = category_response.json()
    categories = ((category_json.get("data") or {}).get("categories") or [])
    print("HP_CATEGORIES " + json.dumps(categories, ensure_ascii=False)[:5000], flush=True)
    spec_category = next(
        (
            row
            for row in categories
            if str(row.get("seoName") or row.get("seoname") or "").lower() == "product-specs"
        ),
        None,
    )
    if not spec_category:
        raise RuntimeError("HP: API não devolveu categoria product-specs")
    tms_id = spec_category.get("tmsId") or spec_category.get("tmsID")
    if not tms_id:
        raise RuntimeError("HP: categoria product-specs sem tmsId")

    details_response = post(
        "https://support.hp.com/wcc-services/pdp/category-details",
        {
            "tmsId": str(tms_id),
            "cc": "us",
            "lc": "en",
            "seriesOid": str(series_oid),
            "modelOid": str(model_oid or ""),
        },
    )
    details_json = details_response.json()
    print("HP_SPEC_DETAILS " + json.dumps(details_json, ensure_ascii=False)[:12000], flush=True)

    report["hp"] = {
        "typeahead_status": hp_search_response.status_code,
        "matches": len(hp_matches),
        "series_oid": series_oid,
        "model_oid": model_oid,
        "category_status": category_response.status_code,
        "details_status": details_response.status_code,
        "spec_category": spec_category,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("MANUFACTURER_SOURCE_PROBE " + json.dumps(report, ensure_ascii=False), flush=True)

    if not lenovo_ok or not lenovo_spec.get("cpu_modelo") or not lenovo_spec.get("ram_gb"):
        raise RuntimeError("Lenovo PSREF não confirmou identidade/specs")


if __name__ == "__main__":
    main()
