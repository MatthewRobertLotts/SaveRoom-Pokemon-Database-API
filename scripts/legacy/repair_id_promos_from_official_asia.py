#!/usr/bin/env python3
"""Repair Indonesian promo buckets from official Asia source.

The previous Indonesian S-P/SV-P rows included cross-language regional promo rows
and Bulbapedia-template artifacts. Official Indonesian card-search exposes full
S-P and SV-P promo lists, so replace those buckets with source-backed rows.
"""
from __future__ import annotations
import importlib.util,json,re,sqlite3,time
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HELPER=Path('/media/matt/Storage/Brain/Pokemon Card Database/fill_id_from_official_asia.py')
spec=importlib.util.spec_from_file_location('id_helper',HELPER)
idhelp=importlib.util.module_from_spec(spec); spec.loader.exec_module(idhelp)
def sort_val(local):
    return int(local) if str(local).isdigit() else None
def official_rows(expansion:str):
    details=[idhelp.parse_detail(i) for i in idhelp.list_detail_ids(expansion)]
    rows=[]; skipped_duplicates=[]; seen=set(); unnum=0
    for d in details:
        if d.get('status')!='ok' or not d.get('name'): continue
        local=(d.get('local') or '').upper()
        # Trophy / event cards have collector exactly S-P or SV-P and no numeric local.
        if local in {'S-P','SV-P',''}:
            if expansion=='S-P':
                local='n' if unnum==0 else f'n{unnum}'
            else:
                local=f'no{unnum}'
            unnum+=1
        # Duplicate collector numbers in official SV-P are duplicate print/distribution rows.
        if local in seen:
            skipped_duplicates.append({'local':local,'name':d['name'],'collector':d.get('collector'),'url':d['url']})
            continue
        seen.add(local)
        cid=f'{expansion}-{local}'
        rows.append({'card_id':cid,'local_id':local,'local_id_sort':sort_val(local),'name':d['name'],'url':d['url'],'collector':d.get('collector','')})
    return rows,details,skipped_duplicates

def remaining(conn):
    return [list(r) for r in conn.execute("""
    SELECT p.set_id, COUNT(*) FROM card_source_provenance p WHERE p.language_code='id' AND p.method='cross_language_template'
      AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """)]
def main():
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    report={'fetched_at':FETCHED_AT,'sets':{}}
    for exp in ['S-P','SV-P']:
        rows,details,skipped=official_rows(exp)
        old=[dict(r) for r in conn.execute('select card_id,local_id,name from cards where language_code=? and set_id=? order by local_id_sort,card_id',('id',exp))]
        conn.execute('delete from card_details where language_code=? and set_id=?',('id',exp))
        conn.execute('delete from card_source_provenance where language_code=? and set_id=?',('id',exp))
        conn.execute('delete from cards where language_code=? and set_id=?',('id',exp))
        for r in rows:
            conn.execute('insert or replace into cards(language_code,set_id,card_id,local_id,local_id_sort,name,image_url) values (?,?,?,?,?,?,?)',('id',exp,r['card_id'],r['local_id'],r['local_id_sort'],r['name'],None))
            conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) values (?,?,?,?,?,?,?)""",('id',exp,r['card_id'],r['url'],'official_asia_id_card_search',f'Official Indonesian {exp} promo row imported from Asia Pokémon card-search; collector={r["collector"]!r}. Replaced prior cross-language/templated regional promo data.',FETCHED_AT))
            conn.execute("""insert or replace into card_details(card_id,language_code,set_id,local_id,local_id_sort,name,fetched_at) values (?,?,?,?,?,?,?)""",(r['card_id'],'id',exp,r['local_id'],r['local_id_sort'],r['name'],FETCHED_AT))
        conn.execute('update sets set official_count=?, total_count=?, fetched_at=? where language_code=? and set_id=?',(len(rows),len(rows),FETCHED_AT,'id',exp))
        report['sets'][exp]={'old_rows_removed':len(old),'official_detail_pages':len(details),'official_rows_inserted':len(rows),'skipped_duplicate_collectors':skipped[:50],'old_sample':old[:30],'new_sample':rows[:30]}
    conn.commit()
    rem=remaining(conn)
    suspicious=conn.execute("select count(*) from cards where language_code='id' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption')").fetchone()[0]
    report['remaining_id']=sum(x[1] for x in rem); report['remaining_by_set']=rem; report['id_suspicious_template_names_remaining']=suspicious
    out=REPORT_DIR/'official_asia_id_promo_repair_completion.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
