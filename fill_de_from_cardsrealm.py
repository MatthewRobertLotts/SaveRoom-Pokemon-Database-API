#!/usr/bin/env python3
from __future__ import annotations
import html,json,re,sqlite3,time,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'de,en;q=0.8'}
SET_URLS={
 'sma':'https://pokemon.cardsrealm.com/de-de/sets/sma-hidden-fates-shiny-vault',
 'g1':'https://pokemon.cardsrealm.com/de-de/sets/g1-gym-heroes',
}
def fetch(url):
 return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45).read().decode('utf-8','ignore')
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def strip_code(name,number,setid):
 toks=clean(name).split()
 if toks and toks[-1].lower()==number.lower(): toks=toks[:-1]
 if toks and toks[-1].lower()==setid.lower(): toks=toks[:-1]
 out=' '.join(toks).strip()
 out=re.sub(r'(GEN|sma)$','',out).strip()
 return out or clean(name)
def parse_set(raw,setid):
 out={}
 pat=re.compile(r'<a itemprop="url" href="([^"]+)" title="([^"]+)".*?<span itemprop="name">([^<]+)</span>\s*#([^<]+)<',re.S)
 for href,title,span,number in pat.findall(raw):
  number=clean(number).upper(); out[number]={'name':strip_code(span,number,setid),'href':href,'title':clean(title)}
 return out
def unresolved(conn):
 return conn.execute("""
 SELECT p.set_id,p.card_id,c.local_id,c.name old_name FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
 WHERE p.language_code='de' AND p.method='cross_language_template'
 AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
 ORDER BY p.set_id,c.local_id_sort,c.card_id
 """).fetchall()
def main():
 REPORT_DIR.mkdir(parents=True,exist_ok=True)
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 maps={}; parsed={}
 for sid,url in SET_URLS.items():
  raw=fetch(url); cards=parse_set(raw,sid); maps[sid]=cards; parsed[sid]=len(cards); print(sid,len(cards))
 rows=unresolved(conn); updated=0; examples=[]
 for r in rows:
  hit=maps.get(r['set_id'],{}).get((r['local_id'] or '').upper())
  if not hit: continue
  src=SET_URLS[r['set_id']]
  if hit.get('href','').startswith('/'): src='https://pokemon.cardsrealm.com'+hit['href']
  conn.execute('update cards set name=? where language_code=? and card_id=?',(hit['name'],'de',r['card_id']))
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('de',r['set_id'],r['card_id'],src,'cardsrealm_de_set_spoiler',f'German card name parsed from CardsRealm German set/card listing; old fallback={r["old_name"]!r}.',FETCHED_AT))
  updated+=1
  if len(examples)<70: examples.append({'card_id':r['card_id'],'old':r['old_name'],'new':hit['name'],'url':src})
 conn.commit()
 by_set=[list(r) for r in conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='de' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc""")]
 remaining=sum(x[1] for x in by_set)
 report={'fetched_at':FETCHED_AT,'parsed_counts':parsed,'updated':updated,'remaining_de':remaining,'remaining_by_set':by_set,'examples':examples}
 out=REPORT_DIR/'cardsrealm_de_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:16000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
