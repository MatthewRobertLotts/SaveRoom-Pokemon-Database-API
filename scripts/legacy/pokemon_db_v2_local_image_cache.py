#!/usr/bin/env python3
"""Create a compressed local WebP image cache for v2 display images.

Default scope is manifest-applied recovered exact source candidates because those
already have verified local original files. This creates a separate app/cache
layer and does not update raw cards.image_url or card_image_candidates.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
PROJECT_ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database')
REPORTS = DB.parent / 'reports'
CACHE_ROOT = PROJECT_ROOT / 'image_cache'
DEFAULT_PROFILE = 'webp_q72_512'
RECOVERED_TYPES = ('exact_tcgdex_recovered_asset', 'exact_asia_official_recovered_asset')


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def safe_name(value: str | None) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value or 'unknown').strip('_')[:120] or 'unknown'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def local_path_from_notes(notes: str | None) -> str | None:
    if not notes:
        return None
    m = re.search(r'local_path=([^;]+)', notes)
    return m.group(1).strip() if m else None


def ensure_table(cur: sqlite3.Cursor) -> None:
    cur.executescript('''
CREATE TABLE IF NOT EXISTS card_image_local_cache (
  language_code TEXT NOT NULL,
  card_id TEXT NOT NULL,
  cache_profile TEXT NOT NULL,
  source_candidate_type TEXT NOT NULL,
  source_remote_url TEXT,
  source_local_original_path TEXT NOT NULL,
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


def candidate_rows(cur: sqlite3.Cursor, scope: str) -> list[dict[str, Any]]:
    if scope != 'recovered-candidates':
        raise ValueError(f'Unsupported scope for now: {scope}')
    placeholders = ','.join('?' for _ in RECOVERED_TYPES)
    data = rows(cur, f'''
        SELECT c.language_code, c.card_id, c.set_id, c.local_id, c.candidate_image_url,
               c.candidate_type, c.notes, s.core_set_id, s.resolved_set_id,
               s.resolved_set_name, s.card_name, s.has_display_image
        FROM card_image_candidates c
        LEFT JOIN v2_card_search s ON s.language_code=c.language_code AND s.card_id=c.card_id
        WHERE c.candidate_type IN ({placeholders})
        ORDER BY c.language_code, COALESCE(s.core_set_id,c.set_id), c.local_id, c.card_id
    ''', RECOVERED_TYPES)
    out = []
    for r in data:
        local = local_path_from_notes(r.get('notes'))
        item = dict(r)
        item['source_local_original_path'] = local
        out.append(item)
    return out


def cache_path_for(item: dict[str, Any], profile: str) -> Path:
    return CACHE_ROOT / profile / safe_name(item['language_code']) / safe_name(item.get('core_set_id') or item.get('set_id') or item.get('resolved_set_id')) / f"{safe_name(item['card_id'])}.webp"


def make_webp(src: Path, dst: Path, *, max_width: int, quality: int) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ('RGB', 'RGBA'):
            im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
        if im.width > max_width:
            ratio = max_width / im.width
            new_size = (max_width, max(1, round(im.height * ratio)))
            im = im.resize(new_size, Image.Resampling.LANCZOS)
        # WebP supports alpha. method=6 is slower but smaller/better.
        im.save(dst, 'WEBP', quality=quality, method=6, optimize=True)
        width, height = im.size
    return {'width': width, 'height': height, 'bytes_cached': dst.stat().st_size, 'sha256_cached': sha256_file(dst)}


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
    items = candidate_rows(cur, args.scope)
    if args.limit:
        items = items[:args.limit]

    created_at = now_utc()
    processed: list[dict[str, Any]] = []
    ok_count = skipped_count = error_count = 0
    original_bytes = cached_bytes = 0
    for item in items:
        status = {k: item.get(k) for k in ['language_code','card_id','card_name','core_set_id','set_id','local_id','candidate_type','candidate_image_url','source_local_original_path']}
        src_text = item.get('source_local_original_path')
        if not src_text:
            skipped_count += 1; status['status'] = 'skipped_missing_local_path'; processed.append(status); continue
        src = Path(src_text)
        if not src.exists():
            skipped_count += 1; status['status'] = 'skipped_original_missing'; processed.append(status); continue
        dst = cache_path_for(item, profile)
        rel = dst.relative_to(CACHE_ROOT / profile).as_posix()
        local_url = f'/images/{rel}'
        try:
            bytes_original = src.stat().st_size
            if args.force or not dst.exists():
                converted = make_webp(src, dst, max_width=args.max_width, quality=args.quality)
            else:
                with Image.open(dst) as im:
                    converted = {'width': im.width, 'height': im.height, 'bytes_cached': dst.stat().st_size, 'sha256_cached': sha256_file(dst)}
            cur.execute('''
                INSERT OR REPLACE INTO card_image_local_cache(
                    language_code,card_id,cache_profile,source_candidate_type,source_remote_url,
                    source_local_original_path,source_original_sha256,local_cache_path,local_image_url,
                    width,height,format,quality,max_width,bytes_original,bytes_cached,sha256_cached,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                item['language_code'], item['card_id'], profile, item['candidate_type'], item.get('candidate_image_url'),
                str(src), sha256_file(src), str(dst), local_url,
                converted['width'], converted['height'], 'webp', args.quality, args.max_width,
                bytes_original, converted['bytes_cached'], converted['sha256_cached'], created_at,
            ))
            ok_count += 1
            original_bytes += bytes_original
            cached_bytes += converted['bytes_cached']
            status.update({'status': 'cached', 'local_cache_path': str(dst), 'local_image_url': local_url,
                           'bytes_original': bytes_original, **converted})
        except Exception as e:  # noqa: BLE001 - report and continue per-image.
            error_count += 1
            status.update({'status': 'error', 'error': str(e)})
        processed.append(status)
    conn.commit()

    status_counts: dict[str, int] = {}
    for r in processed:
        status_counts[r['status']] = status_counts.get(r['status'], 0) + 1
    REPORTS.mkdir(parents=True, exist_ok=True)
    s = stamp()
    json_path = REPORTS / f'v2_local_image_cache_{profile}_{s}.json'
    csv_path = REPORTS / f'v2_local_image_cache_{profile}_{s}.csv'
    payload = {
        'generated_at': created_at,
        'database': str(db),
        'scope': args.scope,
        'cache_profile': profile,
        'cache_root': str(CACHE_ROOT / profile),
        'target_rows': len(items),
        'cached': ok_count,
        'skipped': skipped_count,
        'errors': error_count,
        'status_counts': status_counts,
        'bytes_original': original_bytes,
        'bytes_cached': cached_bytes,
        'compression_ratio_cached_vs_original': round(cached_bytes / original_bytes, 4) if original_bytes else None,
        'bytes_saved': original_bytes - cached_bytes,
        'artifacts': {'json_report': str(json_path), 'csv_report': str(csv_path)},
        'items': processed,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(csv_path, processed)
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Build compressed local WebP cache for Pokémon card images.')
    p.add_argument('--db', default=str(DB))
    p.add_argument('--scope', default='recovered-candidates', choices=['recovered-candidates'])
    p.add_argument('--profile', default=None)
    p.add_argument('--quality', type=int, default=72)
    p.add_argument('--max-width', type=int, default=512)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--force', action='store_true')
    args = p.parse_args(argv)
    if args.limit == 0:
        args.limit = None
    result = run(args)
    print(json.dumps({k: result[k] for k in ['generated_at','scope','cache_profile','target_rows','cached','skipped','errors','status_counts','bytes_original','bytes_cached','compression_ratio_cached_vs_original','bytes_saved','artifacts']}, ensure_ascii=False, indent=2))
    return 0 if result['errors'] == 0 and result['cached'] > 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
