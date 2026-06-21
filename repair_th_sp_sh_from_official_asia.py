#!/usr/bin/env python3
"""Repair and complete Thai S-P/SH using official Asia source.

- Thai S-P in the DB was cross-language templated from a different regional promo
  numbering and does not match official Thai S-P. Replace it with official Thai
  card-search rows.
- Thai SH had excess templated rows (039-053 plus unsupported DARK/FIGHTING
  energy rows) beyond the official Thai Family Happy listing; delete those fake
  excess rows and source the official energy rows.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import time
from pathlib import Path

DB_PATH=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HELPER=Path('/media/matt/Storage/Brain/Pokemon Card Database/fill_th_from_official_asia.py')
spec=importlib.util.spec_from_file_location('th_helper', HELPER)
th=importlib.util.module_from_spec(spec); spec.loader.exec_module(th)

def local_tokens(detail: dict) -> list[str]:
    coll=detail.get('collector') or ''
    toks=re.findall(r'(\d{3})/S-P', coll)
    if toks:
        return toks
    if coll == 'S-P':
        return ['n']
    loc=detail.get('local') or ''
    return [loc] if loc else []

def sort_val(local: str):
    return int(local) if local.isdigit() else None

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row

    # Build official S-P rows.
    sp_details=[th.parse_detail(i) for i in th.list_detail_ids('S-P')]
    sp_rows=[]
    for d in sp_details:
        for loc in local_tokens(d):
            cid='S-P-n' if loc=='n' else f'S-P-{loc}'
            sp_rows.append({'card_id':cid,'local_id':loc,'local_id_sort':sort_val(loc),'name':d['name'],'url':d['url'],'collector':d['collector']})
    # Delete old S-P templated rows/provenance/details and replace with official rows.
    old_sp=[dict(r) for r in conn.execute("select card_id,local_id,name from cards where language_code='th' and set_id='S-P' order by local_id_sort,card_id")]
    conn.execute("delete from card_details where language_code='th' and set_id='S-P'")
    conn.execute("delete from card_source_provenance where language_code='th' and set_id='S-P'")
    conn.execute("delete from cards where language_code='th' and set_id='S-P'")
    for r in sp_rows:
        conn.execute("insert or replace into cards(language_code,set_id,card_id,local_id,local_id_sort,name,image_url) values (?,?,?,?,?,?,?)",('th','S-P',r['card_id'],r['local_id'],r['local_id_sort'],r['name'],None))
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """,('th','S-P',r['card_id'],r['url'],'official_asia_th_card_search',f'Official Thai S-P promo row imported from Asia Pokémon card-search; collector={r["collector"]!r}. Replaced cross-language templated regional promo data.',FETCHED_AT))
        conn.execute("""
            INSERT OR REPLACE INTO card_details(card_id,language_code,set_id,local_id,local_id_sort,name,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """,(r['card_id'],'th','S-P',r['local_id'],r['local_id_sort'],r['name'],FETCHED_AT))
    conn.execute("update sets set official_count=?, total_count=?, fetched_at=? where language_code='th' and set_id='S-P'",(len(sp_rows),len(sp_rows),FETCHED_AT))

    # Complete SH official energies and delete excess rows not present in official Thai source.
    sh_details=[th.parse_detail(i) for i in th.list_detail_ids('SH')]
    sh_by_local={}
    for d in sh_details:
        for loc in local_tokens(d):
            sh_by_local[loc]=d
    official_sh_locals=set(sh_by_local)
    current_sh=[dict(r) for r in conn.execute("select card_id,local_id,name from cards where language_code='th' and set_id='SH'")]
    deleted_sh=[]; updated_sh=[]
    for r in current_sh:
        loc=r['local_id']
        if loc not in official_sh_locals:
            conn.execute("delete from card_details where language_code='th' and card_id=?",(r['card_id'],))
            conn.execute("delete from card_source_provenance where language_code='th' and card_id=?",(r['card_id'],))
            conn.execute("delete from cards where language_code='th' and card_id=?",(r['card_id'],))
            deleted_sh.append(r)
        else:
            d=sh_by_local[loc]
            # If still unresolved, update and add official provenance. Also normalize energy names where official source exists.
            unresolved=conn.execute("""
                SELECT 1 FROM card_source_provenance p WHERE p.language_code='th' AND p.card_id=? AND p.method='cross_language_template'
                 AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
            """,(r['card_id'],)).fetchone()
            if unresolved:
                conn.execute("update cards set name=? where language_code='th' and card_id=?",(d['name'],r['card_id']))
                conn.execute("""
                    INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                    VALUES (?,?,?,?,?,?,?)
                """,('th','SH',r['card_id'],d['url'],'official_asia_th_card_search',f'Thai Family Happy row parsed from official Asia Pokémon card-search; collector={d["collector"]!r}; old fallback={r["name"]!r}.',FETCHED_AT))
                updated_sh.append({'card_id':r['card_id'],'old':r['name'],'new':d['name'],'url':d['url']})
    # Use actual official row count in DB after delete (38 numbered + official energies currently present).
    sh_count=conn.execute("select count(*) from cards where language_code='th' and set_id='SH'").fetchone()[0]
    conn.execute("update sets set total_count=?, fetched_at=? where language_code='th' and set_id='SH'",(sh_count,FETCHED_AT))
    conn.commit()

    remaining=conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p WHERE p.language_code='th' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    """).fetchone()[0]
    by_set=list(conn.execute("""
        SELECT p.set_id,COUNT(*) FROM card_source_provenance p WHERE p.language_code='th' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
        GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """).fetchall())
    report={'fetched_at':FETCHED_AT,'sp_old_rows_removed':len(old_sp),'sp_official_rows_inserted':len(sp_rows),'sp_detail_pages':len(sp_details),'sh_deleted_excess_rows':deleted_sh,'sh_updated_rows':updated_sh,'remaining_th':remaining,'remaining_by_set':[list(x) for x in by_set]}
    out=REPORT_DIR/'official_asia_th_sp_sh_repair_completion.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:16000])
    print('Report:',out)
    conn.close()

if __name__=='__main__': main()
