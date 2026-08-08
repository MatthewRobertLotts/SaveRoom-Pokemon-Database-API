#!/usr/bin/env python3
"""Resolve remaining Japanese {{Mega template artifacts from Bulbapedia raw setlists."""
from __future__ import annotations
import datetime as dt, hashlib, json, re, shutil, sqlite3, urllib.parse
from pathlib import Path
import requests
DB=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS=Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')

def now(): return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
def stamp(): return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')
def rows(cur,sql,p=()): return [dict(r) for r in cur.execute(sql,p).fetchall()]
def scalar(cur,sql,p=()): return cur.execute(sql,p).fetchone()[0]
def hid(prefix,*parts): return prefix+'_'+hashlib.sha1('\u241f'.join(map(str,parts)).encode()).hexdigest()[:24]
def raw_url(page_url):
    # page_url like https://bulbapedia.../wiki/Premium_Champion_Pack_(TCG)
    title=urllib.parse.unquote(page_url.rsplit('/wiki/',1)[1])
    return 'https://bulbapedia.bulbagarden.net/w/index.php?title='+urllib.parse.quote(title,safe='()_')+'&action=raw'
def parse_raw(text):
    m={}
    for line in text.splitlines():
        if '{{Setlist' not in line: continue
        # first param no. e.g. 002/131, 20/32, 024/088
        mm=re.search(r'\{\{Setlist[^|]*\|([^|}]+)\|', line)
        if not mm: continue
        no=mm.group(1).strip()
        local=no.split('/')[0].strip().lstrip('0') or '0'
        content=line
        name=None
        link=re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', content)
        if link:
            title=link.group(1)
            name=re.sub(r'\s*\([^)]*\)\s*$', '', title).strip()
        elif '{{TCG ID|' in content:
            parts=content.replace('{{','').replace('}}','').split('|')
            if len(parts)>=3: name=parts[2].strip()
        if name:
            m[local]=name
            m[local.zfill(3)]=name
    return m

def recreate_views(cur):
    cur.execute('DROP VIEW IF EXISTS cards_with_resolved_sets')
    cur.execute("""CREATE VIEW cards_with_resolved_sets AS SELECT c.language_code,c.set_id,c.card_id,c.local_id,c.local_id_sort,c.name,c.image_url,COALESCE(sa.target_language_code,c.language_code) resolved_language_code,COALESCE(sa.target_set_id,c.set_id) resolved_set_id,rs.name resolved_set_name,rs.series_name resolved_series_name,rs.release_date resolved_release_date,CASE WHEN sa.target_set_id IS NOT NULL THEN 1 ELSE 0 END resolved_via_set_alias,sa.alias_type set_alias_type,sa.method set_alias_method,sa.confidence set_alias_confidence,sa.notes set_alias_notes FROM cards c LEFT JOIN set_aliases sa ON sa.alias_language_code=c.language_code AND sa.alias_set_id=c.set_id LEFT JOIN sets rs ON rs.language_code=COALESCE(sa.target_language_code,c.language_code) AND rs.set_id=COALESCE(sa.target_set_id,c.set_id)""")
    cur.execute('DROP VIEW IF EXISTS cards_v2')
    cur.execute("""CREATE VIEW cards_v2 AS SELECT c.*,COALESCE(ls.core_set_id,sac.target_core_set_id) core_set_id,sc.canonical_name core_set_name,sc.canonical_language_code core_canonical_language_code,sc.canonical_set_id core_canonical_set_id,CASE WHEN COALESCE(ls.core_set_id,sac.target_core_set_id) IS NOT NULL THEN 1 ELSE 0 END resolved_to_core,CASE WHEN sac.target_core_set_id IS NOT NULL THEN 1 ELSE 0 END resolved_via_core_alias FROM cards_with_resolved_sets c LEFT JOIN localized_sets ls ON ls.language_code=c.resolved_language_code AND ls.set_id=c.resolved_set_id LEFT JOIN set_aliases_core sac ON sac.alias_language_code=c.language_code AND sac.alias_set_id=c.set_id LEFT JOIN sets_core sc ON sc.core_set_id=COALESCE(ls.core_set_id,sac.target_core_set_id)""")

def audit(cur):
 return {'core_unresolved':scalar(cur,'SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL'),'visible_template_names':scalar(cur,"SELECT COUNT(*) FROM cards WHERE name LIKE '{{%' OR name LIKE '[[%' OR name='Pardon Our Interruption'"),'unresolved_fallback_rows':scalar(cur,"""SELECT COUNT(*) FROM card_source_provenance p WHERE p.method='cross_language_template' AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))"""),'placeholder_names':scalar(cur,"SELECT COUNT(*) FROM cards WHERE name LIKE 'Unknown card %' OR name LIKE 'Unknown %' OR name LIKE 'Unresolved %' OR name='Pardon Our Interruption'"),'missing_language_set_rows':scalar(cur,'SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id)'),'language_orphan_rows':scalar(cur,'SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL'),'cards':scalar(cur,'SELECT COUNT(*) FROM cards'),'cards_v2':scalar(cur,'SELECT COUNT(*) FROM cards_v2'),'integrity_check':scalar(cur,'PRAGMA integrity_check'),'quick_check':scalar(cur,'PRAGMA quick_check'),'foreign_key_check_rows':len(rows(cur,'PRAGMA foreign_key_check'))}

def main():
 fetched=now(); REPORTS.mkdir(parents=True,exist_ok=True); backup=DB.with_name(DB.stem+f'.backup_before_jp_mega_cleanup_{stamp()}'+DB.suffix); shutil.copy2(DB,backup)
 conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row; cur=conn.cursor(); cur.execute('PRAGMA foreign_keys=ON')
 before=audit(cur)
 dirty=rows(cur,"""SELECT c.language_code,c.set_id,c.card_id,c.local_id,c.name,p.source_url FROM cards c JOIN card_source_provenance p ON p.language_code=c.language_code AND p.card_id=c.card_id AND p.method IN ('bulbapedia_v2_setlist','bulbapedia_setlist') WHERE c.name='{{Mega' GROUP BY c.language_code,c.card_id ORDER BY c.set_id,c.local_id_sort""")
 by_url={}
 for d in dirty: by_url.setdefault(d['source_url'],[]).append(d)
 parsed={}; fetched_pages={}; cleaned=[]; skipped=[]
 for url,items in by_url.items():
  ru=raw_url(url); txt=requests.get(ru,timeout=30,headers={'User-Agent':'HermesAgent/1.0'}).text; fetched_pages[url]={'raw_url':ru,'bytes':len(txt)}; parsed[url]=parse_raw(txt)
  for d in items:
   key=(d['local_id'] or '').lstrip('0') or d['local_id']; new=parsed[url].get(d['local_id']) or parsed[url].get(key) or parsed[url].get((d['local_id'] or '').zfill(3))
   if not new:
    skipped.append({**d,'reason':'local_id_not_found_in_raw_setlist'}); continue
   cur.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?',(new,d['language_code'],d['card_id']))
   cur.execute('UPDATE card_details SET name=? WHERE language_code=? AND card_id=?',(new,d['language_code'],d['card_id']))
   note=f"Resolved truncated Japanese {{Mega}} MediaWiki artifact from Bulbapedia raw setlist {ru}; local_id={d['local_id']}; new_name={new!r}; no machine translation."
   cur.execute("INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) VALUES (?,?,?,?,?,?,?)",(d['language_code'],d['set_id'],d['card_id'],url,'v2_japanese_mega_template_raw_bulbapedia_cleanup',note,fetched))
   doc_id=hid('src',url,'v2_japanese_mega_template_raw_bulbapedia_cleanup',d['language_code'])
   cur.execute("INSERT OR IGNORE INTO source_documents(source_document_id,source_url,source_type,language_code,fetched_at,retrieved_by,reliability_notes) VALUES (?,?, 'bulbapedia_raw_setlist', ?, ?, 'Hermes Agent', 'Fetched raw MediaWiki setlist to recover truncated Mega template names.')",(doc_id,url,d['language_code'],fetched))
   prov_id=hid('prov','cards',d['language_code'],d['card_id'],'v2_japanese_mega_template_raw_bulbapedia_cleanup',url)
   cur.execute("INSERT OR REPLACE INTO provenance_records(provenance_id,entity_table,entity_key,language_code,source_document_id,source_url,method,fetched_at,confidence,source_notes,extraction_notes,created_at) VALUES (?, 'cards', ?, ?, ?, ?, 'v2_japanese_mega_template_raw_bulbapedia_cleanup', ?, 1.0, ?, ?, ?)",(prov_id,f"{d['language_code']}:{d['card_id']}",d['language_code'],doc_id,url,fetched,note,f"old_name='{{{{Mega'; new_name={new!r}; raw_url={ru}",fetched))
   cleaned.append({**d,'new_name':new,'raw_url':ru})
 conn.commit(); recreate_views(cur); conn.commit()
 after=audit(cur)
 wave2={'cards':len(rows(cur,'SELECT card_id FROM cards')),'visible_template_names':sum(1 for r in rows(cur,'SELECT name FROM cards') if r['name'].startswith('{{') or r['name'].startswith('[[') or r['name']=='Pardon Our Interruption'),'core_unresolved':scalar(cur,'SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL')}
 report={'fetched_at':fetched,'database':str(DB),'backup':str(backup),'before':before,'cleaned':len(cleaned),'skipped':skipped,'fetched_pages':fetched_pages,'after_wave1_sql':after,'after_wave2_python':wave2,'pass':after['visible_template_names']==0 and after['core_unresolved']==0 and after['unresolved_fallback_rows']==0 and after['placeholder_names']==0 and after['missing_language_set_rows']==0 and after['language_orphan_rows']==0 and after['integrity_check']=='ok' and after['quick_check']=='ok' and wave2['visible_template_names']==0 and wave2['core_unresolved']==0}
 out=REPORTS/f"v2_japanese_mega_cleanup_final_audit_{fetched[:10]}.json"; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'report':str(out),'backup':str(backup),'pass':report['pass'],'cleaned':len(cleaned),'skipped':len(skipped),'visible_templates':after['visible_template_names'],'core_unresolved':after['core_unresolved'],'integrity':after['integrity_check'],'quick':after['quick_check']},indent=2))
if __name__=='__main__': main()
