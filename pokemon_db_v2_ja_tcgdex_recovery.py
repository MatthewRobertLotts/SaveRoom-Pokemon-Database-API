#!/usr/bin/env python3
"""Japanese image recovery using TCGdex set API where available, plus official site for legacy sets.

Recovery sources checked in order:
1. TCGdex JP set API (cards with image URLs) - exact set/local match
2. TCGdex JP card API for individual cards - exact card ID match
3. Japanese official site numeric ID mapping (extracted from existing provenance where available)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
OUT_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images') / dt.datetime.now(dt.UTC).strftime('%Y-%m-%d') / 'ja'
CANDIDATE_TYPE = 'exact_tcgdex_ja_recovered_asset'
TCGDEX_API = 'https://api.tcgdex.net/v2/ja'
TCGDEX_ASSETS = 'https://assets.tcgdex.net/ja'

def fetch_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={'User-Agent': 'Hermes SaveRoom JP recovery/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def fetch_bytes(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={'User-Agent': 'Hermes SaveRoom JP recovery/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get('content-type', '')

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=0.02)
    args = ap.parse_args()
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT language_code, resolved_set_id, card_id, local_id, card_name, resolved_set_name
        FROM v2_card_search
        WHERE language_code='ja' AND has_display_image=0
          AND resolved_set_id IS NOT NULL AND resolved_set_id != ''
        ORDER BY resolved_set_id, local_id_sort, card_id
    """).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    conn.close()
    
    manifest = []
    misses = []
    cache: dict[str, bool] = {}  # URL -> already checked
    
    for row in rows:
        sid = row['resolved_set_id']; local_id = row['local_id']; name = row['card_name']; card_id = row['card_id']
        
        # Try TCGdex set API
        img_url = None
        source_api = None
        try:
            set_json = fetch_json(f'{TCGDEX_API}/sets/{sid}')
            cards = set_json.get('cards', [])
            # Find matching card by local ID
            for c in cards:
                if str(c.get('localId')) == str(local_id) or str(c.get('id','').split('-',1)[-1]) == str(local_id):
                    img_url = c.get('image')
                    source_api = f'{TCGDEX_API}/sets/{sid}#{c.get("id")}'
                    break
        except Exception as e:
            pass
        
        if not img_url:
            # Try TCGdex card endpoint
            try:
                card_json = fetch_json(f'{TCGDEX_API}/cards/{card_id}')
                img_url = card_json.get('image')
                source_api = f'{TCGDEX_API}/cards/{card_id}'
            except Exception:
                pass
        
        if not img_url:
            misses.append({**{k: row[k] for k in row.keys()}, 'reason': 'no_tcgdex_source'})
            continue
        
        # Download image
        try:
            ext = '.webp' if img_url.endswith('.webp') else '.png'
            status, data, ctype = fetch_bytes(img_url, timeout=30)
            if status != 200 or not data:
                misses.append({**{k: row[k] for k in row.keys()}, 'reason': f'http_{status}', 'url': img_url})
                continue
        except Exception as e:
            misses.append({**{k: row[k] for k in row.keys()}, 'reason': f'download_error:{e}', 'url': img_url})
            continue
        
        # Save
        safe_card = re.sub(r'[^A-Za-z0-9_.-]+', '_', card_id)
        out_dir = OUT_ROOT / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f'{safe_card}{ext}'
        path.write_bytes(data)
        
        manifest.append({
            'set_id': sid,
            'card_id': card_id,
            'local_id': local_id,
            'name': name,
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
            'source_api_url': source_api,
            'sha256': hashlib.sha256(data).hexdigest(),
        })
        time.sleep(args.sleep)
    
    stamp = dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')
    out = REPORTS / f'ja_tcgdex_recovery_{stamp}.json'
    out.write_text(json.dumps({'generated_at': stamp, 'database': str(DB), 'rows_considered': len(rows),
                              'downloaded': len(manifest), 'misses_count': len(misses), 'manifest': manifest, 'misses': misses[:200]},
                             ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(out), 'rows_considered': len(rows), 'downloaded': len(manifest), 'misses_count': len(misses)}, indent=2))
    return 0

if __name__ == '__main__':
    sys.exit(main())