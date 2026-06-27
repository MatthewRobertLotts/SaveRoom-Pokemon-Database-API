#!/usr/bin/env python3
"""v9.2 backup and database verification script tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from backup_database import backup_database
from verify_database import verify_database


def _minimal_app_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute('CREATE TABLE cards(id TEXT)')
        cur.execute('CREATE TABLE sets(id TEXT)')
        cur.execute('CREATE TABLE languages(code TEXT)')
        cur.execute('CREATE TABLE v2_card_search_fts(language_code TEXT, card_id TEXT)')
        cur.execute('CREATE TABLE v2_card_detail_api_cache(language_code TEXT, card_id TEXT)')
        conn.commit()
    finally:
        conn.close()


def test_verify_database_requires_existing_file(tmp_path):
    missing = tmp_path / 'missing.sqlite'
    try:
        verify_database(missing)
    except FileNotFoundError as exc:
        assert 'does not exist' in str(exc)
    else:
        raise AssertionError('verify_database accepted a missing file')


def test_verify_database_reports_required_table_counts(tmp_path):
    db = tmp_path / 'ok.sqlite'
    _minimal_app_db(db)

    result = verify_database(db)

    assert result['integrity_check'] == 'ok'
    assert result['required_tables_present'] is True
    assert result['counts']['cards'] == 0


def test_backup_database_refuses_to_overwrite(tmp_path):
    db = tmp_path / 'source.sqlite'
    _minimal_app_db(db)
    dest = tmp_path / 'backup.sqlite'
    dest.write_text('already here')

    try:
        backup_database(db, dest)
    except FileExistsError as exc:
        assert 'already exists' in str(exc)
    else:
        raise AssertionError('backup_database overwrote an existing file')


def test_backup_database_creates_verified_backup_and_metadata(tmp_path):
    db = tmp_path / 'source.sqlite'
    _minimal_app_db(db)
    dest = tmp_path / 'backup.sqlite'

    result = backup_database(db, dest)

    assert Path(result['destination_path']).exists()
    assert Path(result['metadata_path']).exists()
    assert result['integrity_check'] == 'ok'
    assert result['backup_size_bytes'] > 0
