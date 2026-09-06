import asyncio
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.json"
HISTORY_PATH = BASE_DIR / "data" / "history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

TERMOS_EXCLUSAO = ["recondicionado", "refurbished", "usado", "outlet", "grade a", "grade b", "grade c", "seminovo", "open box"]
MARCAS_ACEITES = {"asus":["rog","tuf","vivobook","zenbook","expertbook","proart"],"lenovo":["legion","loq","ideapad","thinkpad","thinkbook","yoga"],"hp":["omen","victus","omnibook","elitebook","probook","envy","pavilion"],"acer":["predator","nitro","swift","aspire","travelmate"],"msi":["raider","vector","stealth","crosshair","katana","prestige","creator"],"dell":["alienware","g-series","g15","g16","xps","inspiron","latitude"]}
TECLADO_PT = ["teclado portugues","teclado pt","teclado pt-pt","keyboard portugues","keyboard pt","keyboard pt-pt","layout pt","layout pt-pt","portuguese keyboard","portuguese layout","pt keyboard","pt-pt"]
TECLADO_NAO_PT = ["teclado espanhol","keyboard espanhol","spanish keyboard","spanish layout","teclado frances","keyboard frances","french keyboard","french layout","teclado alemao","keyboard alemao","german keyboard","german layout","teclado ingles","keyboard ingles","english keyboard","keyboard us","us keyboard","us layout","en-us keyboard","uk keyboard","uk layout","italian keyboard","italian layout","swedish keyboard","swedish layout","nordic keyboard","nordic layout","danish keyboard","danish layout","belgian keyboard","swiss keyboard","azerty","qwertz"]
STOCK_NAO = ["esgotado","fora de stock","out of stock","indisponivel","temporariamente indisponivel","sem stock","sem estoque","unavailable","not available"]
STOCK_SIM = ["em stock","em estoque","disponivel","disponibilidade: disponivel","available","in stock","order now","adicionar ao carrinho","adiciona ao carrinho","add to cart"]


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def carregar_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️ Erro ao ler {path.name}: {exc}")
        return {}


def guardar_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def parse_price_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    try:
        if "," in text and "." in text:
            return float(text.replace(".", "").replace(",", ".")) if text.rfind(",") > text.rfind(".") else float(text.replace(",", ""))
        return float(text.replace(",", "."))
    except ValueError:
        return None


def detetar_stock(texto: str) -> Optional[bool]:
    t = normalizar_texto(texto)
    if any(x in t for x in STOCK_NAO):
        return False
    if any(x in t for x in STOCK_SIM):
        return True
    return None


def detetar_marca_submarca(titulo: str) -> tuple[Optional[str], Optional[str]]:
    t = normalizar_texto(titulo)
    for marca, subs in MARCAS_ACEITES.items():
        if re.search(rf"\b{re.escape(marca)}\b", t):
            for sub in subs:
                if re.search(rf"\b{re.escape(sub)}\b", t):
                    return marca, sub
            return marca, None
    return None, None


def verificar_elegibilidade(titulo: str) -> bool:
    t = normalizar_texto(titulo)
    if any(x in t for x in TERMOS_EXCLUSAO):
        return False
    marca, _ = detetar_marca_submarca(t)
    return marca in MARCAS_ACEITES


def limpar_vram(texto: str) -> str:
    texto = re.sub(r"\b(4|6|8|12|16|24)\s?gb\s?(gddr\d|vram)\b", "", texto)
    return re.sub(r"\b(rtx|rx|gtx)\s?\d{4}\s?\d{1,2}gb\b", "", texto)


def extrair_teclado_do_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    t = normalizar_texto(soup.get_text(" ", strip=True))
    universe = f"{t} {normalizar_texto(str(soup))}"
    if any(x in universe for x in TECLADO_NAO_PT):
        return "nao_pt"
    if any(x in universe for x in TECLADO_PT):
        return "confirmado"
    return "desconhecido"


def extrair_specs_avancadas(texto_bruto: str) -> dict:
    t = normalizar_texto(texto_bruto)
    tl = limpar_vram(t)
    s = {"marca":None,"submarca":None,"gpu_modelo":None,"gpu_tipo":"desconhecida","cpu_modelo":None,"cpu_classe":None,"cpu_str_original":None,"ram_gb":None,"ram_expansivel":False,"armazenamento_tb":None,"ssd_expansivel":False,"bateria_wh":None,"peso_kg":None,"ecra_res":None,"ecra_hz":None,"teclado_pt":"desconhecido","alertas":[],"fontes":{}}
    s["marca"], s["submarca"] = detetar_marca_submarca(t)
    gpus=["rtx 5090","rtx 5080","rtx 5070 ti","rtx 5070","rtx 5060 ti","rtx 5060","rtx 5050","rtx 4090","rtx 4080","rtx 4070","rtx 4060","rtx 4050"]
    for g in gpus:
        if g in t: s["gpu_modelo"]=g; s["gpu_tipo"]="dedicada"; s["fontes"]["gpu"]="modelo_exato"; break
    if not s["gpu_modelo"]:
        if any(x in t for x in ["intel iris","intel arc graphics","radeon graphics","radeon 780m","radeon 890m"]): s["gpu_tipo"]="integrada"
        else: s["alertas"].append("GPU não identificada")
    m=re.search(r"(core\s+ultra\s+[579]\s+\d{3}(?:hx|hs|h|u|v)?|i[579]-\d{4,5}(?:hx|hs|h|u|p)?|ryzen\s+[579]\s+\d{3,4}(?:hx|hs|h|u|s)?)",t)
    if m:
        c=m.group(1); s["cpu_str_original"]=c; s["fontes"]["cpu"]="modelo_detetado"
        s["cpu_modelo"]="tier_1" if re.search(r"ultra 9|i9|ryzen 9",c) else "tier_2" if re.search(r"ultra 7|i7|ryzen 7",c) else "tier_3"
        s["cpu_classe"]="hx" if "hx" in c else "hs" if "hs" in c else "h" if re.search(r"\bh\b|\d+h\b",c) else "u_ultra" if any(x in c for x in [" u"," v"," p"]) else None
    else: s["alertas"].append("CPU não confirmada")
    m=re.search(r"(\d{1,3})\s?gb\s?(ram|ddr[45](?:x)?|memory|so-dimm)\b",tl)
    if m: s["ram_gb"]=int(m.group(1)); s["fontes"]["ram"]="explicita"
    else:
        for raw in re.findall(r"\b(\d{1,3})\s?gb\b",tl):
            v=int(raw)
            if v in [8,12,16,24,32,48,64,96,128]: s["ram_gb"]=v; s["fontes"]["ram"]="heuristica"; s["alertas"].append("RAM inferida por heurística"); break
        if s["ram_gb"] is None: s["alertas"].append("RAM desconhecida")
    if any(x in t for x in ["ram expansivel","so-dimm","slot ram","ram upgrade","upgradable memory"]): s["ram_expansivel"]=True
    for v,p in [(2.0,r"2\s?tb(?:\s?(?:ssd|nvme|pcie))?"),(1.0,r"1\s?tb(?:\s?(?:ssd|nvme|pcie))?"),(.5,r"512\s?gb(?:\s?(?:ssd|nvme|pcie))?")]:
        m=re.search(p,t)
        if m: s["armazenamento_tb"]=v; s["fontes"]["armazenamento"]="explicita" if re.search(r"ssd|nvme|pcie",m.group(0)) else "heuristica"; break
    if s["armazenamento_tb"] is None: s["alertas"].append("Armazenamento não confirmado")
    if any(x in t for x in ["ssd extra","2x m.2","2 x m.2","slot m.2 livre","segundo ssd","segundo m.2","armazenamento expansivel"]): s["ssd_expansivel"]=True
    m=re.search(r"(\d{2,3})\s?wh\b",t)
    if m: s["bateria_wh"]=int(m.group(1))
    else: s["alertas"].append("Bateria (Wh) desconhecida")
    m=re.search(r"(\d[\.,]\d+)\s?kg\b",t)
    if m: s["peso_kg"]=float(m.group(1).replace(",","."))
    else: s["alertas"].append("Peso desconhecido")
    if any(x in t for x in ["qhd+","2880x1800","2560x1600","wqxga"]): s["ecra_res"]="qhd+"
    elif any(x in t for x in ["qhd","2560x1440"]): s["ecra_res"]="qhd"
    elif any(x in t for x in ["1200p","1920x1200","wuxga","16:10"]): s["ecra_res"]="fhd+"
    elif any(x in t for x in ["fhd","1920x1080","1080p"]): s["ecra_res"]="fhd"
    else: s["alertas"].append("Resolução do ecrã desconhecida")
    m=re.search(r"(\d{2,3})\s?hz\b",t)
    if m: s["ecra_hz"]=int(m.group(1))
    else: s["alertas"].append("Frequência do ecrã desconhecida")
    if any(x in t for x in TECLADO_PT): s["teclado_pt"]="confirmado"; s["fontes"]["teclado"]="texto"
    elif any(x in t for x in TECLADO_NAO_PT): s["teclado_pt"]="nao_pt"; s["fontes"]["teclado"]="texto"; s["alertas"].append("Teclado não é PT")
    else: s["alertas"].append("Teclado PT não confirmado")
    return s


def calcular_qualidade_dados(s: dict) -> tuple[float,str]:
    q=.20*bool(s.get("cpu_modelo"))+.20*(s.get("gpu_tipo")!="desconhecida")
    if s.get("ram_gb"): q += .20 if s.get("fontes",{}).get("ram")=="explicita" else .14
    for c,w in [("bateria_wh",.10),("peso_kg",.10),("ecra_res",.10),("ecra_hz",.10)]: q += w if s.get(c) is not None else 0
    return q,"ALTA" if q>=.85 else "MEDIA" if q>=.5 else "BAIXA"


def calcular_scores(s: dict, preco: float, weights: dict) -> dict:
    if s["teclado_pt"]=="nao_pt": return {"status":"REJEITADO","alertas":["Teclado explicitamente não português."]}
    if s["ram_gb"]==8: return {"status":"REJEITADO","alertas":["8GB RAM confirmado - insuficiente."]}
    if s["peso_kg"] and s["peso_kg"]>2.8: return {"status":"REJEITADO","alertas":["Excede limite de peso (>2.8kg)."]}
    ram=s["ram_gb"]; p_ram=50 if ram is None else 100 if ram>=32 else 80 if ram>=16 else 40
    arm=s["armazenamento_tb"]; p_ssd=50 if arm is None else 100 if arm>=2 else 85 if arm>=1 else 65
    p_res={"qhd+":100,"qhd":95,"fhd+":85,"fhd":75,None:60}.get(s["ecra_res"],60); p_hz=min(100,(s.get("ecra_hz") or 60)/1.65)
    p_cpu=weights.get("cpu_base",{"tier_1":100,"tier_2":85,"tier_3":70}).get(s["cpu_modelo"],50)
    penal={"u_ultra":0,"hs":5,"h":10,"hx":20,None:10}; auto=50 if s["bateria_wh"] is None else max(0,min(100,s["bateria_wh"]/90*100)-penal.get(s["cpu_classe"],10))
    gpu=weights.get("gpu_base",{}); p_gpu=gpu.get(s["gpu_modelo"],50) if s["gpu_tipo"]=="dedicada" else 15 if s["gpu_tipo"]=="integrada" else 30
    peso=s.get("peso_kg"); p_peso=50 if peso is None else 100 if peso<=1.4 else 0 if peso>=2.8 else max(0,100-(peso-1.4)*71.4)
    p_ram_long=50 if ram is None else 100 if ram>=32 else 95 if ram==16 and s["ram_expansivel"] else 75 if ram==16 else 40
    exp=s["ssd_expansivel"]; p_ssd_long=50 if arm is None else 100 if arm>=2 or (arm==1 and exp) else 85 if arm==1 else 75 if arm==.5 and exp else 65 if arm==.5 else 50
    feup=p_ram*.2+auto*.3+p_ssd*.15+p_res*.2+p_cpu*.15; gaming=p_gpu*.65+p_cpu*.2+p_hz*.1+p_ram*.05; longevity=p_ram_long*.35+p_ssd_long*.25+auto*.2+p_cpu*.2; final=feup*.5+gaming*.25+longevity*.15+p_peso*.1
    conf,qual=calcular_qualidade_dados(s); rank=round(final*(.85+.15*conf),1); value=round(rank/((preco/1000)**1.2),1) if preco>0 else 0
    alerts=list(s["alertas"])
    if s["teclado_pt"]=="desconhecido": alerts.append("Teclado PT não confirmado — portátil mantido no ranking.")
    return {"status":"ACEITE","score_final":round(final,1),"score_ranking":rank,"value_score":value,"qualidade_dados":qual,"confianca_percentual":f"{int(conf*100)}%","fontes_extraidas":s["fontes"],"alertas":alerts,"detalhes":{"marca":s.get("marca"),"submarca":s.get("submarca"),"teclado_pt":s.get("teclado_pt"),"FEUP":round(feup,1),"Gaming":round(gaming,1),"Longevidade":round(longevity,1),"Portabilidade":round(p_peso,1)}}


async def confirmar_teclado_produto(page: Page,url:str)->str:
    try:
        r=await page.goto(url,timeout=30000,wait_until="domcontentloaded")
        if r and r.status>=400:return "desconhecido"
        try: await page.wait_for_load_state("networkidle",timeout=8000)
        except PlaywrightTimeout: pass
        return extrair_teclado_do_html(await page.content())
    except Exception:return "desconhecido"


async def extrair_grelha_categoria(page: Page, cfg: dict, limit:int=30)->list[dict]:
    loja,url=cfg["loja"],cfg["url"]
    try:
        r=await page.goto(url,timeout=int(cfg.get("timeout_ms",45000)),wait_until="domcontentloaded"); status=r.status if r else "N/A"; title=await page.title(); print(f"   [Debug {loja}] Status: {status} | Título: '{title}'")
        if status in (403,429) or "just a moment" in title.lower(): print(f"   ⚠️ {loja} bloqueada ou requer CAPTCHA."); return []
        try: await page.wait_for_load_state("networkidle",timeout=15000)
        except PlaywrightTimeout: pass
        for _ in range(int(cfg.get("scroll_passes",4))): await page.evaluate("window.scrollTo(0, document.body.scrollHeight);"); await page.wait_for_timeout(int(cfg.get("scroll_wait_ms",1800)))
    except PlaywrightTimeout: print(f"   ⚠️ Timeout em {loja}; a extrair o que carregou...")
    except Exception as exc: print(f"   ❌ Erro de navegação em {loja}: {exc}"); return []
    soup=BeautifulSoup(await page.content(),"html.parser")
    selectors=cfg.get("card_selectors") or ["article","div[class*='product-card']","div[class*='productCard']","div[class*='product-item']","div[class*='ProductItem']","div[data-name='product']","li[class*='product']"]
    cards=soup.select(", ".join(selectors))
    if not cards:
        for a in soup.select("a[href]"):
            href=a.get("href",""); hints=cfg.get("product_path_hints",["/produto/","/product/","/produtos/","/computadores-portateis/","/portateis/","/laptop/"])
            if not any(h in href.lower() for h in hints): continue
            p=a
            for _ in range(6):
                p=p.parent if p else None
                if not p: break
                txt=p.get_text(" ",strip=True)
                if 20<=len(txt)<=1200 and re.search(r"\d{2,4}(?:[.,]\d{2})\s*€",txt): cards.append(p); break
    out=[]; seen=set()
    for card in cards:
        if len(out)>=limit: break
        n=card.select_one("h1,h2,h3,h4,[class*='title'],[class*='Title'],[class*='name'],[class*='Name'],a[title],img[alt]"); title=(n.get("alt") or n.get("title") or n.get_text(" ",strip=True)) if n else ""; title=re.sub(r"\s+"," ",title).strip()
        if len(title)<10 or title in seen: continue
        price=None
        for sel in cfg.get("price_selectors") or ["[itemprop='price']","[class*='price']",".price","span[class*='Price']"]:
            n=card.select_one(sel)
            if n: price=parse_price_value(n.get("content") or n.get("data-price") or n.get_text(" ",strip=True));
            if price is not None and 200<=price<=4500: break
        if price is None:
            m=re.search(r"(\d{2,4}[.,]\d{2})\s*€?",card.get_text(" ",strip=True)); price=parse_price_value(m.group(1)) if m else None
        if price is None or not 200<=price<=4500: continue
        a=card.select_one("a[href]"); link=urljoin(url,a["href"]) if a else url; seen.add(title); out.append({"loja":loja,"titulo":title,"preco":price,"url":link,"stock":detetar_stock(card.get_text(" ",strip=True))})
    return out


def enviar_alerta(titulo:str,mensagem:str,prioridade:str="default",tags:str="computer")->None:
    if not NTFY_TOPIC:return
    try:
        requests.post("https://ntfy.sh",json={"topic":NTFY_TOPIC,"title":titulo,"message":mensagem,"tags":[t.strip() for t in tags.split(",")],"priority":4 if prioridade=="high" else 3},timeout=15).raise_for_status()
    except Exception as exc: print(f"❌ Erro ao enviar JSON para o ntfy: {exc}")


async def main()->None:
    print("🚀 A iniciar Rastreador V6 — scraper consolidado...")
    config=carregar_json(CONFIG_PATH); history=carregar_json(HISTORY_PATH); history.setdefault("offers",{}); settings=config.get("settings",{}); weights=config.get("weights",{}); min_value=settings.get("min_value_score_alerta",45.0); budget=settings.get("budget_hard",1500.0); analisados=alertas=0
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--disable-blink-features=AutomationControlled","--no-sandbox"]); ctx=await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",viewport={"width":1920,"height":1080},locale="pt-PT")
        for cat in config.get("category_urls",[]):
            loja=cat["loja"]; print(f"\n🔍 A varrer categoria: {loja}..."); page=await ctx.new_page(); products=await extrair_grelha_categoria(page,cat,limit=settings.get("max_produtos_por_categoria",30)); await page.close(); print(f"   => Encontrados {len(products)} itens na grelha da {loja}.")
            for item in products:
                if not verificar_elegibilidade(item["titulo"]) or item["preco"]>budget: continue
                s=extrair_specs_avancadas(item["titulo"]); analisados+=1
                if s["teclado_pt"]=="desconhecido":
                    d=await ctx.new_page(); detected=await confirmar_teclado_produto(d,item["url"]); await d.close(); s["teclado_pt"]=detected; s["fontes"]["teclado"]="pagina_produto" if detected!="desconhecido" else "nao_confirmado"; 
                    if detected=="confirmado": s["alertas"]=[a for a in s["alertas"] if a!="Teclado PT não confirmado"]
                    elif detected=="nao_pt" and "Teclado não é PT" not in s["alertas"]: s["alertas"].append("Teclado não é PT")
                av=calcular_scores(s,item["preco"],weights)
                if av["status"]=="REJEITADO": print(f"   [-] {item['titulo'][:55]}... | REJEITADO: {av['alertas']}"); continue
                key=f"{loja}::{item['titulo']}"; entries=history["offers"].setdefault(key,[]); prev=entries[-1] if entries else None; entries.append({"timestamp":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"price":item["preco"],"stock":item["stock"],"score_final":av["score_final"],"score_ranking":av["score_ranking"],"value_score":av["value_score"],"qualidade_dados":av["qualidade_dados"],"teclado_pt":s["teclado_pt"],"marca":s.get("marca"),"submarca":s.get("submarca")}); history["offers"][key]=entries[-60:]
                print(f"   [+] {item['titulo'][:45]}... | {item['preco']:.2f}€ | Rank: {av['score_ranking']} | Value: {av['value_score']} | Dados: {av['qualidade_dados']}")
                opportunity=av["value_score"]>=min_value; drop=bool(prev and prev["price"]-item["preco"]>5.0)
                if (opportunity or drop) and item["stock"] is True:
                    alertas+=1; prefix="🌟 OPORTUNIDADE" if opportunity else "📉 QUEDA PREÇO"; label={"confirmado":"PT confirmado","nao_pt":"NÃO PT","desconhecido":"não confirmado"}.get(s["teclado_pt"],s["teclado_pt"]); msg=f"{item['titulo']}\n\nLoja: {loja}\nPreço: {item['preco']:.2f}€\nRank: {av['score_ranking']}/100\nValue: {av['value_score']}\nDados: {av['qualidade_dados']} ({av['confianca_percentual']})\nTeclado: {label}\n🔗 {item['url']}"; enviar_alerta(f"{prefix}: {item['preco']:.0f}€",msg,"high","star2" if opportunity else "chart_with_downwards_trend")
        await browser.close()
    guardar_json(HISTORY_PATH,history); enviar_alerta("🔄 Relatório de Rastreio V6",f"Rastreio concluído.\nPortáteis considerados: {analisados}\nAlertas: {alertas}","default","white_check_mark"); print(f"\n✅ Concluído ({analisados} portáteis considerados).")


if __name__=="__main__": asyncio.run(main())
