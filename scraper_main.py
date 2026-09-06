from scraper_core import *
from scraper_specs import *
from scraper_scrape import *

def main():
 st=datetime.now(timezone.utc);cfg=load(CONFIG_PATH);hist=load(HISTORY_PATH);hist.setdefault('offers',{});settings=cfg.get('settings',{});weights=cfg.get('weights',{});cats=cfg.get('category_urls',[]);budget=float(settings.get('budget_hard',1500));maxp=int(settings.get('max_produtos_por_categoria',30));workers=min(len(cats),int(settings.get('max_lojas_paralelas',6)));enrich=int(settings.get('max_enriquecimentos_detalhe',48));session=requests.Session();session.headers.update({'User-Agent':UA,'Accept-Language':'pt-PT,pt;q=0.9,en;q=0.7','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
 with ThreadPoolExecutor(max_workers=workers or 1) as ex:
  fm={ex.submit(category,session,c,maxp):c['loja'] for c in cats}; results={}
  for f in as_completed(fm):
   loja=fm[f]
   try:results[loja]=f.result()
   except Exception as e:results[loja]={'loja':loja,'url':'','produtos':[],'bloqueada':False,'erro':str(e),'status_code':None}
 stats={'bloqueadas':0,'sem':0,'encontrados':0,'candidatos':0,'enriquecidos':0,'aceites':0,'rej':0,'igpu':0,'desconhecida':0,'gpu_preco_rej':0,'alertas':0,'quedas':0,'tiers':{'DIAMANTE':0,'OURO':0,'PRATA':0,'BRONZE':0}}
 loja_stats={c['loja']:{'encontrados':0,'candidatos':0,'aceites':0,'rejeitados':0,'bloqueada':False,'status':None,'erro':None} for c in cats}
 pending=[]
 for c in cats:
  loja=c['loja'];r=results.get(loja,{})
  rs=loja_stats[loja];rs['encontrados']=len(r.get('produtos',[]));rs['bloqueada']=bool(r.get('bloqueada'));rs['status']=r.get('status_code');rs['erro']=r.get('erro');stats['encontrados']+=rs['encontrados'];stats['bloqueadas']+=int(rs['bloqueada']);stats['sem']+=int(not rs['bloqueada'] and not rs['erro'] and not r.get('produtos',[]))
  for it in r.get('produtos',[]):
   if it['preco']>budget or not eligible(it['titulo']):continue
   sp=specs(it['titulo']);it['_specs']=sp;rs['candidatos']+=1;stats['candidatos']+=1
   if not validate_price(sp,it['preco'],settings):rs['rejeitados']+=1;stats['rej']+=1;continue
   if sp.get('gpu_tipo')!='integrada':pending.append(it)
   else:continue
 pending=sorted(pending,key=lambda x:(x.get('_specs',{}).get('gpu_tipo')=='dedicada',x['preco']))[:enrich]
 with ThreadPoolExecutor(max_workers=workers or 1) as ex:
  futs=[ex.submit(detail,session,it) for it in pending]
  for f in as_completed(futs):
   f.result();stats['enriquecidos']+=1
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
   key=f"{loja}::{it.get('url') or it['titulo']}";legacy=f"{loja}::{it['titulo']}";key=key if key in hist['offers'] or legacy not in hist['offers'] else legacy;entries=hist['offers'].setdefault(key,[]);prev=entries[-1] if entries else None
   rec={'timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'price':it['preco'],'price_previous':it.get('preco_anterior'),'discount_percent':round((it['preco_anterior']-it['preco'])/it['preco_anterior']*100,1) if it.get('preco_anterior') and it['preco_anterior']>it['preco'] else None,'stock':it.get('stock'),'score_ranking':a.get('score_ranking',0),'value_score':a.get('value_score',0),'oportunidade':a.get('oportunidade'),'qualidade_dados':a.get('qualidade_dados'),'gpu':sp.get('gpu_modelo'),'gpu_tipo':sp.get('gpu_tipo'),'cpu':sp.get('cpu_str_original'),'url':it['url']};entries.append(rec);hist['offers'][key]=entries[-60:]
   ok,reason=alert(prev,{'preco':it['preco'],'oportunidade':a.get('oportunidade')},settings)
   if ok and it.get('stock') is not False and validar_url(it):
    stats['alertas']+=1;stats['quedas']+=int(reason.startswith('queda de preço'));notify(f"💻 {a.get('oportunidade') or 'ATUALIZAÇÃO'} | {it['preco']:.0f}€",f"{it['titulo']}\n\nLoja: {loja}\nPreço: {it['preco']:.2f}€\nMotivo: {reason}\nGPU: {sp.get('gpu_modelo') or sp.get('gpu_tipo')}\nCPU: {sp.get('cpu_str_original') or '?'}\nRAM: {sp.get('ram_gb') or '?'}GB\n🔗 {it['url']}",'high' if a.get('oportunidade') in {'DIAMANTE','OURO'} else 'default')
 save(HISTORY_PATH,hist);top.sort(reverse=True);elapsed=(datetime.now(timezone.utc)-st).total_seconds();print('🔎 TOP oportunidades:')
 for v,rk,loja,titulo,p,tier,gpu,cpuv in top[:5]:print(f'   {loja} | {p:.2f}€ | Rank {rk:.1f} | Value {v:.1f} | {tier or "—"} | {gpu} | {cpuv} | {titulo}')
 max_ouro=1000*(100/float(settings.get('ouro_value_min',110)))**(1/1.2);max_dia=1000*(100/float(settings.get('diamante_value_min',130)))**(1/1.2);print(f'📐 Calibração atual: com Rank=100, Ouro só é matematicamente possível abaixo de {max_ouro:.0f}€ e Diamante abaixo de {max_dia:.0f}€.')
 for loja,rs in loja_stats.items():print(f"🏪 {loja}: encontrados={rs['encontrados']} candidatos={rs['candidatos']} aceites={rs['aceites']} rejeitados={rs['rejeitados']} bloqueada={rs['bloqueada']} HTTP={rs['status']} erro={rs['erro'] or '-'}")
 summary=f"📊 v7.2 | Lojas: {len(cats)} | Bloqueadas: {stats['bloqueadas']} | Sem resultados: {stats['sem']} | Encontrados: {stats['encontrados']} | Candidatos: {stats['candidatos']} | Enriquecidos: {stats['enriquecidos']} | Aceites: {stats['aceites']} | Rej. iGPU: {stats['igpu']} | Rej. GPU/preço: {stats['gpu_preco_rej']} | GPU desconhecida: {stats['desconhecida']} | Alertas: {stats['alertas']} | Quedas: {stats['quedas']} | Diamante: {stats['tiers']['DIAMANTE']} | Ouro: {stats['tiers']['OURO']} | Prata: {stats['tiers']['PRATA']} | Bronze: {stats['tiers']['BRONZE']} | {elapsed:.1f}s}";print(summary);notify('🔄 Relatório de Rastreio',summary)
def validar_url(it):
 u=it.get('url');return bool(u and urlparse(u).scheme in {'http','https'})
