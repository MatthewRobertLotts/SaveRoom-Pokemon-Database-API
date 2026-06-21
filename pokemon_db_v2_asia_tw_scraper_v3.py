#!/usr/bin/env python3
"""Complete ZH-TW image recovery - v3.

Scrapes ALL pages for each ZH-TW set from Asia Pokemon card site.
Downloads images and maps to DB card_ids.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import hashlib
from pathlib import Path

import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
CANDIDATE_TYPE = 'exact_asia_tw_scraped_asset'
UA = 'SaveRoomPokemonZhTwScraper/1.0'


def get_zh_tw_sets() -> list[tuple[str, int]]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cur.execute('''
        SELECT DISTINCT s.core_set_id, COUNT(*) as missing
        FROM v2_card_search s
        WHERE s.language_code='zh-tw' AND s.has_display_image=0
        GROUP BY s.core_set_id
        ORDER BY missing DESC
    ''').fetchall()
    conn.close()
    return rows


def get_db_cards_for_set(set_id: str) -> list[dict]:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cur.execute('''
        SELECT c.card_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code='zh-tw' AND s.has_display_image=0 AND s.core_set_id=?
        ORDER BY c.local_id_sort
    ''', (set_id,)).fetchall()
    conn.close()
    return [{'card_id': r[0], 'local_id': r[1], 'name': r[2]} for r in rows]


def scrape_set_pages(set_id: str, total_cards: int) -> list[dict]:
    """Scrape ALL pages for a set. Returns list of {detail_id, image_url}."""
    all_cards = []
    page = 1
    
    while len(all_cards) < total_cards:
        url = f'https://asia.pokemon-card.com/tw/card-search/list/?expansionCodes={set_id}&pageNo={page}'
        
        try:
            r = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
            })
            
            if r.status_code != 200:
                break
            
            content = r.text
            details = re.findall(r'/tw/card-search/detail/(\d+)/', content)
            imgs = re.findall(r'/tw/card-img/(tw\d+\.png)', content)
            
            if not details:
                break
            
            for detail_id, img in zip(details, imgs):
                all_cards.append({
                    'detail_id': detail_id,
                    'image_url': f'https://asia.pokemon-card.com/tw/card-img/{img}',
                })
            
            # Always continue to next page if we got 20 cards (full page)
            if len(details) < 20:
                break
            
            page += 1
            time.sleep(0.3)
            
        except requests.RequestException:
            time.sleep(5)
            continue
    
    return all_cards


def download_image(url: str, path: Path) -> tuple[bool, int]:
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
    sets = get_zh_tw_sets()
    print(f'ZH-TW sets: {len(sets)}, total missing: {sum(s[1] for s in sets)}')
    
    all_manifest = []
    total_downloaded = 0
    total_not_found = 0
    date_str = time.strftime('%Y-%m-%d')
    
    for set_id, count in sets:
        db_cards = get_db_cards_for_set(set_id)
        print(f'{set_id} ({count}): scraping...', end=' ', flush=True)
        
        scraped = scrape_set_pages(set_id, count)
        print(f'found {len(scraped)}', end=' ')
        
        if not scraped:
            # Set not available on TW site
            for db_card in db_cards:
                all_manifest.append({
                    'set_id': set_id,
                    'card_id': db_card['card_id'],
                    'status': 'set_not_on_tw_site',
                })
                total_not_found += 1
            print()
            continue
        
        # Download images
        downloaded = 0
        for i, db_card in enumerate(db_cards):
            if i < len(scraped):
                s = scraped[i]
                img_path = IMAGE_ROOT / date_str / 'zh-tw' / set_id / f"{db_card['card_id']}.png"
                ok, size = download_image(s['image_url'], img_path)
                
                if ok:
                    downloaded += 1
                    total_downloaded += 1
                    status = 'downloaded'
                else:
                    status = 'download_failed'
                
                all_manifest.append({
                    'set_id': set_id,
                    'card_id': db_card['card_id'],
                    'local_id': db_card['local_id'],
                    'name': db_card['name'],
                    'detail_id': s['detail_id'],
                    'image_url': s['image_url'],
                    'status': status,
                    'bytes': size,
                    'candidate_type': CANDIDATE_TYPE,
                })
            else:
                all_manifest.append({
                    'set_id': set_id,
                    'card_id': db_card['card_id'],
                    'status': 'not_found_in_search',
                })
                total_not_found += 1
        
        print(f'dl:{downloaded}/{len(db_cards)}')
        time.sleep(1)
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    manifest_path = REPORTS / f'zh_tw_asia_scrape_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    manifest_path.write_text(json.dumps(all_manifest, ensure_ascii=False, indent=2))
    
    print(f'\n=== DONE ===')
    print(f'Downloaded: {total_downloaded}')
    print(f'Not found: {total_not_found}')
    print(f'Manifest: {manifest_path}')


if __name__ == '__main__':
    main()
