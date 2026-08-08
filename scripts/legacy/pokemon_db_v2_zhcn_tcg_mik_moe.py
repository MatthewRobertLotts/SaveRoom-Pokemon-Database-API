#!/usr/bin/env python3
"""Recover Chinese Simplified card images from tcg.mik.moe.

URL format: https://tcg.mik.moe/static/img/<set_id>/<number>.png
"""
from __future__ import annotations
import json, re, sqlite3, time, hashlib
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonZhCn/1.0'

def build_set_mapping():
    """Build DB set_id -> tcg.mik.moe set_id mapping."""
    conn = sqlite3.connect(DB); cur = conn.cursor()
    
    # Get existing ZH-CN image URLs to understand the pattern
    rows = cur.execute('''
        SELECT DISTINCT c.image_url
        FROM cards c
        WHERE c.language_code='zh-cn' 
          AND c.image_url IS NOT NULL AND c.image_url != ''
          AND c.image_url LIKE '%tcg.mik.moe%'
    ''').fetchall()
    
    existing_tcg_ids = set()
    for (url,) in rows:
        m = re.search(r'/static/img/([^/]+)/', url)
        if m:
            existing_tcg_ids.add(m.group(1))
    
    # Get missing ZH-CN set IDs
    missing = cur.execute('''
        SELECT DISTINCT s.core_set_id
        FROM v2_card_search s
        WHERE s.language_code='zh-cn' AND s.has_display_image=0
    ''').fetchall()
    
    mapping = {}
    for (set_id,) in missing:
        # Try various transformations
        candidates = [
            set_id.upper(),
            set_id.upper().replace('.', ''),
            re.sub(r'(\d)\.(\d)', r'\1\2', set_id.upper()),
        ]
        
        for candidate in candidates:
            if candidate in existing_tcg_ids:
                mapping[set_id] = candidate
                break
        
        if set_id not in mapping:
            # Test if URL works
            for candidate in candidates:
                url = f'https://tcg.mik.moe/static/img/{candidate}/001.png'
                try:
                    r = requests.head(url, timeout=5, allow_redirects=True)
                    if r.status_code == 200 and int(r.headers.get('content-length', 0)) > 1000:
                        mapping[set_id] = candidate
                        break
                except:
                    pass
    
    conn.close()
    return mapping

def get_missing_cards_for_set(set_id):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT c.card_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code='zh-cn' AND s.has_display_image=0 AND s.core_set_id=?
    ''', (set_id,)).fetchall()
    conn.close()
    return [{'card_id': r[0], 'local_id': r[1], 'name': r[2]} for r in rows]

def download_image(url, path):
    try:
        r = requests.get(url, timeout=20, stream=True, headers={'User-Agent': UA})
        if r.status_code != 200: return False, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(); total = 0
        with path.open('wb') as f:
            for chunk in r.iter_content(65536):
                if chunk: f.write(chunk); h.update(chunk); total += len(chunk)
        return True, total
    except: return False, 0

def main():
    print('Building set mapping...')
    mapping = build_set_mapping()
    print(f'Mapped {len(mapping)} set IDs')
    
    all_manifest = []
    date_str = time.strftime('%Y-%m-%d')
    
    for set_id, tcg_id in sorted(mapping.items(), key=lambda x: x[0]):
        db_cards = get_missing_cards_for_set(set_id)
        print(f'{set_id} -> {tcg_id} ({len(db_cards)}):', end=' ', flush=True)
        
        dl = 0
        for c in db_cards:
            local_id = c['local_id']
            # Try with and without leading zeros
            for lid in [local_id, local_id.lstrip('0') or '0', local_id.zfill(3)]:
                url = f'https://tcg.mik.moe/static/img/{tcg_id}/{lid}.png'
                path = IMAGE_ROOT / date_str / 'zh-cn' / set_id / f"{c['card_id']}.png"
                ok, sz = download_image(url, path)
                if ok:
                    dl += 1
                    all_manifest.append({
                        'set_id': set_id, 'card_id': c['card_id'], 'local_id': local_id, 'name': c['name'],
                        'image_url': url, 'asset_url': url,
                        'status': 'downloaded', 'candidate_type': 'exact_zhcn_tcg_mik_moe',
                        'language_code': 'zh-cn', 'local_path': str(path), 'bytes': sz,
                        'core_set_id': set_id, 'resolved_set_id': set_id,
                        'source_set_id': set_id, 'source_card_id': c['card_id'],
                        'source_api_url': url,
                    })
                    break
            else:
                all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': 'zh-cn', 'status': 'not_found'})
        
        print(f'{dl}/{len(db_cards)}')
        time.sleep(0.5)
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'zhcn_tcg_mik_moe_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': all_manifest}, ensure_ascii=False, indent=2))
    dl = sum(1 for m in all_manifest if m.get('status') == 'downloaded')
    print(f'\nDone: {dl} downloaded')

if __name__ == '__main__':
    main()
