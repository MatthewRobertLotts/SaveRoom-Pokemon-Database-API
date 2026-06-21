#!/usr/bin/env python3
"""Japanese card recovery via official pokemon-card.com site.

Maps DB set/local to numeric card IDs, extracts image URLs from detail pages.
Uses browser tool since the site is JS-rendered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Any

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
OUT_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images') / 'jp_official' / dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')
CANDIDATE_TYPE = 'exact_jp_official_scraped_asset'

# Known regulation marks for set mappings (DB set -> official site regu)
REGU_MAP = {
    # E-card era
    'E1': 'E', 'E2': 'E', 'E3': 'E', 'E4': 'E', 'E5': 'E',
    # ADV era  
    'ADV1': 'EX', 'ADV2': 'EX', 'ADV3': 'EX', 'ADV4': 'EX', 'ADV5': 'EX',
    # DP era
    'DP1a': 'DP', 'DP1b': 'DP', 'DP2': 'DP', 'DP3': 'DP', 'DP4a': 'DP',
    'DP4b': 'DP', 'DP5a': 'DP', 'DP5b': 'DP', 'DP6': 'DP',
    # SP/Platinum
    'Pt1': 'Pl', 'Pt2': 'Pl', 'Pt3': 'Pl', 'Pt4': 'Pl',
}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sets', type=str, default='')
    args = ap.parse_args()
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    
    set_filter = ''
    params = ['ja']
    if args.sets:
        set_filter = f" AND resolved_set_id IN ({','.join(['?' for _ in args.sets.split(',')])})"
        params.extend(args.sets.split(','))
    
    rows = conn.execute(f"""
        SELECT language_code, resolved_set_id, card_id, local_id, card_name, resolved_set_name
        FROM v2_card_search
        WHERE language_code=? AND has_display_image=0 {set_filter}
        ORDER BY resolved_set_id, local_id_sort, card_id
    """, params).fetchall()
    
    if args.limit:
        rows = rows[:args.limit]
    
    conn.close()
    
    manifest = []
    misses = []
    
    # For each row, we need to find the numeric ID via the Japanese site
    # This requires browser-based scraping - output the URLs to manually process or use browser tool
    detail_urls = []
    for r in rows:
        sid = r['resolved_set_id']
        regu = REGU_MAP.get(sid, 'SV')  # Default to SV for newer sets
        detail_urls.append({
            'db_set': sid,
            'local_id': r['local_id'],
            'card_name': r['card_name'],
            'card_id': r['card_id'],
            'search_term': f'{sid} {r["local_id"]}',  # Use for search
            'detail_url_pattern': f'https://www.pokemon-card.com/card-search/details.php/card/<NUM>/regu/{regu}/',
        })
    
    print(f'Japanese cards to map: {len(rows)}')
    print('First 10 sets:')
    sets_seen = {}
    for r in rows[:20]:
        sid = r['resolved_set_id']
        sets_seen[sid] = sets_seen.get(sid, 0) + 1
    for sid, n in sorted(sets_seen.items(), key=lambda x: -x[1]):
        print(f'  {sid}: {n}')
    
    # Output URLs for browser scraping
    out = REPORTS / f'ja_official_mapping_needed_{dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")}.json'
    out.write_text(json.dumps({'generated_at': dt.datetime.now(dt.UTC).isoformat(), 
                              'detail_urls': detail_urls[:100]}, 
                             ensure_ascii=False, indent=2))
    print(f'Mapping URLs saved to: {out}')
    return 0

if __name__ == '__main__':
    main()