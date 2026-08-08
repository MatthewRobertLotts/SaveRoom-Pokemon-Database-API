#!/usr/bin/env python3
"""Recover English card images from pokemontcg.io using set-based search.

For each missing English set, get all cards from pokemontcg.io and match by number.
"""
from __future__ import annotations
import json, sqlite3, time, hashlib, re
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonEnSet/1.0'

def get_missing_sets():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT DISTINCT s.core_set_id, COUNT(*) as cnt
        FROM v2_card_search s
        WHERE s.language_code='en' AND s.has_display_image=0
        GROUP BY s.core_set_id ORDER BY COUNT(*) DESC
    ''').fetchall()
    conn.close()
    return rows

def find_ptcg_set_id(db_set_id):
    """Find the matching pokemontcg.io set ID for our DB set ID."""
    # Get all pokemontcg.io sets
    url = 'https://api.pokemontcg.io/v2/sets?pageSize=250'
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    
    ptcg_sets = {s['id']: s for s in r.json().get('data', [])}
    
    # Direct match
    if db_set_id in ptcg_sets:
        return db_set_id
    if db_set_id.lower() in ptcg_sets:
        return db_set_id.lower()
    
    # Try transformations
    cleaned = re.sub(r'[.\-]', '', db_set_id.lower())
    if cleaned in ptcg_sets:
        return cleaned
    
    # Try to match by set name
    # Get a sample card name from our DB
    conn = sqlite3.connect(DB); cur = conn.cursor()
    sample = cur.execute('''
        SELECT c.name FROM cards c 
        WHERE c.language_code='en' AND c.set_id=? 
        LIMIT 1
    ''', (db_set_id,)).fetchone()
    conn.close()
    
    if sample:
        # Search for this card on pokemontcg.io
        url = 'https://api.pokemontcg.io/v2/cards'
        params = {'q': f'name:{sample[0]}', 'pageSize': 5}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            cards = r.json().get('data', [])
            if cards:
                # Use the set ID from the first matching card
                return cards[0].get('set', {}).get('id')
    
    return None

def get_cards_from_ptcg_set(ptcg_set_id):
    """Get all cards from a pokemontcg.io set."""
    all_cards = []
    page = 1
    
    while True:
        url = 'https://api.pokemontcg.io/v2/cards'
        params = {'q': f'set.id:{ptcg_set_id}', 'pageSize': 250, 'page': page}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            break
        
        cards = r.json().get('data', [])
        if not cards:
            break
        
        all_cards.extend(cards)
        
        total = r.json().get('totalCount', 0)
        if len(all_cards) >= total:
            break
        
        page += 1
        time.sleep(0.3)
    
    return all_cards

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
    print('Getting missing English sets...')
    missing_sets = get_missing_sets()
    print(f'Missing sets: {len(missing_sets)}')
    
    # Build set ID mapping
    print('\nBuilding set ID mapping...')
    set_mapping = {}
    for db_set_id, count in missing_sets:
        ptcg_id = find_ptcg_set_id(db_set_id)
        if ptcg_id:
            set_mapping[db_set_id] = ptcg_id
            print(f'  {db_set_id:20s} -> {ptcg_id} ({count} cards)')
        else:
            print(f'  {db_set_id:20s}: NO MAPPING')
    
    print(f'\nMapped {len(set_mapping)}/{len(missing_sets)} sets')
    
    # Process each set
    manifest = []
    date_str = time.strftime('%Y-%m-%d')
    total_downloaded = 0
    total_matched = 0
    
    for db_set_id, ptcg_set_id in set_mapping.items():
        print(f'\nProcessing {db_set_id} -> {ptcg_set_id}...')
        
        # Get all cards from pokemontcg.io set
        ptcg_cards = get_cards_from_ptcg_set(ptcg_set_id)
        print(f'  Got {len(ptcg_cards)} cards from pokemontcg.io')
        
        # Build number -> image_url map
        ptcg_by_number = {}
        for card in ptcg_cards:
            num = str(card.get('number', ''))
            img = card.get('images', {}).get('large', '')
            if num and img:
                ptcg_by_number[num] = img
                # Also try without leading zeros
                ptcg_by_number[num.lstrip('0') or '0'] = img
        
        # Get missing cards from our DB
        conn = sqlite3.connect(DB); cur = conn.cursor()
        db_cards = cur.execute('''
            SELECT c.card_id, c.local_id, c.name
            FROM cards c
            JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
            WHERE c.language_code='en' AND s.has_display_image=0 AND s.core_set_id=?
        ''', (db_set_id,)).fetchall()
        conn.close()
        
        matched = 0
        for card_id, local_id, name in db_cards:
            img_url = ptcg_by_number.get(local_id) or ptcg_by_number.get(local_id.lstrip('0') or '0')
            
            if img_url:
                path = IMAGE_ROOT / date_str / 'en' / db_set_id / f"{card_id}.png"
                ok, sz = download_image(img_url, path)
                
                if ok:
                    matched += 1
                    total_downloaded += 1
                
                manifest.append({
                    'set_id': db_set_id, 'card_id': card_id, 'local_id': local_id, 'name': name,
                    'image_url': img_url, 'asset_url': img_url,
                    'status': 'downloaded' if ok else 'download_failed',
                    'candidate_type': 'exact_ptcg_io_set', 'language_code': 'en',
                    'local_path': str(path) if ok else '', 'bytes': sz if ok else 0,
                    'core_set_id': db_set_id, 'resolved_set_id': db_set_id,
                    'source_set_id': db_set_id, 'source_card_id': card_id,
                    'source_api_url': img_url,
                })
            else:
                manifest.append({
                    'set_id': db_set_id, 'card_id': card_id, 'language_code': 'en', 'status': 'no_match_in_set',
                })
        
        total_matched += matched
        print(f'  Matched: {matched}/{len(db_cards)}')
        time.sleep(1)
    
    print(f'\nTotal: {total_matched} matched, {total_downloaded} downloaded')
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'en_ptcg_set_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': manifest}, ensure_ascii=False, indent=2))
    print(f'Manifest: {mp}')

if __name__ == '__main__':
    main()
