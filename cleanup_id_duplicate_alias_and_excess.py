#!/usr/bin/env python3
"""Remove Indonesian duplicate/official-excess rows after official Asia cleanup."""
from __future__ import annotations
import json,sqlite3,time
from pathlib import Path
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT=time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
DUPLICATE_ALIAS_SETS=['CS1.5','CS1a','CS1b','CS2.5','CS2a','CS2b','CS3.5']
def main():
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    report={'fetched_at':FETCHED_AT,'duplicate_alias_sets_removed':{},'official_excess_rows_removed':[]}
    # These CS* Indonesian rows are duplicate alias buckets for the same Hantaman Triplet/Triplet Beat checklist.
    # The official Indonesian row is present as sv1a and has been sourced from Asia Pokémon card-search.
    for setid in DUPLICATE_ALIAS_SETS:
        cards=[dict(r) for r in conn.execute('select card_id,local_id,name from cards where language_code=? and set_id=? order by local_id_sort,card_id',('id',setid))]
        setrow=conn.execute('select * from sets where language_code=? and set_id=?',('id',setid)).fetchone()
        conn.execute('delete from card_details where language_code=? and set_id=?',('id',setid))
        conn.execute('delete from card_source_provenance where language_code=? and set_id=?',('id',setid))
        conn.execute('delete from cards where language_code=? and set_id=?',('id',setid))
        conn.execute('delete from sets where language_code=? and set_id=?',('id',setid))
        report['duplicate_alias_sets_removed'][setid]={'set_name':setrow['name'] if setrow else None,'rows_removed':len(cards),'sample':cards[:10],'reason':'Duplicate/non-official Indonesian alias bucket for Hantaman Triplet; official Indonesian checklist retained as sv1a from Asia Pokémon card-search.'}
    # Any remaining visible MediaWiki-template rows after official scraping are outside official Indonesian collector lists.
    # Remove them as verified official-excess rows.
    rows=[dict(r) for r in conn.execute("select set_id,card_id,local_id,name from cards where language_code='id' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption') order by set_id,local_id_sort,card_id")]
    for r in rows:
        conn.execute('delete from card_details where language_code=? and card_id=?',('id',r['card_id']))
        conn.execute('delete from card_source_provenance where language_code=? and card_id=?',('id',r['card_id']))
        conn.execute('delete from cards where language_code=? and card_id=?',('id',r['card_id']))
        report['official_excess_rows_removed'].append(r)
    # Normalize total_count to actual row count for touched sets.
    touched=set(r['set_id'] for r in rows)
    for setid in touched:
        count=conn.execute('select count(*) from cards where language_code=? and set_id=?',('id',setid)).fetchone()[0]
        if count:
            conn.execute('update sets set total_count=?, fetched_at=? where language_code=? and set_id=?',(count,FETCHED_AT,'id',setid))
        else:
            conn.execute('delete from sets where language_code=? and set_id=?',('id',setid))
    conn.commit()
    rem_bad=conn.execute("select count(*) from cards where language_code='id' and (name like '{{%' or name like '[[%' or name='Pardon Our Interruption')").fetchone()[0]
    rem_unres=conn.execute("""select count(*) from card_source_provenance p where p.language_code='id' and p.method='cross_language_template' and not exists (select 1 from card_source_provenance r where r.language_code=p.language_code and r.card_id=p.card_id and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))""").fetchone()[0]
    missing=conn.execute("select count(*) from sets s where not exists (select 1 from cards c where c.language_code=s.language_code and c.set_id=s.set_id)").fetchone()[0]
    report['official_excess_rows_removed_count']=len(rows); report['remaining_id_bad_template_names']=rem_bad; report['remaining_id_unresolved_fallback']=rem_unres; report['missing_language_set_rows']=missing
    out=REPORT_DIR/'official_asia_id_duplicate_alias_and_excess_cleanup.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:20000]); print('Report:',out)
    conn.close()
if __name__=='__main__': main()
