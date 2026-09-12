"""Read-only verification of the public getProducts listing operation."""
import json
from urllib.parse import parse_qsl, urlencode
from bs4 import BeautifulSoup
from curl_cffi import requests

base = "https://www.radiopopular.pt"
query = {"filters[category_n2_name][]": "Computadores Portáteis", "filters[disponibilidade][]": "Ocultar Produtos Indisponíveis"}
url = base + "/destaque/6a20120dc7e006.23735122?" + urlencode(query)
r = requests.get(url, timeout=20, impersonate="chrome131")
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")
grid = soup.select_one("[data-products-page][data-products-total]")
assert grid is not None
fields = []
for el in soup.select("#filters .filter-form input[name]"):
    if el.has_attr("disabled") or (el.get("type") in ("checkbox", "radio") and not el.has_attr("checked")):
        continue
    fields.append((el.get("name"), el.get("value", "")))
print("FORM", json.dumps(fields, ensure_ascii=False))
filters = {}
for name, value in fields:
    if name not in ("priceMin", "priceMax"):
        filters.setdefault(name, []).append(value)
print("GRID", {k:v for k,v in grid.attrs.items() if k != "data-products-where"})
for page in (2, 3):
    data = {"method": "getProducts", "page": grid["data-products-page"], "where": grid["data-products-where"],
            "filters": json.dumps(filters, ensure_ascii=False), "order": grid.get("data-products-order", "relevancia asc"),
            "pageNumber": page, "updatedFilters": 0}
    r = requests.post(base + "/ajax", data=data, timeout=20, impersonate="chrome131", headers={"Referer": url})
    print("PAGE_STATUS", page, r.status_code)
    r.raise_for_status()
    payload = r.json()
    html = payload.get("modules") or payload.get("content", {}).get("products", "")
    if not isinstance(html, str):
        print("MODULE_TYPE", type(html).__name__, str(html)[:2000])
        html = ""
    products = BeautifulSoup(html, "html.parser")
    links = sorted({a["href"] for a in products.select('a[href*="/produto/"]')})
    print("PAGE", json.dumps({"page":page, "keys":list(payload), "total":payload.get("total", payload.get("productsTotal")), "current":payload.get("productsCurrent"), "urls":links, "sample":html[:1400]}, ensure_ascii=False))

js = requests.get(base + "/includes/js/rp.js?v=202609091153", timeout=20, impersonate="chrome131").text
import re
for m in list(re.finditer("productsFilters", js))[:15]:
    print("FILTER_JS", js[max(0,m.start()-500):m.start()+600])
