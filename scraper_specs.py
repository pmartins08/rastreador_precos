from scraper_core import *

def specs(text):
 t=norm(text); out={'marca':None,'submarca':None,'gpu_modelo':None,'gpu_tipo':'desconhecida','gpu_modelos_detectados':[],'cpu_modelo':None,'cpu_classe':None,'cpu_str_original':None,'ram_gb':None,'ram_expansivel':False,'armazenamento_tb':None,'ssd_expansivel':False,'bateria_wh':None,'peso_kg':None,'ecra_res':None,'ecra_hz':None,'teclado_pt':'desconhecido','alertas':[],'fontes':{}}
 out['marca'],out['submarca']=brand(t); gs,gt,gm=gpus(t); out['gpu_modelos_detectados']=gs; out['gpu_tipo']=gt; out['gpu_modelo']=gm; out['fontes']['gpu']='modelo_exato' if gm else 'dedicada_generica' if gt=='dedicada' else 'integrada' if gt=='integrada' else None
 if not out['fontes']['gpu']:out['alertas'].append('GPU não identificada')
 c,tr,cl=cpu(t); out['cpu_str_original']=c; out['cpu_modelo']=tr; out['cpu_classe']=cl; out['fontes']['cpu']='modelo_detetado' if c else None
 if not c:out['alertas'].append('CPU não confirmada')
 m=re.search(r'(\d{1,3})\s?gb\s?(?:ram|ddr[45](?:x)?|memory|so-dimm)\b',t)
 if m:out['ram_gb']=int(m.group(1));out['fontes']['ram']='explicita'
 else:
  for m in re.finditer(r'\b(\d{1,3})\s?gb\b',t):
   v=int(m.group(1)); bef=t[max(0,m.start()-18):m.start()]
   if v in (8,12,16,24,32,48,64,96,128) and not re.search(r'(?:rtx|gtx|rx)\s?[a-z]?\d{3,4}',bef):out['ram_gb']=v;out['fontes']['ram']='heuristica';break
 if out['ram_gb'] is None:out['alertas'].append('RAM desconhecida')
 out['ram_expansivel']=any(x in t for x in ['ram expansivel','so-dimm','slot ram','ram upgrade','upgradable memory','memoria expansivel'])
 for cap,p in ((2.0,r'2\s?tb(?:\s?(?:ssd|nvme|pcie))?'),(1.0,r'1\s?tb(?:\s?(?:ssd|nvme|pcie))?'),(.5,r'512\s?gb(?:\s?(?:ssd|nvme|pcie))?')):
  if re.search(p,t):out['armazenamento_tb']=cap;out['fontes']['armazenamento']='explicita';break
 if out['armazenamento_tb'] is None:out['alertas'].append('Armazenamento não confirmado')
 out['ssd_expansivel']=any(x in t for x in ['ssd extra','2x m.2','2 x m.2','slot m.2 livre','segundo ssd','segundo m.2','armazenamento expansivel'])
 m=re.search(r'(\d{2,3})\s?wh\b',t); out['bateria_wh']=int(m.group(1)) if m else None
 m=re.search(r'(\d[.,]\d+)\s?kg\b',t); out['peso_kg']=float(m.group(1).replace(',','.')) if m else None
 for vals,res in [(['qhd+','2880x1800','2560x1600','wqxga','2.8k'],'qhd+'),(['qhd','2560x1440'],'qhd'),(['1200p','1920x1200','wuxga'],'fhd+'),(['fhd','1920x1080','1080p'],'fhd')]:
  if any(x in t for x in vals):out['ecra_res']=res;break
 m=re.search(r'(\d{2,3})\s?hz\b',t); out['ecra_hz']=int(m.group(1)) if m else None
 if any(x in t for x in KNPT):out['teclado_pt']='nao_pt'
 elif any(x in t for x in KPT):out['teclado_pt']='confirmado'
 return out

def quality(s):
 q=.20*bool(s.get('cpu_modelo'))+.25*(s.get('gpu_tipo')=='dedicada')+.20*bool(s.get('ram_gb'))+.10*bool(s.get('bateria_wh'))+.10*bool(s.get('peso_kg'))+.075*bool(s.get('ecra_res'))+.075*bool(s.get('ecra_hz'))
 return q,'ALTA' if q>=.85 else 'MEDIA' if q>=.50 else 'BAIXA'
def tier(v,c):
 if v>=float(c.get('diamante_value_min',130)):return 'DIAMANTE'
 if v>=float(c.get('ouro_value_min',110)):return 'OURO'
 if v>=float(c.get('prata_value_min',90)):return 'PRATA'
 if v>=float(c.get('bronze_value_min',70)):return 'BRONZE'

def score(s,p,w,c):
 if s.get('teclado_pt')=='nao_pt':return {'status':'REJEITADO','alertas':['Teclado explicitamente não português.']}
 if s.get('gpu_tipo')=='integrada':return {'status':'REJEITADO','alertas':['GPU apenas integrada — excluído para gaming/modelação 3D.']}
 if s.get('gpu_tipo')=='desconhecida':return {'status':'ACEITE','score_final':0.0,'score_ranking':0.0,'value_score':0.0,'oportunidade':None,'qualidade_dados':'BAIXA','confianca_percentual':'0%','fontes_extraidas':s['fontes'],'alertas':['GPU não confirmada — sem oportunidade.'],'detalhes':{}}
 if s.get('ram_gb')==8:return {'status':'REJEITADO','alertas':['8GB RAM confirmado - insuficiente.']}
 if s.get('peso_kg') and s['peso_kg']>2.8:return {'status':'REJEITADO','alertas':['Excede limite de peso (>2.8kg).']}
 r=s.get('ram_gb'); arm=s.get('armazenamento_tb'); cpuv={'tier_1':100,'tier_2':85,'tier_3':70}.get(s.get('cpu_modelo'),50); gp=GPU_SCORE.get(s.get('gpu_modelo'),45); pr=50 if r is None else 100 if r>=32 else 80 if r>=16 else 40; pa=50 if arm is None else 100 if arm>=2 else 85 if arm>=1 else 65; res={'qhd+':100,'qhd':95,'fhd+':85,'fhd':75,None:60}.get(s.get('ecra_res'),60); hz=min(100,(s.get('ecra_hz') or 60)/1.65); bat=50 if not s.get('bateria_wh') else max(0,min(100,s['bateria_wh']/90*100)-{'u_ultra':0,'hs':5,'h':10,'hx':20,None:10}.get(s.get('cpu_classe'),10)); wt=50 if not s.get('peso_kg') else (100 if s['peso_kg']<=1.4 else 0 if s['peso_kg']>=2.8 else max(0,100-(s['peso_kg']-1.4)*71.4)); conf,qname=quality(s); feup=pr*.2+bat*.3+pa*.15+res*.2+cpuv*.15; gaming=gp*.65+cpuv*.2+hz*.1+pr*.05; long=(100 if r and r>=32 else 95 if r==16 and s.get('ram_expansivel') else 75 if r==16 else 50)*.35+(100 if arm and arm>=2 else 85 if arm==1 else 75 if arm==.5 and s.get('ssd_expansivel') else 50)*.25+bat*.2+cpuv*.2; final=feup*.5+gaming*.25+long*.15+wt*.1; rank=round(max(0,min(100,final*(.85+.15*conf))),1); val=round(rank/((p/1000)**1.2),1); return {'status':'ACEITE','score_final':round(final,1),'score_ranking':rank,'value_score':val,'oportunidade':tier(val,c) if qname in ('ALTA','MEDIA') else None,'qualidade_dados':qname,'confianca_percentual':f'{int(conf*100)}%','fontes_extraidas':s['fontes'],'alertas':s.get('alertas',[]),'detalhes':{'gpu':s.get('gpu_modelo'),'gpu_tipo':s.get('gpu_tipo'),'cpu':s.get('cpu_str_original'),'ram_gb':r,'armazenamento_tb':arm}}
