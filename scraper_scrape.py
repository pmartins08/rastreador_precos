from scraper_core import *
from scraper_specs import *

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
   typ=x.get('@type'); typ=typ if isinstance(typ,list) else [typ]
   if any(str(y).lower() in ('product','productgroup') for y in typ):
    off=x.get('offers'); off=off[0] if isinstance(off,list) and off else off if isinstance(off,dict) else {}; pr=price(off.get('price'))
    if x.get('name') and pr:out.append({'titulo':str(x['name']).strip(),'preco':pr,'url':urljoin(base,str(x.get('url') or off.get('url') or base))})
   stack.extend(v for v in x.values() if isinstance(v,(dict,list)))
 return out

def title(card):
 n=card.select_one("h1,h2,h3,h4,[class*='title'],[class*='Title'],[class*='name'],[class*='Name'],a[title],img[alt]"); return re.sub(r'\s+',' ',(n.get('alt') or n.get('title') or n.get_text(' ',strip=True)) if n else '').strip()
def link(card,base,hints):
 arr=[]
 for a in card.select('a[href]'):
  h=(a.get('href') or '').strip()
  if not h or h.startswith('#') or h.lower().startswith('javascript:'):continue
  u=urljoin(base,h); sc=(5 if any(x.lower() in u.lower() for x in hints) else 0)+(2 if a.get('title') else 0)+(1 if a.select_one('img') else 0);arr.append((sc,u))
 return max(arr,default=(0,None))[1]
def current_price(card):
 vals=[]
 for n in card.select("[itemprop='price'],meta[property='product:price:amount'],[data-price]"): vals += [v for v in [price(n.get('content') or n.get('data-price') or n.get_text(' ',strip=True))] if v is not None]
 if vals:return min(vals)
 vals=[]
 for n in card.select("[class*='price'],[class*='Price']"):
  cl=norm(' '.join(n.get('class',[])))
  if any(x in cl for x in ['old','previous','was','regular','strike']):continue
  vals+=prices(n.get_text(' ',strip=True))
 return min(vals) if vals else (min(prices(card.get_text(' ',strip=True))) if prices(card.get_text(' ',strip=True)) else None)
def old_price(card,cur):
 vals=[]
 for n in card.select("[class*='old'],[class*='Old'],[class*='was'],[class*='Was'],[class*='previous'],[class*='Previous'],del,s,strike"): vals += prices(n.get_text(' ',strip=True))
 vals=[v for v in vals if cur is None or v>cur+.01]; return min(vals) if vals else None
def candidates(soup,cfg,base,limit):
 hints=cfg.get('product_path_hints',['/produto/','/product/','/portatil/','/portateis/']); cards=[]
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
  t=title(c); p=current_price(c)
  if len(t)<10 or p is None or not 100<=p<=10000:continue
  u=link(c,base,hints) or base; k=(norm(t),u)
  if k in seen:continue
  seen.add(k);out.append({'titulo':t,'preco':p,'preco_anterior':old_price(c,p),'url':u,'stock':stock(c.get_text(' ',strip=True))})
  if len(out)>=limit:break
 return out

def category(session,cfg,limit):
 try:r=session.get(cfg['url'],timeout=max(5,int(cfg.get('timeout_ms',12000))//1000),allow_redirects=True)
 except Exception as e:return {'loja':cfg['loja'],'url':cfg['url'],'produtos':[],'bloqueada':False,'erro':str(e),'status_code':None}
 soup=BeautifulSoup(r.text,'html.parser'); ti=soup.title.get_text(' ',strip=True) if soup.title else ''
 blocked=r.status_code in (401,403,429,503) or any(x in ti.lower() for x in ('just a moment','access denied','verify you are human')) or 'cf-chl-' in r.text.lower()
 if blocked:return {'loja':cfg['loja'],'url':r.url,'produtos':[],'bloqueada':True,'erro':f'HTTP {r.status_code}','status_code':r.status_code,'titulo_pagina':ti}
 items=jsonld(soup,r.url)+candidates(soup,cfg,r.url,limit); seen=set();merged=[]
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
  tx=n.get_text(' ',strip=True); nt=norm(tx)
  if 2<=len(tx)<=500 and any(k in nt for k in ['gpu','placa grafica','graphics','cpu','processador','ram','memoria','memory']):parts.append(tx)
 return ' '.join(dict.fromkeys(parts))

def gpu_fields(soup):
 """Recolhe somente linhas/elementos que parecem ser a especificação gráfica do produto."""
 out=[]
 labels=['gpu','placa grafica','placa gráfica','graphics card','graphic card','graphics processor','processador grafico','video card','vga']
 for tr in soup.select('tr'):
  cells=[norm(x.get_text(' ',strip=True)) for x in tr.find_all(['th','td'])]
  row=' '.join(cells).strip()
  if row and any(k in row for k in labels):out.append(row)
 for dt in soup.select('dt'):
  lab=norm(dt.get_text(' ',strip=True))
  if any(k in lab for k in labels):
   dd=dt.find_next_sibling('dd'); out.append(' '.join(x for x in [dt.get_text(' ',strip=True),dd.get_text(' ',strip=True) if dd else ''] if x))
 for n in soup.find_all(['li','p','div','span']):
  tx=' '.join(n.stripped_strings); nt=norm(tx)
  if 8<=len(tx)<=350 and any(re.search(rf'\b{re.escape(k)}\b',nt) for k in labels):out.append(tx)
 return list(dict.fromkeys(out))

def detail(session,item):
 try:r=session.get(item['url'],timeout=10,allow_redirects=True,headers={'Referer':item.get('_category_url','')})
 except:return item
 if r.status_code>=400:return item
 soup=BeautifulSoup(r.text,'html.parser'); spec_tx=detail_fields(soup); sp=item['_specs']
 product_title=''
 h1=soup.select_one('h1')
 if h1:product_title=h1.get_text(' ',strip=True)
 elif soup.title:product_title=soup.title.get_text(' ',strip=True)
 ds,gt,gm=gpu_from_contexts([product_title])
 if gt=='desconhecida':ds,gt,gm=gpu_from_contexts(gpu_fields(soup))
 if gt=='desconhecida':
  ds,gt,gm=gpus(product_title)
 if gt!='desconhecida':
  sp['gpu_tipo']=gt;sp['gpu_modelo']=gm;sp['gpu_modelos_detectados']=ds;sp.setdefault('fontes',{})['gpu']='titulo_produto' if product_title and gt!='desconhecida' and (ds or any(x in norm(product_title) for x in IGPU)) else 'especificacao_gpu'
 else:
  sp['gpu_tipo']='desconhecida';sp['gpu_modelo']=None;sp['gpu_modelos_detectados']=[];sp.setdefault('fontes',{})['gpu']=None
 en=specs(norm(product_title+' '+spec_tx))
 for f in ['cpu_modelo','cpu_classe','cpu_str_original','ram_gb','ram_expansivel','armazenamento_tb','ssd_expansivel','bateria_wh','peso_kg','ecra_res','ecra_hz','teclado_pt']:
  if en.get(f) not in (None,'desconhecida','desconhecido',False):sp[f]=en[f];sp.setdefault('fontes',{})[f]='pagina_produto'
 sp.setdefault('fontes',{})['detalhe_produto']='pagina_produto'; return item

def keyboard(session,item):
 if item['_specs'].get('teclado_pt')!='desconhecido':return item
 try:r=session.get(item['url'],timeout=9,allow_redirects=True)
 except:return item
 if r.status_code<400:
  t=norm(r.text);item['_specs']['teclado_pt']='nao_pt' if any(x in t for x in KNPT) else 'confirmado' if any(x in t for x in KPT) else 'desconhecido'
 return item

def validate_price(s,p,c):
 if p<=0 or p<float(c.get('preco_minimo_global',250)):return False
 g=s.get('gpu_modelo'); floor=(c.get('gpu_preco_min') or {}).get(g,GPU_FLOOR.get(g)) if g else None; return not floor or p>=float(floor)

def notify(title,msg,prio='default',tags='computer'):
 if not NTFY_TOPIC:print('⚠️ NTFY_TOPIC não definido; notificação ignorada.');return False
 try:r=requests.post('https://ntfy.sh',json={'topic':NTFY_TOPIC,'title':title,'message':msg,'tags':[x.strip() for x in tags.split(',') if x.strip()],'priority':4 if prio=='high' else 3},timeout=10);r.raise_for_status();print(f'📲 Notificação enviada: {title}');return True
 except requests.RequestException as e:print(f'❌ Erro ntfy: {e}');return False

def alert(prev,cur,c):
 if prev is None:
  return (True,'nova oportunidade '+cur['oportunidade'].lower()) if cur.get('oportunidade') else (False,'')
 if isinstance(prev.get('price'),(int,float)) and cur['preco']<prev['price']-float(c.get('alerta_queda_preco_eur',5)):return True,f"queda de preço: {prev['price']:.2f}€ → {cur['preco']:.2f}€"
 if cur.get('oportunidade') and cur.get('oportunidade')!=prev.get('oportunidade'):return True,'escalou para '+cur['oportunidade'].lower()
 return False,''
