#!/usr/bin/env python3
"""Complete Thai fallback rows from official Asia Pokémon card search.

Official Thai source:
https://asia.pokemon-card.com/th/card-search/list/?expansionCodes=<SET>&pageNo=N
and /th/card-search/detail/<id>/ detail pages.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS = {'User-Agent': 'Mozilla/5.0 SaveRoom/1.0', 'Accept-Language': 'th,en;q=0.8'}
EXPANSIONS = ['S11', 'S-P', 'SH', 'S8a', 'S10b']
ENERGY_LOCAL = {
    'พื้นฐานพลังงานมืด': 'DAR',
    'พลังงานมืดพื้นฐาน': 'DAR',
    'พื้นฐานพลังงานต่อสู้': 'FIG',
    'พลังงานต่อสู้พื้นฐาน': 'FIG',
    'พื้นฐานพลังงานไฟ': 'FIR',
    'พลังงานไฟพื้นฐาน': 'FIR',
    'พื้นฐานพลังงานหญ้า': 'GRA',
    'พลังงานหญ้าพื้นฐาน': 'GRA',
    'พื้นฐานพลังงานสายฟ้า': 'LIG',
    'พลังงานสายฟ้าพื้นฐาน': 'LIG',
    'พื้นฐานพลังงานโลหะ': 'MET',
    'พลังงานโลหะพื้นฐาน': 'MET',
    'พื้นฐานพลังงานพลังจิต': 'PSY',
    'พลังงานพลังจิตพื้นฐาน': 'PSY',
    'พื้นฐานพลังงานน้ำ': 'WAT',
    'พลังงานน้ำพื้นฐาน': 'WAT',
}

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode('utf-8', 'ignore')

def clean(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()

def list_detail_ids(expansion: str) -> list[str]:
    ids=[]; seen=set()
    for page in range(1, 80):
        url=f'https://asia.pokemon-card.com/th/card-search/list/?expansionCodes={urllib.parse.quote(expansion)}&pageNo={page}'
        raw=fetch(url)
        found=re.findall(r'/th/card-search/detail/(\d+)/', raw)
        # Dedupe while preserving order; each card has only one link in current HTML, but be safe.
        new=[]
        for x in found:
            if x not in seen:
                seen.add(x); new.append(x); ids.append(x)
        if not found or not new:
            break
    return ids

def parse_detail(card_id_num: str) -> dict:
    url=f'https://asia.pokemon-card.com/th/card-search/detail/{card_id_num}/'
    raw=fetch(url)
    m=re.search(r'<h1 class="pageHeader cardDetail">(.*?)</h1>', raw, re.S|re.I)
    name=clean(m.group(1)) if m else None
    # remove evolution stage labels that appear as nested span text at the start
    for prefix in ['พื้นฐาน ', 'ร่าง 1 ', 'ร่าง 2 ', 'โปเกมอน V ', 'โปเกมอน VMAX ', 'โปเกมอน VSTAR ']:
        if name and name.startswith(prefix):
            name=name[len(prefix):].strip()
    cm=re.search(r'<span class="collectorNumber">\s*([^<]+?)\s*</span>', raw, re.S|re.I)
    collector=clean(cm.group(1)) if cm else ''
    local=collector.split('/')[0].strip().upper() if collector else ''
    # Expansion symbol e.g. S11_T@4x.png, S-P_T@4x.png
    em=re.search(r'/mark/([^"/]+?)_T@4x\.png', raw)
    expansion=em.group(1) if em else ''
    if not local and name in ENERGY_LOCAL:
        local=ENERGY_LOCAL[name]
    return {'detail_id':card_id_num,'url':url,'name':name,'collector':collector,'local':local,'expansion':expansion}

def unresolved(conn):
    return conn.execute("""
        SELECT p.set_id,p.card_id,c.local_id,c.name AS old_name
        FROM card_source_provenance p JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        WHERE p.language_code='th' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
        ORDER BY p.set_id,c.local_id_sort,c.card_id
    """).fetchall()

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    maps={}; parsed_counts={}; detail_counts={}
    for exp in EXPANSIONS:
        ids=list_detail_ids(exp)
        detail_counts[exp]=len(ids)
        print(exp,'detail ids',len(ids))
        cards=[]
        with cf.ThreadPoolExecutor(max_workers=12) as ex:
            for card in ex.map(parse_detail, ids):
                cards.append(card)
        # map by expansion+local, and also by requested exp+local if expansion parsing differs
        m={}
        for card in cards:
            if card.get('local'):
                m[card['local'].upper()]=card
        maps[exp]=m; parsed_counts[exp]=len(m)
        print(exp,'parsed locals',len(m))
    rows=unresolved(conn)
    updated=0; misses=[]; examples=[]
    for r in rows:
        set_id=r['set_id']; local=(r['local_id'] or '').upper()
        hit=maps.get(set_id,{}).get(local)
        if not hit:
            misses.append(dict(r)); continue
        name=hit['name']
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?',(name,'th',r['card_id']))
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """,('th',set_id,r['card_id'],hit['url'],'official_asia_th_card_search',f'Thai name parsed from official Asia Pokémon card-search detail page; collector={hit["collector"]!r}; old fallback={r["old_name"]!r}.',FETCHED_AT))
        updated+=1
        if len(examples)<60:
            examples.append({'card_id':r['card_id'],'old':r['old_name'],'new':name,'collector':hit['collector'],'url':hit['url']})
    conn.commit()
    remaining=conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p WHERE p.language_code='th' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    """).fetchone()[0]
    by_set=list(conn.execute("""
        SELECT p.set_id, COUNT(*) FROM card_source_provenance p WHERE p.language_code='th' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
        GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """).fetchall())
    report={'fetched_at':FETCHED_AT,'detail_counts':detail_counts,'parsed_counts':parsed_counts,'input_unresolved':len(rows),'updated':updated,'miss_count':len(misses),'remaining_th':remaining,'remaining_by_set':[list(x) for x in by_set],'examples':examples,'misses':misses[:200]}
    out=REPORT_DIR/'official_asia_th_completion.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:16000])
    print('Report:',out)
    conn.close()

if __name__=='__main__': main()
