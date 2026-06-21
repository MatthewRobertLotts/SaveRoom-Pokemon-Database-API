#!/usr/bin/env python3
"""Multi-language Asia site scraper - fixed version."""
from __future__ import annotations

import json, re, sqlite3, time, hashlib
from pathlib import Path
import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
UA = 'SaveRoomPokemonMultiLang/1.0'

def get_missing_sets(lang):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('SELECT DISTINCT s.core_set_id, COUNT(*) FROM v2_card_search s WHERE s.language_code=? AND s.has_display_image=0 GROUP BY s.core_set_id ORDER BY COUNT(*) DESC', (lang,)).fetchall()
    conn.close()
    return rows

def get_db_cards(lang, set_id):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows = cur.execute('SELECT c.card_id, c.local_id, c.name FROM cards c JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id WHERE c.language_code=? AND s.has_display_image=0 AND s.core_set_id=? ORDER BY c.local_id_sort', (lang, set_id)).fetchall()
    conn.close()
    return [{'card_id': r[0], 'local_id': r[1], 'name': r[2]} for r in rows]

def scrape_set(site_code, set_id, total):
    all_cards = []
    page = 1
    while len(all_cards) < total:
        url = f'https://asia.pokemon-card.com/{site_code}/card-search/list/?expansionCodes={set_id}&pageNo={page}'
        try:
            r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8'})
            if r.status_code != 200: break
            details = re.findall(rf'/{site_code}/card-search/detail/(\d+)/', r.text)
            imgs = re.findall(rf'/{site_code}/card-img/({site_code}\d+\.png)', r.text)
            if not details: break
            for did, img in zip(details, imgs):
                all_cards.append({'detail_id': did, 'image_url': f'https://asia.pokemon-card.com/{site_code}/card-img/{img}'})
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
    all_manifest = []
    date_str = time.strftime('%Y-%m-%d')
    
    for lang, site in [('zh-tw', 'tw'), ('th', 'th')]:
        sets = get_missing_sets(lang)
        print(f'\n{lang}: {len(sets)} sets, {sum(s[1] for s in sets)} missing')
        
        for set_id, count in sets:
            db_cards = get_db_cards(lang, set_id)
            print(f'  {set_id} ({count}):', end=' ', flush=True)
            scraped = scrape_set(site, set_id, count)
            
            if not scraped:
                print('not found')
                for c in db_cards:
                    all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': lang, 'status': 'not_found'})
                continue
            
            dl = 0
            for i, c in enumerate(db_cards):
                if i < len(scraped):
                    s = scraped[i]
                    path = IMAGE_ROOT / date_str / lang / set_id / f"{c['card_id']}.png"
                    ok, sz = download_image(s['image_url'], path)
                    if ok: dl += 1
                    all_manifest.append({
                        'set_id': set_id, 'card_id': c['card_id'], 'local_id': c['local_id'], 'name': c['name'],
                        'detail_id': s['detail_id'], 'image_url': s['image_url'],
                        'status': 'downloaded' if ok else 'download_failed',
                        'candidate_type': f'exact_asia_{site}_scraped', 'language_code': lang,
                        'local_path': str(path) if ok else '', 'bytes': sz if ok else 0,
                        'core_set_id': set_id, 'resolved_set_id': set_id, 'source_set_id': set_id, 'source_card_id': c['card_id'],
                        'source_api_url': f'https://asia.pokemon-card.com/{site}/card-search/detail/{s["detail_id"]}/',
                    })
                else:
                    all_manifest.append({'set_id': set_id, 'card_id': c['card_id'], 'language_code': lang, 'status': 'not_found'})
            
            print(f'{dl}/{len(db_cards)}')
            time.sleep(1)
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    mp = REPORTS / f'multi_lang_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    mp.write_text(json.dumps(all_manifest, ensure_ascii=False, indent=2))
    dl = sum(1 for m in all_manifest if m.get('status') == 'downloaded')
    print(f'\nDone: {dl} downloaded, manifest: {mp}')

if __name__ == '__main__':
    main()
