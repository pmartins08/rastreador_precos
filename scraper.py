from __future__ import annotations
import json,os,re,time,unicodedata
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup
BASE=Path(__file__).resolve().parent;CONFIG_PATH=BASE/'config'/'config.json';HISTORY_PATH=BASE/'data'/'history.json';NTFY_TOPIC=os.getenv('NTFY_TOPIC','')
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36';HEADERS={'User-Agent':UA,'Accept-Language':'pt-PT,pt;q=0.9,en;q=0.7','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
EXCLUDE=['recondicionado','refurbished','usado','outlet','grade a','grade b','grade c','seminovo','open box'];BRANDS={'asus':{'rog','tuf','vivobook','zenbook','expertbook','proart'},'lenovo':{'legion','loq','ideapad','thinkpad','thinkbook','yoga'},'hp':{'omen','victus','omnibook','elitebook','probook','envy','pavilion'}}
KPT=['teclado portugues','teclado pt','teclado pt-pt','keyboard portugues','keyboard pt','keyboard pt-pt','layout pt','layout pt-pt','portuguese keyboard','portuguese layout','pt keyboard','pt-pt'];KNPT=['teclado espanhol','spanish keyboard','spanish layout','teclado frances','french keyboard','french layout','teclado alemao','german keyboard','german layout','teclado ingles','english keyboard','keyboard us','us keyboard','us layout','en-us keyboard','uk keyboard','uk layout','italian keyboard','italian layout','azerty','qwertz'];SNO=['esgotado','fora de stock','out of stock','indisponivel','temporariamente indisponivel','sem stock','unavailable','not available','sold out'];SSI=['em stock','em estoque','disponivel','disponibilidade: disponivel','available','in stock','order now','adicionar ao carrinho','adiciona ao carrinho','add to cart','em stock online'];BLOCK=('captcha','recaptcha','hcaptcha','verify you are human','just a moment','checking your browser','cf-chl-','access denied','robot check','are you a robot')
GPU_MODELOS=sorted(['rtx 5090','rtx 5080','rtx 5070 ti','rtx 5070','rtx 5060 ti','rtx 5060','rtx 5050','rtx 4090','rtx 4080','rtx 4070','rtx 4060','rtx 4050','rtx a5500','rtx a5000','rtx a4500','rtx a3000','rtx a2000','radeon rx 7900m','radeon rx 7800m','radeon rx 7700s','radeon rx 7600s','radeon rx 7600m xt','radeon rx 7600m','radeon rx 6850m xt','radeon rx 6800m','radeon rx 6650m','radeon rx 6600m','radeon rx 6550m','radeon rx 6500m'],key=len,reverse=True);IGPU=['intel iris','intel arc graphics','intel graphics','intel uhd','intel xe','intel xe graphics','intel arc integrated','radeon graphics','radeon 610m','radeon 680m','radeon 780m','radeon 840m','radeon 890m','radeon 760m','amd radeon graphics','amd integrated graphics','qualcomm adreno','adreno'];GPU_GEN=['rtx graphics','rtx discrete','geforce rtx','geforce mx','radeon rx','radeon pro']
GPU_SCORE={'rtx 5090':100,'rtx 5080':98,'rtx 5070 ti':97,'rtx 5070':95,'rtx 5060 ti':90,'rtx 5060':85,'rtx 5050':60,'rtx 4090':100,'rtx 4080':98,'rtx 4070':80,'rtx 4060':65,'rtx 4050':45,'rtx a5500':96,'rtx a5000':92,'rtx a4500':82,'rtx a3000':68,'rtx a2000':55,'radeon rx 7900m':96,'radeon rx 7800m':88,'radeon rx 7700s':80,'radeon rx 7600s':68,'radeon rx 7600m xt':72,'radeon rx 7600m':65,'radeon rx 6850m xt':78,'radeon rx 6800m':76,'radeon rx 6650m':60,'radeon rx 6600m':56,'radeon rx 6550m':48,'radeon rx 6500m':42};GPU_FLOOR={k:v for k,v in zip(GPU_SCORE,{})}
GPU_FLOOR={'rtx 5090':1600,'rtx 5080':1250,'rtx 5070 ti':1000,'rtx 5070':850,'rtx 5060 ti':700,'rtx 5060':600,'rtx 5050':500,'rtx 4090':1400,'rtx 4080':1200,'rtx 4070':850,'rtx 4060':650,'rtx 4050':500,'rtx a5500':1300,'rtx a5000':1200,'rtx a4500':900,'rtx a3000':650,'rtx a2000':550,'radeon rx 7900m':1100,'radeon rx 7800m':850,'radeon rx 7700s':750,'radeon rx 7600s':650,'radeon rx 7600m xt':700,'radeon rx 7600m':600,'radeon rx 6850m xt':750,'radeon rx 6800m':750,'radeon rx 6650m':550,'radeon rx 6600m':500,'radeon rx 6550m':450,'radeon rx 6500m':400}
CPU_PAT=[r'core\s+ultra\s+[3579]\s+[0-9]{3,5}[a-z]*',r'core\s+[3579]\s+[0-9]{3,5}[a-z]*',r'core\s+i[3579]\s+[0-9]{4,5}[a-z]*',r'i[3579]-[0-9]{4,5}[a-z]*',r'ryzen(?:\s+ai)?\s+[3579]\s+[0-9]{3,5}[a-z]*']
ALIASES={'gpu':['gpu','placa grafica','graphics card','graphic card','graphic processor','processador grafico','video card','vga','placa grafica discreta','placa grafica dedicada'],'igpu':['placa grafica integrada','onboard graphics','integrated graphics','integrated gpu'],'vram':['memoria grafica','graphics memory','video memory','vram'],'tgp':['tgp','total graphics power','potencia grafica'],'cpu':['processador','cpu','processor','modelo do processador'],'ram':['memoria ram','ram','system memory','memory','memoria instalada'],'ram_type':['tipo de memoria','memory type','tipo ram','ram type'],'storage':['disco ssd','ssd','armazenamento','storage','capacidade ssd'],'screen':['ecra','display','screen','painel','tipo de ecra'],'resolution':['resolucao','resolution'],'refresh':['refresh rate','frequencia','taxa de atualizacao','hz'],'brightness':['brilho','brightness','nits','cd/m2'],'panel':['tipo de painel','panel type','panel','technology'],'battery':['bateria','battery','capacidade da bateria','battery capacity'],'weight':['peso','weight','peso do produto'],'keyboard':['teclado','keyboard','layout'],'ram_slots':['slots ram','ram slots','so-dimm','memoria expansivel'],'m2':['m.2','slot m.2','slots m.2','nvme','pcie']}
def norm(x):return re.sub(r'\s+',' ',''.join(c for c in unicodedata.normalize('NFKD',str(x or '')) if not unicodedata.combining(c))).lower().strip()
def load(p):
 try:return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
 except:return {}
def save(p,d):p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def price(v):
 try:
  s=str(v).strip().replace('€','').replace('\xa0','').replace(' ','');return float(s.replace('.','').replace(',','.')) if ',' in s and '.' not in s else float(s.replace(',','.'))
 except:return None
def prices(t):return [v for x in re.findall(r'(?<!\d)(\d{1,4}(?:[.,]\d{2})?)\s*€',t or '') if (v:=price(x)) is not None and 50<=v<=10000]
def stock(t):
 t=norm(t)
 if any(x in t for x in SNO):return False
 if any(x in t for x in SSI):return True
 return None
def brand(t):
 t=norm(t)
 for b,subs in BRANDS.items():
  if re.search(rf'\b{b}\b',t):
   for s in sorted(subs,key=len,reverse=True):
    if re.search(rf'\b{re.escape(s)}\b',t):return b,s
   return b,None
 return None,None
def eligible(t):return not any(x in norm(t) for x in EXCLUDE) and brand(t)[0] in BRANDS
def gp(p):return r'(?<![a-z0-9])'+r'[\s._-]*'.join(re.escape(x) for x in p.split())+r'(?![a-z0-9])'
def gpus(t):
 t=norm(t); d=[x for x in GPU_MODELOS if re.search(gp(x),t)]
 if d:return d,'dedicada',d[0]
 if any(re.search(gp(x),t) for x in GPU_GEN):return [],'dedicada',None
 if any(re.search(gp(x),t) for x in IGPU):return [],'integrada',None
 return [],'desconhecida',None
def cpu(t):
 for p in CPU_PAT:
  m=re.search(p,norm(t))
  if m:
   s=m.group(0);tier='tier_1' if re.search(r'ultra\s+9|core\s+i9|ryzen(?:\s+ai)?\s+9',s) else 'tier_2' if re.search(r'ultra\s+7|core\s+i7|ryzen(?:\s+ai)?\s+7',s) else 'tier_3';lo=s.lower();cls='hx' if 'hx' in lo else 'hs' if 'hs' in lo else 'h' if re.search(r'\d+h\b',lo) else 'u_ultra' if re.search(r'\b[uvp]\b',lo) else None;return s,tier,cls
 return None,None,None
def _key(label):
 n=norm(label)
 for k,a in ALIASES.items():
  if any(re.search(rf'\b{re.escape(x)}\b',n) for x in a):return k
 return None
def pairs(soup):
 out=[]
 for tr in soup.select('table tr'):
  c=[x for x in tr.find_all(['th','td']) if x.get_text(' ',strip=True)]
  if len(c)>=2:out.append((_key(c[0].get_text(' ',strip=True)),c[0].get_text(' ',strip=True),c[1].get_text(' ',strip=True),'table',.98))
 for dt in soup.select('dl dt'):
  dd=dt.find_next_sibling('dd')
  if dd:out.append((_key(dt.get_text(' ',strip=True)),dt.get_text(' ',strip=True),dd.get_text(' ',strip=True),'dl',.98))
 for n in soup.find_all(['li','div','p']):
  a=n.select_one("[class*='label'],[class*='name'],[class*='key']");b=n.select_one("[class*='value'],[class*='detail'],[class*='spec-value']")
  if a and b and a is not b:out.append((_key(a.get_text(' ',strip=True)),a.get_text(' ',strip=True),b.get_text(' ',strip=True),'label_value',.92))
 return [x for x in out if x[0]]
def best(ps):
 return sorted(ps,key=lambda x:x[4],reverse=True)[0] if ps else None
def nram(t):
 if re.search(r'vram|memoria grafica|graphics memory|video memory',norm(t)):return None
 m=re.search(r'\b(4|8|12|16|24|32|48|64|96|128)\s*gb\b',norm(t));return int(m.group(1)) if m else None
def nstorage(t):
 vals=[]
 for m in re.finditer(r'\b(\d+(?:[.,]\d+)?)\s*(tb|gb)\b',norm(t)):
  v=float(m.group(1).replace(',','.'));gb=v*1024 if m.group(2)=='tb' else v
  if 128<=gb<=8192:vals.append(gb)
 return round(max(vals)/1024,2) if vals else None
def extract(title,soup):
 ps=pairs(soup); by={}
 for x in ps:by.setdefault(x[0],[]).append(x)
 o=specs(title);o['fontes']=o.get('fontes',{});o['evidencias']=o.get('evidencias',{});o['conflitos']=o.get('conflitos',[]);o['marca'],o['submarca']=brand(title)
 for k in ['gpu','igpu','cpu','ram','storage','vram','tgp','battery','weight','resolution','screen','refresh','brightness','panel','keyboard','ram_type','ram_slots','m2']:
  z=best(by.get(k,[]))
  if not z:continue
  val=z[2];o['evidencias'][k]=val;o['fontes'][k]=z[3]
  if k=='gpu':
   d,gt,gm=gpus(val);o['gpu_tipo']='dedicada' if d or gt=='dedicada' else gt;o['gpu_modelo']=gm;o['gpu_modelos_detectados']=d
  elif k=='cpu':o['cpu_str_original']=cpu(val)[0];o['cpu_modelo']=cpu(val)[0];o['cpu_classe']=cpu(val)[2]
  elif k=='ram':o['ram_gb']=nram(val)
  elif k=='storage':o['armazenamento_tb']=nstorage(val)
  elif k=='vram':
   m=re.search(r'(\d{1,2})\s*gb',norm(val));o['vram_gb']=int(m.group(1)) if m else None
  elif k=='tgp':
   m=re.search(r'(\d{2,3})\s*w',norm(val));o['tgp_w']=int(m.group(1)) if m else None
  elif k=='battery':
   m=re.search(r'(\d{2,3})\s*wh',norm(val));o['bateria_wh']=int(m.group(1)) if m else None
  elif k=='weight':
   m=re.search(r'(\d[.,]\d+)\s*kg',norm(val));o['peso_kg']=float(m.group(1).replace(',','.')) if m else None
  elif k=='refresh':
   m=re.search(r'(\d{2,3})\s*hz',norm(val));o['ecra_hz']=int(m.group(1)) if m else None
  elif k=='resolution':
   v=norm(val);o['ecra_res']='4k' if re.search(r'3840\s*x\s*2160|4k|uhd',v) else 'qhd+' if re.search(r'2880\s*x\s*1800|2560\s*x\s*1600|wqxga|qhd\+',v) else 'qhd' if re.search(r'2560\s*x\s*1440|qhd',v) else 'fhd+' if re.search(r'1920\s*x\s*1200|wuxga|1200p',v) else 'fhd' if re.search(r'1920\s*x\s*1080|1080p|fhd',v) else o['ecra_res']
  elif k=='screen':
   v=norm(val);m=re.search(r'(\d{1,2}(?:[.,]\d)?)\s*(?:"|inch|polegadas)',v);o['ecra_tamanho']=float(m.group(1).replace(',','.')) if m else o.get('ecra_tamanho');m=re.search(r'(\d{2,3})\s*hz',v);o['ecra_hz']=o.get('ecra_hz') or (int(m.group(1)) if m else None);o['ecra_painel']= 'oled' if 'oled' in v else 'mini-led' if 'mini-led' in v or 'miniled' in v else 'ips' if 'ips' in v else o.get('ecra_painel')
  elif k=='brightness':
   m=re.search(r'(\d{2,4})\s*(?:nits?|cd/m2)',norm(val));o['ecra_brightness_nits']=int(m.group(1)) if m else None
  elif k=='keyboard':
   v=norm(val);o['teclado_pt']='nao_pt' if any(x in v for x in KNPT) else 'confirmado' if any(x in v for x in KPT) else o['teclado_pt']
 o['ram_expansivel']=bool(by.get('ram_slots'));o['ssd_expansivel']=bool(by.get('m2'))
 tg,tt,tgpu=gpus(title)
 if tgpu:o['gpu_tipo']='dedicada';o['gpu_modelo']=tgpu;o['gpu_modelos_detectados']=tg;o['fontes']['gpu']='title';o['evidencias']['gpu']=title
 return o
def specs(text):
 o=extract('',BeautifulSoup('', 'html.parser'));t=norm(text);o['marca'],o['submarca']=brand(t);d,gt,gm=gpus(t);o['gpu_tipo']=gt;o['gpu_modelo']=gm;o['gpu_modelos_detectados']=d;c,_,cl=cpu(t);o['cpu_modelo']=c;o['cpu_str_original']=c;o['cpu_classe']=cl;o['ram_gb']=nram(t);o['armazenamento_tb']=nstorage(t);m=re.search(r'(\d{2,3})\s*wh',t);o['bateria_wh']=int(m.group(1)) if m else None;m=re.search(r'(\d[.,]\d+)\s*kg',t);o['peso_kg']=float(m.group(1).replace(',','.')) if m else None;m=re.search(r'(\d{2,3})\s*hz',t);o['ecra_hz']=int(m.group(1)) if m else None;o['ecra_res']='qhd+' if re.search(r'2560\s*x\s*1600|qhd\+',t) else 'fhd+' if re.search(r'1920\s*x\s*1200|wuxga',t) else 'fhd' if re.search(r'1920\s*x\s*1080|fhd',t) else None;o['teclado_pt']='nao_pt' if any(x in t for x in KNPT) else 'confirmado' if any(x in t for x in KPT) else 'desconhecido';return o
def quality(s):
 q=sum(w for w,v in [(0.16,s.get('cpu_modelo')),(0.24,s.get('gpu_tipo')=='dedicada'),(0.16,s.get('ram_gb')),(0.10,s.get('armazenamento_tb')),(0.10,s.get('bateria_wh')),(0.08,s.get('peso_kg')),(0.08,s.get('ecra_res')),(0.08,s.get('ecra_hz'))] if v);return q,'ALTA' if q>=.85 else 'MEDIA' if q>=.55 else 'BAIXA'
def tier(v,c):return 'DIAMANTE' if v>=float(c.get('diamante_value_min',130)) else 'OURO' if v>=float(c.get('ouro_value_min',110)) else 'PRATA' if v>=float(c.get('prata_value_min',90)) else 'BRONZE' if v>=float(c.get('bronze_value_min',70)) else None
def pscore(p,c):
 s=float(c.get('budget_soft',1300));h=float(c.get('budget_hard',1500));return 150 if p<=s else max(70,100-(p-h)/max(h,1)*60) if p>=h else 150-50*(p-s)/max(h-s,1)
def score(s,p,w,c):
 if s.get('teclado_pt')=='nao_pt':return {'status':'REJEITADO','alertas':['Teclado explicitamente não português.']}
 if s.get('gpu_tipo')=='integrada':return {'status':'REJEITADO','alertas':['GPU apenas integrada — excluído.']}
 if s.get('gpu_tipo')=='desconhecida':return {'status':'ACEITE','score_final':0,'score_ranking':0,'value_score':0,'oportunidade':None,'qualidade_dados':'BAIXA','confianca_percentual':'0%','fontes_extraidas':s.get('fontes',{}),'alertas':['GPU não confirmada — sem oportunidade.'],'detalhes':{}}
 if s.get('ram_gb')==8:return {'status':'REJEITADO','alertas':['8GB RAM confirmado - insuficiente.']}
 if s.get('peso_kg') and s['peso_kg']>2.8:return {'status':'REJEITADO','alertas':['Excede limite de peso (>2.8kg).']}
 r=s.get('ram_gb');a=s.get('armazenamento_tb');cv={'tier_1':100,'tier_2':85,'tier_3':70}.get(cpu(s.get('cpu_modelo') or '')[1],50);gpv=GPU_SCORE.get(s.get('gpu_modelo'),45);rp=50 if r is None else 100 if r>=32 else 80 if r>=16 else 40;ap=50 if a is None else 100 if a>=2 else 85 if a>=1 else 65;res={'4k':100,'qhd+':100,'qhd':95,'fhd+':85,'fhd':75,None:60}.get(s.get('ecra_res'),60);hz=min(100,(s.get('ecra_hz') or 60)/1.65);bat=50 if not s.get('bateria_wh') else max(0,min(100,s['bateria_wh']/90*100)-{'hx':20,'h':10,'hs':5,'u_ultra':0,None:10}.get(s.get('cpu_classe'),10));wt=50 if not s.get('peso_kg') else 100 if s['peso_kg']<=1.4 else 0 if s['peso_kg']>=2.8 else max(0,100-(s['peso_kg']-1.4)*71.4);conf,q=quality(s);fe=rp*.2+bat*.3+ap*.15+res*.2+cv*.15;gaming=gpv*.65+cv*.2+hz*.1+rp*.05;long=(100 if r and r>=32 else 95 if r==16 and s.get('ram_expansivel') else 75 if r==16 else 50)*.35+(100 if a and a>=2 else 85 if a==1 else 50)*.25+bat*.2+cv*.2;final=fe*.5+gaming*.25+long*.15+wt*.1;rank=round(max(0,min(100,final*(.85+.15*conf))),1);value=round(.7*rank+.3*pscore(p,c),1);return {'status':'ACEITE','score_final':round(final,1),'score_ranking':rank,'value_score':value,'oportunidade':tier(value,c) if q in ('ALTA','MEDIA') else None,'qualidade_dados':q,'confianca_percentual':f'{int(conf*100)}%','fontes_extraidas':s.get('fontes',{}),'alertas':s.get('alertas',[]),'detalhes':{'gpu':s.get('gpu_modelo'),'gpu_tipo':s.get('gpu_tipo'),'vram_gb':s.get('vram_gb'),'tgp_w':s.get('tgp_w'),'cpu':s.get('cpu_str_original'),'ram_gb':r,'armazenamento_tb':a,'ecra_res':s.get('ecra_res'),'ecra_hz':s.get('ecra_hz')}}
def validate_price(s,p,c):
 if p<=0 or p<float(c.get('preco_minimo_global',250)):return False
 g=s.get('gpu_modelo');f=(c.get('gpu_preco_min') or {}).get(g,GPU_FLOOR.get(g)) if g else None;return not f or p>=float(f)
def alert(prev,cur,c):
 if prev is None:return (True,'nova oportunidade '+cur['oportunidade'].lower()) if cur.get('oportunidade') else (False,'')
 if isinstance(prev.get('price'),(int,float)) and cur['preco']<prev['price']-float(c.get('alerta_queda_preco_eur',5)):return True,f"queda de preço: {prev['price']:.2f}€ → {cur['preco']:.2f}€"
 if cur.get('oportunidade') and cur.get('oportunidade')!=prev.get('oportunidade'):return True,'escalou para '+cur['oportunidade'].lower()
 return False,''
def blocked(r):
 if r.status_code in {401,403,429,503}:return True,f'HTTP {r.status_code}'
 try:t=norm((BeautifulSoup(r.text,'html.parser').title.get_text(' ',strip=True) if BeautifulSoup(r.text,'html.parser').title else '')+' '+r.text[:60000])
 except:t=''
 return next(((True,x) for x in BLOCK if x in t),(False,None))
def fetch(session,url,timeout,referer=''):
 h=dict(HEADERS);h.update({'Referer':referer} if referer else {});last=None
 for i in range(3):
  try:
   r=session.get(url,timeout=timeout,allow_redirects=True,headers=h);b,why=blocked(r)
   if not b and r.status_code<400:return r.text,r,None
   if b:return None,r,why
   last=f'HTTP {r.status_code}'
  except requests.RequestException as e:last=str(e)
  if i<2:time.sleep(1+i)
 return None,None,last
def jsonld(soup,base):
 out=[]
 for sc in soup.select('script[type="application/ld+json"]'):
  try:o=json.loads(sc.string or sc.get_text())
  except:continue
  stack=[o]
  while stack:
   x=stack.pop()
   if isinstance(x,list):stack.extend(x);continue
   if not isinstance(x,dict):continue
   typ=x.get('@type');types=typ if isinstance(typ,list) else [typ];off=x.get('offers');off=off[0] if isinstance(off,list) and off else off if isinstance(off,dict) else {};p=price(off.get('price'));name=x.get('name')
   if name and p:out.append({'titulo':str(name).strip(),'preco':p,'url':urljoin(base,str(x.get('url') or off.get('url') or base))})
   stack.extend(v for v in x.values() if isinstance(v,(dict,list)))
 return out
def candidates(soup,cfg,base,limit):
 hints=cfg.get('product_path_hints',[]);cards=[]
 for sel in cfg.get('card_selectors') or ['article','li[class*="product"]','div[class*="product-card"]','div[class*="productCard"]','div[class*="product-item"]','[data-product-id]']:
  try:cards+=soup.select(sel)
  except:pass
 out=[];seen=set()
 for c in cards:
  n=c.select_one('h1,h2,h3,h4,[class*="title"],[class*="name"],a[title],img[alt]');t=(n.get('alt') or n.get('title') or n.get_text(' ',strip=True)) if n else '';p=current_price(c)
  if len(t)<10 or p is None or not 100<=p<=10000:continue
  aa=[(5 if any(x.lower() in (a.get('href') or '').lower() for x in hints) else 0,a.get('href')) for a in c.select('a[href]')];u=urljoin(base,max(aa or [(0,base)])[1]);k=(norm(t),u)
  if k in seen:continue
  seen.add(k);out.append({'titulo':re.sub(r'\s+',' ',t).strip(),'preco':p,'preco_anterior':old_price(c,p),'url':u,'stock':stock(c.get_text(' ',strip=True))})
  if len(out)>=limit:break
 return out
def current_price(card):
 vals=[]
 for n in card.select('[itemprop="price"],[data-price],meta[property="product:price:amount"]'):
  v=price(n.get('content') or n.get('data-price') or n.get_text(' ',strip=True));
  if v is not None:vals.append(v)
 if vals:return min(vals)
 vals=prices(card.get_text(' ',strip=True));return min(vals) if vals else None
def old_price(card,cur):
 vals=[]
 for n in card.select('[class*="old"],[class*="was"],del,s,strike'):vals+=prices(n.get_text(' ',strip=True))
 vals=[v for v in vals if cur is None or v>cur+.01];return min(vals) if vals else None
def category(session,cfg,limit):
 text,r,err=fetch(session,cfg['url'],max(5,int(cfg.get('timeout_ms',12000))//1000))
 if text is None:return {'loja':cfg['loja'],'url':cfg['url'],'produtos':[],'bloqueada':True,'erro':err,'status_code':r.status_code if r else None}
 soup=BeautifulSoup(text,'html.parser');items=jsonld(soup,r.url)+candidates(soup,cfg,r.url,limit);out=[];seen=set()
 for x in items:
  k=norm(x['titulo'])
  if k in seen or not eligible(x['titulo']):continue
  x['loja']=cfg['loja'];x['_category_url']=r.url;out.append(x);seen.add(k)
  if len(out)>=limit:break
 return {'loja':cfg['loja'],'url':r.url,'produtos':out,'bloqueada':False,'erro':None,'status_code':r.status_code}
def enrich(session,item):
 text,r,err=fetch(session,item['url'],12,item.get('_category_url',''));item.setdefault('_fetch',{})['detail_error']=err
 if not text:return item
 soup=BeautifulSoup(text,'html.parser');h=soup.select_one('h1');title=h.get_text(' ',strip=True) if h else item['titulo'];pg=extract(title,soup);sp=item['_specs'];tg,tt,tgpu=gpus(title)
 if tgpu:sp['gpu_tipo']='dedicada';sp['gpu_modelo']=tgpu;sp['gpu_modelos_detectados']=tg;sp.setdefault('fontes',{})['gpu']='title'
 else:sp.update({k:v for k,v in pg.items() if v not in (None,'desconhecido','desconhecida',[],False)});sp.setdefault('fontes',{}).update(pg.get('fontes',{}));sp.setdefault('evidencias',{}).update(pg.get('evidencias',{}));sp.setdefault('conflitos',[]).extend(pg.get('conflitos',[]));sp.setdefault('alertas',[]).extend(x for x in pg.get('alertas',[]) if x not in sp['alertas'])
 item['_specs']=sp;return item
def keyboard(session,item):
 sp=item['_specs']
 if sp.get('teclado_pt')!='desconhecido':return item
 text,_,_=fetch(session,item['url'],10)
 if text:
  t=norm(text);sp['teclado_pt']='nao_pt' if any(x in t for x in KNPT) else 'confirmado' if any(x in t for x in KPT) else 'desconhecido'
 return item
def notify(title,msg,prio='default'):
 if not NTFY_TOPIC:print('⚠️ NTFY_TOPIC não definido; notificação ignorada.');return False
 try:r=requests.post('https://ntfy.sh',json={'topic':NTFY_TOPIC,'title':title,'message':msg,'priority':4 if prio=='high' else 3,'tags':['computer']},timeout=10);r.raise_for_status();return True
 except requests.RequestException as e:print('❌ ntfy:',e);return False
def validar_url(i):return bool(i.get('url') and urlparse(i['url']).scheme in {'http','https'})
def smoke_tests():
 c={'bronze_value_min':70,'prata_value_min':90,'ouro_value_min':110,'diamante_value_min':130,'preco_minimo_global':250,'alerta_queda_preco_eur':5,'gpu_preco_min':{'rtx 5090':1600},'budget_soft':1300,'budget_hard':1500};w={'gpu_base':GPU_SCORE,'cpu_base':{'tier_1':100,'tier_2':85,'tier_3':70}}
 assert specs('ASUS Vivobook Intel UHD Graphics Core 7 350 16GB 512GB')['gpu_tipo']=='integrada';assert score(specs('ASUS Vivobook Intel UHD Graphics Core 7 350 16GB 512GB'),900,w,c)['status']=='REJEITADO'
 for x in ['RTX 5070','RTX5070','RTX-5070','RTX.5070']:assert specs('ASUS TUF '+x)['gpu_modelo']=='rtx 5070'
 html='<table><tr><th>Placa gráfica discreta</th><td>NVIDIA GeForce RTX 5070</td></tr><tr><th>Memória gráfica</th><td>8 GB GDDR7</td></tr><tr><th>TGP</th><td>115 W</td></tr><tr><th>Memória RAM</th><td>32 GB DDR5</td></tr><tr><th>Disco SSD</th><td>1 TB NVMe</td></tr><tr><th>Resolução</th><td>2560 x 1600</td></tr><tr><th>Refresh Rate</th><td>240 Hz</td></tr><tr><th>Bateria</th><td>90 Wh</td></tr><tr><th>Peso</th><td>2,05 kg</td></tr></table>';s=extract('ASUS TUF RTX 5070',BeautifulSoup(html,'html.parser'));assert s['gpu_modelo']=='rtx 5070' and s['vram_gb']==8 and s['tgp_w']==115 and s['ram_gb']==32 and s['armazenamento_tb']==1 and s['ecra_res']=='qhd+' and s['ecra_hz']==240 and s['bateria_wh']==90
 ok,reason=alert({'price':1700,'oportunidade':'OURO'},{'preco':1400,'oportunidade':'OURO'},c);assert ok and '1700.00€' in reason and '1400.00€' in reason
 print('OK: V8 estruturada, GPU/RAM/VRAM/TGP/ecrã/bateria, scoring e histórico.')
def main():
 started=datetime.now(timezone.utc);cfg=load(CONFIG_PATH);hist=load(HISTORY_PATH);hist.setdefault('offers',{});settings=cfg.get('settings',{});weights=cfg.get('weights',{});cats=cfg.get('category_urls',[]);budget=float(settings.get('budget_hard',1500));workers=min(max(1,len(cats)),int(settings.get('max_lojas_paralelas',6)));limit=int(settings.get('max_produtos_por_categoria',30));enrich_n=int(settings.get('max_enriquecimentos_detalhe',48));session=requests.Session();session.headers.update(HEADERS);results={}
 with ThreadPoolExecutor(max_workers=workers) as ex:
  fs={ex.submit(category,session,c,limit):c['loja'] for c in cats}
  for f in as_completed(fs):
   try:results[fs[f]]=f.result()
   except Exception as e:results[fs[f]]={'loja':fs[f],'produtos':[],'bloqueada':False,'erro':str(e),'status_code':None}
 pending=[];stats={'bloqueadas':0,'encontrados':0,'candidatos':0,'enriquecidos':0,'aceites':0,'rej':0,'igpu':0,'desconhecida':0,'tiers':{'DIAMANTE':0,'OURO':0,'PRATA':0,'BRONZE':0},'alertas':0}
 lojas={c['loja']:{'encontrados':0,'candidatos':0,'aceites':0,'rejeitados':0,'bloqueada':False} for c in cats}
 for c in cats:
  loja=c['loja'];r=results.get(loja,{});lojas[loja]['encontrados']=len(r.get('produtos',[]));lojas[loja]['bloqueada']=bool(r.get('bloqueada'));stats['encontrados']+=lojas[loja]['encontrados'];stats['bloqueadas']+=int(lojas[loja]['bloqueada'])
  for it in r.get('produtos',[]):
   if it['preco']>budget or not eligible(it['titulo']):continue
   it['_specs']=specs(it['titulo']);lojas[loja]['candidatos']+=1;stats['candidatos']+=1
   if validate_price(it['_specs'],it['preco'],settings):pending.append(it)
   else:lojas[loja]['rejeitados']+=1
 pending=sorted(pending,key=lambda x:(x['_specs'].get('gpu_tipo')=='dedicada',x['preco']))[:enrich_n]
 with ThreadPoolExecutor(max_workers=workers) as ex:
  for f in as_completed([ex.submit(enrich,session,x) for x in pending]):f.result();stats['enriquecidos']+=1
 with ThreadPoolExecutor(max_workers=workers) as ex:
  for f in as_completed([ex.submit(keyboard,session,x) for c in cats for x in results.get(c['loja'],{}).get('produtos',[]) if x.get('_specs',{}).get('teclado_pt')=='desconhecido']):f.result()
 top=[]
 for c in cats:
  loja=c['loja']
  for it in results.get(loja,{}).get('produtos',[]):
   s=it.get('_specs');
   if not s:continue
   if not validate_price(s,it['preco'],settings) or s.get('gpu_tipo')=='integrada':stats['rej']+=1;stats['igpu']+=int(s.get('gpu_tipo')=='integrada');lojas[loja]['rejeitados']+=1;continue
   a=score(s,it['preco'],weights,settings)
   if a['status']=='REJEITADO':stats['rej']+=1;lojas[loja]['rejeitados']+=1;continue
   stats['aceites']+=1;lojas[loja]['aceites']+=1;stats['desconhecida']+=int(s.get('gpu_tipo')=='desconhecida');
   if a.get('oportunidade'):stats['tiers'][a['oportunidade']]+=1
   top.append((a['value_score'],a['score_ranking'],loja,it['titulo'],it['preco'],a.get('oportunidade'),s.get('gpu_modelo') or s.get('gpu_tipo')))
   key=f"{loja}::{it.get('url') or it['titulo']}";e=hist['offers'].setdefault(key,[]);prev=e[-1] if e else None;e.append({'timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'price':it['preco'],'price_previous':it.get('preco_anterior'),'value_score':a.get('value_score',0),'score_ranking':a.get('score_ranking',0),'oportunidade':a.get('oportunidade'),'qualidade_dados':a.get('qualidade_dados'),'confianca_percentual':a.get('confianca_percentual'),'gpu':s.get('gpu_modelo'),'gpu_tipo':s.get('gpu_tipo'),'vram_gb':s.get('vram_gb'),'tgp_w':s.get('tgp_w'),'cpu':s.get('cpu_str_original'),'ram_gb':s.get('ram_gb'),'armazenamento_tb':s.get('armazenamento_tb'),'ecra_res':s.get('ecra_res'),'ecra_hz':s.get('ecra_hz'),'bateria_wh':s.get('bateria_wh'),'peso_kg':s.get('peso_kg'),'fontes':s.get('fontes',{}),'conflitos':s.get('conflitos',[]),'url':it['url']});hist['offers'][key]=e[-60:];ok,why=alert(prev,{'preco':it['preco'],'oportunidade':a.get('oportunidade')},settings)
   if ok and it.get('stock') is not False and validar_url(it):stats['alertas']+=int(notify(f"💻 {a.get('oportunidade') or 'ATUALIZAÇÃO'} | {it['preco']:.0f}€",f"{it['titulo']}\nLoja: {loja}\nPreço: {it['preco']:.2f}€\nMotivo: {why}\nGPU: {s.get('gpu_modelo') or s.get('gpu_tipo')}\nVRAM: {s.get('vram_gb') or '?'}GB\nCPU: {s.get('cpu_str_original') or '?'}\nRAM: {s.get('ram_gb') or '?'}GB\nScore: {a.get('score_ranking',0):.1f}\nValue: {a.get('value_score',0):.1f}\nConfiança: {a.get('confianca_percentual','0%')}\n🔗 {it['url']}",'high' if a.get('oportunidade') in {'DIAMANTE','OURO'} else 'default'))
 save(HISTORY_PATH,hist);top.sort(reverse=True);elapsed=(datetime.now(timezone.utc)-started).total_seconds();print('🔎 TOP oportunidades:');[print(f'   {x[2]} | {x[4]:.2f}€ | Rank {x[1]:.1f} | Value {x[0]:.1f} | {x[5] or "—"} | {x[6]} | {x[3]}') for x in top[:8]];[print(f"🏪 {k}: encontrados={v['encontrados']} candidatos={v['candidatos']} aceites={v['aceites']} rejeitados={v['rejeitados']} bloqueada={v['bloqueada']}") for k,v in lojas.items()];summary=f"📊 V8 | Lojas: {len(cats)} | Bloqueadas: {stats['bloqueadas']} | Encontrados: {stats['encontrados']} | Candidatos: {stats['candidatos']} | Enriquecidos: {stats['enriquecidos']} | Aceites: {stats['aceites']} | iGPU: {stats['igpu']} | GPU desconhecida: {stats['desconhecida']} | Alertas: {stats['alertas']} | Diamante: {stats['tiers']['DIAMANTE']} | Ouro: {stats['tiers']['OURO']} | Prata: {stats['tiers']['PRATA']} | Bronze: {stats['tiers']['BRONZE']} | {elapsed:.1f}s";print(summary);notify('🔄 Relatório de Rastreio V8',summary)
if __name__=='__main__': smoke_tests() if os.getenv('SMOKE_TEST')=='1' else main()
