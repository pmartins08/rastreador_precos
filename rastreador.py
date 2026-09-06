import asyncio
from playwright.async_api import async_playwright
import requests
import re

# Substitui pelo nome do teu tópico na app ntfy!
NTFY_TOPIC = "alertas_portateis_feup_123" 

PORTATEIS = [
    {
        "nome": "ASUS TUF A16 FA608UM (Ryzen 7 / RTX 5060 / 32GB) - PCDiga",
        "url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop/computadores-portateis/portatil-asus-tuf-gaming-a16-2025-16-fa608um-r72b56cs1-jaeger-gray-90nr0kv1-m004e0-4711636047074",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF F16 FX608JMR (Intel i7 / RTX 5060 / 32GB) - Worten",
        "url": "https://www.worten.pt/produtos/portatil-gaming-asus-tuf-fx608jmr-intel-core-i7-14650hx-nvidia-geforce-rtx-5060-ram-32-gb-1-tb-ssd-16-8585385",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF F16 FX608JMR (Intel i7 / RTX 5060 / 32GB) - Fnac",
        "url": "https://www.fnac.pt/Computador-Portatil-Gaming-Asus-TUF-A16-FX608JMR-74A56CB1-16-NVIDIA-GeForce-RTX-5060-Intel-Core-i7-14650HX-32GB-1TB-SSD-Computador-Portatil-Computador-Portatil-Gaming/a13799931",
        "alvo": 1500.00
    },
    {
        "nome": "ASUS TUF F16 FX608JMI (Intel i7 / RTX 5060 / 32GB) - PcComponentes",
        "url": "https://www.pccomponentes.pt/portatil-asus-tuf-gaming-f16-fx608jmi-74b56cs1-16-intel-core-i7-14650hx-32gb-1tb-ssd-rtx-5060-pt",
        "alvo": 1500.00
    }
]

def enviar_alerta(mensagem):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=mensagem.encode('utf-8'),
            headers={"Title": "🚨 Portátil ASUS - Alerta", "Tags": "computer,moneybag", "Priority": "high"},
            timeout=10
        )
    except Exception as e:
        print(f"Erro ao enviar notificação: {e}")

async def obter_preco(page, url):
    try:
        # networkidle espera que a página pare totalmente de carregar elementos anti-bot
        await page.goto(url, wait_until="networkidle", timeout=50000)
        # Espera adicional para os pop-ups de cookies passarem
        await page.wait_for_timeout(5000) 
        
        html = await page.content()
        padrao_moeda = re.compile(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*€|(\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s*€')
        numeros = padrao_moeda.findall(html)
        
        if numeros:
            for match in numeros:
                n = match[0] if match[0] else match[1]
                valor_limpo = float(n.replace('.', '').replace(',', '.'))
                if 800 <= valor_limpo <= 2500: 
                    return valor_limpo
    except Exception as e:
        pass
    return None

async def main():
    async with async_playwright() as p:
        # Argumentos especiais para enganar sistemas Cloudflare/Datadome
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        # Elimina a assinatura padrão de robô do Playwright
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        
        for p_info in PORTATEIS:
            print(f"\n🔍 A verificar: {p_info['nome']}...")
            preco = await obter_preco(page, p_info["url"])
            
            if preco:
                print(f"   => Preço atual lido: {preco}€ (Orçamento: {p_info['alvo']}€)")
                if preco <= p_info["alvo"]:
                    msg = f"O modelo {p_info['nome']} baixou para {preco}€!\n\nCompra aqui: {p_info['url']}"
                    enviar_alerta(msg)
            else:
                print("   => ❌ Não foi possível identificar um preço de portátil válido nesta página hoje.")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
