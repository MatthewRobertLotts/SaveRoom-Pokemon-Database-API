#!/usr/bin/env python3
"""Complete ZH-TW image recovery.

Phase 1: Use web_extract to scrape all search result pages for each set.
Phase 2: Extract image URLs and download them.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import hashlib
from pathlib import Path
from typing import Any

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
    
    # Phase 1: Build URL list for web_extract
    all_urls = []
    set_page_map = []  # (set_id, page_num, url)
    
    for set_id, count in sets:
        # Estimate pages (20 cards per page)
        num_pages = (count + 19) // 20
        for page in range(1, num_pages + 1):
            url = f'https://asia.pokemon-card.com/tw/card-search/list/?expansionCodes={set_id}&pageNo={page}'
            all_urls.append(url)
            set_page_map.append((set_id, page, url))
    
    print(f'Total URLs to scrape: {len(all_urls)}')
    
    # Phase 2: Scrape in batches using web_extract (simulated via requests since web_extract is a tool)
    # Since we can't call web_extract from Python, we'll use requests directly
    # The Asia site works with direct requests
    
    all_scraped = {}  # set_id -> list of (detail_id, image_url)
    
    for set_id, count in sets:
        print(f'\n{set_id} ({count}):', end=' ', flush=True)
        all_scraped[set_id] = []
        
        page = 1
        while True:
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
                    all_scraped[set_id].append({
                        'detail_id': detail_id,
                        'image_url': f'https://asia.pokemon-card.com/tw/card-img/{img}',
                    })
                
                print(f'p{page}({len(details)})', end=' ')
                
                if '下一頁' not in content and '下一页' not in content:
                    break
                
                page += 1
                time.sleep(0.5)
                
            except requests.RequestException as e:
                print(f'err:{e}', end=' ')
                time.sleep(5)
                continue
        
        print(f'total:{len(all_scraped[set_id])}')
        time.sleep(1)
    
    # Phase 3: Match and download
    print('\n\nDownloading images...')
    all_manifest = []
    total_downloaded = 0
    total_failed = 0
    
    for set_id, count in sets:
        db_cards = get_db_cards_for_set(set_id)
        scraped = all_scraped.get(set_id, [])
        
        date_str = time.strftime('%Y-%m-%d')
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
                    total_failed += 1
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
                    'local_id': db_card['local_id'],
                    'name': db_card['name'],
                    'status': 'not_found',
                })
        
        print(f'{set_id}: {downloaded}/{len(db_cards)}')
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    manifest_path = REPORTS / f'zh_tw_asia_scrape_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    manifest_path.write_text(json.dumps(all_manifest, ensure_ascii=False, indent=2))
    
    print(f'\n=== DONE ===')
    print(f'Downloaded: {total_downloaded}')
    print(f'Failed: {total_failed}')
    print(f'Manifest: {manifest_path}')


if __name__ == '__main__':
    main()
