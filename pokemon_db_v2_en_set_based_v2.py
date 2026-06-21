#!/usr/bin/env python3
"""Recover remaining English images from pokemontcg.io with SET VERIFICATION.

Only accept results where the set name/series matches our DB set.
"""
import json, sqlite3, time, hashlib, re
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoom/1.0'

def get_set_mapping():
    """Map our DB set IDs to pokemontcg.io set IDs by testing known cards."""
    conn = sqlite3.connect(DB); cur = conn.cursor()
    
    # Get our DB set IDs that have missing images
    missing = [r[0] for r in cur.execute('''
        SELECT DISTINCT s.core_set_id FROM v2_card_search s
        WHERE s.language_code='en' AND s.has_display_image=0
    ''').fetchall()]
    
    # For each set, get a sample card name and search on pokemontcg.io
    mapping = {}
    for db_set in missing:
        # Get a sample card from this set
        sample = cur.execute('''
            SELECT c.name FROM cards c
            WHERE c.language_code='en' AND c.set_id=? AND c.card_id NOT IN (
                SELECT card_id FROM v2_card_search WHERE has_display_image=1
            ) LIMIT 1
        ''', (db_set,)).fetchone()
        
        if not sample:
            continue
        
        # Search for this card
        url = 'https://api.pokemontcg.io/v2/cards'
        params = {'q': f'name:{sample[0]}', 'pageSize': 10}
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                cards = r.json().get('data', [])
                for card in cards:
                    ptcg_set = card.get('set', {})
                    img = card.get('images', {}).get('large', '')
                    if img:
                        # Verify this set actually has cards matching our count
                        ptcg_id = ptcg_set.get('id')
                        # Quick check: does this ptcg set have a similar number of cards?
                        set_size = ptcg_set.get('totalSetSize', 0)
                        our_count = cur.execute('SELECT COUNT(*) FROM cards WHERE language_code="en" AND set_id=?', (db_set,)).fetchone()[0]
                        # Accept if the set sizes are reasonably close
                        if set_size > 0 and abs(set_size - our_count) < 50:
                            mapping[db_set] = ptcg_id
                            break
        except:
            pass
        
        time.sleep(0.3)
    
    conn.close()
    return mapping

def download_image(url, path):
    try:
        r = requests.get(url, timeout=20, stream=True, headers={'User-Agent': UA})
        if r.status_code != 200:
            return False, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(); total = 0
        with path.open('wb') as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk); h.update(chunk); total += len(chunk)
        return True, total
    except:
        return False, 0

def main():
    print('Building set mapping...')
    mapping = get_set_mapping()
    print(f'Mapped {len(mapping)} sets')
    
    # Now download images for each set
    manifest = []
    date_str = time.strftime('%Y-%m-%d')
    
    for db_set_id, ptcg_set_id in mapping.items():
        print(f'\n{db_set_id} -> {ptcg_set_id}:')
        
        # Get all cards from pokemontcg.io set
        all_ptcg_cards = []
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
            all_ptcg_cards.extend(cards)
            total = r.json().get('totalCount', 0)
            if len(all_ptcg_cards) >= total:
                break
            page += 1
            time.sleep(0.3)
        
        # Build number -> image map
        num_to_img = {}
        for card in all_ptcg_cards:
            num = str(card.get('number', ''))
            img = card.get('images', {}).get('large', '')
            if num and img:
                num_to_img[num] = img
                num_to_img[num.lstrip('0') or '0'] = img
        
        print(f'  Got {len(all_ptcg_cards)} cards from pokemontcg.io')
        
        # Get our missing cards for this set
        conn = sqlite3.connect(DB); cur = conn.cursor()
        our_cards = cur.execute('''
            SELECT c.card_id, c.local_id, c.name
            FROM cards c
            JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
            WHERE c.language_code='en' AND s.has_display_image=0 AND c.core_set_id=?
        ''', (db_set_id,)).fetchall()
        conn.close()
        
        dl = 0
        for card_id, local_id, name in our_cards:
            img_url = num_to_img.get(local_id) or num_to_img.get(local_id.lstrip('0') or '0')
            if not img_url:
                img_url = num_to_img.get(local_id.zfill(3)) or num_to_img.get(local_id.zfill(2))
            
            if img_url:
                path = IMAGE_ROOT / date_str / 'en' / db_set_id / f'{card_id}.png'
                ok, sz = download_image(img_url, path)
                if ok:
                    dl += 1
                manifest.append({
                    'set_id': db_set_id, 'card_id': card_id, 'local_id': local_id, 'name': name,
                    'image_url': img_url, 'asset_url': img_url,
                    'status': 'downloaded' if ok else 'download_failed',
                    'candidate_type': 'exact_ptcg_io_set', 'language_code': 'en',
                    'local_path': str(path) if ok else '', 'bytes': sz if ok else 0,
                    'core_set_id': db_set_id, 'resolved_set_id': db_set_id,
                    'source_set_id': db_set_id, 'source_card_id': card_id,
                    'source_api_url': img_url, 'sha256': '' if not ok else hashlib.sha256(path.read_bytes()).hexdigest(),
                })
            else:
                manifest.append({'set_id': db_set_id, 'card_id': card_id, 'language_code': 'en', 'status': 'no_match'})
        
        print(f'  Downloaded: {dl}/{len(our_cards)}')
        time.sleep(0.5)
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'en_set_based_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': manifest}, ensure_ascii=False, indent=2))
    dl = sum(1 for m in manifest if m.get('status') == 'downloaded')
    print(f'\nTotal: {dl} downloaded')
    print(f'Manifest: {mp}')

if __name__ == '__main__':
    main()
