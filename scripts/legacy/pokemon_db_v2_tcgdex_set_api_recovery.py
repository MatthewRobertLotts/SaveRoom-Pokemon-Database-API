#!/usr/bin/env python3
"""Bulk image recovery from TCGdex set API for all languages.

Uses the TCGdex set endpoint which returns all cards with image URLs.
Matches to DB cards missing images, downloads, writes manifest.
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
CANDIDATE_TYPE = 'exact_tcgdex_set_api_recovered_asset'
UA = 'SaveRoomPokemonBulkRecovery/1.0 (+manifest-first)'

# Map DB language codes to TCGdex language codes
LANG_MAP = {
    'en': 'en', 'fr': 'fr', 'de': 'de', 'it': 'it', 'es': 'es',
    'pt': 'pt-br', 'pt-br': 'pt-br', 'ja': 'ja', 'ko': 'ko',
    'zh-tw': 'zh-tw', 'zh-cn': 'zh-cn', 'th': 'th', 'id': 'id',
    'es-mx': 'es',  # Mexican Spanish uses ES TCGdex
}


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def get_db_set_mapping(db: Path, languages: list[str]) -> dict[str, dict[str, str]]:
    """Get mapping of DB set_id -> TCGdex set_id from existing image URLs."""
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    mapping = {}
    for lang in languages:
        rows = cur.execute('''
            SELECT DISTINCT c.set_id, c.image_url
            FROM cards c
            WHERE c.language_code = ?
              AND c.image_url IS NOT NULL AND c.image_url != ''
        ''', (lang,)).fetchall()
        for set_id, url in rows:
            # Extract TCGdex set from URL
            m = re.match(r'https://assets\.tcgdex\.net/[^/]+/([^/]+)/([^/]+)/', url)
            if m:
                tcgdex_series, tcgdex_set = m.group(1), m.group(2)
                key = f'{lang}:{set_id}'
                mapping[key] = {'series': tcgdex_series, 'set': tcgdex_set}
    conn.close()
    return mapping


def get_tcgdex_set_cards(tcgdex_lang: str, set_id: str) -> list[dict[str, Any]]:
    """Get all cards from a TCGdex set."""
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
    try:
        r = requests.get(url, timeout=20, stream=True, headers={'User-Agent': UA})
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


def gather(args: argparse.Namespace) -> dict[str, Any]:
    db = Path(args.db)
    languages = args.languages.split(',') if args.languages else list(LANG_MAP.keys())
    
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get all missing image cards by set
    lang_placeholders = ','.join('?' for _ in languages)
    rows = cur.execute(f'''
        SELECT s.language_code, s.card_id, s.core_set_id, s.local_id, s.card_name
        FROM v2_card_search s
        WHERE s.language_code IN ({lang_placeholders})
          AND s.has_display_image = 0
        ORDER BY s.language_code, s.core_set_id, s.local_id_sort
    ''', languages).fetchall()
    
    # Group by language -> set_id
    by_lang_set: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in rows:
        lang = r['language_code']
        set_id = r['core_set_id']
        if lang not in by_lang_set:
            by_lang_set[lang] = {}
        if set_id not in by_lang_set[lang]:
            by_lang_set[lang][set_id] = []
        by_lang_set[lang][set_id].append(dict(r))
    
    conn.close()
    
    # Get existing set mapping
    set_mapping = get_db_set_mapping(db, languages)
    
    REPORTS.mkdir(parents=True, exist_ok=True)
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    
    manifest: list[dict[str, Any]] = []
    downloaded = attempted = 0
    set_not_found = card_not_found = 0
    
    for lang, sets in by_lang_set.items():
        tcgdex_lang = LANG_MAP.get(lang, lang)
        for set_id, db_cards in sets.items():
            # Try to find TCGdex set ID
            mapping_key = f'{lang}:{set_id}'
            tcgdex_info = set_mapping.get(mapping_key)
            
            if tcgdex_info:
                tcgdex_set_id = tcgdex_info['set']
            else:
                # Try the DB set_id directly as TCGdex set_id
                tcgdex_set_id = set_id
            
            # Get cards from TCGdex
            tcgdex_cards = get_tcgdex_set_cards(tcgdex_lang, tcgdex_set_id)
            
            if not tcgdex_cards:
                # Try lowercase
                tcgdex_cards = get_tcgdex_set_cards(tcgdex_lang, tcgdex_set_id.lower())
            
            if not tcgdex_cards:
                # Try uppercase
                tcgdex_cards = get_tcgdex_set_cards(tcgdex_lang, tcgdex_set_id.upper())
            
            if not tcgdex_cards:
                set_not_found += 1
                for card in db_cards:
                    manifest.append({
                        'language_code': lang, 'card_id': card['card_id'],
                        'core_set_id': set_id, 'local_id': card['local_id'],
                        'card_name': card['card_name'],
                        'status': 'tcgdex_set_not_found',
                        'candidate_type': CANDIDATE_TYPE,
                        'source_name': 'tcgdex_set_api',
                        'attempted_at': now_utc(),
                    })
                continue
            
            # Build map of local_id -> TCGdex card
            tcgdex_by_local: dict[str, dict[str, Any]] = {}
            for tc in tcgdex_cards:
                local_id = tc.get('localId', '')
                if local_id:
                    tcgdex_by_local[local_id] = tc
            
            # Match DB cards to TCGdex cards
            for card in db_cards:
                attempted += 1
                entry = {
                    'language_code': lang, 'card_id': card['card_id'],
                    'core_set_id': set_id, 'local_id': card['local_id'],
                    'card_name': card['card_name'],
                    'attempted_at': now_utc(),
                    'candidate_type': CANDIDATE_TYPE,
                    'source_name': 'tcgdex_set_api',
                    'tcgdex_set_id': tcgdex_set_id,
                }
                
                local_id = card['local_id']
                tc_card = tcgdex_by_local.get(local_id)
                
                if not tc_card:
                    entry['status'] = 'card_not_in_tcgdex_set'
                    card_not_found += 1
                    manifest.append(entry)
                    continue
                
                image_url = tc_card.get('image', '')
                if not image_url:
                    entry['status'] = 'tcgdex_card_has_no_image'
                    entry['tcgdex_card_name'] = tc_card.get('name')
                    manifest.append(entry)
                    continue
                
                entry.update({
                    'tcgdex_card_name': tc_card.get('name'),
                    'asset_url': image_url,
                })
                
                if args.dry_run:
                    entry['status'] = 'verified_not_downloaded_dry_run'
                    manifest.append(entry)
                    downloaded += 1  # Count as "would download"
                    continue
                
                # Download image
                path = IMAGE_ROOT / date_stamp() / safe_name(lang) / safe_name(set_id) / f"{safe_name(card['card_id'])}.webp"
                dl_ok, sha, size, dl_ctype, dl_status = download_image(image_url, path)
                
                if dl_ok:
                    downloaded += 1
                    entry.update({
                        'status': 'downloaded',
                        'local_path': str(path),
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
    
    # Write manifest
    status_counts: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    for m in manifest:
        status_counts[m['status']] = status_counts.get(m['status'], 0) + 1
        lang_counts[m['language_code']] = lang_counts.get(m['language_code'], 0) + 1
    
    run_stamp = stamp()
    manifest_json = REPORTS / f'v2_tcgdex_set_api_recovery_manifest_{run_stamp}.json'
    manifest_csv = REPORTS / f'v2_tcgdex_set_api_recovery_manifest_{run_stamp}.csv'
    
    payload = {
        'generated_at': now_utc(),
        'database': str(db),
        'source': 'TCGdex set API (bulk)',
        'candidate_type': CANDIDATE_TYPE,
        'mode': 'dry_run' if args.dry_run else 'download',
        'target_rows': attempted,
        'downloaded': downloaded,
        'set_not_found': set_not_found,
        'card_not_found': card_not_found,
        'status_counts': status_counts,
        'language_counts': lang_counts,
        'image_root': str(IMAGE_ROOT),
        'manifest': manifest,
    }
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Write CSV summary (just status counts, not full manifest)
    summary_data = [{'status': k, 'count': v} for k, v in status_counts.items()]
    write_csv(manifest_csv, summary_data)
    
    payload['artifacts'] = {'manifest_json': str(manifest_json), 'manifest_csv': str(manifest_csv)}
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    
    return payload


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted(set().union(*(d.keys() for d in data))) if data else ['status']
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Bulk image recovery from TCGdex set API.')
    p.add_argument('--db', default=str(DB))
    p.add_argument('--languages', default='', help='Comma-separated DB language codes; empty = all')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--timeout', type=int, default=15)
    args = p.parse_args(argv)
    result = gather(args)
    print(json.dumps({k: result[k] for k in ['generated_at', 'mode', 'target_rows', 'downloaded', 'set_not_found', 'card_not_found', 'status_counts', 'language_counts', 'artifacts']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
