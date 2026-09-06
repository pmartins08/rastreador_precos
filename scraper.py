import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "products.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")


def carregar_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def guardar_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)


def parse_price_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                return float(text.replace(".", "").replace(",", "."))
            return float(text.replace(",", ""))
        if "," in text:
            return float(text.replace(".", "").replace(",", "."))
        return float(text)
    except ValueError:
        return None


def availability_to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).lower()
    positive = ["instock", "in stock", "available", "disponivel", "disponível"]
    negative = ["outofstock", "out of stock", "soldout", "sold out", "indisponivel", "indisponível", "esgotado"]
    
    if any(x in text for x in positive):
        return True
    if any(x in text for x in negative):
        return False
    return None


def _walk_jsonld(obj: Any, result: dict) -> None:
    if isinstance(obj, dict):
        obj_type = obj.get("@type")
        types = set()
        if isinstance(obj_type, list):
            types = {str(x).lower() for x in obj_type}
        elif obj_type:
            types = {str(obj_type).lower()}

        if "offer" in types or "aggregateoffer" in types or "product" in types:
            if result["price"] is None and obj.get("price") is not None:
                result["price"] = parse_price_value(obj.get("price"))
            if result["stock"] is None and obj.get("availability") is not None:
                result["stock"] = availability_to_bool(obj.get("availability"))

        for key in ("offers", "itemOffered", "item", "mainEntity"):
            if key in obj:
                _walk_jsonld(obj[key], result)
                
        for value in obj.values():
            if isinstance(value, (dict, list)):
                _walk_jsonld(value, result)
    elif isinstance(obj, list):
        for item in obj:
            _walk_jsonld(item, result)


def extrair_preco_e_stock(html_content: str) -> tuple[Optional[float], Optional[bool]]:
    soup = BeautifulSoup(html_content, "html.parser")
    result = {"price": None, "stock": None}

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw: continue
        try:
            data = json.loads(raw)
            _walk_jsonld(data, result)
            if result["price"] is not None and result["stock"] is not None:
                return result["price"], result["stock"]
        except (json.JSONDecodeError, TypeError):
            continue

    if result["price"] is None:
        for attrs in [{"itemprop": "price"}, {"property": "product:price:amount"}, {"name": "price"}]:
            node = soup.find("meta", attrs)
            if node and node.get("content"):
                result["price"] = parse_price_value(node.get("content"))
                if result["price"] is not None: break

    if result["stock"] is None:
        for attrs in [{"itemprop": "availability"}, {"property": "product:availability"}]:
            node = soup.find("meta", attrs)
            if node and node.get("content"):
                result["stock"] = availability_to_bool(node.get("content"))
                if result["stock"] is not None: break

    if result["price"] is None:
        matches = re.findall(
            r"(?:€\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})|\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d{3,5}(?:,\d{2}))\s*€?",
            html_content,
        )
        prices = [parse_price_value(m) for m in matches]
        valid = [p for p in prices if p is not None and 300 <= p <= 4000]
        if valid:
            result["price"] = min(valid)

    if result["stock"] is None:
        text = soup.get_text(" ", strip=True).lower()
        if any(x in text for x in ["esgotado", "indisponível", "out of stock", "sem stock"]):
            result["stock"] = False
        elif any(x in text for x in ["em stock", "adicionar", "comprar", "available"]):
            result["stock"] = True
        elif result["price"] is not None:
            result["stock"] = True

    return result["price"], result["stock"]


def calcular_categoria(preco: float, rules: dict) -> tuple[str, str, str]:
    if preco <= rules.get("excellent_max", 0): return "COMPRA_EXCELENTE", "high", "star"
    if preco <= rules.get("very_good_max", 0): return "COMPRA_MUITO_BOA", "high", "white_check_mark"
    if preco <= rules.get("acceptable_max", 0): return "PRECO_ACEITAVEL", "default", "information_source"
    if preco <= rules.get("wait_max", 0): return "ESPERAR", "default", "hourglass_flowing_sand"
    return "EVITAR", "low", "warning"


def get_recent_prices(entries: list[dict], days: int = 30) -> list[float]:
    now = datetime.now(timezone.utc)
    result = []
    for entry in entries:
        try:
            dt = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if (now - dt).days <= days and entry.get("price") is not None:
                result.append(float(entry["price"]))
        except (KeyError, ValueError, TypeError):
            continue
    return result


def analisar_historico(entries: list[dict], preco_atual: float) -> dict:
    prices_30 = get_recent_prices(entries, 30)
    all_prices = [float(e["price"]) for e in entries if e.get("price") is not None]
    base = prices_30 or all_prices
    return {
        "media_30d": round(sum(base) / len(base), 2) if base else None,
        "min_30d": round(min(prices_30), 2) if prices_30 else None,
        "min_historico": round(min(all_prices), 2) if all_prices else None,
    }


def should_alert(previous: Optional[dict], current: dict) -> bool:
    if previous is None:
        return current["stock"] is True and current["category"] in {"COMPRA_EXCELENTE", "COMPRA_MUITO_BOA"}
    if previous.get("stock") is False and current["stock"] is True: return True
    if previous.get("price") is not None and current["price"] < previous["price"] - 1.0: return True
    if previous.get("category") != current["category"]: return True
    return False


def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC: return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=mensagem.encode("utf-8"),
            headers={"Title": titulo.encode("ascii", "ignore").decode("ascii"), "Tags": tags, "Priority": prioridade},
            timeout=15,
        ).raise_for_status()
    except requests.RequestException:
        pass


async def consultar_oferta(page: Page, oferta: dict) -> tuple[Optional[float], Optional[bool], str]:
    try:
        await page.goto(oferta["url"], timeout=40000, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    try:
        html = await page.content()
        title = (await page.title()).lower()
    except Exception:
        return None, None, "DOM_ERROR"

    if "404" in title or "not found" in title: return None, None, "NOT_FOUND"
    if "just a moment" in title or "um momento" in title: return None, None, "BLOCKED"

    price, stock = extrair_preco_e_stock(html)
    return price, stock, "OK"


async def processar_produto(context: BrowserContext, sem: asyncio.Semaphore, product: dict, offer: dict, rules: dict, history: dict) -> int:
    key = f"{product['product_id']}::{offer['loja']}"
    
    async with sem:
        page = await context.new_page()
        price, stock, status = await consultar_oferta(page, offer)
        await page.close()

    if status != "OK" or price is None:
        print(f"   => ❌ Falha: {product['nome']} ({offer['loja']}) - Status: {status}")
        return 0

    entries = history["offers"].setdefault(key, [])
    previous = entries[-1] if entries else None
    category, priority, tag = calcular_categoria(price, rules)
    metrics = analisar_historico(entries, price)

    current = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "price": round(price, 2),
        "stock": stock,
        "category": category,
    }
    entries.append(current)
    history["offers"][key] = entries[-180:]

    print(f"   => ✅ Lido: {product['nome']} ({offer['loja']}) | {price:.2f} € | {stock}")

    if should_alert(previous, current) and stock is not False:
        msg = (f"{product['nome']} — {offer['loja']}\n\n💶 Preço: {price:.2f} €\n"
               f"📦 Stock: {'🟢 Em stock' if stock else '🔴 Indisponível'}\n🏷️ Classificação: {category.replace('_', ' ')}\n")
        if metrics.get("media_30d"): msg += f"📊 Média 30d: {metrics['media_30d']:.2f} €\n"
        if metrics.get("min_historico"): msg += f"📉 Mín. Histórico: {metrics['min_historico']:.2f} €\n"
        msg += f"\n🔗 {offer['url']}"
        
        enviar_alerta(f"{category.replace('_', ' ')} — {price:.0f} EUR", msg, priority, f"{tag},computer")
        return 1
    return 0


async def main() -> None:
    print("🚀 A iniciar Rastreador V2 (Concorrente)...")
    config = carregar_json(CONFIG_PATH)
    if not config: return
        
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})
    rules = config.get("alert_rules", {})

    total_ofertas = sum(len(p.get("offers", [])) for p in config.get("products", []))
    alertas_disparados = 0
    sem = asyncio.Semaphore(5) # Limita a 5 abas em simultâneo

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT"
        )

        tasks = []
        for product in config.get("products", []):
            for offer in product.get("offers", []):
                tasks.append(processar_produto(context, sem, product, offer, rules, history))
        
        resultados = await asyncio.gather(*tasks)
        alertas_disparados = sum(resultados)

        await browser.close()

    if alertas_disparados == 0 and total_ofertas > 0:
        enviar_alerta("Rastreio Concluído", f"✅ {total_ofertas} ofertas verificadas.\nSem novas descidas de preço ou alterações de stock.", "min", "mag")
        print("   => ℹ️ Heartbeat enviado (Nenhuma alteração detetada).")

    guardar_json(HISTORY_PATH, history)
    print("\n✅ Rastreamento concluído.")

if __name__ == "__main__":
    asyncio.run(main())
