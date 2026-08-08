#!/usr/bin/env python3
"""Complete Indonesian fallback rows from official Asia Pokémon card search."""
from __future__ import annotations
import concurrent.futures as cf
import html,json,re,sqlite3,time,urllib.parse,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Accept-Language':'id,en;q=0.8'}
EXPANSIONS=['S11','S-P','S8a','S10b','SV-P']
ENERGY_LOCAL={
    'Energi Kegelapan Dasar':'DAR','Energi Petarung Dasar':'FIG','Energi Api Dasar':'FIR','Energi Daun Dasar':'GRA',
    'Energi Listrik Dasar':'LIG','Energi Logam Dasar':'MET','Energi Psychic Dasar':'PSY','Energi Air Dasar':'WAT',
    'Energi Dasar Kegelapan':'DAR','Energi Dasar Petarung':'FIG','Energi Dasar Api':'FIR','Energi Dasar Daun':'GRA',
    'Energi Dasar Listrik':'LIG','Energi Dasar Logam':'MET','Energi Dasar Psychic':'PSY','Energi Dasar Air':'WAT',
}
def fetch(url:str)->str:
    return urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45).read().decode('utf-8','ignore')
def clean(s:str)->str:
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def list_detail_ids(expansion:str)->list[str]:
    ids=[]; seen=set()
    for page in range(1,80):
        url=f'https://asia.pokemon-card.com/id/card-search/list/?expansionCodes={urllib.parse.quote(expansion)}&pageNo={page}'
        raw=fetch(url)
        found=re.findall(r'/id/card-search/detail/(\d+)/',raw)
        new=[]
        for x in found:
            if x not in seen:
                seen.add(x); new.append(x); ids.append(x)
        if not found or not new:
            break
    return ids
def parse_detail(num:str)->dict:
    url=f'https://asia.pokemon-card.com/id/card-search/detail/{num}/'
    raw=fetch(url)
    # If missing detail redirects to the global list, do not parse as a card.
    if 'Hasil Pencarian Kartu' in raw and '<h1 class="pageHeader cardDetail"' not in raw:
        return {'detail_id':num,'url':url,'status':'not_detail'}
    tm=re.search(r'<title>(.*?)\|',raw,re.S|re.I)
    name=clean(tm.group(1)) if tm else None
    if not name:
        hm=re.search(r'<h1 class="pageHeader cardDetail">(.*?)</h1>',raw,re.S|re.I)
        name=clean(hm.group(1)) if hm else None
    # Remove card-class markers that appear in h1 extraction if title was unavailable.
    for prefix in ['basic ','Stage 1 ','Stage 2 ','Pokémon V ','Pokémon VMAX ','Pokémon VSTAR ']:
        if name and name.startswith(prefix): name=name[len(prefix):].strip()
    cm=re.search(r'<span class="collectorNumber">\s*([^<]+?)\s*</span>',raw,re.S|re.I)
    collector=clean(cm.group(1)) if cm else ''
    local=collector.split('/')[0].strip().upper() if collector else ''
    em=re.search(r'/mark/([^"/]+?)_[A-Z]@4x\.png',raw)
    expansion=em.group(1) if em else ''
    if (not local or local.isdigit()) and name in ENERGY_LOCAL:
        local=ENERGY_LOCAL[name]
    return {'detail_id':num,'url':url,'status':'ok','name':name,'collector':collector,'local':local,'expansion':expansion}
def unresolved(conn):
    return conn.execute("""
    SELECT p.set_id,p.card_id,c.local_id,c.name old_name
    FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
    WHERE p.language_code='id' AND p.method='cross_language_template'
      AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    ORDER BY p.set_id,c.local_id_sort,c.card_id
    """).fetchall()
def remaining_counts(conn):
    return [list(r) for r in conn.execute("""
    SELECT p.set_id, COUNT(*) FROM card_source_provenance p WHERE p.language_code='id' AND p.method='cross_language_template'
      AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """)]
def main():
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    maps={}; detail_counts={}; parsed_counts={}; samples={}
    for exp in EXPANSIONS:
        ids=list_detail_ids(exp); detail_counts[exp]=len(ids); print(exp,'detail ids',len(ids))
        cards=[]
        with cf.ThreadPoolExecutor(max_workers=12) as ex:
            for c in ex.map(parse_detail,ids): cards.append(c)
        m={}
        for c in cards:
            if c.get('status')=='ok' and c.get('local'):
                m[c['local'].upper()]=c
        maps[exp]=m; parsed_counts[exp]=len(m); samples[exp]=list(m.items())[:5]
        print(exp,'parsed locals',len(m))
    rows=unresolved(conn)
    updated=0; examples=[]; misses=[]
    for r in rows:
        set_id=r['set_id']; local=(r['local_id'] or '').upper()
        hit=maps.get(set_id,{}).get(local)
        if not hit:
            misses.append(dict(r)); continue
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?',(hit['name'],'id',r['card_id']))
        conn.execute("""INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) VALUES (?,?,?,?,?,?,?)""",('id',set_id,r['card_id'],hit['url'],'official_asia_id_card_search',f'Indonesian name parsed from official Asia Pokémon card-search detail page; collector={hit["collector"]!r}; old fallback={r["old_name"]!r}.',FETCHED_AT))
        updated+=1
        if len(examples)<80: examples.append({'card_id':r['card_id'],'old':r['old_name'],'new':hit['name'],'collector':hit['collector'],'url':hit['url']})
    conn.commit()
    rem=remaining_counts(conn)
    report={'fetched_at':FETCHED_AT,'detail_counts':detail_counts,'parsed_counts':parsed_counts,'input_unresolved':len(rows),'updated':updated,'miss_count':len(misses),'remaining_id':sum(x[1] for x in rem),'remaining_by_set':rem,'examples':examples,'misses':misses[:200]}
    out=REPORT_DIR/'official_asia_id_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:18000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
