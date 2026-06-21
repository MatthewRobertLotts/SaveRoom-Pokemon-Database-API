#!/usr/bin/env python3
"""Complete Korean unresolved fallback rows from Daldagury Korean TCG API."""
from __future__ import annotations
import json,sqlite3,time,urllib.parse,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
API='https://api.daldagury.com'
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Origin':'https://daldagury.com','Referer':'https://daldagury.com/'}
ENERGY={
 'DAR':'기본 악 에너지','FIG':'기본 격투 에너지','FIR':'기본 불꽃 에너지','GRA':'기본 풀 에너지',
 'LIG':'기본 번개 에너지','MET':'기본 강철 에너지','PSY':'기본 초 에너지','WAT':'기본 물 에너지'
}
def get_json(path,params=None):
    qs='?'+urllib.parse.urlencode(params) if params else ''
    url=API+path+qs
    return json.load(urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45))
def all_sets(): return get_json('/tcg/pokemon/sets')['resultData']
def choose_set_id(sets,code):
    matches=[s for s in sets if s.get('setCode')==code]
    # Prefer Korean region/source rows and Korean set names.
    kr=[s for s in matches if s.get('region')=='KR' or ('확장팩' in (s.get('setNameKo') or '') or '강화 확장팩' in (s.get('setNameKo') or ''))]
    pool=kr or matches
    if not pool: return None,[]
    # Prefer largest cardCount and newest Daldagury id if multiple.
    pool=sorted(pool,key=lambda s:(int(s.get('cardCount') or 0), int(s.get('setId') or 0)), reverse=True)
    return pool[0].get('setId'), matches
def cards_for_set(setid):
    data=get_json('/tcg/cards/search',{'gameCode':'pokemon','setIds':setid,'limit':500})['resultData']['data']
    m={}
    for c in data:
        num=(c.get('cardNumber') or '').upper()
        if num and num not in m: m[num]=c
    return m,data
def unresolved(conn):
    return conn.execute("""
    SELECT p.set_id,p.card_id,c.local_id,c.name old_name
    FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
    WHERE p.language_code='ko' AND p.method='cross_language_template'
      AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    ORDER BY p.set_id,c.local_id_sort,c.card_id
    """).fetchall()
def rem_by_set(conn):
    return [list(r) for r in conn.execute("""
    SELECT p.set_id,COUNT(*) FROM card_source_provenance p WHERE p.language_code='ko' AND p.method='cross_language_template'
      AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """)]
def main():
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    sets=all_sets(); needed=sorted({r['set_id'] for r in unresolved(conn)})
    maps={}; set_meta={}
    for code in needed:
        sid,matches=choose_set_id(sets,code)
        set_meta[code]={'chosen_set_id':sid,'matches':[{'setId':s.get('setId'),'setCode':s.get('setCode'),'setNameKo':s.get('setNameKo'),'region':s.get('region'),'cardCount':s.get('cardCount')} for s in matches[:10]]}
        if sid:
            maps[code],data=cards_for_set(sid)
            set_meta[code]['api_card_rows']=len(data); set_meta[code]['mapped_locals']=len(maps[code])
    rows=unresolved(conn); updated=0; misses=[]; examples=[]
    for r in rows:
        code=r['set_id']; local=(r['local_id'] or '').upper()
        hit=maps.get(code,{}).get(local)
        # Some official Korean card search APIs omit unnumbered energies; use official Korean TCG energy names by type code only when card is energy-code local.
        if not hit and local in ENERGY:
            name=ENERGY[local]; url=f'https://daldagury.com/tcg/pokemon?set={set_meta.get(code,{}).get("chosen_set_id")}'
            method='korean_energy_name_fixed_source'
        elif hit:
            name=hit['nameKo']; url=f'https://daldagury.com/tcg/pokemon/card/{hit["cardId"]}'
            method='daldagury_ko_card_api'
        else:
            misses.append(dict(r)); continue
        conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'ko',r['card_id']))
        conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('ko',code,r['card_id'],url,method,f'Korean name sourced from Daldagury Korean Pokémon TCG API/card page or fixed official Korean energy name; local={local!r}; old fallback={r["old_name"]!r}.',FETCHED_AT))
        updated+=1
        if len(examples)<80: examples.append({'card_id':r['card_id'],'old':r['old_name'],'new':name,'url':url})
    conn.commit()
    rem=rem_by_set(conn)
    report={'fetched_at':FETCHED_AT,'set_meta':set_meta,'input_unresolved':len(rows),'updated':updated,'miss_count':len(misses),'remaining_ko':sum(x[1] for x in rem),'remaining_by_set':rem,'examples':examples,'misses':misses[:100]}
    out=REPORT_DIR/'daldagury_ko_fallback_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
