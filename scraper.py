import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "products.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")


def carregar_json(path: Path) -> dict:
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
            # Formato PT: 1.299,99
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
    if any(x in text for x in ["instock", "in stock", "available", "disponivel", "disponível"]):
        return True
    if any(x in text for x in ["outofstock", "out of stock", "soldout", "sold out", "indisponivel", "indisponível", "esgotado"]):
        return False
    return None


def _walk_jsonld(obj: Any, result: dict) -> None:
    if isinstance(obj, dict):
        obj_type = obj.get("@type")
        if isinstance(obj_type, list):
            types = {str(x).lower() for x in obj_type}
        else:
            types = {str(obj_type).lower()}

        if "offer" in types or "aggregateoffer" in types or "product" in types:
            if result["price"] is None and obj.get("price") is not None:
                result["price"] = parse_price_value(obj.get("price"))
            if result["stock"] is None and obj.get("availability") is not None:
                result["stock"] = availability_to_bool(obj.get("availability"))

        for key in ("offers", "offers", "mainEntity"):
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
        if not raw:
            continue
        try:
            data = json.loads(raw)
            _walk_jsonld(data, result)
            if result["price"] is not None and result["stock"] is not None:
                break
        except (json.JSONDecodeError, TypeError):
            continue

    if result["price"] is None:
        for attrs in [
            {"itemprop": "price"},
            {"property": "product:price:amount"},
            {"name": "price"},
        ]:
            node = soup.find("meta", attrs)
            if node and node.get("content"):
                result["price"] = parse_price_value(node.get("content"))
                if result["price"] is not None:
                    break

    if result["stock"] is None:
        for attrs in [
            {"itemprop": "availability"},
            {"property": "product:availability"},
        ]:
            node = soup.find("meta", attrs)
            if node and node.get("content"):
                result["stock"] = availability_to_bool(node.get("content"))
                if result["stock"] is not None:
                    break

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
        negative = [
            "esgotado online", "indisponível", "indisponivel", "fora de stock",
            "sem stock", "out of stock", "sold out"
        ]
        positive = [
            "em stock", "em estoque", "adicionar ao carrinho", "adicionar",
            "comprar", "entrega imediata", "add to cart", "available"
        ]
        if any(x in text for x in negative):
            result["stock"] = False
        elif any(x in text for x in positive):
            result["stock"] = True
        elif result["price"] is not None:
            result["stock"] = True

    return result["price"], result["stock"]


def calcular_categoria(preco: float, rules: dict) -> tuple[str, str, str]:
    if preco <= rules["excellent_max"]:
        return "COMPRA_EXCELENTE", "high", "star"
    if preco <= rules["very_good_max"]:
        return "COMPRA_MUITO_BOA", "high", "white_check_mark"
    if preco <= rules["acceptable_max"]:
        return "PRECO_ACEITAVEL", "default", "information_source"
    if preco <= rules["wait_max"]:
        return "ESPERAR", "default", "hourglass_flowing_sand"
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
        "max_30d": round(max(prices_30), 2) if prices_30 else None,
        "min_historico": round(min(all_prices), 2) if all_prices else None,
        "variacao_media_30d_pct": round((preco_atual / (sum(prices_30) / len(prices_30)) - 1) * 100, 2)
        if prices_30 else None,
    }


def should_alert(previous: Optional[dict], current: dict) -> bool:
    if previous is None:
        return current["stock"] is True and current["category"] in {
            "COMPRA_EXCELENTE", "COMPRA_MUITO_BOA"
        }
    if previous.get("stock") is False and current["stock"] is True:
        return True
    if previous.get("price") is not None and current["price"] < previous["price"] - 1.0:
        return True
    if previous.get("category") != current["category"]:
        return True
    return False


def enviar_alerta(titulo: str, mensagem: str, prioridade: str = "default", tags: str = "computer") -> None:
    if not NTFY_TOPIC:
        print("   => ℹ️ NTFY_TOPIC não configurado; alerta não enviado.")
        return
    try:
        response = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=mensagem.encode("utf-8"),
            headers={
                "Title": titulo.encode("ascii", "ignore").decode("ascii") or "Alerta de Portateis",
                "Tags": tags,
                "Priority": prioridade,
            },
            timeout=15,
        )
        response.raise_for_status()
        print("   => 🚨 Notificação enviada para o Ntfy.")
    except requests.RequestException as exc:
        print(f"   => ❌ Erro Ntfy: {exc}")


async def consultar_oferta(page: Page, oferta: dict) -> tuple[Optional[float], Optional[bool], str]:
    try:
        await page.goto(oferta["url"], timeout=40000, wait_until="domcontentloaded")
    except Exception as exc:
        print(f"   => Aviso na navegação: {exc}")

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    title = await page.title()
    html = await page.content()
    lowered_title = title.lower()
    if "404" in lowered_title or "not found" in lowered_title:
        return None, None, "NOT_FOUND"
    if "just a moment" in lowered_title or "um momento" in lowered_title:
        return None, None, "BLOCKED"

    price, stock = extrair_preco_e_stock(html)
    return price, stock, "OK"


async def main() -> None:
    print("🚀 A iniciar Rastreador V2...")
    config = carregar_json(CONFIG_PATH)
    history = carregar_json(HISTORY_PATH)
    history.setdefault("offers", {})
    rules = config["alert_rules"]

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT",
            extra_http_headers={"Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        page = await context.new_page()

        for product in config["products"]:
            for offer in product["offers"]:
                key = f"{product['product_id']}::{offer['loja']}"
                print(f"\n🔍 {product['nome']} — {offer['loja']}")

                price, stock, status = await consultar_oferta(page, offer)
                if status != "OK":
                    print(f"   => Estado da consulta: {status}")
                    continue
                if price is None:
                    print("   => ❌ Preço não identificado.")
                    continue

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

                print(f"   => Preço: {price:.2f} € | Stock: {stock} | Categoria: {category}")
                if metrics["media_30d"] is not None:
                    print(f"   => Média 30d: {metrics['media_30d']:.2f} € | Mín. 30d: {metrics['min_30d']:.2f} €")

                if should_alert(previous, current) and stock is not False:
                    msg = (
                        f"{product['nome']} — {offer['loja']}\n\n"
                        f"💶 Preço: {price:.2f} €\n"
                        f"📦 Stock: {'🟢 Em stock' if stock else '🔴 Indisponível'}\n"
                        f"🏷️ Classificação: {category.replace('_', ' ')}\n"
                    )
                    if metrics["media_30d"] is not None:
                        msg += f"📊 Média 30d: {metrics['media_30d']:.2f} €\n"
                    if metrics["min_historico"] is not None:
                        msg += f"📉 Mínimo histórico observado: {metrics['min_historico']:.2f} €\n"
                    msg += f"\n🔗 {offer['url']}"
                    enviar_alerta(
                        f"{category.replace('_', ' ')} — {price:.0f} EUR",
                        msg,
                        priority,
                        f"{tag},computer"
                    )

                await asyncio.sleep(2)

        await browser.close()

    guardar_json(HISTORY_PATH, history)
    print("\n✅ Rastreamento concluído e histórico guardado.")


if __name__ == "__main__":
    asyncio.run(main())
