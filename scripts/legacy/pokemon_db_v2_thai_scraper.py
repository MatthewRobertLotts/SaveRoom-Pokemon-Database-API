#!/usr/bin/env python3
"""Thai image scraper - remaining sets."""
from __future__ import annotations
import json, re, sqlite3, time, hashlib
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonThScraper/1.0'

COMPLETED = {'SCF', 'SCE', 'SC1a', 'SC1b', 'SC1D', 'S8b'}

def get_missing_sets():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('SELECT DISTINCT s.core_set_id, COUNT(*) FROM v2_card_search s WHERE s.language_code=\"th\" AND s.has_display_image=0 GROUP BY s.core_set_id ORDER BY COUNT(*) DESC').fetchall()
    conn.close()
    return [(s[0], s[1]) for s in rows if s[0] not in COMPLETED]

def get_db_cards(set_id):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('SELECT c.card_id, c.local_id, c.name FROM cards c JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id WHERE c.language_code=\"th\" AND s.has_display_image=0 AND s.core_set_id=? ORDER BY c.local_id_sort', (set_id,)).fetchall()
    conn.close()
    return [{'card_id': r[0], 'local_id': r[1], 'name': r[2]} for r in rows]

def scrape_set(set_id, total):
    all_cards = []
    page = 1
    while len(all_cards) < total:
        url = f'https://asia.pokemon-card.com/th/card-search/list/?expansionCodes={set_id}&pageNo={page}'
        try:
            r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'th,en;q=0.8'})
            if r.status_code != 200: break
            details = re.findall(r'/th/card-search/detail/(\d+)/', r.text)
            imgs = re.findall(r'/th/card-img/([^\"\'\s]+\.png)', r.text)
            if not details: break
            for did, img in zip(details, imgs):
                all_cards.append({'detail_id': did, 'image_url': f'https://asia.pokemon-card.com/th/card-img/{img}'})
            if len(details) < 20: break
            page += 1
            time.sleep(0.3)
        except: time.sleep(5); continue
    return all_cards

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
    sets = get_missing_sets()
    print(f'Thai remaining: {len(sets)} sets, {sum(s[1] for s in sets)} missing')
    
    all_manifest = []
    date_str = time.strftime('%Y-%m-%d')
    
    for set_id, count in sets:
        db_cards = get_db_cards(set_id)
        print(f'{set_id} ({count}):', end=' ', flush=True)
        scraped = scrape_set(set_id, count)
        
        if not scraped:
            print('not found')
            for c in db_cards:
                all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': 'th', 'status': 'not_found'})
            continue
        
        dl = 0
        for i, c in enumerate(db_cards):
            if i < len(scraped):
                s = scraped[i]
                path = IMAGE_ROOT / date_str / 'th' / set_id / f"{c['card_id']}.png"
                ok, sz = download_image(s['image_url'], path)
                if ok: dl += 1
                all_manifest.append({
                    'set_id': set_id, 'card_id': c['card_id'], 'local_id': c['local_id'], 'name': c['name'],
                    'detail_id': s['detail_id'], 'image_url': s['image_url'], 'asset_url': s['image_url'],
                    'status': 'downloaded' if ok else 'download_failed',
                    'candidate_type': 'exact_asia_th_scraped_asset', 'language_code': 'th',
                    'local_path': str(path) if ok else '', 'bytes': sz if ok else 0,
                    'core_set_id': set_id, 'resolved_set_id': set_id, 'source_set_id': set_id, 'source_card_id': c['card_id'],
                    'source_api_url': f'https://asia.pokemon-card.com/th/card-search/detail/{s["detail_id"]}/',
                })
            else:
                all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': 'th', 'status': 'not_found'})
        
        print(f'{dl}/{len(db_cards)}')
        time.sleep(1)
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'thai_remaining_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps({'manifest': all_manifest, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ')}, ensure_ascii=False, indent=2))
    dl = sum(1 for m in all_manifest if m.get('status') == 'downloaded')
    print(f'\nDone: {dl} downloaded')

if __name__ == '__main__':
    main()
