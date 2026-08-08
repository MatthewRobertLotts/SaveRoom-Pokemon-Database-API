#!/usr/bin/env python3
"""Build set ID mapping from existing TCGdex image URLs and use it to recover European language images.

For each language, builds a mapping of DB set_id -> TCGdex series/set from existing images.
Then uses TCGdex set API to find and download images for missing cards.
"""
from __future__ import annotations

import json, re, sqlite3, time, hashlib
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonTcgdexSetAPI/1.0'

# TCGdex language codes for European languages
TCGDEX_LANG = {'en': 'en', 'fr': 'fr', 'de': 'de', 'it': 'it', 'es': 'es', 'pt': 'pt-br'}


def build_set_mapping(lang):
    """Build DB set_id -> (tcgdex_series, tcgdex_set) from existing image URLs."""
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT DISTINCT c.set_id, c.image_url
        FROM cards c
        WHERE c.language_code = ? AND c.image_url IS NOT NULL AND c.image_url != ''
        AND c.image_url LIKE '%tcgdex.net%'
    ''', (lang,)).fetchall()
    conn.close()
    
    mapping = {}
    tcgdex_code = TCGDEX_LANG.get(lang, lang)
    for set_id, url in rows:
        m = re.match(rf'https://assets\.tcgdex\.net/{tcgdex_code}/([^/]+)/([^/]+)/', url)
        if m:
            if set_id not in mapping:
                mapping[set_id] = (m.group(1), m.group(2))
    return mapping


def get_missing_cards(lang):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('''
        SELECT c.card_id, c.set_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code = ? AND s.has_display_image = 0
        ORDER BY c.set_id, c.local_id_sort
    ''', (lang,)).fetchall()
    conn.close()
    return [dict(zip(['card_id', 'set_id', 'local_id', 'name'], r)) for r in rows]


def get_tcgdex_set_cards(tcgdex_lang, series, set_id):
    """Get all cards from a TCGdex set."""
    url = f'https://api.tcgdex.net/v2/{tcgdex_lang}/sets/{set_id}'
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent': UA})
        if r.status_code != 200: return []
        data = r.json()
        return data.get('cards', [])
    except: return []


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
    all_manifest = []
    date_str = time.strftime('%Y-%m-%d')
    
    for lang in ['en', 'fr', 'de', 'it', 'es', 'pt']:
        tcgdex_lang = TCGDEX_LANG.get(lang, lang)
        print(f'\n{lang}:')
        
        # Build set mapping from existing images
        mapping = build_set_mapping(lang)
        print(f'  Set mapping: {len(mapping)} sets')
        
        # Get missing cards
        missing = get_missing_cards(lang)
        print(f'  Missing cards: {len(missing)}')
        
        # Group missing cards by set_id
        by_set = {}
        for card in missing:
            sid = card['set_id']
            if sid not in by_set: by_set[sid] = []
            by_set[sid].append(card)
        
        # For each set, try to get images from TCGdex
        for set_id, cards in by_set.items():
            if set_id not in mapping:
                # Try direct set_id
                series, tcgdex_set = 'tcgp', set_id
            else:
                series, tcgdex_set = mapping[set_id]
            
            # Get cards from TCGdex set
            tcgdex_cards = get_tcgdex_set_cards(tcgdex_lang, series, tcgdex_set)
            
            if not tcgdex_cards:
                # Try with different series prefixes
                for try_series in ['tcgp', 'base', 'xy', 'sm', 'bw', 'dp', 'ex', 'pop', 'ecard', 'swsh', 'sv']:
                    tcgdex_cards = get_tcgdex_set_cards(tcgdex_lang, try_series, set_id.lower())
                    if tcgdex_cards:
                        series = try_series
                        break
            
            if not tcgdex_cards:
                for c in cards:
                    all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': lang, 'status': 'tcgdex_set_not_found'})
                continue
            
            # Build local_id -> image_url map from TCGdex cards
            tcgdex_by_local = {}
            for tc in tcgdex_cards:
                lid = tc.get('localId', '')
                img = tc.get('image', '')
                if lid and img:
                    tcgdex_by_local[lid] = img
                    # Also try without leading zeros
                    tcgdex_by_local[lid.lstrip('0') or '0'] = img
            
            dl = 0
            for c in cards:
                local_id = c['local_id']
                img_url = tcgdex_by_local.get(local_id) or tcgdex_by_local.get(local_id.lstrip('0') or '0')
                
                if img_url:
                    path = IMAGE_ROOT / date_str / lang / set_id / f"{c['card_id']}.webp"
                    ok, sz = download_image(img_url, path)
                    if ok: dl += 1
                    all_manifest.append({
                        'set_id': set_id, 'card_id': c['card_id'], 'local_id': local_id, 'name': c['name'],
                        'image_url': img_url, 'status': 'downloaded' if ok else 'download_failed',
                        'candidate_type': 'exact_tcgdex_set_api_recovered', 'language_code': lang,
                        'local_path': str(path) if ok else '', 'bytes': sz if ok else 0,
                        'core_set_id': set_id, 'resolved_set_id': set_id, 'source_set_id': set_id, 'source_card_id': c['card_id'],
                        'source_api_url': f'https://api.tcgdex.net/v2/{tcgdex_lang}/sets/{set_id}',
                    })
                else:
                    all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': lang, 'status': 'card_not_in_tcgdex'})
            
            print(f'  {set_id}: {dl}/{len(cards)}')
            time.sleep(0.5)
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'european_tcgdex_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps(all_manifest, ensure_ascii=False, indent=2))
    dl = sum(1 for m in all_manifest if m.get('status') == 'downloaded')
    print(f'\nDone: {dl} downloaded, manifest: {mp}')

if __name__ == '__main__':
    main()
