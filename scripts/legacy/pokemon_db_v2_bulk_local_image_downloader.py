#!/usr/bin/env python3
"""Bulk-download v2 display images directly into the local compressed app cache.

This script is for app/offline serving, not source truth mutation:
- downloads the current v2 display_image_url for rows that do not already have a local cache;
- compresses directly to WebP (no full-size original archive unless source was already recovered);
- records metadata in card_image_local_cache;
- does not update cards.image_url or card_image_candidates.

Run in batches and then refresh API cache with pokemon_db_v2_search_api.py setup-fts.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
PROJECT_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database')
REPORTS = DB.parent / 'reports'
CACHE_ROOT = PROJECT_ROOT / 'image_cache'
DEFAULT_PROFILE = 'webp_q72_512'
USER_AGENT = 'SaveRoomPokemonLocalImageCache/1.0'


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def ensure_table(cur: sqlite3.Cursor) -> None:
    cur.executescript('''
CREATE TABLE IF NOT EXISTS card_image_local_cache (
  language_code TEXT NOT NULL,
  card_id TEXT NOT NULL,
  cache_profile TEXT NOT NULL,
  source_candidate_type TEXT NOT NULL,
  source_remote_url TEXT,
  source_local_original_path TEXT NOT NULL DEFAULT '',
  source_original_sha256 TEXT,
  local_cache_path TEXT NOT NULL,
  local_image_url TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  format TEXT NOT NULL,
  quality INTEGER NOT NULL,
  max_width INTEGER NOT NULL,
  bytes_original INTEGER NOT NULL,
  bytes_cached INTEGER NOT NULL,
  sha256_cached TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (language_code, card_id, cache_profile)
);
CREATE INDEX IF NOT EXISTS idx_card_image_local_cache_card ON card_image_local_cache(language_code, card_id);
CREATE INDEX IF NOT EXISTS idx_card_image_local_cache_profile ON card_image_local_cache(cache_profile);
''')


def target_rows(cur: sqlite3.Cursor, *, profile: str, limit: int | None, source_types: list[str] | None, languages: list[str] | None) -> list[dict[str, Any]]:
    where = ["s.has_display_image=1", "s.display_image_url IS NOT NULL", "TRIM(s.display_image_url)<>''", "s.display_image_url NOT LIKE '/images/%'", "NOT EXISTS (SELECT 1 FROM card_image_local_cache lc WHERE lc.language_code=s.language_code AND lc.card_id=s.card_id AND lc.cache_profile=?)"]
    params: list[Any] = [profile]
    if source_types:
        where.append('s.display_image_source_type IN (%s)' % ','.join('?' for _ in source_types))
        params.extend(source_types)
    if languages:
        where.append('s.language_code IN (%s)' % ','.join('?' for _ in languages))
        params.extend(languages)
    sql = f'''
        SELECT s.language_code, s.card_id, s.raw_set_id, s.resolved_set_id, s.core_set_id,
               s.local_id, s.card_name, s.display_image_url, s.display_image_source_type,
               s.display_image_source_language_code
        FROM v2_card_search s
        WHERE {' AND '.join(where)}
        ORDER BY
          CASE s.display_image_source_type WHEN 'exact_existing_image' THEN 0 WHEN 'exact_asia_official_recovered_asset' THEN 1 WHEN 'exact_tcgdex_recovered_asset' THEN 1 WHEN 'same_card_id_existing_image' THEN 2 ELSE 3 END,
          s.language_code, s.core_set_id, s.local_id_sort, s.card_id
    '''
    if limit:
        sql += ' LIMIT ?'
        params.append(limit)
    return rows(cur, sql, tuple(params))


def cache_path_for(item: dict[str, Any], profile: str) -> Path:
    return CACHE_ROOT / profile / safe_name(item['language_code']) / safe_name(item.get('core_set_id') or item.get('resolved_set_id') or item.get('raw_set_id')) / f"{safe_name(item['card_id'])}.webp"


def compress_image_bytes(raw: bytes, dst: Path, *, max_width: int, quality: int) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ('RGB', 'RGBA'):
            im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
        if im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, max(1, round(im.height * ratio))), Image.Resampling.LANCZOS)
        im.save(dst, 'WEBP', quality=quality, method=6, optimize=True)
        width, height = im.size
    return {'width': width, 'height': height, 'bytes_cached': dst.stat().st_size, 'sha256_cached': sha256_file(dst)}


def fetch_and_cache(item: dict[str, Any], *, profile: str, max_width: int, quality: int, timeout: int, retries: int) -> dict[str, Any]:
    out = {k: item.get(k) for k in ['language_code','card_id','core_set_id','local_id','card_name','display_image_url','display_image_source_type']}
    dst = cache_path_for(item, profile)
    rel = dst.relative_to(CACHE_ROOT / profile).as_posix()
    out['local_image_url'] = f'/images/{rel}'
    url = item['display_image_url']
    candidate_urls = [url]
    # TCGdex often stores extensionless asset handles. Resolve them to actual files.
    if 'assets.tcgdex.net/' in url and not re.search(r'\.(webp|png|jpg|jpeg)(?:\?|$)', url, re.I):
        candidate_urls = [url.rstrip('/') + suffix for suffix in ('/high.webp', '/low.webp', '/high.png', '/low.png')] + [url]
    headers = {'User-Agent': USER_AGENT}
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            last_non_image = None
            for fetch_url in candidate_urls:
                r = requests.get(fetch_url, headers=headers, timeout=timeout)
                ctype = r.headers.get('content-type') or ''
                if r.status_code == 200 and ctype.startswith('image/'):
                    break
                last_non_image = (fetch_url, r.status_code, ctype)
            else:
                fetch_url, status, ctype = last_non_image or (url, None, None)
                out.update({'status': 'not_image', 'http_status': status, 'content_type': ctype, 'resolved_fetch_url': fetch_url, 'attempt': attempt})
                return out
            if r.status_code != 200:
                out.update({'status': 'http_error', 'http_status': r.status_code, 'content_type': ctype, 'resolved_fetch_url': fetch_url, 'attempt': attempt})
                return out
            raw = r.content
            converted = compress_image_bytes(raw, dst, max_width=max_width, quality=quality)
            out.update({'status': 'cached', 'http_status': r.status_code, 'content_type': ctype,
                        'resolved_fetch_url': fetch_url,
                        'bytes_original': len(raw), 'source_original_sha256': sha256_bytes(raw),
                        'local_cache_path': str(dst), **converted})
            return out
        except Exception as e:  # noqa: BLE001 - per-image retry/report.
            last_error = str(e)
            time.sleep(min(2 * attempt, 8))
    out.update({'status': 'error', 'error': last_error})
    return out


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    fields = sorted(set().union(*(d.keys() for d in data))) if data else ['status']
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(data)


def run(args: argparse.Namespace) -> dict[str, Any]:
    db = Path(args.db)
    profile = args.profile or f'webp_q{args.quality}_{args.max_width}'
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ensure_table(cur)
    source_types = [s.strip() for s in args.source_types.split(',') if s.strip()] if args.source_types else None
    languages = [s.strip() for s in args.languages.split(',') if s.strip()] if args.languages else None
    targets = target_rows(cur, profile=profile, limit=args.limit, source_types=source_types, languages=languages)
    created_at = now_utc()
    results: list[dict[str, Any]] = []
    if targets and not args.dry_run:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(fetch_and_cache, item, profile=profile, max_width=args.max_width, quality=args.quality, timeout=args.timeout, retries=args.retries) for item in targets]
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                if res.get('status') == 'cached':
                    cur.execute('''
                        INSERT OR REPLACE INTO card_image_local_cache(
                            language_code,card_id,cache_profile,source_candidate_type,source_remote_url,
                            source_local_original_path,source_original_sha256,local_cache_path,local_image_url,
                            width,height,format,quality,max_width,bytes_original,bytes_cached,sha256_cached,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ''', (
                        res['language_code'], res['card_id'], profile, res.get('display_image_source_type') or 'unknown', res.get('display_image_url'),
                        '', res.get('source_original_sha256'), res['local_cache_path'], res['local_image_url'],
                        res['width'], res['height'], 'webp', args.quality, args.max_width,
                        res['bytes_original'], res['bytes_cached'], res['sha256_cached'], created_at,
                    ))
                    if args.commit_interval and len(results) % args.commit_interval == 0:
                        conn.commit()
        conn.commit()
    else:
        for item in targets:
            results.append({k: item.get(k) for k in ['language_code','card_id','core_set_id','local_id','card_name','display_image_url','display_image_source_type']} | {'status': 'dry_run'})
    status_counts: dict[str, int] = {}
    original = cached = 0
    for r in results:
        status_counts[r['status']] = status_counts.get(r['status'], 0) + 1
        original += int(r.get('bytes_original') or 0)
        cached += int(r.get('bytes_cached') or 0)
    REPORTS.mkdir(parents=True, exist_ok=True)
    s = stamp()
    json_path = REPORTS / f'v2_bulk_local_image_download_{profile}_{s}.json'
    csv_path = REPORTS / f'v2_bulk_local_image_download_{profile}_{s}.csv'
    payload = {
        'generated_at': created_at,
        'database': str(db),
        'cache_profile': profile,
        'cache_root': str(CACHE_ROOT / profile),
        'dry_run': args.dry_run,
        'limit': args.limit,
        'source_types': source_types,
        'languages': languages,
        'target_rows': len(targets),
        'status_counts': status_counts,
        'bytes_original_downloaded': original,
        'bytes_cached': cached,
        'compression_ratio_cached_vs_original': round(cached / original, 4) if original else None,
        'bytes_saved': original - cached,
        'artifacts': {'json_report': str(json_path), 'csv_report': str(csv_path)},
        'items': results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(csv_path, results)
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Bulk download v2 display images into compressed local cache.')
    p.add_argument('--db', default=str(DB))
    p.add_argument('--profile', default=None)
    p.add_argument('--quality', type=int, default=72)
    p.add_argument('--max-width', type=int, default=512)
    p.add_argument('--limit', type=int, default=1000, help='Batch size; use 0 for all remaining matching rows')
    p.add_argument('--source-types', default='', help='Comma-separated display_image_source_type filter')
    p.add_argument('--languages', default='', help='Comma-separated language filter')
    p.add_argument('--workers', type=int, default=12)
    p.add_argument('--timeout', type=int, default=20)
    p.add_argument('--retries', type=int, default=1)
    p.add_argument('--commit-interval', type=int, default=100, help='Commit successful cache metadata every N completed downloads.')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    if args.limit == 0:
        args.limit = None
    result = run(args)
    print(json.dumps({k: result[k] for k in ['generated_at','cache_profile','dry_run','limit','source_types','languages','target_rows','status_counts','bytes_original_downloaded','bytes_cached','compression_ratio_cached_vs_original','bytes_saved','artifacts']}, ensure_ascii=False, indent=2))
    return 0 if result['target_rows'] == 0 or result['status_counts'].get('cached', 0) > 0 or args.dry_run else 1


if __name__ == '__main__':
    raise SystemExit(main())
