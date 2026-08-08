#!/usr/bin/env python3
"""Targeted Japanese image recovery from TCGdex API.

Manifest-first only: queries TCGdex API for Japanese cards missing images,
downloads verified images, writes manifest. Apply with pokemon_db_v2_apply_recovered_images.py.
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
from urllib.parse import urljoin

import requests

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
IMAGE_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database/recovered_images')
SOURCE_BASE = 'https://api.tcgdex.net/v2/ja/cards/'
IMAGE_BASE = 'https://assets.tcgdex.net/ja/'
CANDIDATE_TYPE = 'exact_tcgdex_ja_recovered_asset'
UA = 'SaveRoomPokemonJaImageRecovery/1.0 (+manifest-first; contact: local SaveRoom DB maintenance)'


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def date_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def target_rows(db: Path, set_codes: list[str] | None, limit: int | None) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    params: list[Any] = ['ja']
    lang_clause = '?'
    set_clause = ''
    if set_codes:
        set_clause = ' AND lower(s.core_set_id) IN (' + ','.join('?' for _ in set_codes) + ')'
        params.extend([s.lower() for s in set_codes])
    sql = f'''
        SELECT s.language_code, s.card_id, s.raw_set_id, s.resolved_set_id, s.core_set_id,
               s.local_id, s.local_id_sort, s.card_name, s.resolved_set_name,
               s.resolved_series_name, s.resolved_release_date
        FROM v2_card_search s
        WHERE s.language_code = ({lang_clause})
          AND s.has_display_image = 0
          AND s.core_set_id IS NOT NULL
          {set_clause}
        ORDER BY s.core_set_id, s.local_id_sort, s.card_id
    '''
    out = rows(cur, sql, tuple(params))
    conn.close()
    return out[:limit] if limit else out


class TCGdexJaClient:
    def __init__(self, timeout: int = 15, sleep: float = 0.02):
        self.timeout = timeout
        self.sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': UA})

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        url = f'{SOURCE_BASE}{card_id}'
        try:
            r = self.session.get(url, timeout=self.timeout)
            time.sleep(self.sleep)
            if r.status_code == 200:
                return r.json()
            return None
        except requests.RequestException:
            return None

    def download_image(self, image_url: str, path: Path) -> tuple[bool, str | None, int, str | None, int | None]:
        try:
            # Append /high.webp if not already present
            if not image_url.endswith(('/high.webp', '/low.webp', '.webp', '.png', '.jpg')):
                image_url = image_url.rstrip('/') + '/high.webp'
            r = self.session.get(image_url, timeout=self.timeout, stream=True)
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


def local_image_path(item: dict[str, Any], url: str) -> Path:
    ext = 'webp'
    return IMAGE_ROOT / date_stamp() / safe_name(item['language_code']) / safe_name(item.get('core_set_id') or item.get('raw_set_id')) / f"{safe_name(item['card_id'])}.{ext}"


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted(set().union(*(d.keys() for d in data))) if data else ['status']
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)


def gather(args: argparse.Namespace) -> dict[str, Any]:
    db = Path(args.db)
    set_codes = [s.strip() for s in args.sets.split(',') if s.strip()] if args.sets else None
    wanted = target_rows(db, set_codes, args.limit)
    if not wanted:
        print(json.dumps({'generated_at': now_utc(), 'mode': 'download', 'target_rows': 0, 'message': 'No target rows found'}, indent=2))
        return {'generated_at': now_utc(), 'target_rows': 0, 'downloaded': 0, 'status_counts': {}, 'language_counts': {}}

    client = TCGdexJaClient(timeout=args.timeout, sleep=args.sleep)
    REPORTS.mkdir(parents=True, exist_ok=True)
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    downloaded = attempted = matched = 0
    not_found = no_image = 0

    def process_card(item: dict[str, Any]) -> dict[str, Any]:
        card_id = item['card_id']
        entry = {k: item.get(k) for k in ['language_code', 'card_id', 'card_name', 'raw_set_id', 'resolved_set_id', 'core_set_id', 'local_id', 'resolved_set_name', 'resolved_series_name']}
        entry.update({
            'attempted_at': now_utc(),
            'status': 'not_found_in_tcgdex',
            'candidate_type': CANDIDATE_TYPE,
            'source_name': 'tcgdex_ja_api',
            'source_api_url': f'{SOURCE_BASE}{card_id}',
        })

        card_data = client.get_card(card_id)
        if card_data is None:
            entry['status'] = 'not_found_in_tcgdex'
            return entry

        image_url = card_data.get('image')
        if not image_url:
            entry['status'] = 'tcgdex_card_has_no_image'
            entry['tcgdex_card_name'] = card_data.get('name')
            return entry

        entry.update({
            'tcgdex_card_name': card_data.get('name'),
            'tcgdex_set_name': card_data.get('set', {}).get('name'),
            'asset_url': image_url,
            'source_api_url': f'{SOURCE_BASE}{card_id}',
        })

        if args.dry_run:
            entry['status'] = 'verified_not_downloaded_dry_run'
            entry['local_path'] = str(local_image_path(item, image_url))
            return entry

        path = local_image_path(item, image_url)
        dl_ok, sha, size, dl_ctype, dl_status = client.download_image(image_url, path)
        if dl_ok:
            entry.update({
                'status': 'downloaded',
                'local_path': str(path),
                'sha256': sha,
                'bytes': size,
                'download_http_status': dl_status,
                'download_content_type': dl_ctype,
                'verification_method': 'tcgdex_ja_api_and_image_http_verified',
            })
        else:
            entry.update({
                'status': 'download_failed',
                'download_http_status': dl_status,
                'download_content_type': dl_ctype,
            })
        return entry

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(process_card, item) for item in wanted]
        for fut in as_completed(futs):
            entry = fut.result()
            attempted += 1
            status = entry['status']
            if status == 'downloaded':
                downloaded += 1
                matched += 1
            elif status == 'not_found_in_tcgdex':
                not_found += 1
            elif status == 'tcgdex_card_has_no_image':
                no_image += 1
            manifest.append(entry)

            if attempted % 100 == 0:
                print(f'  Progress: {attempted}/{len(wanted)} attempted, {downloaded} downloaded', file=sys.stderr)

    status_counts: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    for m in manifest:
        status_counts[m['status']] = status_counts.get(m['status'], 0) + 1
        lang_counts[m['language_code']] = lang_counts.get(m['language_code'], 0) + 1

    run_stamp = stamp()
    manifest_json = REPORTS / f'v2_tcgdex_ja_image_recovery_manifest_{run_stamp}.json'
    manifest_csv = REPORTS / f'v2_tcgdex_ja_image_recovery_manifest_{run_stamp}.csv'
    payload = {
        'generated_at': now_utc(),
        'database': str(db),
        'source': 'TCGdex Japanese card API',
        'candidate_type': CANDIDATE_TYPE,
        'mode': 'dry_run' if args.dry_run else 'download',
        'target_rows': len(wanted),
        'attempted_rows': attempted,
        'matched_rows': matched,
        'downloaded': downloaded,
        'not_found_in_tcgdex': not_found,
        'tcgdex_no_image': no_image,
        'status_counts': status_counts,
        'language_counts': lang_counts,
        'image_root': str(IMAGE_ROOT),
        'manifest': manifest,
    }
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(manifest_csv, manifest)
    payload['artifacts'] = {'manifest_json': str(manifest_json), 'manifest_csv': str(manifest_csv)}
    manifest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Gather Japanese card images from TCGdex API for v2 missing-display rows.')
    p.add_argument('--db', default=str(DB))
    p.add_argument('--sets', default='', help='Optional comma-separated core set codes to target')
    p.add_argument('--limit', type=int, default=0, help='Max target DB rows; 0 = all matching rows')
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--timeout', type=int, default=15)
    p.add_argument('--sleep', type=float, default=0.02)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    if args.limit == 0:
        args.limit = None
    result = gather(args)
    print(json.dumps({k: result[k] for k in ['generated_at', 'mode', 'target_rows', 'attempted_rows', 'matched_rows', 'downloaded', 'not_found_in_tcgdex', 'tcgdex_no_image', 'status_counts', 'language_counts', 'artifacts']}, ensure_ascii=False, indent=2))
    return 0 if result.get('downloaded', 0) > 0 or args.dry_run else 1


if __name__ == '__main__':
    raise SystemExit(main())
