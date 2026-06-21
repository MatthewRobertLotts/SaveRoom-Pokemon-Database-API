#!/usr/bin/env python3
"""Cache all v2 display images locally in compressed WebP batches.

Runs pokemon_db_v2_bulk_local_image_downloader.py repeatedly by display source
priority until no matching display-image rows remain uncached for the selected
profile, then refreshes the FTS/API cache.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
HERE = Path('/media/matt/Storage/Brain/Pokemon Card Database')
DOWNLOADER = HERE / 'pokemon_db_v2_bulk_local_image_downloader.py'
SEARCH_API = HERE / 'pokemon_db_v2_search_api.py'
DEFAULT_SOURCE_ORDER = [
    'exact_existing_image',
    'exact_asia_official_recovered_asset',
    'exact_tcgdex_recovered_asset',
    'same_card_id_existing_image',
    'same_core_local_id_existing_image',
]


def now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def remaining_for(profile: str, source_type: str | None = None) -> int:
    conn = connect(); cur = conn.cursor()
    where = [
        "s.has_display_image=1",
        "s.display_image_url IS NOT NULL",
        "TRIM(s.display_image_url)<>''",
        "NOT EXISTS (SELECT 1 FROM card_image_local_cache lc WHERE lc.language_code=s.language_code AND lc.card_id=s.card_id AND lc.cache_profile=?)",
    ]
    params: list[Any] = [profile]
    if source_type:
        where.append('s.display_image_source_type=?')
        params.append(source_type)
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM v2_card_search s WHERE {' AND '.join(where)}", params).fetchone()[0])
    finally:
        conn.close()


def snapshot(profile: str) -> dict[str, Any]:
    conn = connect(); cur = conn.cursor()
    try:
        table_exists = cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='card_image_local_cache'").fetchone()[0] > 0
        local = cur.execute("SELECT COUNT(*) FROM card_image_local_cache WHERE cache_profile=?", (profile,)).fetchone()[0] if table_exists else 0
        bytes_cached = cur.execute("SELECT COALESCE(SUM(bytes_cached),0) FROM card_image_local_cache WHERE cache_profile=?", (profile,)).fetchone()[0] if table_exists else 0
        by_type = [dict(r) for r in cur.execute('''
            SELECT COALESCE(s.display_image_source_type,'none') AS source_type,
                   COUNT(*) AS display_rows,
                   SUM(CASE WHEN lc.card_id IS NOT NULL THEN 1 ELSE 0 END) AS cached_rows,
                   SUM(CASE WHEN lc.card_id IS NULL THEN 1 ELSE 0 END) AS remaining_rows
            FROM v2_card_search s
            LEFT JOIN card_image_local_cache lc
              ON lc.language_code=s.language_code AND lc.card_id=s.card_id AND lc.cache_profile=?
            WHERE s.has_display_image=1
            GROUP BY COALESCE(s.display_image_source_type,'none')
            ORDER BY remaining_rows DESC
        ''', (profile,))]
        return {
            'generated_at': now(),
            'profile': profile,
            'display_images_total': cur.execute('SELECT COUNT(*) FROM v2_card_search WHERE has_display_image=1').fetchone()[0],
            'local_cache_rows': local,
            'remaining_total': remaining_for(profile),
            'bytes_cached': bytes_cached,
            'by_type': by_type,
        }
    finally:
        conn.close()


def run_batch(source_type: str, args: argparse.Namespace) -> dict[str, Any]:
    cmd = [
        sys.executable, str(DOWNLOADER),
        '--limit', str(args.batch_size),
        '--source-types', source_type,
        '--workers', str(args.workers),
        '--timeout', str(args.timeout),
        '--retries', str(args.retries),
        '--commit-interval', str(args.commit_interval),
        '--quality', str(args.quality),
        '--max-width', str(args.max_width),
    ]
    print(f"[{now()}] START batch source={source_type} limit={args.batch_size}", flush=True)
    proc = subprocess.run(cmd, cwd=str(HERE), text=True, capture_output=True)
    print(proc.stdout, flush=True)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, flush=True)
    if proc.returncode != 0:
        print(f"[{now()}] WARNING batch source={source_type} exited {proc.returncode}; continuing after short pause", flush=True)
    try:
        # The downloader prints one JSON object; parse the last object-shaped block if possible.
        text = proc.stdout.strip()
        parsed = json.loads(text[text.rfind('{'):]) if text else {}
    except Exception:
        parsed = {'returncode': proc.returncode}
    return parsed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Cache all display images locally in batches.')
    p.add_argument('--batch-size', type=int, default=5000)
    p.add_argument('--workers', type=int, default=12)
    p.add_argument('--timeout', type=int, default=20)
    p.add_argument('--retries', type=int, default=1)
    p.add_argument('--commit-interval', type=int, default=100)
    p.add_argument('--quality', type=int, default=72)
    p.add_argument('--max-width', type=int, default=512)
    p.add_argument('--sleep-between-batches', type=float, default=2.0)
    p.add_argument('--max-batches', type=int, default=0, help='Safety cap; 0 means unlimited until complete.')
    p.add_argument('--source-order', default=','.join(DEFAULT_SOURCE_ORDER))
    args = p.parse_args(argv)
    profile = f'webp_q{args.quality}_{args.max_width}'
    source_order = [s.strip() for s in args.source_order.split(',') if s.strip()]

    print(json.dumps({'event': 'start_all_cache', **snapshot(profile)}, ensure_ascii=False, indent=2), flush=True)
    total_batches = 0
    for source_type in source_order:
        while True:
            rem = remaining_for(profile, source_type)
            print(f"[{now()}] remaining source={source_type}: {rem}", flush=True)
            if rem <= 0:
                break
            if args.max_batches and total_batches >= args.max_batches:
                print(f"[{now()}] max_batches reached; stopping early", flush=True)
                print(json.dumps({'event': 'stopped_early', **snapshot(profile)}, ensure_ascii=False, indent=2), flush=True)
                return 2
            run_batch(source_type, args)
            total_batches += 1
            print(json.dumps({'event': 'after_batch', 'source_type': source_type, 'total_batches': total_batches, **snapshot(profile)}, ensure_ascii=False, indent=2), flush=True)
            time.sleep(args.sleep_between_batches)

    # Catch any unexpected/unknown source type rows.
    while True:
        rem = remaining_for(profile, None)
        print(f"[{now()}] remaining all source types: {rem}", flush=True)
        if rem <= 0:
            break
        if args.max_batches and total_batches >= args.max_batches:
            print(json.dumps({'event': 'stopped_early_unknown_sources', **snapshot(profile)}, ensure_ascii=False, indent=2), flush=True)
            return 2
        # Empty source-types means any source type.
        cmd = [
            sys.executable, str(DOWNLOADER), '--limit', str(args.batch_size),
            '--workers', str(args.workers), '--timeout', str(args.timeout), '--retries', str(args.retries),
            '--commit-interval', str(args.commit_interval), '--quality', str(args.quality), '--max-width', str(args.max_width),
        ]
        print(f"[{now()}] START catch-all batch limit={args.batch_size}", flush=True)
        proc = subprocess.run(cmd, cwd=str(HERE), text=True, capture_output=True)
        print(proc.stdout, flush=True)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr, flush=True)
        total_batches += 1
        print(json.dumps({'event': 'after_catch_all_batch', 'total_batches': total_batches, **snapshot(profile)}, ensure_ascii=False, indent=2), flush=True)
        time.sleep(args.sleep_between_batches)

    print(f"[{now()}] Refreshing FTS/API cache", flush=True)
    subprocess.run([sys.executable, str(SEARCH_API), 'setup-fts'], cwd=str(HERE), check=True)
    print(json.dumps({'event': 'complete_all_cache', 'total_batches': total_batches, **snapshot(profile)}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
