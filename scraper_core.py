import json, os, re, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE=Path(__file__).resolve().parent; CONFIG_PATH=BASE/'config'/'config.json'; HISTORY_PATH=BASE/'data'/'history.json'; NTFY_TOPIC=os.getenv('NTFY_TOPIC','')
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
EXCLUDE=['recondicionado','refurbished','usado','outlet','grade a','grade b','grade c','seminovo','open box']
BRANDS={'asus':['rog','tuf','vivobook','zenbook','expertbook','proart'],'lenovo':['legion','loq','ideapad','thinkpad','thinkbook','yoga'],'hp':['omen','victus','omnibook','elitebook','probook','envy','pavilion'],'acer':['predator','nitro','swift','aspire','travelmate'],'msi':['raider','vector','stealth','crosshair','katana','prestige','creator'],'dell':['alienware','g-series','g15','g16','xps','inspiron','latitude']}
KPT=['teclado portugues','teclado pt','teclado pt-pt','keyboard portugues','keyboard pt','keyboard pt-pt','layout pt','layout pt-pt','portuguese keyboard','portuguese layout','pt keyboard','pt-pt']
KNPT=['teclado espanhol','spanish keyboard','spanish layout','teclado frances','french keyboard','french layout','teclado alemao','german keyboard','german layout','teclado ingles','english keyboard','keyboard us','us keyboard','us layout','en-us keyboard','uk keyboard','uk layout','italian keyboard','italian layout','swedish keyboard','swedish layout','danish keyboard','danish layout','belgian keyboard','belgian layout','swiss keyboard','swiss layout','azerty','qwertz']
SNO=['esgotado','fora de stock','out of stock','indisponivel','temporariamente indisponivel','sem stock','unavailable','not available','sold out']
SSI=['em stock','em estoque','disponivel','disponibilidade: disponivel','available','in stock','order now','adicionar ao carrinho','adiciona ao carrinho','add to cart','em stock online']
CPU_PATTERNS=[r'core\\s+ultra\\s+[3579]\\s+\\d{3,4}[a-z]*',r'core\\s+[3579]\\s+\\d{3,4}[a-z]*',r'core\\s+i[3579]\\s+\\d{4,5}[a-z]*',r'i[3579]-\\d{4,5}[a-z]*',r'ryzen(?:\\s+ai)?\\s+[3579]\\s+\\d{3,4}[a-z]*']
GPU_MODELOS=['rtx 5090','rtx 5080','rtx 5070 ti','rtx 5070','rtx 5060 ti','rtx 5060','rtx 5050','rtx 4090','rtx 4080','rtx 4070','rtx 4060','rtx 4050','rtx a5500','rtx a5000','rtx a4500','rtx a3000','rtx a2000','radeon rx 7900m','radeon rx 7800m','radeon rx 7700s','radeon rx 7600s','radeon rx 7600m xt','radeon rx 7600m','radeon rx 6850m xt','radeon rx 6800m','radeon rx 6650m','radeon rx 6600m','radeon rx 6550m','radeon rx 6500m']
GPU_MODELOS=sorted(GPU_MODELOS,key=len,reverse=True)
GPU_GEN=['rtx graphics','rtx discrete','geforce rtx','geforce mx','radeon rx','radeon pro','radeon 6xxxm','radeon 7xxxm']
IGPU=['intel iris','intel arc graphics','intel graphics','intel uhd','intel xe','intel xe graphics','intel arc integrated','radeon graphics','radeon 610m','radeon 680m','radeon 780m','radeon 840m','radeon 890m','radeon 760m','amd radeon graphics','amd integrated graphics','qualcomm adreno','adreno','qualcomm gpu']
GPU_SCORE={'rtx 5090':100,'rtx 5080':98,'rtx 5070 ti':97,'rtx 5070':95,'rtx 5060 ti':90,'rtx 5060':85,'rtx 5050':60,'rtx 4090':100,'rtx 4080':98,'rtx 4070':80,'rtx 4060':65,'rtx 4050':45,'rtx a5500':96,'rtx a5000':92,'rtx a4500':82,'rtx a3000':68,'rtx a2000':55,'radeon rx 7900m':96,'radeon rx 7800m':88,'radeon rx 7700s':80,'radeon rx 7600s':68,'radeon rx 7600m xt':72,'radeon rx 7600m':65,'radeon rx 6850m xt':78,'radeon rx 6800m':76,'radeon rx 6650m':60,'radeon rx 6600m':56,'radeon rx 6550m':48,'radeon rx 6500m':42}
GPU_FLOOR={'rtx 5090':1600,'rtx 5080':1250,'rtx 5070 ti':1000,'rtx 5070':850,'rtx 5060 ti':700,'rtx 5060':600,'rtx 5050':500,'rtx 4090':1400,'rtx 4080':1200,'rtx 4070':850,'rtx 4060':650,'rtx 4050':500,'rtx a5500':1300,'rtx a5000':1200,'rtx a4500':900,'rtx a3000':650,'rtx a2000':550,'radeon rx 7900m':1100,'radeon rx 7800m':850,'radeon rx 7700s':750,'radeon rx 7600s':650,'radeon rx 7600m xt':700,'radeon rx 7600m':600,'radeon rx 6850m xt':750,'radeon rx 6800m':750,'radeon rx 6650m':550,'radeon rx 6600m':500,'radeon rx 6550m':450,'radeon rx 6500m':400}

def norm(x): return re.sub(r'\\s+',' ', ''.join(c for c in unicodedata.normalize('NFKD',x or '') if not unicodedata.combining(c))).lower().strip()
def load(p):
 try:return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
 except Exception:return {}
def save(p,d): p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(p)
def price(v):
 if v is None:return None
 s=str(v).strip().replace('€','').replace('\xa0','').replace(' ','')
 try:return float(s.replace('.','').replace(',','.')) if ',' in s and '.' in s and s.rfind(',')>s.rfind('.') else float(s.replace(',','.'))
 except:return None
def prices(t): return [v for r in re.findall(r'(?<!\\d)(\\d{1,4}(?:[.,]\\d{2})?)\\s*€',t) if (v:=price(r)) is not None and 50<=v<=10000]
def stock(t):
 t=norm(t)
 if any(x in t for x in SNO):return False
 if any(x in t for x in SSI):return True
 return None
def brand(t):
 t=norm(t)
 for b,subs in BRANDS.items():
  if re.search(rf'\\b{b}\\b',t):
   for sub in subs:
    if re.search(rf'\\b{re.escape(sub)}\\b',t):return b,sub
   return b,None
 return None,None
def eligible(t):
 t=norm(t); return not any(x in t for x in EXCLUDE) and brand(t)[0] in BRANDS
def cpu(t):
 for p in CPU_PATTERNS:
  m=re.search(p,t)
  if m:
   c=m.group(0); tier='tier_1' if re.search(r'ultra\\s+9|core\\s+i9|ryzen(?:\\s+ai)?\\s+9',c) else 'tier_2' if re.search(r'ultra\\s+7|core\\s+i7|ryzen(?:\\s+ai)?\\s+7',c) else 'tier_3'; lo=c.lower(); cl='hx' if 'hx' in lo else 'hs' if 'hs' in lo else 'h' if re.search(r'\\d+h\\b|\\bh\\b',lo) else 'u_ultra' if re.search(r'(?:\\s|^)(?:u|v|p)\\b',lo) else None
   return c,tier,cl
 return None,None,None

def gpus(text):
 t=norm(text)
 ds=[g for g in GPU_MODELOS if re.search(rf'(?<![a-z0-9]){re.escape(g)}(?![a-z0-9])',t)]
 if ds:return ds,'dedicada',ds[0]
 if any(re.search(rf'(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])',t) for x in GPU_GEN):return [],'dedicada',None
 if any(re.search(rf'(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])',t) for x in IGPU):return [],'integrada',None
 return [],'desconhecida',None

def gpu_from_contexts(contexts):
 """Deteta GPU apenas em pequenos blocos de evidência pertencentes ao produto."""
 clean=[]
 for x in contexts or []:
  x=re.sub(r'\\s+',' ',str(x or '')).strip()
  if 2<=len(x)<=800: clean.append(x)
 dedicated=[]; has_igpu=False; generic_ded=False
 for x in clean:
  ds,gt,gm=gpus(x)
  if ds:
   dedicated.extend(ds)
  elif gt=='dedicada':
   generic_ded=True
  elif gt=='integrada':
   has_igpu=True
 if dedicated:
  unique=[]
  for g in sorted(dedicated,key=len,reverse=True):
   if g not in unique: unique.append(g)
  return unique,'dedicada',unique[0]
 if generic_ded:return [],'dedicada',None
 if has_igpu:return [],'integrada',None
 return [],'desconhecida',None
