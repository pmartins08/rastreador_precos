import asyncio
from playwright.async_api import async_playwright
import requests
import re

# ==========================================
# CONFIGURAÇÃO DO UTILIZADOR
# ==========================================
# Substitui pelo nome do tópico secreto criado na app ntfy
NTFY_TOPIC = "alertas_portateis_2026" 

# Lista atualizada focada exclusivamente na linha ASUS TUF (RTX 5060 / 32GB) 
# Modelos validados: FX608JMR (Intel) e FA608UM (AMD). O modelo da Rádio Popular foi ignorado.
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

# ==========================================
# LÓGICA DE ALERTA E EXTRAÇÃO
# ==========================================
def enviar_alerta(mensagem):
    """Envia uma notificação push imediata para o telemóvel via ntfy."""
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=mensagem.encode('utf-8'),
            headers={
                "Title": "🚨 Portátil ASUS - Alerta de Preço", 
                "Tags": "computer,moneybag",
                "Priority": "high"
            },
            timeout=10
        )
    except Exception as e:
        print(f"Erro ao enviar notificação: {e}")

async def obter_preco(page, url):
    """Acede à página, aguarda o carregamento completo e extrai o preço validado."""
    try:
        # Acesso robusto anti-bloqueio com timeout de 45 segundos
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Opcional: pequeno compasso de espera para garantir renderização de scripts na Worten/PCDiga
        await page.wait_for_timeout(3000) 
        
        html = await page.content()
        
        # Regex avançado para apanhar formatos europeus (ex: 1.499,00€ ou 1499,00 €)
        padrao_moeda = re.compile(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*€|(\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s*€')
        numeros = padrao_moeda.findall(html)
        
        if numeros:
            for match in numeros:
                # O match retorna um tuple devido aos grupos na regex
                n = match[0] if match[0] else match[1]
                # Normalização: remove os pontos dos milhares e troca vírgula decimal por ponto
                valor_limpo = float(n.replace('.', '').replace(',', '.'))
                
                # Filtro de segurança: Portáteis deste calibre não custam menos de 800€ nem mais de 2500€
                if 800 <= valor_limpo <= 2500: 
                    return valor_limpo
    except Exception as e:
        print(f"Falha na extração para {url}: {e}")
    return None

# ==========================================
# MOTOR PRINCIPAL ASSÍNCRONO
# ==========================================
async def main():
    async with async_playwright() as p:
        # Lança o navegador virtual imitando um utilizador real para evitar bloqueios
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        for p_info in PORTATEIS:
            print(f"\n🔍 A verificar: {p_info['nome']}...")
            preco = await obter_preco(page, p_info["url"])
            
            if preco:
                print(f"   => Preço atual lido: {preco}€ (Orçamento: {p_info['alvo']}€)")
                if preco <= p_info["alvo"]:
                    msg = (
                        f"O modelo {p_info['nome']} baixou para {preco}€!\n\n"
                        f"Compra aqui: {p_info['url']}"
                    )
                    enviar_alerta(msg)
                    print("   => 🚨 ALERTA DISPARADO!")
            else:
                print("   => ❌ Não foi possível identificar um preço de portátil válido nesta página hoje.")
                
        await browser.close()

if __name__ == "__main__":
    # Garante a execução sem erros em ambientes Windows/Linux
    asyncio.run(main())
