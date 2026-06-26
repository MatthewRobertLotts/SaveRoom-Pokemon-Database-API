#!/usr/bin/env python3
"""Create a consistent SQLite backup with metadata."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from verify_database import verify_database


def _default_destination(source: Path, backup_dir: Path | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    parent = backup_dir or source.parent / 'backups'
    return parent / f'{source.stem}.backup-{stamp}{source.suffix}'


def backup_database(source: Path, destination: Path | None = None, *, backup_dir: Path | None = None) -> dict[str, Any]:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f'Source database does not exist or is not a file: {source}')
    dest = destination or _default_destination(source, backup_dir)
    if dest.exists():
        raise FileExistsError(f'Backup destination already exists: {dest}')
    dest.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    src_conn = sqlite3.connect(str(source), timeout=30)
    try:
        src_conn.execute('PRAGMA busy_timeout=30000')
        dest_conn = sqlite3.connect(str(dest), timeout=30)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    verification = verify_database(dest, require_tables=False)
    finished_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    metadata = {
        'source_path': str(source.resolve()),
        'destination_path': str(dest.resolve()),
        'started_at': started_at,
        'finished_at': finished_at,
        'source_size_bytes': source.stat().st_size,
        'backup_size_bytes': dest.stat().st_size,
        'integrity_check': verification['integrity_check'],
        'foreign_key_check_count': verification['foreign_key_check_count'],
    }
    meta_path = dest.with_suffix(dest.suffix + '.metadata.json')
    if meta_path.exists():
        raise FileExistsError(f'Metadata destination already exists: {meta_path}')
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n')
    metadata['metadata_path'] = str(meta_path.resolve())
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Safely back up a SaveRoom Pokémon SQLite database.')
    parser.add_argument('source', type=Path, help='Source SQLite database.')
    parser.add_argument('destination', nargs='?', type=Path, help='Optional exact backup destination. Must not already exist.')
    parser.add_argument('--backup-dir', type=Path, help='Directory for timestamped backup when destination is omitted.')
    parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON.')
    args = parser.parse_args(argv)

    try:
        result = backup_database(args.source, args.destination, backup_dir=args.backup_dir)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Source: {result['source_path']}")
        print(f"Destination: {result['destination_path']}")
        print(f"Started: {result['started_at']}")
        print(f"Finished: {result['finished_at']}")
        print(f"Source size bytes: {result['source_size_bytes']}")
        print(f"Backup size bytes: {result['backup_size_bytes']}")
        print(f"Integrity check: {result['integrity_check']}")
        print(f"Foreign-key check rows: {result['foreign_key_check_count']}")
        print(f"Metadata: {result['metadata_path']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
