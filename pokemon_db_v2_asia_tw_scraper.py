#!/usr/bin/env python3
"""Bulk ZH-TW image scraper using web_extract.

Scrapes search result pages from Asia Pokemon card site for Traditional Chinese,
extracts image URLs, and downloads images.
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

ASIA_BASE = 'https://asia.pokemon-card.com/tw/card-search/list/'
ASIA_IMG_BASE = 'https://asia.pokemon-card.com/tw/card-img/'


def get_zh_tw_sets() -> list[tuple[str, int]]:
    """Get ZH-TW sets with missing images."""
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
    """Get DB cards for a ZH-TW set."""
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


def scrape_page(url: str) -> tuple[list[dict], bool]:
    """Scrape a search results page. Returns (cards, has_next_page)."""
    try:
        r = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
        })
        if r.status_code != 200:
            return [], False
        
        content = r.text
        
        # Extract image URLs and detail URLs
        imgs = re.findall(r'https://asia\.pokemon-card\.com/tw/card-img/(tw\d+\.png)', content)
        details = re.findall(r'https://asia\.pokemon-card\.com/tw/card-search/detail/(\d+)/', content)
        
        cards = []
        for img, detail in zip(imgs, details):
            cards.append({
                'numeric_id': detail,
                'image_url': f'{ASIA_IMG_BASE}{img}',
            })
        
        # Check for next page
        has_next = '下一頁' in content or '下一页' in content
        
        return cards, has_next
    except requests.RequestException:
        return [], False


def download_image(url: str, path: Path) -> tuple[bool, str | None, int]:
    try:
        r = requests.get(url, timeout=20, stream=True, headers={'User-Agent': UA})
        if r.status_code != 200:
            return False, None, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        total = 0
        with path.open('wb') as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
                    total += len(chunk)
        return True, h.hexdigest(), total
    except requests.RequestException:
        return False, None, 0


def process_set(set_id: str, db_cards: list[dict]) -> list[dict]:
    """Process a single ZH-TW set."""
    manifest = []
    
    # Scrape all pages
    all_scraped = []
    page = 1
    while True:
        url = f'{ASIA_BASE}?expansionCodes={set_id}&pageNo={page}'
        cards, has_next = scrape_page(url)
        
        if not cards:
            break
        
        all_scraped.extend(cards)
        page += 1
        
        if not has_next:
            break
        
        time.sleep(1)
    
    # Match scraped cards to DB cards by position
    for i, db_card in enumerate(db_cards):
        if i < len(all_scraped):
            scraped = all_scraped[i]
            
            date_str = time.strftime('%Y-%m-%d')
            img_path = IMAGE_ROOT / date_str / 'zh-tw' / set_id / f"{db_card['card_id']}.png"
            ok, sha, size = download_image(scraped['image_url'], img_path)
            
            manifest.append({
                'set_id': set_id,
                'card_id': db_card['card_id'],
                'local_id': db_card['local_id'],
                'name': db_card['name'],
                'numeric_id': scraped['numeric_id'],
                'image_url': scraped['image_url'],
                'status': 'downloaded' if ok else 'download_failed',
                'sha256': sha,
                'bytes': size,
                'candidate_type': CANDIDATE_TYPE,
            })
        else:
            manifest.append({
                'set_id': set_id,
                'card_id': db_card['card_id'],
                'local_id': db_card['local_id'],
                'name': db_card['name'],
                'status': 'not_found_in_search',
            })
    
    return manifest


def main():
    sets = get_zh_tw_sets()
    print(f'ZH-TW sets to process: {len(sets)}')
    print(f'Total missing: {sum(s[1] for s in sets)}')
    
    all_manifest = []
    total_downloaded = 0
    
    for set_id, count in sets:
        print(f'\n{set_id} ({count} cards)...', end=' ', flush=True)
        
        db_cards = get_db_cards_for_set(set_id)
        manifest = process_set(set_id, db_cards)
        
        downloaded = sum(1 for m in manifest if m.get('status') == 'downloaded')
        total_downloaded += downloaded
        print(f'found {len([m for m in manifest if "image_url" in m])}, downloaded {downloaded}')
        
        all_manifest.extend(manifest)
        time.sleep(2)
    
    # Save manifest
    REPORTS.mkdir(parents=True, exist_ok=True)
    manifest_path = REPORTS / f'zh_tw_asia_scrape_{time.strftime("%Y%m%dT%H%M%SZ")}.json'
    manifest_path.write_text(json.dumps(all_manifest, ensure_ascii=False, indent=2))
    
    print(f'\n=== DONE ===')
    print(f'Total downloaded: {total_downloaded}')
    print(f'Manifest: {manifest_path}')


if __name__ == '__main__':
    main()
