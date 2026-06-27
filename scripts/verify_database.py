#!/usr/bin/env python3
"""Verify a SaveRoom Pokémon SQLite database without mutating it."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REQUIRED_TABLES = (
    'cards',
    'sets',
    'languages',
    'v2_card_search_fts',
    'v2_card_detail_api_cache',
)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = 'file:' + str(path.resolve()) + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def verify_database(path: Path, *, require_tables: bool = True) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f'Database does not exist: {path}')
    if not path.is_file():
        raise ValueError(f'Database path is not a file: {path}')

    with _connect_readonly(path) as conn:
        cur = conn.cursor()
        integrity = cur.execute('PRAGMA integrity_check').fetchone()[0]
        fk_rows = cur.execute('PRAGMA foreign_key_check').fetchall()
        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(set(REQUIRED_TABLES) - tables) if require_tables else []
        if integrity != 'ok':
            raise RuntimeError(f'Integrity check failed for {path}: {integrity}')
        if missing:
            raise RuntimeError(f'Database missing required table(s): {", ".join(missing)}')
        counts: dict[str, int] = {}
        for table in sorted(tables & set(REQUIRED_TABLES)):
            counts[table] = int(cur.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
        return {
            'path': str(path.resolve()),
            'size_bytes': path.stat().st_size,
            'integrity_check': integrity,
            'foreign_key_check_count': len(fk_rows),
            'required_tables_present': not missing,
            'counts': counts,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Verify a SaveRoom Pokémon SQLite database.')
    parser.add_argument('database', type=Path, help='SQLite database path to verify.')
    parser.add_argument('--no-required-tables', action='store_true', help='Only run SQLite checks; do not require app tables.')
    parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON.')
    args = parser.parse_args(argv)

    try:
        result = verify_database(args.database, require_tables=not args.no_required_tables)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Database: {result['path']}")
        print(f"Size bytes: {result['size_bytes']}")
        print(f"Integrity check: {result['integrity_check']}")
        print(f"Foreign-key check rows: {result['foreign_key_check_count']}")
        print(f"Required tables present: {result['required_tables_present']}")
        for table, count in result['counts'].items():
            print(f'{table}: {count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
