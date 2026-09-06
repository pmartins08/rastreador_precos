import requests
import re

NTFY_TOPIC = "alertas_portateis_feup_123" 
SCRAPER_API_KEY = "ee8b2011dbaf963c6ca4bfe22a819c28"

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
            headers={"Title": "🚨 Alerta Portáteis FEUP", "Tags": "computer,moneybag", "Priority": "high"}
        )
    except Exception as e:
        print(f"Erro na notificação: {e}")

def obter_preco(url):
    params = {'api_key': SCRAPER_API_KEY, 'url': url, 'render': 'true', 'country_code': 'pt'}
    try:
        resp = requests.get('https://api.scraperapi.com/', params=params, timeout=120)
        numeros = re.findall(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*€|(\d{1,3}(?:,\d{3})*(?:\.\d{2}))\s*€', resp.text)
        if numeros:
            for match in numeros:
                n = match[0] if match[0] else match[1]
                valor = float(n.replace('.', '').replace(',', '.'))
                # Filtro de segurança adaptado ao orçamento exigido pelo estudo
                if 800 <= valor <= 2500: 
                    return valor
    except Exception as e:
        print(f"Falha na ligação: {e}")
    return None

def main():
    for p in PORTATEIS:
        print(f"\n🔍 A extrair com ScraperAPI: {p['nome']}...")
        preco = obter_preco(p["url"])
        if preco:
            print(f"   => Preço lido: {preco}€ (Alvo: {p['alvo']}€)")
            if preco <= p["alvo"]:
                enviar_alerta(f"{p['nome']} desceu para {preco}€!\nLink: {p['url']}")
        else:
            print("   => ❌ Bloqueado ou preço invisível.")

if __name__ == "__main__":
    main()
