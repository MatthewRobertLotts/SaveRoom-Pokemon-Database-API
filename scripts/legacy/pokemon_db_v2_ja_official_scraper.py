#!/usr/bin/env python3
"""Japanese card image scraper using web_extract (Firecrawl).

Scrapes card detail pages from the official Japanese Pokemon card site,
extracts image URLs, and downloads images.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
CANDIDATE_TYPE = 'exact_jp_official_scraped_asset'
UA = 'SaveRoomPokemonJaScraper/1.0'
JP_CARD_BASE = 'https://www.pokemon-card.com/card-search/details.php/card/'

MISSING_CARDS_FILE = Path('/tmp/ja_missing_cards.json')


def now_utc() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())


def stamp() -> str:
    return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())


def date_stamp() -> str:
    return time.strftime('%Y-%m-%d', time.gmtime())


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def load_missing_cards() -> dict[str, list[dict]]:
    """Load missing cards from file."""
    if MISSING_CARDS_FILE.exists():
        return json.loads(MISSING_CARDS_FILE.read_text())
    return {}


def get_missing_cards_from_db() -> dict[str, list[dict]]:
    """Get Japanese cards missing images from DB."""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cur.execute('''
        SELECT c.set_id, c.card_id, c.local_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.language_code='ja' AND s.has_display_image=0
        ORDER BY c.set_id, c.local_id_sort
    ''').fetchall()
    conn.close()
    
    by_set = {}
    for set_id, card_id, local_id, name in rows:
        if set_id not in by_set:
            by_set[set_id] = []
        by_set[set_id].append({'card_id': card_id, 'local_id': local_id, 'name': name})
    return by_set


def extract_image_from_content(content: str) -> dict[str, str] | None:
    """Extract card image URL from page content."""
    m = re.search(
        r'https://www\.pokemon-card\.com/assets/images/card_images/large/([^/]+)/([^"\'\s]+\.jpg)',
        content
    )
    if m:
        return {
            'series': m.group(1),
            'filename': m.group(2),
            'url': m.group(0),
        }
    return None


def extract_card_ids_from_search(content: str) -> list[str]:
    """Extract numeric card IDs from search results page."""
    return list(dict.fromkeys(re.findall(r'/card-search/details\.php/card/(\d+)/', content)))


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


def build_card_detail_urls_by_set(by_set: dict[str, list[dict]]) -> dict[str, str]:
    """
    Build a mapping of card_id -> detail page URL by scraping set listing pages.
    The Japanese site has set pages at https://www.pokemon-card.com/ex/<set_code>/
    or search pages that list all cards in a set.
    """
    card_url_map = {}
    
    for set_id in by_set.keys():
        # Try the set page
        set_url = f'https://www.pokemon-card.com/ex/{set_id.lower()}/'
        try:
            r = requests.get(set_url, timeout=15, headers={'User-Agent': UA})
            if r.status_code == 200:
                # Extract card detail URLs
                card_ids = extract_card_ids_from_search(r.text)
                if card_ids:
                    cards_in_set = by_set[set_id]
                    for i, card in enumerate(cards_in_set):
                        if i < len(card_ids):
                            card_url_map[card['card_id']] = f'{JP_CARD_BASE}{card_ids[i]}/regu/'
                        continue
        except requests.RequestException:
            pass
        
        # Try searching by set code in the search page
        search_url = f'https://www.pokemon-card.com/card-search/index.php?keyword=&se_ta={set_id}&regulation_sidebar_form=&pg=&illust=&sm_and_keyword=true'
        try:
            r = requests.get(search_url, timeout=15, headers={'User-Agent': UA})
            if r.status_code == 200:
                card_ids = extract_card_ids_from_search(r.text)
                if card_ids:
                    cards_in_set = by_set[set_id]
                    for i, card in enumerate(cards_in_set):
                        if i < len(card_ids):
                            card_url_map[card['card_id']] = f'{JP_CARD_BASE}{card_ids[i]}/regu/'
        except requests.RequestException:
            pass
    
    return card_url_map


def main():
    parser = argparse.ArgumentParser(description='Scrape Japanese card images from official site')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of cards to process')
    parser.add_argument('--download', action='store_true', help='Download images (otherwise just find URLs)')
    parser.add_argument('--save-map', action='store_true', help='Save card URL mapping')
    args = parser.parse_args()
    
    # Load missing cards
    by_set = load_missing_cards()
    if not by_set:
        by_set = get_missing_cards_from_db()
        MISSING_CARDS_FILE.write_text(json.dumps(by_set, ensure_ascii=False))
    
    total_cards = sum(len(c) for c in by_set.values())
    print(f'Japanese cards missing images: {total_cards} across {len(by_set)} sets')
    
    # Build card detail URL mapping
    print('Building card detail URL mapping from set pages...')
    card_url_map = build_card_detail_urls_by_set(by_set)
    print(f'Found {len(card_url_map)} card detail URLs')
    
    if args.save_map:
        map_path = REPORTS / f'ja_card_url_map_{stamp()}.json'
        REPORTS.mkdir(parents=True, exist_ok=True)
        map_path.write_text(json.dumps(card_url_map, ensure_ascii=False, indent=2))
        print(f'URL map saved to: {map_path}')
    
    if not args.download:
        print('Run with --download to download images')
        return
    
    # Download phase - would use web_extract for each card detail page
    # For now, output the URLs that need to be scraped
    print(f'\n{card_url_map} output ready for web_extract')


if __name__ == '__main__':
    main()
