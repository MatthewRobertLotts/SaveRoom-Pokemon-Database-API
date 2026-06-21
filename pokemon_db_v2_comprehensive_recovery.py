#!/usr/bin/env python3
"""Comprehensive image recovery using TCGdex set API.

For each language, gets allcards from TCGdex set endpoints,
matches to DB cards missing images, downloads images.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
CANDIDATE_TYPE = 'exact_tcgdex_comprehensive_recovery'
UA = 'SaveRoomPokemonComprehensiveRecovery/1.0 (+manifest-first)'

# Map DB language codes to TCGdex language codes
LANG_MAP = {
    'en': 'en', 'fr': 'fr', 'de': 'de', 'it': 'it', 'es': 'es',
    'pt': 'pt-br', 'pt-br': 'pt-br', 'ja': 'ja', 'ko': 'ko',
    'zh-tw': 'zh-tw', 'zh-cn': 'zh-cn', 'th': 'th', 'id': 'id',
    'es-mx': 'es',
}


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def get_tcgdex_set_cards(tcgdex_lang: str, set_id: str) -> list[dict[str, Any]]:
    """Get all cards from a TCGdex set endpoint."""
    url = f'https://api.tcgdex.net/v2/{tcgdex_lang}/sets/{set_id}'
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent': UA})
        if r.status_code == 200:
            data = r.json()
            return data.get('cards', [])
    except requests.RequestException:
        pass
    return []


def download_image(url: str, path: Path) -> tuple[bool, str | None, int, str | None, int | None]:
    """Download an image, appending /high.webp if needed."""
    try:
        download_url = url
        if not download_url.endswith(('/high.webp', '/low.webp', '.webp', '.png', '.jpg', '.jpeg')):
            download_url = download_url.rstrip('/') + '/high.webp'
        r = requests.get(download_url, timeout=20, stream=True, headers={'User-Agent': UA})
        ctype = r.headers.get('content-type')
        if r.status_code != 200 or not (ctype and ctype.startswith('image/')):
            return False, None, 0, ctype, r.status_code
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        total = 0
        with path.open('wb') as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
                    total += len(chunk)
        return True, h.hexdigest(), total, ctype, r.status_code
    except requests.RequestException:
        return False, None, 0, None, None


def get_local_id_key(value: str) -> str:
    """Normalize local ID for matching (strip leading zeros)."""
    if not value:
        return ''
    v = str(value).strip()
    try:
        return str(int(v))
    except ValueError:
        return v.lower()


def gather(args: argparse.Namespace) -> dict[str, Any]:
    db = Path(args.db)
    tcgdex_lang = LANG_MAP.get(args.language, args.language)
    
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get all missing cards for this language
    missing_rows = cur.execute('''
        SELECT c.card_id, c.local_id, c.set_id, c.name
        FROM cards c
        JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=s.card_id
        WHERE c.language_code = ? AND s.has_display_image = 0
    ''', (args.language,)).fetchall()
    
    # Group by set_id
    by_set: dict[str, list[dict]] = {}
    for row in missing_rows:
        set_id = row['set_id']
        if set_id not in by_set:
            by_set[set_id] = []
        by_set[set_id].append(dict(row))
    
    # Build local_id key map for matching
    db_by_set_key: dict[str, dict[str, dict]] = {}
    for set_id, cards in by_set.items():
        for card in cards:
            key = f'{set_id}:{get_local_id_key(card["local_id"])}'
            db_by_set_key[key] = card
    
    conn.close()
    
    # Get all TCGdex sets for this language
    print(f'Fetching TCGdex sets for {args.language} ({tcgdex_lang})...', file=sys.stderr)
    sets_url = f'https://api.tcgdex.net/v2/{tcgdex_lang}/sets'
    try:
        r = requests.get(sets_url, timeout=30, headers={'User-Agent': UA})
        tcgdex_sets = r.json() if r.status_code == 200 else []
    except:
        tcgdex_sets = []
    
    print(f'TCGdex sets: {len(tcgdex_sets)}', file=sys.stderr)
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    
    manifest = []
    downloaded = 0
    set_not_matched = 0
    card_not_matched = 0
    
    # For each TCGdex set, get cards and match to DB
    for i, tcgdex_set in enumerate(tcgdex_sets):
        tcgdex_set_id = tcgdex_set['id']
        
        # Check if any DB missing cards are in this set
        # Try matching by set_id directly, then by local_id patterns
        matching_db_cards = []
        for set_id, cards in by_set.items():
            if set_id.lower() == tcgdex_set_id.lower():
                matching_db_cards = cards
                break
        
        if not matching_db_cards:
            # Try fuzzy matching: check if the TCGdex set ID contains the DB set ID or vice versa
            for set_id, cards in by_set.items():
                if (set_id.lower() in tcgdex_set_id.lower() or 
                    tcgdex_set_id.lower() in set_id.lower()):
                    matching_db_cards = cards
                    break
        
        if not matching_db_cards:
            set_not_matched += 1
            continue
        
        # Get TCGdex cards for this set
        tcgdex_cards = get_tcgdex_set_cards(tcgdex_lang, tcgdex_set_id)
        if not tcgdex_cards:
            continue
        
        # Build TCGdex card map by local_id
        tcgdex_by_local = {}
        for tc in tcgdex_cards:
            local_key = get_local_id_key(tc.get('localId', ''))
            if local_key:
                tcgdex_by_local[local_key] = tc
        
        # Match DB cards to TCGdex cards
        for db_card in matching_db_cards:
            local_key = get_local_id_key(db_card['local_id'])
            tc_card = tcgdex_by_local.get(local_key)
            
            entry = {
                'language_code': args.language,
                'card_id': db_card['card_id'],
                'core_set_id': db_card['set_id'],
                'local_id': db_card['local_id'],
                'card_name': db_card['name'],
                'attempted_at': now_utc(),
                'candidate_type': CANDIDATE_TYPE,
                'source_name': 'tcgdex_comprehensive_set_api',
                'tcgdex_set_id': tcgdex_set_id,
            }
            
            if not tc_card:
                entry['status'] = 'card_not_in_tcgdex_set'
                card_not_matched += 1
                manifest.append(entry)
                continue
            
            image_url = tc_card.get('image', '')
            if not image_url:
                entry['status'] = 'tcgdex_card_has_no_image'
                entry['tcgdex_card_name'] = tc_card.get('name')
                manifest.append(entry)
                continue
            
            if args.dry_run:
                entry['status'] = 'verified_not_downloaded_dry_run'
                entry['asset_url'] = image_url
                downloaded += 1
                manifest.append(entry)
                continue
            
            # Download image
            img_dir = IMAGE_ROOT / safe_name(args.language) / safe_name(tcgdex_set_id)
            img_path = img_dir / f"{safe_name(db_card['card_id'])}.webp"
            
            dl_ok, sha, size, dl_ctype, dl_status = download_image(image_url, img_path)
            
            if dl_ok:
                downloaded += 1
                entry.update({
                    'status': 'downloaded',
                    'local_path': str(img_path),
                    'sha256': sha,
                    'bytes': size,
                    'download_http_status': dl_status,
                    'download_content_type': dl_ctype,
                    'verification_method': 'tcgdex_set_api_and_image_http_verified',
                })
            else:
                entry.update({
                    'status': 'download_failed',
                    'download_http_status': dl_status,
                    'download_content_type': dl_ctype,
                })
            
            manifest.append(entry)
        
        if (i + 1) % 20 == 0:
            print(f'  Processed {i+1}/{len(tcgdex_sets)} sets, {downloaded} downloaded', file=sys.stderr)
    
    # Write manifest
    status_counts = {}
    for m in manifest:
        status_counts[m['status']] = status_counts.get(m['status'], 0) + 1
    
    run_stamp = stamp()
    manifest_json = REPORTS / f'v2_comprehensive_recovery_{args.language}_{run_stamp}.json'
    
    payload = {
        'generated_at': now_utc(),
        'language': args.language,
        'tcgdex_lang': tcgdex_lang,
        'mode': 'dry_run' if args.dry_run else 'download',
        'tcgdex_sets_checked': len(tcgdex_sets),
        'downloaded': downloaded,
        'set_not_matched': set_not_matched,
        'card_not_matched': card_not_matched,
        'status_counts': status_counts,
        'artifacts': {'manifest_json': str(manifest_json)},
    }
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Comprehensive image recovery via TCGdex set API.')
    p.add_argument('--language', required=True, help='DB language code')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--db', default=str(DB))
    args = p.parse_args(argv)
    result = gather(args)
    print(json.dumps({k: result[k] for k in ['generated_at', 'language', 'mode', 'tcgdex_sets_checked', 'downloaded', 'set_not_matched', 'card_not_matched', 'status_counts', 'artifacts']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
