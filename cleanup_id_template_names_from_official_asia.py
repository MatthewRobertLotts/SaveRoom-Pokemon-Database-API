#!/usr/bin/env python3
"""Clean Indonesian visible MediaWiki-template names using official Asia card-search."""
from __future__ import annotations
import concurrent.futures as cf, importlib.util, json, sqlite3, time
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HELPER=Path('/media/matt/Storage/Brain/Pokemon Card Database/fill_id_from_official_asia.py')
spec=importlib.util.spec_from_file_location('id_helper',HELPER)
idhelp=importlib.util.module_from_spec(spec); spec.loader.exec_module(idhelp)
def bad_sets(conn):
    return [r[0] for r in conn.execute("select set_id from cards where language_code='id' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption') group by set_id order by set_id")]
def set_map(setid):
    ids=idhelp.list_detail_ids(setid)
    cards=[]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for c in ex.map(idhelp.parse_detail, ids): cards.append(c)
    m={}
    dup=[]
    for c in cards:
        if c.get('status')!='ok' or not c.get('local') or not c.get('name'): continue
        local=c['local'].upper()
        if local in m:
            dup.append({'local':local,'kept':m[local]['url'],'skipped':c['url'],'name':c['name']}); continue
        m[local]=c
    return ids,m,dup
def main():
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    sets=bad_sets(conn)
    report={'fetched_at':FETCHED_AT,'sets':{},'updated_total':0,'miss_total':0}
    for setid in sets:
        print('SET',setid,flush=True)
        ids,m,dup=set_map(setid)
        rows=conn.execute("select card_id,local_id,name from cards where language_code='id' and set_id=? and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption') order by local_id_sort,card_id",(setid,)).fetchall()
        updated=[]; misses=[]
        for r in rows:
            hit=m.get((r['local_id'] or '').upper())
            if not hit:
                misses.append(dict(r)); continue
            conn.execute('update cards set name=? where language_code=? and card_id=?',(hit['name'],'id',r['card_id']))
            conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('id',setid,r['card_id'],hit['url'],'official_asia_id_template_cleanup',f'Indonesian visible MediaWiki-template name replaced from official Asia card-search; collector={hit.get("collector","")!r}; old value={r["name"]!r}.',FETCHED_AT))
            updated.append({'card_id':r['card_id'],'old':r['name'],'new':hit['name'],'url':hit['url']})
        conn.commit()
        report['sets'][setid]={'detail_pages':len(ids),'parsed_locals':len(m),'input_bad_names':len(rows),'updated':len(updated),'misses':misses[:50],'duplicate_collectors':dup[:20],'examples':updated[:10]}
        report['updated_total']+=len(updated); report['miss_total']+=len(misses)
        print(setid,'updated',len(updated),'miss',len(misses),flush=True)
    remaining=conn.execute("select count(*) from cards where language_code='id' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption')").fetchone()[0]
    unresolved=conn.execute("""select count(*) from card_source_provenance p where p.language_code='id' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
    report['remaining_id_bad_template_names']=remaining; report['remaining_id_unresolved_fallback']=unresolved
    out=REPORT_DIR/'official_asia_id_template_name_cleanup.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
