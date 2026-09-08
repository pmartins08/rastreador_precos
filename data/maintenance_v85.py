from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: esperava 1 ocorrência, encontrei {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Configuração: tiers, cobertura e remoção de opções mortas
# ---------------------------------------------------------------------------
config_path = ROOT / "config" / "config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
settings = config["settings"]
settings["diamante_value_min"] = 125.0
settings["max_evaluated_per_run"] = 120
settings.pop("gpu_preco_min", None)
settings.pop("require_pt_keyboard", None)

for store in config.get("category_urls", []):
    if store.get("loja") == "Radio Popular":
        # A run #104 provou que estes filtros devolviam os mesmos produtos da página base.
        store.pop("extra_discovery_urls", None)

# Ainda não existe consumo automático desta fonte; removemos configuração enganadora.
config.pop("reference_sources", None)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Scraper: transportar identificadores fortes quando JSON-LD os fornece
# ---------------------------------------------------------------------------
scraper_path = ROOT / "scraper.py"
scraper = scraper_path.read_text(encoding="utf-8")
scraper = replace_once(
    scraper,
    '''                    record = {\n                        "titulo": str(name).strip(),\n                        "url": str(item_url).strip(),\n                        "preco": price,\n                        "stock": available,\n                    }''',
    '''                    record = {\n                        "titulo": str(name).strip(),\n                        "url": str(item_url).strip(),\n                        "preco": price,\n                        "stock": available,\n                        "sku": item.get("sku") or item.get("productID"),\n                        "mpn": item.get("mpn"),\n                        "ean": (\n                            item.get("gtin13")\n                            or item.get("gtin14")\n                            or item.get("gtin12")\n                            or item.get("gtin")\n                        ),\n                    }''',
    "identificadores JSON-LD",
)
scraper_path.write_text(scraper, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tracker: identidade conservadora, cache como cobertura e histórico compacto
# ---------------------------------------------------------------------------
tracker_path = ROOT / "tracker.py"
tracker = tracker_path.read_text(encoding="utf-8")

insert_selection = r'''

def configuration_signature(item: dict, spec: dict) -> str:
    """Identidade conservadora de uma configuração, nunca apenas da família.

    SKU/MPN/EAN vencem quando existem. Sem um identificador forte, a assinatura
    inclui o título e hardware crítico. Esta chave é apenas metadata por agora:
    não fazemos deduplicação cross-store automática sem confirmação suficiente.
    """
    for field in ("sku", "mpn", "ean"):
        raw = item.get(field)
        if raw:
            return f"{field}:{scraper.norm(raw)}"

    fields = [
        scraper.norm(item.get("titulo", "")),
        str(spec.get("marca") or "?"),
        str(spec.get("submarca") or "?"),
        str(spec.get("cpu_modelo") or "?"),
        str(spec.get("gpu_modelo") or spec.get("gpu_tipo") or "?"),
        f"ram:{spec.get('ram_gb') if spec.get('ram_gb') is not None else '?'}",
        f"ssd:{spec.get('armazenamento_tb') if spec.get('armazenamento_tb') is not None else '?'}",
        f"res:{spec.get('ecra_res') or '?'}",
        f"hz:{spec.get('ecra_hz') if spec.get('ecra_hz') is not None else '?'}",
    ]
    return "cfg:" + "|".join(fields)


def select_with_cache(
    items: list[dict],
    spec_cache: dict[str, dict],
    max_items: int,
    weights: dict,
    settings: dict,
) -> list[dict]:
    """Cache aumenta cobertura: cached primeiro, slots restantes para produtos novos."""
    if max_items <= 0:
        return []
    cached = [
        item for item in items
        if item.get("specs") or (item.get("url") and item["url"] in spec_cache)
    ]
    cached_selected = select_for_evaluation(
        cached, min(max_items, len(cached)), weights, settings
    ) if cached else []
    cached_keys = {(item["loja"], item["url"]) for item in cached_selected}
    remaining_slots = max(0, max_items - len(cached_selected))
    if remaining_slots == 0:
        return cached_selected
    uncached = [
        item for item in items
        if (item["loja"], item["url"]) not in cached_keys
        and not item.get("specs")
        and item.get("url") not in spec_cache
    ]
    return cached_selected + select_for_evaluation(
        uncached, min(remaining_slots, len(uncached)), weights, settings
    )
'''
tracker = replace_once(
    tracker,
    "\ndef latest_specs_by_url(history: dict) -> dict[str, dict]:",
    insert_selection + "\n\ndef latest_specs_by_url(history: dict) -> dict[str, dict]:",
    "helpers de identidade/cache",
)

insert_compaction = r'''

def compact_history(history: dict, entries_per_url: int = 3, keep_runs: int = 8) -> dict:
    """Remove legado pré-V8.5 sem perder cache recente, alertas e runs úteis."""
    out = _history_base()
    grouped: dict[str, list[dict]] = defaultdict(list)
    offers = history.get("offers", {}) if isinstance(history.get("offers"), dict) else {}
    for entries in offers.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not url or entry.get("tracker_version") != VERSION:
                continue
            grouped[str(url)].append(entry)

    for url, entries in grouped.items():
        out["offers"][url] = sorted(entries, key=_timestamp)[-entries_per_url:]

    active_urls = set(out["offers"])
    alerts = history.get("alert_state", {}) if isinstance(history.get("alert_state"), dict) else {}
    out["alert_state"] = {
        key: value for key, value in alerts.items()
        if key in active_urls and isinstance(value, dict)
    }

    learning = history.get("learning", {}) if isinstance(history.get("learning"), dict) else {}
    runs = [
        run for run in (learning.get("runs", []) or [])
        if isinstance(run, dict) and run.get("runner_version") == VERSION
    ]
    out["learning"]["runs"] = sorted(runs, key=_timestamp)[-keep_runs:]
    if isinstance(learning.get("stores"), dict):
        out["learning"]["stores"] = learning["stores"]
    out["tracker_version"] = VERSION
    return out
'''
tracker = replace_once(
    tracker,
    "\ndef previous_for_url(history: dict, url: str) -> dict | None:",
    insert_compaction + "\n\ndef previous_for_url(history: dict, url: str) -> dict | None:",
    "compactação de histórico",
)

tracker = replace_once(
    tracker,
    "    history = load_history()\n    spec_cache = latest_specs_by_url(history)",
    "    history = compact_history(load_history())\n    spec_cache = latest_specs_by_url(history)",
    "compactar histórico no arranque",
)

tracker = replace_once(
    tracker,
    "    selected = select_for_evaluation(list(unique.values()), max_evaluated, weights, settings)",
    "    selected = select_with_cache(list(unique.values()), spec_cache, max_evaluated, weights, settings)",
    "seleção cache-aware",
)

tracker = replace_once(
    tracker,
    '''            "tier": tier,\n            "specs": spec,\n            "url": url,\n        }''',
    '''            "tier": tier,\n            "specs": spec,\n            "url": url,\n            "configuration_key": configuration_signature(item, spec),\n            "sku": item.get("sku"),\n            "mpn": item.get("mpn"),\n            "ean": item.get("ean"),\n        }''',
    "metadata de configuração no histórico",
)

tracker = replace_once(
    tracker,
    '''    out["learning"]["stores"] = _merge_monotonic(\n        (current.get("learning", {}) or {}).get("stores", {}),\n        (run_state.get("learning", {}) or {}).get("stores", {}),\n    )\n    return out''',
    '''    out["learning"]["stores"] = _merge_monotonic(\n        (current.get("learning", {}) or {}).get("stores", {}),\n        (run_state.get("learning", {}) or {}).get("stores", {}),\n    )\n    return compact_history(out)''',
    "compactação após merge concorrente",
)
tracker_path.write_text(tracker, encoding="utf-8")


# ---------------------------------------------------------------------------
# Testes: variantes, identificadores, compactação e novo Diamante
# ---------------------------------------------------------------------------
test_path = ROOT / "tests" / "test_tracker.py"
tests = test_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    '        self.assertEqual(scraper.tier_from_value(130, {}), "DIAMANTE")',
    '        self.assertEqual(scraper.tier_from_value(130, {}), "DIAMANTE")\n        self.assertEqual(scraper.tier_from_value(125, {"diamante_value_min": 125}), "DIAMANTE")',
    "teste Diamante 125",
)

brain_extra = r'''
    def test_jsonld_carries_strong_identifiers(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "ASUS TUF Gaming A16 RTX 5060",
            "url": "https://example.com/tuf",
            "sku": "FA608UM-RV001W",
            "mpn": "90NR0KV1-M00000",
            "gtin13": "4711000000000",
            "offers": {"@type": "Offer", "price": "1499,99"},
        }
        soup = BeautifulSoup(
            f'<script type="application/ld+json">{json.dumps(payload)}</script>',
            "html.parser",
        )
        row = scraper.jsonld_products(soup)[0]
        self.assertEqual(row["sku"], "FA608UM-RV001W")
        self.assertEqual(row["mpn"], "90NR0KV1-M00000")
        self.assertEqual(row["ean"], "4711000000000")

'''
tests = replace_once(
    tests,
    "    def test_card_ignores_monthly_installment(self):",
    brain_extra + "    def test_card_ignores_monthly_installment(self):",
    "teste IDs JSON-LD",
)

tracker_extra = r'''
    def test_configuration_signature_separates_same_family_variants(self):
        base = {
            "loja": "ASUS",
            "url": "https://example.com/tuf-a16",
            "titulo": "ASUS TUF Gaming A16",
        }
        spec_5050 = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 512GB RTX 5050")
        spec_5070 = scraper.specs("ASUS TUF Gaming A16 Ryzen 7 260 32GB 1TB RTX 5070")
        self.assertNotEqual(
            tracker.configuration_signature(base, spec_5050),
            tracker.configuration_signature(base, spec_5070),
        )

    def test_configuration_signature_prefers_sku(self):
        left = {"titulo": "ASUS TUF Gaming A16 RTX 5050", "sku": "FA608-ABC"}
        right = {"titulo": "TUF A16 promoção", "sku": "FA608-ABC"}
        self.assertEqual(
            tracker.configuration_signature(left, {}),
            tracker.configuration_signature(right, {}),
        )

    def test_compact_history_keeps_only_current_v85(self):
        history = tracker._history_base()
        history["offers"] = {
            "legacy": [{"url": "https://x/old", "tracker_version": "8.4", "timestamp": "2026-01-01T00:00:00Z"}],
            "new": [
                {"url": "https://x/new", "tracker_version": "8.5", "timestamp": "2026-01-01T00:00:00Z"},
                {"url": "https://x/new", "tracker_version": "8.5", "timestamp": "2026-01-02T00:00:00Z"},
            ],
        }
        history["alert_state"] = {
            "https://x/old": {"timestamp": "2026-01-01T00:00:00Z"},
            "https://x/new": {"timestamp": "2026-01-02T00:00:00Z"},
        }
        compact = tracker.compact_history(history, entries_per_url=1)
        self.assertNotIn("https://x/old", compact["offers"])
        self.assertEqual(len(compact["offers"]["https://x/new"]), 1)
        self.assertEqual(set(compact["alert_state"]), {"https://x/new"})

    def test_select_with_cache_keeps_cached_and_prioritizes_new(self):
        settings = {"budget_soft": 1300, "budget_hard": 1500}
        weights = {"gpu_base": {"rtx 5070": 95}, "cpu_base": {"tier_2": 85}}
        items = [
            {"loja": "A", "url": "https://a/cached", "titulo": "ASUS Vivobook Core i7-1255U 16GB 512GB", "preco": 700},
            {"loja": "A", "url": "https://a/strong", "titulo": "ASUS TUF Core 7 240H 32GB 1TB RTX 5070", "preco": 1399},
            {"loja": "A", "url": "https://a/weak", "titulo": "ASUS Vivobook Core i7-1255U 16GB 512GB", "preco": 799},
        ]
        selected = tracker.select_with_cache(
            items, {"https://a/cached": {"ram_gb": 16}}, 2, weights, settings
        )
        self.assertEqual(selected[0]["url"], "https://a/cached")
        self.assertEqual(selected[1]["url"], "https://a/strong")

'''
tests = replace_once(
    tests,
    "    def test_unknown_keyboard_wrapper_is_accepted(self):",
    tracker_extra + "    def test_unknown_keyboard_wrapper_is_accepted(self):",
    "testes identidade/cache/compactação",
)
test_path.write_text(tests, encoding="utf-8")


# ---------------------------------------------------------------------------
# README V8.5 final
# ---------------------------------------------------------------------------
readme = r'''# Rastreador de Preços — V8.5

Motor de inteligência de mercado para portáteis ASUS, Lenovo e HP em Portugal. O sistema combina descoberta de catálogo, acesso adaptativo, extração técnica, scoring orientado ao uso FEUP + gaming, histórico, cache e notificações ntfy.

## Estrutura

```text
scraper.py                  cérebro V8: parsing de hardware + scoring
tracker.py                  acesso, descoberta, cache, histórico, alertas e heartbeat
config/config.json          limites, lojas, pesos e tiers
tests/test_tracker.py       regressões do cérebro e do tracker
data/history.json           preços/configurações recentes e estado de alertas
data/access_learning.json   aprendizagem de acesso por loja/método/browser
.github/workflows/tracker.yml
requirements.txt
```

A divisão é intencional: `scraper.py` decide **o que vale a pena**; `tracker.py` decide **como observar o mercado de forma eficiente**.

## Universo

Apenas equipamento novo das famílias:

- ASUS — ROG, TUF, Vivobook, Zenbook, ExpertBook, ProArt
- Lenovo — Legion, LOQ, IdeaPad, ThinkPad, ThinkBook, Yoga
- HP — OMEN, Victus, OmniBook, EliteBook, ProBook, Envy, Pavilion

Apple, usados, recondicionados e outlet ficam excluídos.

## Scoring

O cérebro V8 mantém as dimensões FEUP, Gaming, Longevidade e Portabilidade. O Value Score combina ranking técnico/adequação com preço.

Tiers atuais:

| Tier | Value mínimo |
|---|---:|
| Bronze | 70 |
| Prata | 90 |
| Ouro | 110 |
| Diamante | 125 |

Diamante é deliberadamente raro: representa uma combinação excecional de adequação e preço, sem exigir quase perfeição matemática como acontecia com 130.

## Descoberta e cobertura

O tracker pode combinar:

1. categoria;
2. paginação pública confirmada;
3. JSON-LD e cartões de produto;
4. sitemaps quando demonstram retorno útil;
5. probe mode para lojas persistentemente bloqueadas.

Cada loja tem orçamento próprio e existe também orçamento global/deadline. O sistema não tenta contornar CAPTCHA ou mecanismos anti-bot.

A cache de especificações é independente do orçamento de fichas novas: produtos descobertos novamente podem reutilizar CPU/GPU/RAM/ecrã já confirmados, libertando acessos de detalhe para SKUs novos.

## Identidade de configurações

Nunca assumimos que o nome comercial identifica uma configuração única. `ASUS TUF Gaming A16`, por exemplo, pode existir com GPUs, RAM e SSD diferentes.

A ordem de confiança é:

1. SKU / part number / EAN quando disponível;
2. caso contrário, uma assinatura conservadora que inclui título + CPU + GPU + RAM + SSD + ecrã.

A V8.5 guarda esta assinatura como metadata, mas ainda não funde automaticamente ofertas entre lojas. Uma futura comparação cross-store só será ativada quando a identidade for suficientemente forte para evitar misturar variantes próximas.

## Acesso adaptativo

O tracker aprende por loja + método + perfil de browser. Fontes persistentemente bloqueadas entram em `probe mode`, recebendo uma tentativa barata em vez de desperdiçar dezenas de requests.

A aprendizagem de acesso é persistida em `data/access_learning.json` e não é apagada quando o histórico de preços é compactado.

## Histórico

O histórico V8.5 é automaticamente compactado:

- remove formatos e observações pré-V8.5;
- normaliza chaves por URL;
- mantém apenas observações recentes necessárias para preço/cache;
- preserva estado de alertas válido;
- mantém apenas as runs V8.5 recentes.

## ntfy

Existem dois sinais independentes:

- alertas de oportunidade (Ouro/Diamante, upgrades de tier ou quedas de preço);
- heartbeat de saúde em todas as runs normais.

Se o pipeline falhar antes de o Python terminar, o GitHub Actions envia um heartbeat de falha separado.

## Testes

```bash
python -m py_compile scraper.py tracker.py tests/test_tracker.py
python -m unittest discover -s tests -p 'test_tracker.py' -v
```

A suite cobre preços PT/EU, CPU/GPU, VRAM, TGP, M.2, JSON-LD, IDs fortes, variantes de configuração, cache, paginação, budgets, probe mode, heartbeat, histórico e merge concorrente.

## Execução

O workflow corre em push para `main`, manualmente e a cada 6 horas. A ordem é testes → validação ntfy → tracker → heartbeat → merge/persistência segura.
'''
(ROOT / "README.md").write_text(readme, encoding="utf-8")


# ---------------------------------------------------------------------------
# Compactar histórico existente antes da run final
# ---------------------------------------------------------------------------
history_path = ROOT / "data" / "history.json"
history = json.loads(history_path.read_text(encoding="utf-8"))

def timestamp(record: dict) -> str:
    return str(record.get("timestamp") or "")

grouped: dict[str, list[dict]] = {}
for entries in (history.get("offers", {}) or {}).values():
    if not isinstance(entries, list):
        continue
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("tracker_version") != "8.5" or not entry.get("url"):
            continue
        grouped.setdefault(str(entry["url"]), []).append(entry)

compact_offers = {
    url: sorted(entries, key=timestamp)[-3:]
    for url, entries in grouped.items()
}
active = set(compact_offers)
compact_alerts = {
    key: value
    for key, value in (history.get("alert_state", {}) or {}).items()
    if key in active and isinstance(value, dict)
}
runs = [
    run for run in ((history.get("learning", {}) or {}).get("runs", []) or [])
    if isinstance(run, dict) and run.get("runner_version") == "8.5"
]
compact_history = {
    "schema_version": 8,
    "tracker_version": "8.5",
    "offers": compact_offers,
    "alert_state": compact_alerts,
    "learning": {
        "runs": sorted(runs, key=timestamp)[-8:],
        "stores": (history.get("learning", {}) or {}).get("stores", {}),
    },
}
history_path.write_text(json.dumps(compact_history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Remover legado já absorvido pela arquitetura final
# ---------------------------------------------------------------------------
legacy = [
    "brain_runtime.py",
    "brands.py",
    "catalog.py",
    "hardware.py",
    "pricing.py",
    "response_classification.py",
    "runner.py",
    "runner_v84.py",
    "state_merge.py",
    "structured_data.py",
    "tests/test_core_fixes.py",
    "tests/test_state_merge.py",
    "tests/test_v84.py",
]
for relative in legacy:
    path = ROOT / relative
    if path.exists():
        path.unlink()

# One-shot: o próprio commit de manutenção remove as ferramentas temporárias.
workflow = ROOT / ".github" / "workflows" / "maintenance_v85.yml"
if workflow.exists():
    workflow.unlink()
Path(__file__).unlink()

print("V8.5 final preparada: config, tracker, scraper, testes, README, histórico e legado consolidados.")
