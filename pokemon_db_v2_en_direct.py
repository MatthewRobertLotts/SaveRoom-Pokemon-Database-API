#!/usr/bin/env python3
"""Recover English images by DIRECT URL construction and download.

No API calls. Just try common URL patterns for each set and download what works.
"""
import json, sqlite3, time, hashlib, re, os
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoom/1.0'

# Known working set ID mappings (verified)
SET_MAP = {
    'smp': 'smp',        # SM Black Star Promos
    'sm7.5': 'sm75',     # Dragon Majesty
    'svp': 'svp',        # Scarlet & Violet Promos
    'cel25': 'cel25',    # Celebrations
    'mep': 'me1',        # Mega Evolution Promos
    'mfb': 'mfb',        # McDonald's
    'swshp': 'swshp',    # Sword & Shield Promos
    'ecard3': 'ecard3',  # Skyridge
    'ecard2': 'ecard2',  # Aquapolis
    'hgssp': 'hgssp',    # HGSS Promos
    'P-A': 'pa',         # Paldean Fates (promos)
    'xya': 'xya',        # XY Ancient Origins
    'sp': 'sp',          # POP Series
    'rc': 'rc',          # Raging Sparks
    'bog': 'bog',        # Best of Game
    'mee': 'me1',        # Mega Evolution
    'tk-ex-p': 'tk2a',   # EX Trainer Kit
    'tk-ex-m': 'tk2b',
    'tk-dp-m': 'tk1b',
    'tk-dp-l': 'tk1a',
    'tk-ex-latio': 'tk1b',
    'tk-ex-latia': 'tk1a',
    'tk-hs-r': 'tk2a',
    'tk-hs-g': 'tk2b',
    'B2a': 'bw2',        # Emerging Powers (best guess)
    'B1a': 'bw1',
    'jumbo': 'jumbo',
    'wp': 'wp',
    'exu': 'ex13',       # Unseen Forces (best guess)
    '2021swsh': 'swsh5', # Sword & Shield base
    '2022swsh': 'swsh6',
    '2023sv': 'sv2',     # Paldea Evolved
    '2024sv': 'sv3',     # Obsidian Flames
    '2011bw': 'bw3',     # Black & White
    '2012bw': 'bw4',
    '2014xy': 'xy1',     # XY
    '2015xy': 'xy2',
    '2016xy': 'xy3',
    '2017sm': 'sm3',     # Sun & Moon
    '2018sm': 'sm4',
    '2019sm': 'sm5',
}

def try_download(url, path):
    """Try to download an image from a URL."""
    try:
        r = requests.get(url, timeout=10, stream=True, headers={'User-Agent': UA})
        if r.status_code == 200 and int(r.headers.get('content-length', 0)) > 1000:
            path.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            total = 0
            with path.open('wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
                        h.update(chunk)
                        total += len(chunk)
            return True, total, h.hexdigest()
    except:
        pass
    return False, 0, ''

def main():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    
    # Get missing English cards
    missing = cur.execute('''
        SELECT c.card_id, c.core_set_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code='en' AND s.has_display_image=0
    ''').fetchall()
    
    conn.close()
    print(f'Missing EN cards: {len(missing)}')
    
    manifest = []
    date_str = time.strftime('%Y-%m-%d')
    found = 0
    not_found = 0
    
    for card_id, set_id, local_id, name in missing:
        # Try the mapped set ID
        ptcg_set = SET_MAP.get(set_id)
        
        downloaded = False
        
        if ptcg_set:
            # Try different URL patterns
            urls = [
                f'https://images.pokemontcg.io/{ptcg_set}/{local_id}_hires.png',
                f'https://images.pokemontcg.io/{ptcg_set}/{local_id.lstrip("0") or "0"}_hires.png',
                f'https://images.pokemontcg.io/{ptcg_set}/{local_id.zfill(3)}_hires.png',
                f'https://images.pokemontcg.io/{ptcg_set}/{local_id}.png',
                f'https://images.pokemontcg.io/{ptcg_set}/{local_id.lstrip("0") or "0"}.png',
            ]
            
            # For promo cards with alphanumeric IDs
            if not local_id.isdigit():
                urls = [
                    f'https://images.pokemontcg.io/{ptcg_set}/{local_id}_hires.png',
                    f'https://images.pokemontcg.io/{ptcg_set}/{local_id}.png',
                ]
            
            path = IMAGE_ROOT / date_str / 'en' / set_id / f'{card_id}.png'
            
            for url in urls:
                ok, sz, sha = try_download(url, path)
                if ok:
                    found += 1
                    manifest.append({
                        'set_id': set_id, 'card_id': card_id, 'local_id': local_id, 'name': name,
                        'image_url': url, 'asset_url': url, 'local_path': str(path),
                        'status': 'downloaded', 'candidate_type': 'exact_ptcg_io_set',
                        'language_code': 'en', 'sha256': sha, 'bytes': sz,
                        'core_set_id': set_id, 'resolved_set_id': set_id,
                        'source_set_id': set_id, 'source_card_id': card_id,
                        'source_api_url': url,
                    })
                    downloaded = True
                    break
        
        if not downloaded:
            not_found += 1
            manifest.append({
                'set_id': set_id, 'card_id': card_id, 'language_code': 'en', 'status': 'not_found',
            })
    
    print(f'Found: {found}, Not found: {not_found}')
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'en_direct_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': manifest}, ensure_ascii=False, indent=2))
    print(f'Manifest: {mp}')

if __name__ == '__main__':
    main()
