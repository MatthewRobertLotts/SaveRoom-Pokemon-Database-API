#!/usr/bin/env python3
"""Japanese image recovery from Limitless CDN.

Limitless hosts Japanese card images at:
https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpc/<SET>/<SET>_<NUM>_R_JP_SM.png

where <NUM> is the local_id (without leading zeros).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
OUT_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images') / dt.datetime.now(dt.UTC).strftime('%Y-%m-%d') / 'ja_limitless'
CANDIDATE_TYPE = 'exact_limitless_jp_recovered_asset'
LIMITLESS_JP_CDN = 'https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpc'

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sets', type=str, default='')  # comma-separated
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=0.01)
    args = ap.parse_args()
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    
    # Default: all Japanese sets missing images
    set_filter = ''
    params: list[Any] = ['ja']
    if args.sets:
        set_list = [s.strip() for s in args.sets.split(',')]
        set_filter = ' AND resolved_set_id IN (' + ','.join(['?' for _ in set_list]) + ')'
        params.extend(set_list)
    
    rows = conn.execute(f"""
        SELECT language_code, resolved_set_id, card_id, local_id, card_name
        FROM v2_card_search
        WHERE language_code=? AND has_display_image=0 {set_filter}
          AND resolved_set_id IS NOT NULL
        ORDER BY resolved_set_id, local_id_sort, card_id
    """, params).fetchall()
    
    if args.limit:
        rows = rows[:args.limit]
    
    conn.close()
    
    manifest = []
    misses = []
    processed = 0
    
    for row in rows:
        sid = row['resolved_set_id']
        local_id = row['local_id']
        card_id = row['card_id']
        
        # Remove leading zeros for Limitless format (handle non-numeric like "DAR")
        try:
            num = str(int(local_id)) if local_id and local_id.isdigit() else local_id
        except ValueError:
            num = local_id
        if not num:
            misses.append({**{k: row[k] for k in row.keys()}, 'reason': 'no_local_id'})
            continue
        
        img_url = f'{LIMITLESS_JP_CDN}/{sid}/{sid}_{num}_R_JP_SM.png'
        
        try:
            req = urllib.request.Request(img_url, method='HEAD')
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200:
                    misses.append({**{k: row[k] for k in row.keys()}, 'reason': f'http_{r.status}', 'url': img_url})
                    continue
        except Exception as e:
            misses.append({**{k: row[k] for k in row.keys()}, 'reason': f'head_error', 'url': img_url})
            continue
        
        # Download
        try:
            with urllib.request.urlopen(img_url, timeout=30) as r:
                data = r.read()
        except Exception as e:
            misses.append({**{k: row[k] for k in row.keys()}, 'reason': f'download_error', 'url': img_url})
            continue
        
        safe_card = re.sub(r'[^A-Za-z0-9_.-]+', '_', card_id)
        out_dir = OUT_ROOT / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f'{safe_card}.png'
        path.write_bytes(data)
        
        manifest.append({
            'set_id': sid,
            'card_id': card_id,
            'local_id': local_id,
            'image_url': img_url,
            'asset_url': img_url,
            'status': 'downloaded',
            'candidate_type': CANDIDATE_TYPE,
            'language_code': 'ja',
            'local_path': str(path),
            'bytes': len(data),
            'core_set_id': sid,
            'resolved_set_id': sid,
            'source_set_id': sid,
            'source_card_id': card_id,
            'source_api_url': f'https://limitlesstcg.com/cards/jp/{sid}',
            'sha256': hashlib.sha256(data).hexdigest(),
        })
        processed += 1
        time.sleep(args.sleep)
    
    stamp = dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')
    out = REPORTS / f'ja_limitless_recovery_{stamp}.json'
    out.write_text(json.dumps({
        'generated_at': stamp,
        'database': str(DB),
        'rows_considered': len(rows),
        'downloaded': len(manifest),
        'misses_count': len(misses),
        'manifest': manifest,
        'misses': misses[:50]
    }, ensure_ascii=False, indent=2))
    
    print(json.dumps({
        'report': str(out),
        'rows_considered': len(rows),
        'downloaded': len(manifest),
        'misses_count': len(misses)
    }, indent=2))
    return 0

if __name__ == '__main__':
    main()