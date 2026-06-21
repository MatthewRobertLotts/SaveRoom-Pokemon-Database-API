#!/usr/bin/env python3
from __future__ import annotations
import html,json,re,sqlite3,time,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'it,en;q=0.8'}
SET_URLS={
 'sma':'https://pokemon.cardsrealm.com/it-it/sets/sma-hidden-fates-shiny-vault',
 'g1':'https://pokemon.cardsrealm.com/it-it/sets/g1-gym-heroes',
 'pl2':'https://pokemon.cardsrealm.com/it-it/sets/pl2-rising-rivals',
 'hgss1':'https://pokemon.cardsrealm.com/it-it/sets/hgss1-heartgold-soulsilver',
}
ALPH={
 'hgss1-ONE':'https://pokemon.cardsrealm.com/it-it/card/alph-lithograph-hs-one',
 'hgss2-TWO':'https://pokemon.cardsrealm.com/it-it/card/alph-lithograph-ul-two',
 'hgss3-THREE':'https://pokemon.cardsrealm.com/it-it/card/alph-lithograph-ud-three',
 'hgss4-FOUR':'https://pokemon.cardsrealm.com/it-it/card/alph-lithograph-tm-four',
}
def fetch(url):
 return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45).read().decode('utf-8','ignore')
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def strip_code(name,number):
 toks=clean(name).split()
 if toks and toks[-1].lower()==number.lower(): toks=toks[:-1]
 if toks and re.fullmatch(r'[A-Z0-9]{2,5}', toks[-1]): toks=toks[:-1]
 return ' '.join(toks).strip() or clean(name)
def parse_set(raw):
 out={}
 pat=re.compile(r'<a itemprop="url" href="([^"]+)" title="([^"]+)".*?<span itemprop="name">([^<]+)</span>\s*#([^<]+)<',re.S)
 for href,title,span,number in pat.findall(raw):
  number=clean(number).upper(); out[number]={'name':strip_code(span,number),'href':href,'title':clean(title)}
 return out
def title_name(raw):
 m=re.search(r'<title>(.*?)</title>',raw,re.S|re.I)
 if not m: return None
 return re.split(r'\s*/\s*', clean(m.group(1)))[0].strip()
def unresolved(conn):
 return conn.execute("""
 SELECT p.set_id,p.card_id,c.local_id,c.name old_name FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
 WHERE p.language_code='it' AND p.method='cross_language_template'
 AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
 ORDER BY p.set_id,c.local_id_sort,c.card_id
 """).fetchall()
def main():
 REPORT_DIR.mkdir(parents=True,exist_ok=True)
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
 maps={}; parsed={}
 for sid,url in SET_URLS.items():
  raw=fetch(url); cards=parse_set(raw); maps[sid]=cards; parsed[sid]=len(cards); print(sid,len(cards))
 rows=unresolved(conn); updated=0; misses=[]; examples=[]
 for r in rows:
  hit=maps.get(r['set_id'],{}).get((r['local_id'] or '').upper())
  if not hit:
   misses.append(dict(r)); continue
  src=SET_URLS[r['set_id']]
  if hit.get('href','').startswith('/'): src='https://pokemon.cardsrealm.com'+hit['href']
  conn.execute('update cards set name=? where language_code=? and card_id=?',(hit['name'],'it',r['card_id']))
  conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('it',r['set_id'],r['card_id'],src,'cardsrealm_it_set_spoiler',f'Italian card name parsed from CardsRealm Italian set/card listing; old fallback={r["old_name"]!r}.',FETCHED_AT))
  updated+=1
  if len(examples)<50: examples.append({'card_id':r['card_id'],'old':r['old_name'],'new':hit['name'],'url':src})
 # Alph direct pages
 for cid,url in ALPH.items():
  row=conn.execute("""
  SELECT p.set_id,c.name FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id WHERE p.language_code='it' AND p.card_id=? AND p.method='cross_language_template'
  AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
  """,(cid,)).fetchone()
  if row:
   name=title_name(fetch(url))
   conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'it',cid))
   conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('it',row['set_id'],cid,url,'cardsrealm_it_card_page',f'Italian Alph Lithograph card name parsed from CardsRealm Italian card page; old fallback={row["name"]!r}.',FETCHED_AT))
   updated+=1; examples.append({'card_id':cid,'old':row['name'],'new':name,'url':url})
 conn.commit()
 remaining=conn.execute("""select count(*) from card_source_provenance p where p.language_code='it' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
 by_set=list(conn.execute("""select p.set_id,count(*) from card_source_provenance p where p.language_code='it' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) group by p.set_id order by count(*) desc"""))
 report={'fetched_at':FETCHED_AT,'parsed_counts':parsed,'input_unresolved':len(rows),'updated':updated,'remaining_it':remaining,'remaining_by_set':[list(x) for x in by_set],'examples':examples,'misses':misses[:100]}
 out=REPORT_DIR/'cardsrealm_it_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)[:12000]); print('Report:',out)
 conn.close()
if __name__=='__main__': main()
