from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Padrao nao encontrado: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# scraper.py — precos de cartao: ignorar descontos/mensalidades sem perder
# cartoes cujo preco nao tem uma classe CSS especifica.
# ---------------------------------------------------------------------------
path = ROOT / "scraper.py"
text = path.read_text(encoding="utf-8")
old = '''def _card_prices(card: BeautifulSoup, cat: dict) -> list[float]:
    values: list[float] = []
    selectors = cat.get("price_selectors", []) + [
        "[itemprop='price']",
        "[data-price]",
        "[class*='price']",
        "[class*='Price']",
    ]
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in card.select(selector):
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            raw_text = norm(raw)
            class_text = norm(" ".join(node.get("class", [])))
            if any(
                marker in f"{class_text} {raw_text}"
                for marker in ("month", "mensal", "prestacao", "/ mes", "/mes", "por mes")
            ):
                continue
            direct = parse_price_value(raw)
            if direct is not None:
                values.append(direct)
            values.extend(prices(str(raw)))
    if not values:
        values.extend(prices(card.get_text(" ", strip=True)))
    return values
'''
new = '''PRICE_NOISE_MARKERS = (
    "discount", "desconto", "saving", "savings", "poupanca", "poupa", "cashback",
    "voucher", "cupao", "coupon", "month", "mensal", "prestacao", "installment",
    "financiamento", "finance", "/ mes", "/mes", "por mes",
)


def _price_node_context(node, raw: object) -> str:
    parts = [str(raw or "")]
    current = node
    for _ in range(3):
        if current is None or not hasattr(current, "get"):
            break
        parts.extend([
            " ".join(current.get("class", [])),
            str(current.get("id") or ""),
            str(current.get("aria-label") or ""),
            str(current.get("title") or ""),
        ])
        current = getattr(current, "parent", None)
    return norm(" ".join(parts))


def _price_node_is_noise(node, raw: object) -> bool:
    raw_string = str(raw or "").strip()
    if re.match(r"^[\\-−–—]\\s*\\d", raw_string):
        return True
    context = _price_node_context(node, raw)
    return any(marker in context for marker in PRICE_NOISE_MARKERS)


def _append_price_values(values: list[float], raw: object) -> None:
    direct = parse_price_value(raw)
    if direct is not None:
        values.append(direct)
    values.extend(prices(str(raw)))


def _card_prices(card: BeautifulSoup, cat: dict) -> list[float]:
    values: list[float] = []
    selectors = cat.get("price_selectors", []) + [
        "[itemprop='price']",
        "[data-price]",
        "[class*='price']",
        "[class*='Price']",
    ]
    seen_nodes: set[int] = set()
    for selector in selectors:
        for node in card.select(selector):
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            raw = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            if _price_node_is_noise(node, raw):
                continue
            _append_price_values(values, raw)

    # Fallback conservador para lojas cujo preco aparece como texto simples.
    # Analisa apenas nos com simbolo de euro e nunca o texto inteiro do cartao.
    if not values:
        for string in card.find_all(string=re.compile(r"€")):
            node = string.parent
            raw = str(string).strip()
            if _price_node_is_noise(node, raw):
                continue
            _append_price_values(values, raw)
    return values
'''
text = replace_once(text, old, new, "card price parser")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# tracker.py — fallback contextual de preco de ficha para PCDiga e semelhantes
# ---------------------------------------------------------------------------
path = ROOT / "tracker.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'VERSION = "8.7.1"', 'VERSION = "8.7.2"', "version")
text = replace_once(
    text,
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7", "8.7.1"}',
    'COMPATIBLE_STATE_VERSIONS = {"8.5", "8.6", "8.6.1", "8.7", "8.7.1", "8.7.2"}',
    "compatible versions",
)
old = '''def preferred_page_price(soup: BeautifulSoup, structured_price: float | None = None) -> float | None:
    """Preco de produto por sinais fortes; nunca usa o menor euro da pagina inteira."""
    selectors = [
        "meta[itemprop='price'][content]",
        "meta[property='product:price:amount'][content]",
        "meta[property='og:price:amount'][content]",
        "[itemprop='offers'] [itemprop='price']",
        "[data-price-type='finalPrice'] [data-price-amount]",
        "[data-price-type='finalPrice']",
        "[class*='current-price']",
        "[class*='currentPrice']",
        "[class*='price-current']",
        "[class*='priceCurrent']",
        "[class*='final-price']",
        "[class*='finalPrice']",
        "[class*='special-price']",
        "[class*='sale-price']",
    ]
    bad = (
        "discount", "desconto", "saving", "poupanca", "poupa", "cashback",
        "voucher", "cupao", "coupon", "mensal", "prestacao", "installment",
        "financiamento", "finance", "old-price", "oldprice", "preco antigo",
    )
    values = []
    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            context = scraper.norm(
                " ".join([
                    " ".join(node.get("class", [])),
                    str(node.get("id") or ""),
                    node.get_text(" ", strip=True),
                ])
            )
            if any(token in context for token in bad):
                continue
            raw = (
                node.get("content")
                or node.get("data-price-amount")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            direct = scraper.parse_price_value(raw)
            if direct is not None and 200 <= direct <= 10000:
                values.append(float(direct))
                continue
            values.extend(v for v in scraper.prices(str(raw)) if 200 <= v <= 10000)
    if values:
        return min(values)
    if structured_price is not None and 200 <= float(structured_price) <= 10000:
        return float(structured_price)
    return None
'''
new = '''def _page_price_noise(node, raw: object) -> bool:
    raw_string = str(raw or "").strip()
    if re.match(r"^[\\-−–—]\\s*\\d", raw_string):
        return True
    parts = [raw_string]
    current = node
    for _ in range(3):
        if current is None or not hasattr(current, "get"):
            break
        parts.extend([
            " ".join(current.get("class", [])),
            str(current.get("id") or ""),
            str(current.get("aria-label") or ""),
            str(current.get("title") or ""),
        ])
        current = getattr(current, "parent", None)
    context = scraper.norm(" ".join(parts))
    bad = (
        "discount", "desconto", "saving", "savings", "poupanca", "poupa", "cashback",
        "voucher", "cupao", "coupon", "mensal", "prestacao", "installment",
        "financiamento", "finance", "old-price", "oldprice", "preco antigo",
    )
    return any(token in context for token in bad)


def preferred_page_price(soup: BeautifulSoup, structured_price: float | None = None) -> float | None:
    """Preco de produto por sinais fortes + fallback contextual seguro."""
    selectors = [
        "meta[itemprop='price'][content]",
        "meta[property='product:price:amount'][content]",
        "meta[property='og:price:amount'][content]",
        "[itemprop='offers'] [itemprop='price']",
        "[data-price-type='finalPrice'] [data-price-amount]",
        "[data-price-type='finalPrice']",
        "[class*='current-price']",
        "[class*='currentPrice']",
        "[class*='price-current']",
        "[class*='priceCurrent']",
        "[class*='final-price']",
        "[class*='finalPrice']",
        "[class*='special-price']",
        "[class*='sale-price']",
    ]
    values = []
    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            raw = (
                node.get("content")
                or node.get("data-price-amount")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            if _page_price_noise(node, raw):
                continue
            direct = scraper.parse_price_value(raw)
            if direct is not None and 200 <= direct <= 10000:
                values.append(float(direct))
                continue
            values.extend(v for v in scraper.prices(str(raw)) if 200 <= v <= 10000)
    if values:
        return min(values)

    # PCDiga e outros layouts podem apresentar o preco como texto simples sem
    # classe semantica. So examinamos nos que contem € e excluimos explicitamente
    # descontos/mensalidades, evitando o antigo minimo da pagina inteira.
    visible = []
    for string in soup.find_all(string=re.compile(r"€")):
        raw = str(string).strip()
        node = string.parent
        if _page_price_noise(node, raw):
            continue
        direct = scraper.parse_price_value(raw)
        if direct is not None and 200 <= direct <= 10000:
            visible.append(float(direct))
        else:
            visible.extend(v for v in scraper.prices(raw) if 200 <= v <= 10000)
    if visible:
        return min(visible)
    if structured_price is not None and 200 <= float(structured_price) <= 10000:
        return float(structured_price)
    return None
'''
text = replace_once(text, old, new, "page contextual price")
text = text.replace('"Pré-ranking V8.7.1 |', '"Pré-ranking V8.7.2 |', 1)
text = text.replace('"V8.7.1 | Lojas=%d', '"V8.7.2 | Lojas=%d', 1)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# testes
# ---------------------------------------------------------------------------
path = ROOT / "tests" / "test_tracker.py"
tests = path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n    unittest.main()\n'
extra = r'''

class PriceContextV872Tests(unittest.TestCase):
    def test_card_ignores_discount_amount_and_uses_plain_price(self):
        html = """
        <article>
          <h3>ASUS TUF Gaming A16 RTX 5060 32GB 512GB</h3>
          <a href="/portatil-asus-tuf-a16">Produto</a>
          <span>1.499,99 €</span>
          <span class="old-price">2.299,99 €</span>
          <span class="discount">-800,00 €</span>
        </article>
        """
        card = BeautifulSoup(html, "html.parser").article
        item = scraper.candidate_from_card(
            card,
            "https://example.com/laptops",
            {"loja": "TEST", "product_path_hints": ["/portatil-asus-"]},
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["preco"], 1499.99)

    def test_pcdiga_like_visible_price_beats_wrong_structured_discount(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>ASUS TUF Gaming A16</h1>
              <div><span>1499,99 €</span></div>
              <div class="old-price"><span>2299,99 €</span></div>
              <div class="discount"><span>-800.00€</span></div>
              <div>Financiamento 62,50 € / mês</div>
            </main>
            """,
            "html.parser",
        )
        self.assertEqual(tracker.preferred_page_price(soup, 800.0), 1499.99)
'''
if marker not in tests:
    raise RuntimeError("Marcador final de testes nao encontrado")
tests = tests.replace(marker, extra + marker, 1)
path.write_text(tests, encoding="utf-8")


# ---------------------------------------------------------------------------
# README — manter documentacao alinhada e sem lixo de versoes antigas
# ---------------------------------------------------------------------------
path = ROOT / "README.md"
readme = path.read_text(encoding="utf-8")
readme = readme.replace("# Rastreador de Preços — V8.7", "# Rastreador de Preços — V8.7.2", 1)
readme = readme.replace("A V8.7 executa matching", "A V8.7.2 executa matching")
readme = readme.replace("A V8.7 aprende também", "A V8.7.2 aprende também")
readme = readme.replace("O histórico V8.7 é automaticamente compactado", "O histórico V8.7.2 é automaticamente compactado")
readme = readme.replace("remove formatos e observações pré-V8.7;", "remove formatos incompatíveis e observações antigas;", 1)
readme = readme.replace("mantém apenas as runs V8.7 recentes.", "mantém apenas as runs recentes compatíveis.", 1)
readme = readme.replace("## Refinamentos V8.7", "## Refinamentos V8.7.2", 1)
readme = readme.replace("## Identidade progressiva V8.7", "## Identidade progressiva V8.7.2", 1)
readme = readme.replace("até 12 ofertas cached por run", "até 16 ofertas cached por run")
readme += """

## Capacidade atual

A V8.7.2 está dimensionada para até **180 avaliações**, **70 detail fetches** e **240 pedidos HTTP** por run, com teto de **50 pedidos por loja** e deadline de 8 minutos. Os limites são deliberadamente superiores ao universo atual para absorver novas lojas sem voltar a limitar a análise a 120 produtos.

## Segurança de preço

Valores de desconto, cashback, prestações e financiamento não são tratados como preço do portátil. A ingestão usa sinais de preço do produto e fallback contextual em nós com `€`; valores negativos ou contextos promocionais auxiliares são excluídos. Existe ainda validação de plausibilidade para GPUs dedicadas e uma segunda verificação de orçamento depois do enriquecimento da ficha.
"""
path.write_text(readme, encoding="utf-8")

print("V8.7.2 preparada: preco contextual seguro e documentacao alinhada.")
