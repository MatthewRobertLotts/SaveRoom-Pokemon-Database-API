#!/usr/bin/env python3
"""Generate v10 identity quality report.

Reports on the state of canonical printings, commercial variants, sellable
SKUs, and external references derived by the v10 identity build.

Usage:
    python scripts/report_v10_identity_quality.py --db <DB_PATH>
    python scripts/report_v10_identity_quality.py --db <DB_PATH> --json
    python scripts/report_v10_identity_quality.py --db <DB_PATH> --markdown
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f'file:{db_path.resolve()}?mode=ro', uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _scalar(cur: sqlite3.Cursor, sql: str, default: int = 0) -> int:
    cur.execute(sql)
    row = cur.fetchone()
    return row[0] if row else default


def generate_report(conn: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    cur = conn.cursor()

    # Card totals
    total_cards = _scalar(cur, 'SELECT COUNT(*) FROM v2_card_detail_api_cache')
    cur.execute('''
        SELECT COUNT(DISTINCT card_key) FROM v10_canonical_printing_cards
    ''')
    mapped_cards = cur.fetchone()[0]

    # Identity counts
    cp_count = _scalar(cur, 'SELECT COUNT(*) FROM v10_canonical_printings')
    cv_count = _scalar(cur, 'SELECT COUNT(*) FROM v10_commercial_variants')
    sku_count = _scalar(cur, 'SELECT COUNT(*) FROM v10_sellable_skus')
    er_count = _scalar(cur, 'SELECT COUNT(*) FROM v10_external_references')
    link_count = _scalar(cur, 'SELECT COUNT(*) FROM v10_canonical_printing_cards')

    # Confidence distribution
    cur.execute('SELECT confidence_label, COUNT(*) as cnt FROM v10_canonical_printings GROUP BY confidence_label ORDER BY cnt DESC')
    confidence = {row['confidence_label']: row['cnt'] for row in cur.fetchall()}

    # Finish distribution
    cur.execute('SELECT finish, COUNT(*) as cnt FROM v10_commercial_variants GROUP BY finish ORDER BY cnt DESC')
    finish_dist = {row['finish']: row['cnt'] for row in cur.fetchall()}

    # Item class distribution
    cur.execute('SELECT item_class, COUNT(*) as cnt FROM v10_sellable_skus GROUP BY item_class ORDER BY cnt DESC')
    item_classes = {row['item_class']: row['cnt'] for row in cur.fetchall()}

    # Unknown finish count
    unknown_finish = finish_dist.get('unknown', 0)

    # Top unmapped languages
    cur.execute('''
        SELECT language_code, COUNT(*) as cnt
        FROM v2_card_detail_api_cache
        WHERE card_id NOT IN (SELECT source_card_id FROM v10_canonical_printing_cards)
        GROUP BY language_code
        ORDER BY cnt DESC
        LIMIT ?
    ''', (limit,))
    unmapped_langs = [{'language_code': row['language_code'], 'count': row['cnt']} for row in cur.fetchall()]

    # Top unmapped sets
    cur.execute('''
        SELECT core_set_id, COUNT(*) as cnt
        FROM v2_card_detail_api_cache
        WHERE card_id NOT IN (SELECT source_card_id FROM v10_canonical_printing_cards)
        GROUP BY core_set_id
        ORDER BY cnt DESC
        LIMIT ?
    ''', (limit,))
    unmapped_sets = [{'core_set_id': row['core_set_id'], 'count': row['cnt']} for row in cur.fetchall()]

    # Low-confidence reasons
    cur.execute('''
        SELECT confidence_reason, COUNT(*) as cnt
        FROM v10_canonical_printings
        WHERE confidence_label = 'LOW'
        GROUP BY confidence_reason
        ORDER BY cnt DESC
        LIMIT ?
    ''', (limit,))
    low_confidence_reasons = [{'reason': row['confidence_reason'], 'count': row['cnt']} for row in cur.fetchall()]

    # Last build run
    cur.execute('SELECT * FROM v10_identity_build_runs ORDER BY started_at DESC LIMIT 1')
    last_run = cur.fetchone()
    last_build = None
    if last_run:
        last_build = {
            'build_run_id': last_run['build_run_id'],
            'started_at': last_run['started_at'],
            'status': last_run['status'],
            'cards_seen': last_run['cards_seen'],
            'canonical_printings_created': last_run['canonical_printings_created'],
            'notes': last_run['notes'],
        }

    return {
        'total_cards': total_cards,
        'mapped_cards': mapped_cards,
        'unmapped_cards': total_cards - mapped_cards,
        'canonical_printings': cp_count,
        'commercial_variants': cv_count,
        'sellable_skus': sku_count,
        'external_references': er_count,
        'card_links': link_count,
        'confidence_distribution': confidence,
        'unknown_finish_count': unknown_finish,
        'variants_by_finish': finish_dist,
        'skus_by_item_class': item_classes,
        'top_unmapped_languages': unmapped_langs,
        'top_unmapped_sets': unmapped_sets,
        'low_confidence_reasons': low_confidence_reasons,
        'last_build_run': last_build,
    }


def format_markdown(report: dict[str, Any], limit: int = 20) -> str:
    lines = [
        '# v10 Identity Quality Report',
        '',
        'Auto-generated by `scripts/report_v10_identity_quality.py`.',
        '',
        '## Summary',
        '',
        f'| Metric | Count |',
        f'|--------|-------|',
        f'| Total cards | {report["total_cards"]:,} |',
        f'| Mapped cards | {report["mapped_cards"]:,} |',
        f'| Unmapped cards | {report["unmapped_cards"]:,} |',
        f'| Canonical printings | {report["canonical_printings"]:,} |',
        f'| Card links | {report["card_links"]:,} |',
        f'| Commercial variants | {report["commercial_variants"]:,} |',
        f'| Sellable SKUs | {report["sellable_skus"]:,} |',
        f'| External references | {report["external_references"]:,} |',
        f'| Unknown finish | {report["unknown_finish_count"]:,} |',
        '',
        '## Confidence Distribution',
        '',
        '| Label | Count |',
        '|-------|-------|',
    ]
    for label, count in report['confidence_distribution'].items():
        lines.append(f'| {label} | {count:,} |')

    lines.extend(['', '## Variants by Finish', '', '| Finish | Count |', '|--------|-------|'])
    for finish, count in report['variants_by_finish'].items():
        lines.append(f'| {finish} | {count:,} |')

    lines.extend(['', '## SKUs by Item Class', '', '| Class | Count |', '|--------|-------|'])
    for cls, count in report['skus_by_item_class'].items():
        lines.append(f'| {cls} | {count:,} |')

    if report['top_unmapped_languages']:
        lines.extend(['', '## Top Unmapped Languages', '', '| Language | Count |', '|----------|-------|'])
        for item in report['top_unmapped_languages'][:limit]:
            lines.append(f'| {item["language_code"]} | {item["count"]:,} |')

    if report['top_unmapped_sets']:
        lines.extend(['', '## Top Unmapped Sets', '', '| Set | Count |', '|------|-------|'])
        for item in report['top_unmapped_sets'][:limit]:
            lines.append(f'| {item["core_set_id"]} | {item["count"]:,} |')

    if report['last_build_run']:
        build = report['last_build_run']
        lines.extend([
            '', '## Last Build Run', '',
            f'- **Build ID**: {build["build_run_id"]}',
            f'- **Started**: {build["started_at"]}',
            f'- **Status**: {build["status"]}',
            f'- **Cards seen**: {build["cards_seen"]:,}',
            f'- **Notes**: {build["notes"]}',
        ])
    else:
        lines.extend(['', '## Last Build Run', '', '*No build runs recorded.*'])

    lines.extend(['', '## Quality Status', ''])
    unmapped = report['unmapped_cards']
    total = report['total_cards']
    if total > 0:
        pct = round(100 * unmapped / total, 1)
        lines.append(f'- Coverage: {100 - pct:.1f}% mapped ({unmapped:,} unmapped)')
    lines.append(f'- Unknown finish: {report["unknown_finish_count"]:,} variants')
    lines.append('')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Generate v10 identity quality report.')
    parser.add_argument('--db', required=True, type=Path, help='SQLite database path.')
    parser.add_argument('--json', action='store_true', help='Output as JSON.')
    parser.add_argument('--markdown', action='store_true', help='Output as markdown.')
    parser.add_argument('--limit', type=int, default=20, help='Max rows in top-N lists.')
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f'ERROR: Database not found: {args.db}', file=sys.stderr)
        return 1

    try:
        conn = _connect(args.db)
    except Exception as e:
        print(f'ERROR: Cannot connect: {e}', file=sys.stderr)
        return 1

    try:
        report = generate_report(conn, limit=args.limit)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    elif args.markdown:
        print(format_markdown(report, limit=args.limit))
    else:
        print('v10 Identity Quality Summary')
        print('=' * 40)
        for key in ['total_cards', 'mapped_cards', 'unmapped_cards',
                     'canonical_printings', 'card_links', 'commercial_variants',
                     'sellable_skus', 'external_references', 'unknown_finish_count']:
            val = report[key]
            print(f'  {key}: {val:,}')
        print()
        print('  confidence_distribution:')
        for label, count in report['confidence_distribution'].items():
            print(f'    {label}: {count:,}')
        if report['last_build_run']:
            print(f'  last_build_run: {report["last_build_run"]["build_run_id"]} ({report["last_build_run"]["status"]})')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
