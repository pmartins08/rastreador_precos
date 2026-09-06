import re
import json
import asyncio
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

NTFY_TOPIC = "alertas_portateis_feup_123"

PORTATEIS = [
    {
        "nome": "ASUS TUF A16 FA608UM - PCDiga",
        "url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop/computadores-portateis/portatil-asus-tuf-gaming-a16-16-fa608umi-r72b56cs1-jaeger-gray-90nr0kv1-m00h70-4711636583923",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF F16 FX608JMR - Worten",
        "url": "https://www.worten.pt/produtos/portatil-gaming-asus-tuf-fx608jmr-intel-core-i7-14650hx-nvidia-geforce-rtx-5060-ram-32-gb-1-tb-ssd-16-8585385",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF F16 FX608JMR - Fnac (Oficial)",
        "url": "https://www.fnac.pt/Computador-Portatil-Gaming-Asus-TUF-A16-FX608JMR-74A56CB1-16-NVIDIA-GeForce-RTX-5060-Intel-Core-i7-14650HX-32GB-1TB-SSD-Computador-Portatil-Computador-Portatil-Gaming/a13799931?oref=00000000-0000-0000-0000-000000000000",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF F16 FX608JMI - PcComponentes",
        "url": "https://www.pccomponentes.pt/portatil-asus-tuf-gaming-f16-fx608jmi-74b56cs1-16-intel-core-i7-14650hx-32gb-1tb-ssd-rtx-5060-pt",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF A16 - ASUS Portugal (Oficial)",
        "url": "https://estore.asus.com/pt/portatil-gaming-asus-tuf-gaming-a16.html",
        "alvo": 1500.00
    }
]

def enviar_alerta(titulo, mensagem, prioridade="high", tags="rotating_light,computer"):
    titulo_ascii = titulo.encode('ascii', 'ignore').decode('ascii').strip()
    if not titulo_ascii:
        titulo_ascii = "Alerta de Portatil"
        
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=mensagem.encode('utf-8'),
            headers={
                "Title": titulo_ascii, 
                "Tags": tags, 
                "Priority": prioridade
            }
        )
        print("   => 🚨 Notificação enviada para o Ntfy com sucesso!")
    except Exception as e:
        print(f"   => ❌ Erro ao enviar notificação no Ntfy: {e}")

def extrair_preco_e_stock(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    preco = None
    em_stock = None

    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            dados = json.loads(script.string if script.string else "")
            def procurar(obj):
                nonlocal preco, em_stock
                if isinstance(obj, dict):
                    if obj.get('@type') in ['Offer', 'AggregateOffer', 'Product']:
                        if 'price' in obj and not preco:
                            try: preco = float(obj['price'])
                            except: pass
                        if 'availability' in obj and em_stock is None:
                            avail = str(obj['availability']).lower()
                            if 'instock' in avail: em_stock = True
                            elif any(x in avail for x in ['outofstock', 'soldout', 'discontinued']): em_stock = False
                    if 'offers' in obj: procurar(obj['offers'])
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)): procurar(v)
                elif isinstance(obj, list):
                    for item in obj: procurar(item)

            procurar(dados)
            if preco and em_stock is not None: break
        except:
            continue

    if not preco:
        meta_price = soup.find('meta', {'itemprop': 'price'}) or soup.find('meta', {'property': 'product:price:amount'})
        if meta_price and meta_price.get('content'):
            try: preco = float(meta_price['content'])
            except: pass

    if em_stock is None:
        meta_avail = soup.find('meta', {'itemprop': 'availability'}) or soup.find('meta', {'property': 'product:availability'})
        if meta_avail and meta_avail.get('content'):
            content_avail = meta_avail['content'].lower()
            if 'instock' in content_avail: em_stock = True
            elif 'outofstock' in content_avail: em_stock = False

    if not preco:
        numeros = re.findall(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*€|(\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s*€', html_content)
        precos = [float((m[0] or m[1]).replace('.', '').replace(',', '.')) for m in numeros if (m[0] or m[1])]
        precos_validos = [v for v in precos if 800 <= v <= 2500]
        if precos_validos: preco = min(precos_validos)

    if em_stock is None:
        html_lower = html_content.lower()
        if any(t in html_lower for t in ["esgotado online", "indisponível", "fora de stock", "sem stock", "out of stock"]):
            em_stock = False
        elif any(t in html_lower for t in ["em stock", "adicionar", "comprar", "entrega imediata", "add to cart"]):
            em_stock = True
        elif preco:
            em_stock = True

    return preco, em_stock

async def main():
    print("🚀 A iniciar Rastreador (GitHub Actions)...")
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1920, "height": 1080},
            locale="pt-PT",
            extra_http_headers={
                "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['pt-PT', 'pt', 'en-US', 'en']});
        """)
        
        page = await context.new_page()
        
        for p_info in PORTATEIS:
            print(f"🔍 A verificar: {p_info['nome']}...")
            
            try:
                await page.goto(p_info["url"], timeout=40000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"   => Aviso na navegação: {e}")
            
            await page.wait_for_timeout(3000)
            try: await page.mouse.wheel(0, 400)
            except: pass
            
            try:
                titulo_pagina = await page.title()
                
                if "asus.com" in titulo_pagina.lower() or "momento" in titulo_pagina.lower():
                    print("   => ⏳ Ecrã de proteção detetado. A tentar contornar com interações humanas...")
                    for i in range(5):
                        await page.mouse.move(200 + (i * 100), 300 + (i * 50))
                        await page.wait_for_timeout(1500)
                    titulo_pagina = await page.title() 
                
                html_completo = await page.content()
                print(f"   => Título lido: '{titulo_pagina}'")
                
                if "404" in titulo_pagina or "Not Found" in titulo_pagina:
                    print("   => ❌ Link Inexistente / Erro 404 na Loja.")
                    continue
                    
                if "Um momento" in titulo_pagina or "Just a moment" in titulo_pagina or "asus.com" == titulo_pagina.lower():
                    print("   => 🛡️ Proteção Anti-Bot imbatível nesta tentativa. Ignorado com segurança.")
                    continue

                preco_final, em_stock = extrair_preco_e_stock(html_completo)
                status_stock_str = "🟢 EM STOCK" if em_stock else "🔴 ESGOTADO / INDISPONÍVEL"
                
                if preco_final:
                    print(f"   => Preço lido: {preco_final}€ (Alvo: {p_info['alvo']}€)")
                    print(f"   => Estado do Stock: {status_stock_str}")
                    
                    if preco_final <= p_info["alvo"]:
                        if em_stock:
                            titulo_alerta = f"PROMOCAO EM STOCK ({preco_final} EUR)"
                            msg_alerta = f"🚨 O produto {p_info['nome']} está disponível por {preco_final}€!\n\n📦 Estado: 🟢 Em Stock\n🔗 Comprar: {p_info['url']}"
                            enviar_alerta(titulo_alerta, msg_alerta, prioridade="high", tags="rotating_light,computer,white_check_mark")
                        else:
                            titulo_alerta = f"PRECO NO ALVO MAS ESGOTADO ({preco_final} EUR)"
                            msg_alerta = f"⚠️ O preço de {p_info['nome']} desceu para {preco_final}€, mas o produto encontra-se esgotado online.\n\n📦 Estado: 🔴 Esgotado\n🔗 Ver Loja: {p_info['url']}"
                            enviar_alerta(titulo_alerta, msg_alerta, prioridade="default", tags="warning,computer,x")
                else:
                    print("   => ❌ Não foi possível extrair o preço nesta tentativa.")

            except Exception as e:
                print(f"   => ❌ Erro de processamento: {str(e)}")
            
            await asyncio.sleep(4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
