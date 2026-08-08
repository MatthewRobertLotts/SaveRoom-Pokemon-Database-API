#!/usr/bin/env python3
"""Finish remaining Portuguese Pocket rows using species/name reference pages.

For the final PT Pocket rows, pokemonpocketbr.com has source pages for the same
Portuguese card/species name even when the exact secret-print target id is not on
that page. For Type: Null, use a direct Portuguese page from GetMyDex.
"""
from __future__ import annotations
import json, re, html, sqlite3, time, urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'pt-BR,pt;q=0.9,en;q=0.8'}
# target card_id -> (source_url, expected Portuguese name)
SOURCES={
 'A4a-093':('https://pokemonpocketbr.com/carta/b1-048-psyduck/','Psyduck'),
 'A4a-094':('https://pokemonpocketbr.com/carta/b1-049-golduck/','Golduck'),
 'A4a-095':('https://pokemonpocketbr.com/carta/a1-068-krabby/','Krabby'),
 'A4a-096':('https://pokemonpocketbr.com/carta/a1-069-kingler/','Kingler'),
 'A4a-097':('https://pokemonpocketbr.com/carta/a3-054-pyukumuku/','Pyukumuku'),
 'A4a-098':('https://pokemonpocketbr.com/carta/a2a-045-gible/','Gible'),
 'A4a-099':('https://pokemonpocketbr.com/carta/a2a-046-gabite/','Gabite'),
 'A4a-100':('https://pokemonpocketbr.com/carta/b2a-064-wooper-de-paldea/','Wooper de Paldea'),
 'A4a-102':('https://pokemonpocketbr.com/carta/a1a-032-mew-ex/','Mew ex'),
 'A4a-104':('https://pokemonpocketbr.com/carta/a2b-048-clodsire-de-paldea-ex/','Clodsire de Paldea ex'),
 'B2-223':('https://pokemonpocketbr.com/carta/a4-101-tyrogue/','Tyrogue'),
 'B2a-126':('https://pokemonpocketbr.com/carta/a4-033-entei/','Entei'),
 'B2a-127':('https://pokemonpocketbr.com/carta/a4-059-suicune/','Suicune'),
 'B2a-128':('https://pokemonpocketbr.com/carta/a4-071-raikou/','Raikou'),
 'B1a-096':('https://getmydex.com/pt/card/pokemon/b1a/b1a-096','Type: Null'),
}

def fetch(url):
 req=urllib.request.Request(url,headers=HEADERS)
 with urllib.request.urlopen(req,timeout=30) as r: return r.read().decode('utf-8','ignore')
def strip(s):
 return re.sub(r'\s+',' ', html.unescape(re.sub(r'<[^>]+>',' ',s)).replace(':ex:','ex')).strip()
def parse_name(url, raw):
 m=re.search(r'>\s*Nome:\s*</span>\s*<span[^>]*>(.*?)</span>', raw, re.S|re.I)
 if m: return strip(m.group(1))
 # GetMyDex / generic title
 mt=re.search(r'<title>(.*?)</title>', raw, re.S|re.I)
 if mt:
  t=strip(mt.group(1))
  # "Type: Null #096 | ..."
  return re.split(r'\s+#|\s+\|', t)[0].strip()
 return None

def unresolved(conn, cid):
 return conn.execute("""
 SELECT p.set_id,c.name FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
 WHERE p.language_code='pt' AND p.card_id=? AND p.method='cross_language_template'
   AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
 """,(cid,)).fetchone()

def main():
 conn=sqlite3.connect(DB); updated=0; examples=[]; failures=[]
 for cid,(url,expected) in SOURCES.items():
  row=unresolved(conn,cid)
  if not row: continue
  set_id,old=row
  try:
   raw=fetch(url); name=parse_name(url,raw) or expected
  except Exception as e:
   failures.append({'card_id':cid,'url':url,'error':str(e)}); continue
  # If source parser returns a different but non-empty name, trust exact source. Otherwise expected is from source URL slug/search hit.
  if not name: name=expected
  conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?',(name,'pt',cid))
  method='pokemonpocketbr_species_name_reference' if 'pokemonpocketbr.com' in url else 'getmydex_pt_card_page'
  conn.execute("""
  INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
  VALUES (?,?,?,?,?,?,?)
  """,('pt',set_id,cid,url,method,f'Portuguese Pocket final-row name sourced from Portuguese card/species reference page; old fallback={old!r}.',FETCHED_AT))
  updated+=1; examples.append({'card_id':cid,'old':old,'new':name,'url':url})
 conn.commit()
 remaining=conn.execute("""
 SELECT COUNT(*) FROM card_source_provenance p WHERE p.language_code='pt' AND p.method='cross_language_template'
   AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
 """).fetchone()[0]
 by_set=list(conn.execute("""
 SELECT p.set_id,COUNT(*) FROM card_source_provenance p WHERE p.language_code='pt' AND p.method='cross_language_template'
   AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')) GROUP BY p.set_id ORDER BY COUNT(*) DESC
 """).fetchall())
 report={'fetched_at':FETCHED_AT,'updated':updated,'failures':failures,'remaining_pt':remaining,'remaining_by_set':[list(x) for x in by_set],'examples':examples}
 out=REPORT_DIR/'pt_pocket_final_species_reference_completion.json'
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
 print('Report:',out)
 conn.close()
if __name__=='__main__': main()
