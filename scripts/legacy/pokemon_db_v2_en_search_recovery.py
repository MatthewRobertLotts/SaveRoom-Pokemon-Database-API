#!/usr/bin/env python3
"""Recover English card images from pokemontcg.io using search API.

For each missing card, search by name and download the matching image.
"""
from __future__ import annotations
import json, sqlite3, time, hashlib, re
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonEnRecovery/1.0'

def get_missing_cards():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT c.card_id, c.set_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code='en' AND s.has_display_image=0
        ORDER BY c.set_id, c.local_id_sort
    ''').fetchall()
    conn.close()
    return [{'card_id': r[0], 'set_id': r[1], 'local_id': r[2], 'name': r[3]} for r in rows]

def search_card(name, set_hint=None):
    """Search for a card on pokemontcg.io."""
    # Clean the name for search
    search_name = re.sub(r'[^a-zA-Z0-9\s\-]', '', name).strip()
    if not search_name:
        return None
    
    url = 'https://api.pokemontcg.io/v2/cards'
    params = {
        'q': f'name:{search_name}',
        'pageSize': 10,
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        
        cards = r.json().get('data', [])
        if not cards:
            return None
        
        # If we have a set hint, try to match by set name
        if set_hint:
            for card in cards:
                card_set = card.get('set', {}).get('name', '').lower()
                if set_hint.lower() in card_set:
                    img = card.get('images', {}).get('large', '')
                    if img:
                        return {
                            'image_url': img,
                            'set_id': card.get('set', {}).get('id'),
                            'number': card.get('number'),
                        }
        
        # Otherwise, take the first result with an image
        for card in cards:
            img = card.get('images', {}).get('large', '')
            if img:
                return {
                    'image_url': img,
                    'set_id': card.get('set', {}).get('id'),
                    'number': card.get('number'),
                }
        
        return None
    except:
        return None

def download_image(url, path):
    try:
        r = requests.get(url, timeout=20, stream=True, headers={'User-Agent': UA})
        if r.status_code != 200:
            return False, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        total = 0
        with path.open('wb') as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
                    total += len(chunk)
        return True, total
    except:
        return False, 0

def main():
    print('Getting missing English cards...')
    missing = get_missing_cards()
    print(f'Total missing: {len(missing)}')
    
    manifest = []
    date_str = time.strftime('%Y-%m-%d')
    found = 0
    not_found = 0
    
    for i, card in enumerate(missing):
        card_id = card['card_id']
        set_id = card['set_id']
        local_id = card['local_id']
        name = card['name']
        
        # Search for the card
        result = search_card(name, set_id)
        
        if result:
            img_url = result['image_url']
            path = IMAGE_ROOT / date_str / 'en' / set_id / f"{card_id}.png"
            ok, sz = download_image(img_url, path)
            
            if ok:
                found += 1
                status = 'downloaded'
            else:
                status = 'download_failed'
            
            manifest.append({
                'set_id': set_id, 'card_id': card_id, 'local_id': local_id, 'name': name,
                'image_url': img_url, 'asset_url': img_url,
                'status': status, 'candidate_type': 'exact_ptcg_io_search',
                'language_code': 'en', 'local_path': str(path) if ok else '',
                'bytes': sz if ok else 0,
                'core_set_id': set_id, 'resolved_set_id': set_id,
                'source_set_id': set_id, 'source_card_id': card_id,
                'source_api_url': img_url,
            })
        else:
            not_found += 1
            manifest.append({
                'set_id': set_id, 'card_id': card_id, 'language_code': 'en', 'status': 'not_found',
            })
        
        if (i + 1) % 50 == 0:
            print(f'  Progress: {i+1}/{len(missing)} (found: {found}, not found: {not_found})')
        
        time.sleep(0.2)  # Rate limiting
    
    print(f'\nDone: {found} found, {not_found} not found')
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'en_search_recovery_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': manifest}, ensure_ascii=False, indent=2))
    print(f'Manifest: {mp}')

if __name__ == '__main__':
    main()
