#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, html,json,re,sqlite3,time,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'de,en;q=0.8'}
SETS=['sma','g1','xya']
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def fetch(url): return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=25).read().decode('utf-8','ignore')
def parse_name(raw):
 if 'Seite nicht gefunden' in raw or '404:' in raw: return None
 m=re.search(r'<title>(.*?)</title>',raw,re.S|re.I)
 if m:
  t=clean(m.group(1))
  name=t.split('|')[0].strip()
  if name and '404' not in name and 'Seite nicht gefunden' not in name: return name
 m=re.search(r'(?m)^#\s+(.+)$', raw)
 if m: return clean(m.group(1)).replace('- _','-').replace('_','')
 return None
def get(row):
 setid,cid,local,old=row
 url=f'https://www.pokemon.com/de/pokemon-sammelkartenspiel/pokemon-karten/series/{setid}/{local}/'
 try:
  name=parse_name(fetch(url))
  return {'set_id':setid,'card_id':cid,'local_id':local,'old':old,'url':url,'name':name,'status':'ok' if name else 'no_name'}
 except Exception as e:
  return {'set_id':setid,'card_id':cid,'local_id':local,'old':old,'url':url,'status':'error','error':str(e)}
def main():
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 rows=[(r['set_id'],r['card_id'],r['local_id'],r['name']) for r in conn.execute('select set_id,card_id,local_id,name from cards where language_code=? and set_id in (?,?,?) order by set_id,local_id_sort',('de',*SETS))]
 results=[]
 with cf.ThreadPoolExecutor(max_workers=10) as ex:
  for res in ex.map(get, rows): results.append(res)
 updated=[]; failures=[]
 for res in results:
  if res.get('status')!='ok':
   # g1 73a is known 404 from official; CardsRealm remains.
   failures.append(res); continue
  if res['name'] != res['old']:
   conn.execute('update cards set name=? where language_code=? and card_id=?',(res['name'],'de',res['card_id']))
   updated.append({'card_id':res['card_id'],'old':res['old'],'new':res['name'],'url':res['url']})
  # Add provenance for official pages, even if name unchanged, only for touched fallback work sets.
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('de',res['set_id'],res['card_id'],res['url'],'official_pokemon_de_card_archive',f'German localized card name verified from official Pokémon Germany card archive; previous value={res["old"]!r}.',FETCHED_AT))
 conn.commit()
 by_set=[list(r) for r in conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='de' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc""")]
 report={'fetched_at':FETCHED_AT,'input_rows':len(rows),'updated_count':len(updated),'updated':updated[:120],'failure_count':len(failures),'failures':failures[:50],'remaining_de':sum(x[1] for x in by_set),'remaining_by_set':by_set}
 out=REPORT_DIR/'official_pokemon_de_archive_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
