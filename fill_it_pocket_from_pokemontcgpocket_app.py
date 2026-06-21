#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures as cf, html,json,re,sqlite3,time,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'it,en;q=0.8'}
def fetch(url):
 return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=30).read().decode('utf-8','ignore')
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def parse_name(raw,cid):
 m=re.search(r'<title>(.*?)</title>',raw,re.S|re.I)
 if not m: return None
 t=clean(m.group(1))
 return re.split(r'\s+'+re.escape(cid)+r'\s+\|',t)[0].strip()
def unresolved_pocket(conn):
 return conn.execute("""
 SELECT p.set_id,p.card_id,c.name old_name FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
 WHERE p.language_code='it' AND s.series_name LIKE '%Pocket%' AND p.method='cross_language_template'
 AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
 ORDER BY p.set_id,c.local_id_sort,c.card_id
 """).fetchall()
def get(row):
 cid=row['card_id']; url=f'https://pokemontcgpocket.app/it/card/{cid}'
 try:
  raw=fetch(url); name=parse_name(raw,cid)
  if not name: return {**dict(row),'status':'no_name','url':url}
  return {**dict(row),'status':'ok','url':url,'name':name}
 except Exception as e: return {**dict(row),'status':'error','url':url,'error':str(e)}
def main():
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 rows=unresolved_pocket(conn); print('it pocket unresolved',len(rows))
 results=[]
 with cf.ThreadPoolExecutor(max_workers=12) as ex:
  for res in ex.map(get, rows): results.append(res)
 updated=0; examples=[]; failures=[]
 for res in results:
  if res['status']!='ok': failures.append(res); continue
  conn.execute('update cards set name=? where language_code=? and card_id=?',(res['name'],'it',res['card_id']))
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('it',res['set_id'],res['card_id'],res['url'],'pokemontcgpocket_app_it_card_page',f'Italian Pocket name parsed from pokemontcgpocket.app Italian card page; old fallback={res["old_name"]!r}.',FETCHED_AT))
  updated+=1
  if len(examples)<60: examples.append({'card_id':res['card_id'],'old':res['old_name'],'new':res['name'],'url':res['url']})
 conn.commit()
 remaining=conn.execute("""select count(*) from card_source_provenance p where p.language_code='it' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
 by_set=list(conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='it' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc"""))
 report={'fetched_at':FETCHED_AT,'input_rows':len(rows),'updated':updated,'failure_count':len(failures),'remaining_it':remaining,'remaining_by_set':[list(x) for x in by_set],'examples':examples,'failures':failures[:50]}
 out=REPORT_DIR/'pokemontcgpocket_app_it_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:16000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
