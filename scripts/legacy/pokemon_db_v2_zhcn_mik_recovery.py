#!/usr/bin/env python3
"""Recover exact Chinese Simplified card images from tcg.mik.moe.

Strict source policy: only same-language zh-cn assets from tcg.mik.moe are
inserted into the manifest. No placeholders and no cross-language fallbacks.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
ROOT = Path('/media/matt/Storage/Brain/Pokemon Card Database')
OUT_ROOT = ROOT / 'recovered_images' / 'zh_cn_mik'
REPORTS = ROOT / 'full_tcgdex' / 'reports'
BASE = 'https://tcg.mik.moe/static/img'
UA = 'Mozilla/5.0 (Hermes SaveRoom source-backed image recovery)'
CANDIDATE_TYPE = 'exact_zhcn_tcg_mik_moe'


def urlopen_bytes(url: str, timeout: int = 12) -> bytes | None:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get('content-type') or '').lower()
            if r.status == 200 and 'image' in ctype:
                return r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    except Exception:
        return None
    return None


def existing_mappings(conn: sqlite3.Connection) -> dict[str, str]:
    mapping: dict[str, str] = {}
    q = """
    SELECT resolved_set_id, display_image_url
    FROM v2_card_search
    WHERE language_code='zh-cn'
      AND has_display_image=1
      AND display_image_source_language_code='zh-cn'
      AND display_image_url LIKE 'https://tcg.mik.moe/static/img/%'
    """
    for row in conn.execute(q):
        m = re.search(r'/static/img/([^/]+)/', row['display_image_url'] or '')
        if not m:
            continue
        resolved = row['resolved_set_id']
        mik = m.group(1)
        mapping[resolved] = mik
        mapping[resolved.lower()] = mik
        mapping[resolved.upper()] = mik
        # Also map variants without final C for DB rows like csm1c/CSM1cC duplicates.
        if mik.endswith('C'):
            mapping[mik[:-1]] = mik
            mapping[mik[:-1].lower()] = mik
            mapping[mik[:-1].upper()] = mik
    return mapping


def candidate_sets(sid: str, known: dict[str, str]) -> list[str]:
    out: list[str] = []

    def add(x: str | None) -> None:
        if x and x not in out:
            out.append(x)

    add(known.get(sid))
    add(known.get(sid.lower()))
    add(known.get(sid.upper()))
    manual = {
        # tcg.mik.moe exposes Terastal Festival ex as CSV9.5C.
        # DB resolved_set_id for Chinese Simplified is SV8a (237 cards).
        'SV8a': 'CSV9.5C',
        'sv8a': 'CSV9.5C',
    }
    add(manual.get(sid))
    add(sid)

    low = sid.lower()
    if low.startswith('csm'):
        rest = sid[3:]
        # tcg.mik uses CSM + original suffix casing + trailing C, e.g. csm1c -> CSM1cC
        add('CSM' + rest + ('' if rest.endswith('C') else 'C'))
        add('CSM' + rest.lower() + ('' if rest.lower().endswith('c') else 'C'))
        # dotted variants: csm1.5 -> CSM1.5C
        add('CSM' + rest.upper() + ('' if rest.upper().endswith('C') else 'C'))
    elif low.startswith('csv'):
        rest = sid[3:]
        add('CSV' + rest.upper())
        if not rest.upper().endswith('C'):
            add('CSV' + rest.upper() + 'C')
    elif low.startswith('cs'):
        rest = sid[2:]
        add('CS' + rest + ('' if rest.endswith('C') else 'C'))
        add('CS' + rest.lower() + ('' if rest.lower().endswith('c') else 'C'))
        add('CS' + rest.upper() + ('' if rest.upper().endswith('C') else 'C'))
    elif low.startswith('sv'):
        # Some Simplified Chinese modern sets are prefixed CSV on mik.moe.
        rest = sid[2:]
        add('CSV' + rest.upper())
        if not rest.upper().endswith('C'):
            add('CSV' + rest.upper() + 'C')
        add(sid.upper())
        if not sid.upper().endswith('C'):
            add(sid.upper() + 'C')
    else:
        add(sid.upper())
        if not sid.upper().endswith(('A', 'B', 'C')):
            add(sid.upper() + 'C')
    return out


def candidate_numbers(local_id: str | None) -> list[str]:
    vals: list[str] = []

    def add(x: str | None) -> None:
        if x and x not in vals:
            vals.append(x)

    if local_id is None:
        return vals
    s = str(local_id).strip()
    add(s)
    m = re.search(r'(\d+)', s)
    if m:
        n = int(m.group(1))
        add(f'{n:03d}')
        add(str(n))
    return vals


def choose_set_mapping(sid: str, sample_local_ids: list[str], known: dict[str, str]) -> str | None:
    for mik_set in candidate_sets(sid, known):
        for local_id in sample_local_ids[:5]:
            for num in candidate_numbers(local_id):
                url = f'{BASE}/{mik_set}/{num}.png'
                if urlopen_bytes(url, timeout=8):
                    return mik_set
    return None


def download_one(row: dict, mik_set: str) -> dict | None:
    for num in candidate_numbers(row.get('local_id')):
        url = f'{BASE}/{mik_set}/{num}.png'
        data = urlopen_bytes(url)
        if not data:
            continue
        safe_card = re.sub(r'[^A-Za-z0-9_.-]+', '_', row['card_id'])
        out_dir = OUT_ROOT / row['resolved_set_id']
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f'{safe_card}.png'
        path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        return {
            'language_code': 'zh-cn',
            'card_id': row['card_id'],
            'name': row.get('card_name') or row.get('name') or '',
            'local_id': row.get('local_id'),
            'image_url': url,
            'asset_url': url,
            'local_path': str(path),
            'status': 'downloaded',
            'candidate_type': CANDIDATE_TYPE,
            'core_set_id': row['resolved_set_id'],
            'resolved_set_id': row['resolved_set_id'],
            'source_set_id': mik_set,
            'source_card_id': f'{mik_set}-{num}',
            'source_api_url': f'{BASE}/{mik_set}/',
            'bytes': len(data),
            'sha256': sha,
        }
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(DB))
    ap.add_argument('--limit-sets', type=int, default=0)
    ap.add_argument('--limit-cards-per-set', type=int, default=0)
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--sets', default='')
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    known = existing_mappings(conn)

    if args.sets:
        set_ids = [s.strip() for s in args.sets.split(',') if s.strip()]
    else:
        q = """
        SELECT resolved_set_id, COUNT(*) n
        FROM v2_card_search
        WHERE language_code='zh-cn' AND has_display_image=0
        GROUP BY resolved_set_id
        ORDER BY n DESC
        """
        set_ids = [r['resolved_set_id'] for r in conn.execute(q)]
    if args.limit_sets:
        set_ids = set_ids[:args.limit_sets]

    manifest: list[dict] = []
    set_results: list[dict] = []
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    for sid in set_ids:
        limit_sql = f' LIMIT {int(args.limit_cards_per_set)}' if args.limit_cards_per_set else ''
        rows = [dict(r) for r in conn.execute(
            """
            SELECT card_id, card_name, local_id, resolved_set_id
            FROM v2_card_search
            WHERE language_code='zh-cn' AND has_display_image=0 AND resolved_set_id=?
            ORDER BY local_id_sort, local_id, card_id
            """ + limit_sql,
            (sid,),
        )]
        if not rows:
            continue
        mik_set = choose_set_mapping(sid, [r.get('local_id') for r in rows if r.get('local_id')], known)
        if not mik_set:
            set_results.append({'resolved_set_id': sid, 'status': 'no_mapping', 'cards': len(rows), 'candidates': candidate_sets(sid, known)})
            print(f'{sid}: no mapping ({len(rows)} cards)')
            continue
        print(f'{sid}: mapped to {mik_set}; downloading {len(rows)} cards')
        downloaded = 0
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(download_one, row, mik_set) for row in rows]
            for fut in cf.as_completed(futs):
                item = fut.result()
                if item:
                    manifest.append(item)
                    downloaded += 1
        set_results.append({'resolved_set_id': sid, 'mik_set_id': mik_set, 'status': 'downloaded', 'cards': len(rows), 'downloaded': downloaded})
        print(f'{sid}: {downloaded}/{len(rows)} downloaded')

    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    out = REPORTS / f'zh_cn_mik_recovery_{stamp}.json'
    out.write_text(json.dumps({'generated_at': stamp, 'source': 'tcg.mik.moe', 'manifest': manifest, 'set_results': set_results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'MANIFEST={out}')
    print(f'ENTRIES={len(manifest)}')
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
