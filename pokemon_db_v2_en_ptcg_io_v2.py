#!/usr/bin/env python3
"""Recover English card images from pokemontcg.io API.

Builds set ID mapping from existing images, then downloads missing card images.
"""
from __future__ import annotations
import json, re, sqlite3, time, hashlib
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonPtcgIO/1.0'

def get_ptcg_sets():
    url = 'https://api.pokemontcg.io/v2/sets?pageSize=250'
    r = requests.get(url, timeout=15)
    return {s['id']: s for s in r.json().get('data', [])}

def build_set_mapping():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    
    # Get mapping from existing TCGdex image URLs
    rows = cur.execute('''
        SELECT DISTINCT c.set_id, c.image_url
        FROM cards c
        WHERE c.language_code = 'en' 
          AND c.image_url IS NOT NULL AND c.image_url != ''
          AND c.image_url LIKE '%tcgdex.net%'
    ''').fetchall()
    
    mapping = {}
    for set_id, url in rows:
        m = re.match(r'https://assets\.tcgdex\.net/en/([^/]+)/([^/]+)/', url)
        if m:
            tcgdex_set = m.group(2)
            if set_id not in mapping:
                mapping[set_id] = tcgdex_set
    
    # Get all missing English set IDs and try to map them
    ptcg_sets = get_ptcg_sets()
    missing_sets = cur.execute('''
        SELECT DISTINCT s.core_set_id
        FROM v2_card_search s
        WHERE s.language_code='en' AND s.has_display_image=0
    ''').fetchall()
    
    for (set_id,) in missing_sets:
        if set_id in mapping:
            continue
        # Direct match
        if set_id in ptcg_sets:
            mapping[set_id] = set_id
            continue
        # Lowercase
        if set_id.lower() in ptcg_sets:
            mapping[set_id] = set_id.lower()
            continue
        # Remove dots and dashes
        transformed = set_id.lower().replace('.', '').replace('-', '').replace(' ', '')
        if transformed in ptcg_sets:
            mapping[set_id] = transformed
            continue
        # Try prefix matching for numbered sets (B2a -> bw2, etc.)
        prefix = re.match(r'([a-z]+)(\d+)([a-z]?)', set_id.lower())
        if prefix:
            base, num, suffix = prefix.groups()
            for ptcg_prefix in ['bw', 'xy', 'sm', 'sv', 'swsh', 'dp', 'pl', 'hgss', 'ex', 'base', 'gym', 'neo', 'pop', 'ecard', 'col', 'mcd', 'pgo', 'cel', 'sma', 'det', 'g1', 'ru1', 'dv1', 'dc1', 'mfb', 'xya', 'sp', 'rc', 'tk', 'wp', 'jumbo', 'bog', 'hgssp', 'mee', 'mep', 'svp', 'sve']:
                candidate = f'{ptcg_prefix}{num}{suffix}'
                if candidate in ptcg_sets:
                    mapping[set_id] = candidate
                    break
    
    conn.close()
    return mapping, ptcg_sets

def get_missing_cards_for_set(set_id):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT c.card_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code='en' AND s.has_display_image=0 AND s.core_set_id=?
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
    mapping, ptcg_sets = build_set_mapping()
    print(f'Mapped {len(mapping)} set IDs')
    
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT DISTINCT s.core_set_id, COUNT(*)
        FROM v2_card_search s
        WHERE s.language_code='en' AND s.has_display_image=0
        GROUP BY s.core_set_id ORDER BY COUNT(*) DESC
    ''').fetchall()
    conn.close()
    
    all_manifest = []
    date_str = time.strftime('%Y-%m-%d')
    
    for set_id, count in rows:
        if set_id not in mapping:
            continue
        
        ptcg_set_id = mapping[set_id]
        db_cards = get_missing_cards_for_set(set_id)
        
        print(f'{set_id} -> {ptcg_set_id} ({len(db_cards)}):', end=' ', flush=True)
        
        # Get all cards from pokemontcg.io set
        url = f'https://api.pokemontcg.io/v2/cards?set.id={ptcg_set_id}&pageSize=250'
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                print('API error')
                continue
            
            ptcg_cards = r.json().get('data', [])
            total_pages = r.json().get('totalCount', 0) // 250 + 1
            for page in range(2, min(total_pages + 1, 10)):
                r2 = requests.get(f'{url}&page={page}', timeout=15)
                if r2.status_code == 200:
                    ptcg_cards.extend(r2.json().get('data', []))
            
            # Build local_id -> image_url map
            ptcg_by_local = {}
            for tc in ptcg_cards:
                lid = str(tc.get('number', ''))
                img = tc.get('images', {}).get('large', '')
                if lid and img:
                    ptcg_by_local[lid] = img
                    ptcg_by_local[lid.lstrip('0') or '0'] = img
            
            dl = 0
            for c in db_cards:
                local_id = c['local_id']
                img_url = ptcg_by_local.get(local_id) or ptcg_by_local.get(local_id.lstrip('0') or '0')
                
                if img_url:
                    path = IMAGE_ROOT / date_str / 'en' / set_id / f"{c['card_id']}.png"
                    ok, sz = download_image(img_url, path)
                    if ok: dl += 1
                    all_manifest.append({
                        'set_id': set_id, 'card_id': c['card_id'], 'local_id': local_id, 'name': c['name'],
                        'image_url': img_url, 'asset_url': img_url,
                        'status': 'downloaded' if ok else 'download_failed',
                        'candidate_type': 'exact_ptcg_io_recovered', 'language_code': 'en',
                        'local_path': str(path) if ok else '', 'bytes': sz if ok else 0,
                        'core_set_id': set_id, 'resolved_set_id': set_id,
                        'source_set_id': set_id, 'source_card_id': c['card_id'],
                        'source_api_url': f'https://api.pokemontcg.io/v2/cards/{ptcg_set_id}-{local_id}',
                    })
                else:
                    all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': 'en', 'status': 'card_not_found'})
            
            print(f'{dl}/{len(db_cards)}')
            time.sleep(0.3)
            
        except Exception as e:
            print(f'error: {e}')
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'en_ptcg_io_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': all_manifest}, ensure_ascii=False, indent=2))
    dl = sum(1 for m in all_manifest if m.get('status') == 'downloaded')
    print(f'\nDone: {dl} downloaded')

if __name__ == '__main__':
    main()
