import json, os, re, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
BASE=Path(__file__).resolve().parent; CONFIG_PATH=BASE/'config'/'config.json'; HISTORY_PATH=BASE/'data'/'history.json'; NTFY_TOPIC=os.getenv('NTFY_TOPIC','')
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
EXCLUDE=['recondicionado','refurbished','usado','outlet','grade a','grade b','grade c','seminovo','open box']
BRANDS={'asus':['rog','tuf','vivobook','zenbook','expertbook','proart'],'lenovo':['legion','loq','ideapad','thinkpad','thinkbook','yoga'],'hp':['omen','victus','omnibook','elitebook','probook','envy','pavilion'],'acer':['predator','nitro','swift','aspire','travelmate'],'msi':['raider','vector','stealth','crosshair','katana','prestige','creator'],'dell':['alienware','g-series','g15','g16','xps','inspiron','latitude']}
KPT=['teclado portugues','teclado pt','teclado pt-pt','keyboard portugues','keyboard pt','keyboard pt-pt','layout pt','layout pt-pt','portuguese keyboard','portuguese layout','pt keyboard','pt-pt']; KNPT=['teclado espanhol','spanish keyboard','spanish layout','teclado frances','french keyboard','french layout','teclado alemao','german keyboard','german layout','teclado ingles','english keyboard','keyboard us','us keyboard','us layout','en-us keyboard','uk keyboard','uk layout','italian keyboard','italian layout','swedish keyboard','swedish layout','danish keyboard','danish layout','belgian keyboard','belgian layout','swiss keyboard','swiss layout','azerty','qwertz']
SNO=['esgotado','fora de stock','out of stock','indisponivel','temporariamente indisponivel','sem stock','unavailable','not available','sold out']; SSI=['em stock','em estoque','disponivel','disponibilidade: disponivel','available','in stock','order now','adicionar ao carrinho','adiciona ao carrinho','add to cart','em stock online']
CPU_PATTERNS=[r'core\s+ultra\s+[3579]\s+\d{3,4}[a-z]*',r'core\s+[3579]\s+\d{3,4}[a-z]*',r'core\s+i[3579]\s+\d{4,5}[a-z]*',r'i[3579]-\d{4,5}[a-z]*',r'ryzen(?:\s+ai)?\s+[3579]\s+\d{3,4}[a-z]*']
GPU_MODELOS=sorted(['rtx 5090','rtx 5080','rtx 5070 ti','rtx 5070','rtx 5060 ti','rtx 5060','rtx 5050','rtx 4090','rtx 4080','rtx 4070','rtx 4060','rtx 4050','rtx a5500','rtx a5000','rtx a4500','rtx a3000','rtx a2000','radeon rx 7900m','radeon rx 7800m','radeon rx 7700s','radeon rx 7600s','radeon rx 7600m xt','radeon rx 7600m','radeon rx 6850m xt','radeon rx 6800m','radeon rx 6650m','radeon rx 6600m','radeon rx 6550m','radeon rx 6500m'],key=len,reverse=True)
GPU_GEN=['rtx graphics','rtx discrete','geforce rtx','geforce mx','radeon rx','radeon pro','radeon 6xxxm','radeon 7xxxm']; IGPU=['intel iris','intel arc graphics','intel graphics','intel uhd','intel xe','intel xe graphics','intel arc integrated','radeon graphics','radeon 610m','radeon 680m','radeon 780m','radeon 840m','radeon 890m','radeon 760m','amd radeon graphics','amd integrated graphics','qualcomm adreno','adreno','qualcomm gpu']
GPU_SCORE={'rtx 5090':100,'rtx 5080':98,'rtx 5070 ti':97,'rtx 5070':95,'rtx 5060 ti':90,'rtx 5060':85,'rtx 5050':60,'rtx 4090':100,'rtx 4080':98,'rtx 4070':80,'rtx 4060':65,'rtx 4050':45,'rtx a5500':96,'rtx a5000':92,'rtx a4500':82,'rtx a3000':68,'rtx a2000':55,'radeon rx 7900m':96,'radeon rx 7800m':88,'radeon rx 7700s':80,'radeon rx 7600s':68,'radeon rx 7600m xt':72,'radeon rx 7600m':65,'radeon rx 6850m xt':78,'radeon rx 6800m':76,'radeon rx 6650m':60,'radeon rx 6600m':56,'radeon rx 6550m':48,'radeon rx 6500m':42}
GPU_FLOOR={'rtx 5090':1600,'rtx 5080':1250,'rtx 5070 ti':1000,'rtx 5070':850,'rtx 5060 ti':700,'rtx 5060':600,'rtx 5050':500,'rtx 4090':1400,'rtx 4080':1200,'rtx 4070':850,'rtx 4060':650,'rtx 4050':500,'rtx a5500':1300,'rtx a5000':1200,'rtx a4500':900,'rtx a3000':650,'rtx a2000':550,'radeon rx 7900m':1100,'radeon rx 7800m':850,'radeon rx 7700s':750,'radeon rx 7600s':650,'radeon rx 7600m xt':700,'radeon rx 7600m':600,'radeon rx 6850m xt':750,'radeon rx 6800m':750,'radeon rx 6650m':550,'radeon rx 6600m':500,'radeon rx 6550m':450,'radeon rx 6500m':400}

def norm(x): return re.sub(r'\s+',' ',''.join(c for c in unicodedata.normalize('NFKD',x or '') if not unicodedata.combining(c))).lower().strip()
def load(p):
 try:return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
 except Exception:return {}
def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def price(v):
 if v is None:return None
 s=str(v).strip().replace('€','').replace('\xa0','').replace(' ','')
 try:return float(s.replace('.','').replace(',','.')) if ',' in s and '.' in s and s.rfind(',')>s.rfind('.') else float(s.replace(',','.'))
 except:return None
def prices(t): return [v for r in re.findall(r'(?<!\d)(\d{1,4}(?:[.,]\d{2})?)\s*€',t) if (v:=price(r)) is not None and 50<=v<=10000]
def stock(t):
 t=norm(t)
 if any(x in t for x in SNO):return False
 if any(x in t for x in SSI):return True
 return None
def brand(t):
 t=norm(t)
 for b,subs in BRANDS.items():
  if re.search(rf'\b{re.escape(b)}\b',t):
   for sub in subs:
    if re.search(rf'\b{re.escape(sub)}\b',t):return b,sub
   return b,None
 return None,None
def eligible(t): t=norm(t);return not any(x in t for x in EXCLUDE) and brand(t)[0] in BRANDS
def cpu(t):
 for p in CPU_PATTERNS:
  m=re.search(p,t)
  if m:
   c=m.group(0);tier='tier_1' if re.search(r'ultra\s+9|core\s+i9|ryzen(?:\s+ai)?\s+9',c) else 'tier_2' if re.search(r'ultra\s+7|core\s+i7|ryzen(?:\s+ai)?\s+7',c) else 'tier_3';lo=c.lower();cl='hx' if 'hx' in lo else 'hs' if 'hs' in lo else 'h' if re.search(r'\d+h\b|\bh\b',lo) else 'u_ultra' if re.search(r'(?:\s|^)(?:u|v|p)\b',lo) else None;return c,tier,cl
 return None,None,None
def _gpu_pattern(name): return r'(?<![a-z0-9])'+r'[\s._-]*'.join(re.escape(x) for x in name.split())+r'(?![a-z0-9])'
def gpus(text):
 t=norm(text).replace('–','-').replace('—','-');ds=[g for g in GPU_MODELOS if re.search(_gpu_pattern(g),t)]
 if ds:return ds,'dedicada',ds[0]
 if any(re.search(_gpu_pattern(x),t) for x in GPU_GEN):return [],'dedicada',None
 if any(re.search(_gpu_pattern(x),t) for x in IGPU):return [],'integrada',None
 return [],'desconhecida',None
def gpu_from_contexts(contexts):
 clean=[re.sub(r'\s+',' ',str(x or '')).strip() for x in contexts or []];clean=[x for x in clean if 2<=len(x)<=800];dedicated=[];ig=False;generic=False
 for x in clean:
  ds,gt,_=gpus(x)
  if ds:dedicated.extend(ds)
  elif gt=='dedicada':generic=True
  elif gt=='integrada':ig=True
 if dedicated:
  u=[]
  for g in sorted(dedicated,key=len,reverse=True):
   if g not in u:u.append(g)
  return u,'dedicada',u[0]
 if generic:return [],'dedicada',None
 if ig:return [],'integrada',None
 return [],'desconhecida',None
def specs(text):
 t=norm(text);o={'marca':None,'submarca':None,'gpu_modelo':None,'gpu_tipo':'desconhecida','gpu_modelos_detectados':[],'cpu_modelo':None,'cpu_classe':None,'cpu_str_original':None,'ram_gb':None,'ram_expansivel':False,'armazenamento_tb':None,'ssd_expansivel':False,'bateria_wh':None,'peso_kg':None,'ecra_res':None,'ecra_hz':None,'teclado_pt':'desconhecido','alertas':[],'fontes':{}}
 o['marca'],o['submarca']=brand(t);gs,gt,gm=gpus(t);o['gpu_modelos_detectados'],o['gpu_tipo'],o['gpu_modelo']=gs,gt,gm;o['fontes']['gpu']='modelo_exato' if gm else 'dedicada_generica' if gt=='dedicada' else 'integrada' if gt=='integrada' else None
 if not o['fontes']['gpu']:o['alertas'].append('GPU não identificada')
 c,tr,cl=cpu(t);o['cpu_str_original'],o['cpu_modelo'],o['cpu_classe']=c,tr,cl;o['fontes']['cpu']='modelo_detetado' if c else None
 m=re.search(r'(\d{1,3})\s?gb\s?(?:ram|ddr[45](?:x)?|memory|so-dimm)\b',t)
 if m:o['ram_gb']=int(m.group(1));o['fontes']['ram']='explicita'
 else:
  for m in re.finditer(r'\b(\d{1,3})\s?gb\b',t):
   v=int(m.group(1));bef=t[max(0,m.start()-18):m.start()]
   if v in (8,12,16,24,32,48,64,96,128) and not re.search(r'(?:rtx|gtx|rx)\s?[a-z]?\d{3,4}',bef):o['ram_gb']=v;o['fontes']['ram']='heuristica';break
 o['ram_expansivel']=any(x in t for x in ['ram expansivel','so-dimm','slot ram','ram upgrade','upgradable memory','memoria expansivel'])
 for cap,p in ((2.0,r'2\s?tb(?:\s?(?:ssd|nvme|pcie))?'),(1.0,r'1\s?tb(?:\s?(?:ssd|nvme|pcie))?'),(.5,r'512\s?gb(?:\s?(?:ssd|nvme|pcie))?')):
  if re.search(p,t):o['armazenamento_tb']=cap;o['fontes']['armazenamento']='explicita';break
 o['ssd_expansivel']=any(x in t for x in ['ssd extra','2x m.2','2 x m.2','slot m.2 livre','segundo ssd','segundo m.2','armazenamento expansivel'])
 m=re.search(r'(\d{2,3})\s?wh\b',t);o['bateria_wh']=int(m.group(1)) if m else None;m=re.search(r'(\d[.,]\d+)\s?kg\b',t);o['peso_kg']=float(m.group(1).replace(',','.')) if m else None
 for vals,res in [(['qhd+','2880x1800','2560x1600','wqxga','2.8k'],'qhd+'),(['qhd','2560x1440'],'qhd'),(['1200p','1920x1200','wuxga'],'fhd+'),(['fhd','1920x1080','1080p'],'fhd')]:
  if any(x in t for x in vals):o['ecra_res']=res;break
 m=re.search(r'(\d{2,3})\s?hz\b',t);o['ecra_hz']=int(m.group(1)) if m else None
 if any(x in t for x in KNPT):o['teclado_pt']='nao_pt'
 elif any(x in t for x in KPT):o['teclado_pt']='confirmado'
 return o
def quality(s):
 q=.20*bool(s.get('cpu_modelo'))+.25*(s.get('gpu_tipo')=='dedicada')+.20*bool(s.get('ram_gb'))+.10*bool(s.get('bateria_wh'))+.10*bool(s.get('peso_kg'))+.075*bool(s.get('ecra_res'))+.075*bool(s.get('ecra_hz'));return q,'ALTA' if q>=.85 else 'MEDIA' if q>=.50 else 'BAIXA'
def tier(v,c):
 if v>=float(c.get('diamante_value_min',130)):return 'DIAMANTE'
 if v>=float(c.get('ouro_value_min',110)):return 'OURO'
 if v>=float(c.get('prata_value_min',90)):return 'PRATA'
 if v>=float(c.get('bronze_value_min',70)):return 'BRONZE'
 return None
def price_score(p,c):
 soft=float(c.get('budget_soft',1300));hard=float(c.get('budget_hard',1500))
 if p<=soft:return 150.0
 if p>=hard:return max(70.0,100.0-((p-hard)/max(hard,1.0))*60.0)
 return 150.0-50.0*((p-soft)/max(hard-soft,1.0))
def score(s,p,w,c):
 if s.get('teclado_pt')=='nao_pt':return {'status':'REJEITADO','alertas':['Teclado explicitamente não português.']}
 if s.get('gpu_tipo')=='integrada':return {'status':'REJEITADO','alertas':['GPU apenas integrada — excluído para gaming/modelação 3D.']}
 if s.get('gpu_tipo')=='desconhecida':return {'status':'ACEITE','score_final':0.0,'score_ranking':0.0,'value_score':0.0,'oportunidade':None,'qualidade_dados':'BAIXA','confianca_percentual':'0%','fontes_extraidas':s['fontes'],'alertas':['GPU não confirmada — sem oportunidade.'],'detalhes':{}}
 if s.get('ram_gb')==8:return {'status':'REJEITADO','alertas':['8GB RAM confirmado - insuficiente.']}
 if s.get('peso_kg') and s['peso_kg']>2.8:return {'status':'REJEITADO','alertas':['Excede limite de peso (>2.8kg).']}
 r=s.get('ram_gb');arm=s.get('armazenamento_tb');cpuv={'tier_1':100,'tier_2':85,'tier_3':70}.get(s.get('cpu_modelo'),50);gp=GPU_SCORE.get(s.get('gpu_modelo'),45);pr=50 if r is None else 100 if r>=32 else 80 if r>=16 else 40;pa=50 if arm is None else 100 if arm>=2 else 85 if arm>=1 else 65;res={'qhd+':100,'qhd':95,'fhd+':85,'fhd':75,None:60}.get(s.get('ecra_res'),60);hz=min(100,(s.get('ecra_hz') or 60)/1.65);bat=50 if not s.get('bateria_wh') else max(0,min(100,s['bateria_wh']/90*100)-{'u_ultra':0,'hs':5,'h':10,'hx':20,None:10}.get(s.get('cpu_classe'),10));wt=50 if not s.get('peso_kg') else (100 if s['peso_kg']<=1.4 else 0 if s['peso_kg']>=2.8 else max(0,100-(s['peso_kg']-1.4)*71.4));conf,qname=quality(s);feup=pr*.2+bat*.3+pa*.15+res*.2+cpuv*.15;gaming=gp*.65+cpuv*.2+hz*.1+pr*.05;long=(100 if r and r>=32 else 95 if r==16 and s.get('ram_expansivel') else 75 if r==16 else 50)*.35+(100 if arm and arm>=2 else 85 if arm==1 else 75 if arm==.5 and s.get('ssd_expansivel') else 50)*.25+bat*.2+cpuv*.2;final=feup*.5+gaming*.25+long*.15+wt*.1;rank=round(max(0,min(100,final*(.85+.15*conf))),1)
 pscore=price_score(p,c);value=round(max(0,min(150,(1.30*rank)*.70+pscore*.30)),1);op=tier(value,c) if qname in ('ALTA','MEDIA') else None
 return {'status':'ACEITE','score_final':round(final,1),'score_ranking':rank,'value_score':value,'oportunidade':op,'qualidade_dados':qname,'confianca_percentual':f'{int(conf*100)}%','fontes_extraidas':s['fontes'],'alertas':s.get('alertas',[]),'detalhes':{'gpu':s.get('gpu_modelo'),'gpu_tipo':s.get('gpu_tipo'),'cpu':s.get('cpu_str_original'),'ram_gb':r,'armazenamento_tb':arm,'price_score':round(pscore,1)}}
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
   typ=x.get('@type');typ=typ if isinstance(typ,list) else [typ]
   if any(str(y).lower() in ('product','productgroup') for y in typ):
    off=x.get('offers');off=off[0] if isinstance(off,list) and off else off if isinstance(off,dict) else {};pr=price(off.get('price'))
    if x.get('name') and pr:out.append({'titulo':str(x['name']).strip(),'preco':pr,'url':urljoin(base,str(x.get('url') or off.get('url') or base))})
   stack.extend(v for v in x.values() if isinstance(v,(dict,list)))
 return out
def title(card):
 n=card.select_one("h1,h2,h3,h4,[class*='title'],[class*='Title'],[class*='name'],[class*='Name'],a[title],img[alt]");return re.sub(r'\s+',' ',(n.get('alt') or n.get('title') or n.get_text(' ',strip=True)) if n else '').strip()
def link(card,base,hints):
 arr=[]
 for a in card.select('a[href]'):
  h=(a.get('href') or '').strip()
  if not h or h.startswith('#') or h.lower().startswith('javascript:'):continue
  u=urljoin(base,h);sc=(5 if any(x.lower() in u.lower() for x in hints) else 0)+(2 if a.get('title') else 0)+(1 if a.select_one('img') else 0);arr.append((sc,u))
 return max(arr,default=(0,None))[1]
def current_price(card):
 vals=[]
 for n in card.select("[itemprop='price'],meta[property='product:price:amount'],[data-price]"):
  v=price(n.get('content') or n.get('data-price') or n.get_text(' ',strip=True))
  if v is not None:vals.append(v)
 if vals:return min(vals)
 vals=[]
 for n in card.select("[class*='price'],[class*='Price']"):
  cl=norm(' '.join(n.get('class',[])))
  if any(x in cl for x in ['old','previous','was','regular','strike']):continue
  vals+=prices(n.get_text(' ',strip=True))
 return min(vals) if vals else (min(prices(card.get_text(' ',strip=True))) if prices(card.get_text(' ',strip=True)) else None)
def old_price(card,cur):
 vals=[]
 for n in card.select("[class*='old'],[class*='Old'],[class*='was'],[class*='Was'],[class*='previous'],[class*='Previous'],del,s,strike"):vals+=prices(n.get_text(' ',strip=True))
 vals=[v for v in vals if cur is None or v>cur+.01];return min(vals) if vals else None
def candidates(soup,cfg,base,limit):
 hints=cfg.get('product_path_hints',['/produto/','/product/','/portatil/','/portateis/']);cards=[]
 for sel in cfg.get('card_selectors') or ['article',"li[class*='product']","div[class*='product-card']","div[class*='productCard']","div[class*='product-item']",'[data-product-id]',"[data-testid*='product']"]:cards+=soup.select(sel)
 for a in soup.select('a[href]'):
  parent=a
  for _ in range(int(cfg.get('parent_climb',7))):
   parent=parent.parent if parent else None
   if not parent:break
   tx=parent.get_text(' ',strip=True)
   if 25<=len(tx)<=2200 and prices(tx):cards.append(parent);break
 out=[];seen=set()
 for c in cards:
  t=title(c);p=current_price(c)
  if len(t)<10 or p is None or not 100<=p<=10000:continue
  u=link(c,base,hints) or base;k=(norm(t),u)
  if k in seen:continue
  seen.add(k);out.append({'titulo':t,'preco':p,'preco_anterior':old_price(c,p),'url':u,'stock':stock(c.get_text(' ',strip=True))})
  if len(out)>=limit:break
 return out
def category(session,cfg,limit):
 try:r=session.get(cfg['url'],timeout=max(5,int(cfg.get('timeout_ms',12000))//1000),allow_redirects=True)
 except Exception as e:return {'loja':cfg['loja'],'url':cfg['url'],'produtos':[],'bloqueada':False,'erro':str(e),'status_code':None}
 soup=BeautifulSoup(r.text,'html.parser');ti=soup.title.get_text(' ',strip=True) if soup.title else '';blocked=r.status_code in (401,403,429,503) or any(x in ti.lower() for x in ('just a moment','access denied','verify you are human')) or 'cf-chl-' in r.text.lower()
 if blocked:return {'loja':cfg['loja'],'url':r.url,'produtos':[],'bloqueada':True,'erro':f'HTTP {r.status_code}','status_code':r.status_code,'titulo_pagina':ti}
 items=jsonld(soup,r.url)+candidates(soup,cfg,r.url,limit);seen=set();merged=[]
 for it in items:
  k=norm(it['titulo'])
  if k in seen:continue
  it['loja']=cfg['loja'];it['_category_url']=r.url;merged.append(it);seen.add(k)
  if len(merged)>=limit:break
 return {'loja':cfg['loja'],'url':r.url,'produtos':merged,'bloqueada':False,'erro':None,'status_code':r.status_code,'titulo_pagina':ti}
def detail_fields(soup):
 parts=[]
 for n in soup.select('table tr,dl,.specifications,.specs,.specification,.tech-specs,[class*="spec"],[class*="Spec"]'):
  tx=n.get_text(' ',strip=True)
  if 10<=len(tx)<=6000:parts.append(tx)
 for n in soup.find_all(['li','div','span','td','p']):
  tx=n.get_text(' ',strip=True);nt=norm(tx)
  if 2<=len(tx)<=500 and any(k in nt for k in ['gpu','placa grafica','graphics','cpu','processador','ram','memoria','memory']):parts.append(tx)
 return ' '.join(dict.fromkeys(parts))
def gpu_fields(soup):
 out=[];labels=['gpu','placa grafica','graphics card','graphic card','graphics processor','processador grafico','video card','vga']
 for tr in soup.select('tr'):
  cells=[norm(x.get_text(' ',strip=True)) for x in tr.find_all(['th','td'])];row=' '.join(cells).strip()
  if row and any(k in row for k in labels):out.append(row)
 for dt in soup.select('dt'):
  lab=norm(dt.get_text(' ',strip=True))
  if any(k in lab for k in labels):
   dd=dt.find_next_sibling('dd');out.append(' '.join(x for x in [dt.get_text(' ',strip=True),dd.get_text(' ',strip=True) if dd else ''] if x))
 for n in soup.find_all(['li','p','div','span']):
  tx=' '.join(n.stripped_strings);nt=norm(tx)
  if 8<=len(tx)<=350 and any(re.search(rf'\b{re.escape(k)}\b',nt) for k in labels):out.append(tx)
 return list(dict.fromkeys(out))
def detail(session,item):
 try:r=session.get(item['url'],timeout=10,allow_redirects=True,headers={'Referer':item.get('_category_url','')})
 except:return item
 if r.status_code>=400:return item
 soup=BeautifulSoup(r.text,'html.parser');sp=item['_specs'];existing=(sp.get('gpu_tipo'),sp.get('gpu_modelo'));h1=soup.select_one('h1');product_title=h1.get_text(' ',strip=True) if h1 else (soup.title.get_text(' ',strip=True) if soup.title else '')
 ds,gt,gm=gpu_from_contexts([product_title])
 if gt=='desconhecida':ds,gt,gm=gpu_from_contexts(gpu_fields(soup))
 if gt!='desconhecida':sp['gpu_tipo'],sp['gpu_modelo'],sp['gpu_modelos_detectados']=gt,gm,ds;sp.setdefault('fontes',{})['gpu']='titulo_produto' if product_title and (ds or gt=='integrada') else 'especificacao_gpu'
 elif existing[0]=='desconhecida':sp['gpu_tipo'],sp['gpu_modelo'],sp['gpu_modelos_detectados']='desconhecida',None,[];sp.setdefault('fontes',{})['gpu']=None
 en=specs(norm(product_title+' '+detail_fields(soup)))
 for f in ['cpu_modelo','cpu_classe','cpu_str_original','ram_gb','ram_expansivel','armazenamento_tb','ssd_expansivel','bateria_wh','peso_kg','ecra_res','ecra_hz','teclado_pt']:
  if en.get(f) not in (None,'desconhecida','desconhecido',False):sp[f]=en[f];sp.setdefault('fontes',{})[f]='pagina_produto'
 sp.setdefault('fontes',{})['detalhe_produto']='pagina_produto';return item
def keyboard(session,item):
 if item['_specs'].get('teclado_pt')!='desconhecido':return item
 try:r=session.get(item['url'],timeout=9,allow_redirects=True)
 except:return item
 if r.status_code<400:
  t=norm(r.text);item['_specs']['teclado_pt']='nao_pt' if any(x in t for x in KNPT) else 'confirmado' if any(x in t for x in KPT) else 'desconhecido'
 return item
def validate_price(s,p,c):
 if p<=0 or p<float(c.get('preco_minimo_global',250)):return False
 g=s.get('gpu_modelo');floor=(c.get('gpu_preco_min') or {}).get(g,GPU_FLOOR.get(g)) if g else None;return not floor or p>=float(floor)
def notify(title,msg,prio='default',tags='computer'):
 if not NTFY_TOPIC:print('⚠️ NTFY_TOPIC não definido; notificação ignorada.');return False
 try:r=requests.post('https://ntfy.sh',json={'topic':NTFY_TOPIC,'title':title,'message':msg,'tags':[x.strip() for x in tags.split(',') if x.strip()],'priority':4 if prio=='high' else 3},timeout=10);r.raise_for_status();print(f'📲 Notificação enviada: {title}');return True
 except requests.RequestException as e:print(f'❌ Erro ntfy: {e}');return False
def alert(prev,cur,c):
 if prev is None:return (True,'nova oportunidade '+cur['oportunidade'].lower()) if cur.get('oportunidade') else (False,'')
 if isinstance(prev.get('price'),(int,float)) and cur['preco']<prev['price']-float(c.get('alerta_queda_preco_eur',5)):return True,f"queda de preço: {prev['price']:.2f}€ → {cur['preco']:.2f}€"
 if cur.get('oportunidade') and cur.get('oportunidade')!=prev.get('oportunidade'):return True,'escalou para '+cur['oportunidade'].lower()
 return False,''
def validar_url(it):
 u=it.get('url');return bool(u and urlparse(u).scheme in {'http','https'})
def main():
 st=datetime.now(timezone.utc);cfg=load(CONFIG_PATH);hist=load(HISTORY_PATH);hist.setdefault('offers',{});settings=cfg.get('settings',{});weights=cfg.get('weights',{});cats=cfg.get('category_urls',[]);budget=float(settings.get('budget_hard',1500));maxp=int(settings.get('max_produtos_por_categoria',30));workers=min(len(cats),int(settings.get('max_lojas_paralelas',6)));enrich=int(settings.get('max_enriquecimentos_detalhe',48));session=requests.Session();session.headers.update({'User-Agent':UA,'Accept-Language':'pt-PT,pt;q=0.9,en;q=0.7','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
 with ThreadPoolExecutor(max_workers=workers or 1) as ex:
  fm={ex.submit(category,session,c,maxp):c['loja'] for c in cats};results={}
  for f in as_completed(fm):
   loja=fm[f]
   try:results[loja]=f.result()
   except Exception as e:results[loja]={'loja':loja,'url':'','produtos':[],'bloqueada':False,'erro':str(e),'status_code':None}
 stats={'bloqueadas':0,'sem':0,'encontrados':0,'candidatos':0,'enriquecidos':0,'aceites':0,'rej':0,'igpu':0,'desconhecida':0,'gpu_preco_rej':0,'alertas':0,'quedas':0,'tiers':{'DIAMANTE':0,'OURO':0,'PRATA':0,'BRONZE':0}};loja_stats={c['loja']:{'encontrados':0,'candidatos':0,'aceites':0,'rejeitados':0,'bloqueada':False,'status':None,'erro':None} for c in cats};pending=[]
 for c in cats:
  loja=c['loja'];r=results.get(loja,{});rs=loja_stats[loja];rs['encontrados']=len(r.get('produtos',[]));rs['bloqueada']=bool(r.get('bloqueada'));rs['status']=r.get('status_code');rs['erro']=r.get('erro');stats['encontrados']+=rs['encontrados'];stats['bloqueadas']+=int(rs['bloqueada']);stats['sem']+=int(not rs['bloqueada'] and not rs['erro'] and not r.get('produtos',[]))
  for it in r.get('produtos',[]):
   if it['preco']>budget or not eligible(it['titulo']):continue
   sp=specs(it['titulo']);it['_specs']=sp;rs['candidatos']+=1;stats['candidatos']+=1
   if not validate_price(sp,it['preco'],settings):rs['rejeitados']+=1;stats['rej']+=1;continue
   if sp.get('gpu_tipo')!='integrada':pending.append(it)
 pending=sorted(pending,key=lambda x:(x.get('_specs',{}).get('gpu_tipo')=='dedicada',x['preco']))[:enrich]
 with ThreadPoolExecutor(max_workers=workers or 1) as ex:
  futs=[ex.submit(detail,session,it) for it in pending]
  for f in as_completed(futs):f.result();stats['enriquecidos']+=1
 with ThreadPoolExecutor(max_workers=workers or 1) as ex:
  futs=[ex.submit(keyboard,session,it) for c in cats for it in results.get(c['loja'],{}).get('produtos',[]) if it.get('_specs') and it['_specs'].get('teclado_pt')=='desconhecido']
  for f in as_completed(futs):f.result()
 top=[]
 for c in cats:
  loja=c['loja']
  for it in results.get(loja,{}).get('produtos',[]):
   sp=it.get('_specs')
   if not sp:continue
   rs=loja_stats[loja]
   if sp.get('gpu_tipo')=='integrada':stats['rej']+=1;stats['igpu']+=1;rs['rejeitados']+=1;continue
   if not validate_price(sp,it['preco'],settings):stats['rej']+=1;stats['gpu_preco_rej']+=1;rs['rejeitados']+=1;continue
   a=score(sp,it['preco'],weights,settings)
   if a['status']=='REJEITADO':stats['rej']+=1;rs['rejeitados']+=1;continue
   stats['aceites']+=1;rs['aceites']+=1
   if sp.get('gpu_tipo')=='desconhecida':stats['desconhecida']+=1
   if a.get('oportunidade'):stats['tiers'][a['oportunidade']]+=1
   top.append((float(a.get('value_score',0)),float(a.get('score_ranking',0)),loja,it['titulo'],it['preco'],a.get('oportunidade'),sp.get('gpu_modelo') or sp.get('gpu_tipo'),sp.get('cpu_str_original') or '?'))
   key=f"{loja}::{it.get('url') or it['titulo']}";legacy=f"{loja}::{it['titulo']}";key=key if key in hist['offers'] or legacy not in hist['offers'] else legacy;entries=hist['offers'].setdefault(key,[]);prev=entries[-1] if entries else None;rec={'timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'price':it['preco'],'price_previous':it.get('preco_anterior'),'discount_percent':round((it['preco_anterior']-it['preco'])/it['preco_anterior']*100,1) if it.get('preco_anterior') and it['preco_anterior']>it['preco'] else None,'stock':it.get('stock'),'score_ranking':a.get('score_ranking',0),'value_score':a.get('value_score',0),'oportunidade':a.get('oportunidade'),'qualidade_dados':a.get('qualidade_dados'),'gpu':sp.get('gpu_modelo'),'gpu_tipo':sp.get('gpu_tipo'),'cpu':sp.get('cpu_str_original'),'url':it['url']};entries.append(rec);hist['offers'][key]=entries[-60:];ok,reason=alert(prev,{'preco':it['preco'],'oportunidade':a.get('oportunidade')},settings)
   if ok and it.get('stock') is not False and validar_url(it):stats['alertas']+=1;stats['quedas']+=int(reason.startswith('queda de preço'));notify(f"💻 {a.get('oportunidade') or 'ATUALIZAÇÃO'} | {it['preco']:.0f}€",f"{it['titulo']}\n\nLoja: {loja}\nPreço: {it['preco']:.2f}€\nMotivo: {reason}\nGPU: {sp.get('gpu_modelo') or sp.get('gpu_tipo')}\nCPU: {sp.get('cpu_str_original') or '?'}\nRAM: {sp.get('ram_gb') or '?'}GB\n🔗 {it['url']}",'high' if a.get('oportunidade') in {'DIAMANTE','OURO'} else 'default')
 save(HISTORY_PATH,hist);top.sort(reverse=True);elapsed=(datetime.now(timezone.utc)-st).total_seconds();print('🔎 TOP oportunidades:');[print(f'   {loja} | {p:.2f}€ | Rank {rk:.1f} | Value {v:.1f} | {tier_name or "—"} | {gpu} | {cpuv} | {titulo}') for v,rk,loja,titulo,p,tier_name,gpu,cpuv in top[:5]];print(f"📐 Calibração: qualidade=70% do value, preço=30%; budget soft={settings.get('budget_soft',1300)}€, hard={settings.get('budget_hard',1500)}€.");[print(f"🏪 {loja}: encontrados={rs['encontrados']} candidatos={rs['candidatos']} aceites={rs['aceites']} rejeitados={rs['rejeitados']} bloqueada={rs['bloqueada']} HTTP={rs['status']} erro={rs['erro'] or '-'}") for loja,rs in loja_stats.items()];summary=f"📊 v7.3 | Lojas: {len(cats)} | Bloqueadas: {stats['bloqueadas']} | Sem resultados: {stats['sem']} | Encontrados: {stats['encontrados']} | Candidatos: {stats['candidatos']} | Enriquecidos: {stats['enriquecidos']} | Aceites: {stats['aceites']} | Rej. iGPU: {stats['igpu']} | Rej. GPU/preço: {stats['gpu_preco_rej']} | GPU desconhecida: {stats['desconhecida']} | Alertas: {stats['alertas']} | Quedas: {stats['quedas']} | Diamante: {stats['tiers']['DIAMANTE']} | Ouro: {stats['tiers']['OURO']} | Prata: {stats['tiers']['PRATA']} | Bronze: {stats['tiers']['BRONZE']} | {elapsed:.1f}s";print(summary);notify('🔄 Relatório de Rastreio',summary)
if __name__=='__main__':main()
