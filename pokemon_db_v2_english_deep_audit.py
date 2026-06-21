#!/usr/bin/env python3
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, UTC
from pathlib import Path

from PIL import Image

DB = Path('full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = Path('full_tcgdex/reports')
SAFE_EXACT_TYPES = {
    'exact_existing_image',
    'same_core_local_id_existing_image',
    'exact_tcgdex_recovered_asset',
    'exact_tcgdex_set_api_recovered_asset',
    'exact_ptcg_io_set',
    'exact_limitless_tcg_pocket_asset',
    'exact_pkmncards_asset',
    'exact_dittobase_asset',
    'exact_cardsrealm_asset',
    'exact_pricecharting_asset',
    'exact_tcgcollector_asset',
    'exact_wonderclub_asset',
}
SUSPICIOUS_TYPES = {'exact_ptcg_io_search', 'exact_ptcg_io_recovered_asset'}
PLACEHOLDER_TERMS = ['placeholder', 'card-back', 'card_back', 'back-card', 'pokemon-card-back', '/back.', 'no-image', 'no_image']

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def norm(s: str | None) -> str:
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())

def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    now = datetime.now(UTC).isoformat()
    rows = [dict(r) for r in cur.execute("select * from v2_card_search where language_code='en' order by resolved_set_id, local_id_sort, card_id")]
    total = len(rows)
    missing = [r for r in rows if not r['has_display_image']]
    shown = [r for r in rows if r['has_display_image']]

    # Audit 1: display/cache integrity.
    cache_rows = [dict(r) for r in cur.execute("select * from card_image_local_cache where language_code='en'")]
    cache_by_card = {r['card_id']: r for r in cache_rows}
    cache_issues = []
    checked_cache_files = 0
    for r in shown:
        cache = cache_by_card.get(r['card_id'])
        # Exact existing tcgdex rows may not all be locally cached; flag but don't hard-fail as broken if remote display exists.
        if cache:
            path = Path(cache['local_cache_path'])
            if not path.exists():
                cache_issues.append({'card_id': r['card_id'], 'issue': 'local_cache_missing', 'path': str(path)})
                continue
            checked_cache_files += 1
            try:
                actual_sha = sha256_file(path)
                if actual_sha != cache['sha256_cached']:
                    cache_issues.append({'card_id': r['card_id'], 'issue': 'local_cache_sha256_mismatch', 'expected': cache['sha256_cached'], 'actual': actual_sha})
                with Image.open(path) as im:
                    if im.width != cache['width'] or im.height != cache['height']:
                        cache_issues.append({'card_id': r['card_id'], 'issue': 'local_cache_dimension_mismatch', 'db': [cache['width'], cache['height']], 'actual': [im.width, im.height]})
                    if im.width <= 0 or im.height <= 0:
                        cache_issues.append({'card_id': r['card_id'], 'issue': 'invalid_dimensions', 'actual': [im.width, im.height]})
            except Exception as e:
                cache_issues.append({'card_id': r['card_id'], 'issue': 'local_cache_read_error', 'error': f'{type(e).__name__}:{e}'})
    displayed_without_cache = [r['card_id'] for r in shown if r['card_id'] not in cache_by_card]

    # Audit 2: source safety/provenance.
    source_counts = dict(collections.Counter((r['display_image_source_type'] or 'NONE') for r in rows))
    source_language_issues = [
        {'card_id': r['card_id'], 'source_language': r['display_image_source_language_code'], 'source_type': r['display_image_source_type']}
        for r in shown
        if r['display_image_source_language_code'] not in (None, '', 'en')
    ]
    placeholder_like = [
        {'card_id': r['card_id'], 'url': r['display_image_url'], 'source_type': r['display_image_source_type']}
        for r in shown
        if any(term in (r['display_image_url'] or '').lower() for term in PLACEHOLDER_TERMS)
    ]
    unsupported_source_types = [
        {'card_id': r['card_id'], 'source_type': r['display_image_source_type'], 'url': r['display_image_url']}
        for r in shown
        if (r['display_image_source_type'] or '') not in SAFE_EXACT_TYPES and (r['display_image_source_type'] or '') not in SUSPICIOUS_TYPES
    ]
    suspicious_search_sources = [
        {'card_id': r['card_id'], 'set': r['resolved_set_id'], 'local_id': r['local_id'], 'name': r['card_name'], 'source_type': r['display_image_source_type'], 'url': r['display_image_url']}
        for r in shown
        if (r['display_image_source_type'] or '') in SUSPICIOUS_TYPES
    ]

    # Candidate set mismatch audit: compare best candidate source_set_id against displayed row set when available.
    mismatches = []
    for r in cur.execute("""
        select s.card_id, s.resolved_set_id, s.local_id, s.card_name,
               b.candidate_type, b.source_set_id, b.source_card_id, b.candidate_image_url
        from v2_card_search s
        join v2_card_image_best b on b.language_code=s.language_code and b.card_id=s.card_id
        where s.language_code='en' and s.has_display_image=1
          and b.source_set_id is not null and b.source_set_id != ''
          and b.source_set_id != s.resolved_set_id
        order by s.resolved_set_id, s.local_id_sort, s.card_id
    """):
        mismatches.append(dict(r))

    # Audit 3: set/card consistency.
    duplicate_card_ids = [dict(r) for r in cur.execute("select card_id, count(*) n from cards where language_code='en' group by card_id having n > 1 order by n desc, card_id")]
    set_counts = [dict(r) for r in cur.execute("""
        select resolved_set_id, resolved_set_name, count(*) rows,
               sum(case when has_display_image=1 then 1 else 0 end) with_image,
               sum(case when has_display_image=0 then 1 else 0 end) missing
        from v2_card_search where language_code='en'
        group by resolved_set_id, resolved_set_name
        order by missing desc, resolved_set_id
    """)]
    sets_with_missing = [r for r in set_counts if r['missing']]
    null_core_fields = [dict(r) for r in cur.execute("""
        select card_id, resolved_set_id, local_id, card_name, resolved_set_name, core_set_id
        from v2_card_search where language_code='en'
          and (card_id is null or card_id='' or resolved_set_id is null or resolved_set_id='' or local_id is null or local_id='' or card_name is null or card_name='' or resolved_set_name is null or resolved_set_name='')
        order by resolved_set_id, local_id_sort, card_id
    """)]
    same_set_local_name_conflicts = [dict(r) for r in cur.execute("""
        select resolved_set_id, local_id, count(distinct card_name) names, group_concat(distinct card_name) card_names, count(*) rows
        from v2_card_search where language_code='en'
        group by resolved_set_id, local_id
        having count(distinct card_name) > 1
        order by resolved_set_id, local_id
    """)]
    api_cache_count = cur.execute("select count(*) from v2_card_detail_api_cache").fetchone()[0]
    search_count = cur.execute("select count(*) from v2_card_search").fetchone()[0]
    english_api_cache_count = cur.execute("select count(*) from v2_card_detail_api_cache where language_code='en'").fetchone()[0]
    integrity = cur.execute('pragma integrity_check').fetchone()[0]
    quick = cur.execute('pragma quick_check').fetchone()[0]
    conn.close()

    report = {
        'generated_at': now,
        'database': str(DB.resolve()),
        'summary': {
            'english_rows': total,
            'english_with_display_image': len(shown),
            'english_missing_display_image': len(missing),
            'english_missing_rows': [
                {k: r[k] for k in ('resolved_set_id','resolved_set_name','card_id','local_id','card_name')}
                for r in missing
            ],
            'db_integrity_check': integrity,
            'db_quick_check': quick,
            'api_cache_rows': api_cache_count,
            'v2_card_search_rows': search_count,
            'api_cache_matches_search_rows': api_cache_count == search_count,
            'english_api_cache_rows': english_api_cache_count,
        },
        'audit1_image_cache_integrity': {
            'checked_local_cache_files': checked_cache_files,
            'english_displayed_without_local_cache_count': len(displayed_without_cache),
            'english_displayed_without_local_cache_sample': displayed_without_cache[:50],
            'cache_issue_count': len(cache_issues),
            'cache_issues': cache_issues[:200],
        },
        'audit2_source_safety': {
            'source_type_counts': source_counts,
            'source_language_issue_count': len(source_language_issues),
            'source_language_issues': source_language_issues[:200],
            'placeholder_like_count': len(placeholder_like),
            'placeholder_like': placeholder_like[:200],
            'unsupported_source_type_count': len(unsupported_source_types),
            'unsupported_source_types': unsupported_source_types[:200],
            'suspicious_search_source_count': len(suspicious_search_sources),
            'suspicious_search_sources_sample': suspicious_search_sources[:200],
            'best_candidate_source_set_mismatch_count': len(mismatches),
            'best_candidate_source_set_mismatch_sample': mismatches[:200],
        },
        'audit3_set_card_consistency': {
            'sets_with_missing': sets_with_missing,
            'duplicate_card_id_count': len(duplicate_card_ids),
            'duplicate_card_ids_sample': duplicate_card_ids[:50],
            'null_or_blank_core_field_count': len(null_core_fields),
            'null_or_blank_core_fields': null_core_fields[:200],
            'same_set_local_name_conflict_count': len(same_set_local_name_conflicts),
            'same_set_local_name_conflicts_sample': same_set_local_name_conflicts[:200],
        },
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f'en_deep_audit_{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({
        'report': str(out),
        'summary': report['summary'],
        'audit1_cache_issue_count': len(cache_issues),
        'audit1_without_local_cache_count': len(displayed_without_cache),
        'audit2_source_language_issue_count': len(source_language_issues),
        'audit2_placeholder_like_count': len(placeholder_like),
        'audit2_suspicious_search_source_count': len(suspicious_search_sources),
        'audit2_source_set_mismatch_count': len(mismatches),
        'audit3_null_or_blank_core_field_count': len(null_core_fields),
        'audit3_same_set_local_name_conflict_count': len(same_set_local_name_conflicts),
    }, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
