#!/usr/bin/env python3
"""Clean Korean visible MediaWiki-template names using Daldagury Korean TCG API."""
from __future__ import annotations
import json,sqlite3,time,urllib.parse,urllib.request
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
API='https://api.daldagury.com'
HEADERS={'User-Agent':'Mozilla/5.0 SaveRoom/1.0','Origin':'https://daldagury.com','Referer':'https://daldagury.com/'}
def get_json(path,params=None):
    url=API+path+('?' + urllib.parse.urlencode(params) if params else '')
    return json.load(urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=60))
def all_sets(): return get_json('/tcg/pokemon/sets')['resultData']
def choose_set_id(sets,code):
    matches=[s for s in sets if (s.get('setCode') or '').lower()==code.lower()]
    kr=[s for s in matches if s.get('region')=='KR' or ('확장팩' in (s.get('setNameKo') or '') or '강화 확장팩' in (s.get('setNameKo') or '') or '하이클래스팩' in (s.get('setNameKo') or ''))]
    pool=kr or matches
    if not pool: return None,matches
    pool=sorted(pool,key=lambda s:(int(s.get('cardCount') or 0), int(s.get('setId') or 0)), reverse=True)
    return pool[0].get('setId'), matches
def cards_for_set(setid):
    resp=get_json('/tcg/cards/search',{'gameCode':'pokemon','setIds':setid,'limit':500})
    rd=resp.get('resultData')
    if not rd or not isinstance(rd, dict):
        return {},[],[]
    data=rd.get('data') or []
    m={}; dups=[]
    for c in data:
        num=(c.get('cardNumber') or '').upper()
        if not num: continue
        if num in m:
            dups.append({'local':num,'kept':m[num].get('cardId'),'skipped':c.get('cardId'),'nameKo':c.get('nameKo')}); continue
        m[num]=c
    return m,data,dups
def main():
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    badsets=[r[0] for r in conn.execute("select set_id from cards where language_code='ko' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption') group by set_id order by set_id")]
    sets=all_sets()
    report={'fetched_at':FETCHED_AT,'sets':{},'updated_total':0,'miss_total':0}
    for code in badsets:
        sid,matches=choose_set_id(sets,code)
        print('SET',code,'sid',sid,flush=True)
        rows=conn.execute("select card_id,local_id,name from cards where language_code='ko' and set_id=? and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption') order by local_id_sort,card_id",(code,)).fetchall()
        if not sid:
            report['sets'][code]={'chosen_set_id':None,'input_bad_names':len(rows),'updated':0,'misses':[dict(r) for r in rows[:50]],'matches':[]}
            report['miss_total']+=len(rows); continue
        m,data,dups=cards_for_set(sid)
        updated=[]; misses=[]
        for r in rows:
            hit=m.get((r['local_id'] or '').upper())
            if not hit:
                misses.append(dict(r)); continue
            name=hit['nameKo']; url=f'https://daldagury.com/tcg/pokemon/card/{hit["cardId"]}'
            conn.execute('update cards set name=? where language_code=? and card_id=?',(name,'ko',r['card_id']))
            conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('ko',code,r['card_id'],url,'daldagury_ko_template_cleanup',f'Korean visible MediaWiki-template name replaced from Daldagury Korean TCG API/card page; old value={r["name"]!r}.',FETCHED_AT))
            updated.append({'card_id':r['card_id'],'old':r['name'],'new':name,'url':url})
        conn.commit()
        report['sets'][code]={'chosen_set_id':sid,'matches':[{'setId':s.get('setId'),'setCode':s.get('setCode'),'setNameKo':s.get('setNameKo'),'region':s.get('region'),'cardCount':s.get('cardCount')} for s in matches[:10]],'api_card_rows':len(data),'mapped_locals':len(m),'input_bad_names':len(rows),'updated':len(updated),'misses':misses[:50],'duplicate_collectors':dups[:20],'examples':updated[:10]}
        report['updated_total']+=len(updated); report['miss_total']+=len(misses)
        print(code,'updated',len(updated),'miss',len(misses),flush=True)
    remaining=conn.execute("select count(*) from cards where language_code='ko' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption')").fetchone()[0]
    unresolved=conn.execute("""select count(*) from card_source_provenance p where p.language_code='ko' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
    report['remaining_ko_bad_template_names']=remaining; report['remaining_ko_unresolved_fallback']=unresolved
    out=REPORT_DIR/'daldagury_ko_template_name_cleanup.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
