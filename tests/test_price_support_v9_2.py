#!/usr/bin/env python3
"""v9.2 price schema idempotency/concurrency regression tests."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from pokemon_db_v2_fastapi import (
    PRICE_HISTORY_V4_COLUMNS,
    PRICE_HISTORY_V5_COLUMNS,
    ensure_price_support,
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _expected_history_columns() -> set[str]:
    return {
        'id', 'card_id', 'language_code', 'condition', 'price_gbp', 'sold_date',
        'listing_url', 'source', 'confidence_score', 'imported_at',
        *PRICE_HISTORY_V4_COLUMNS.keys(),
        *PRICE_HISTORY_V5_COLUMNS.keys(),
    }


def test_ensure_price_support_repeated_idempotency(tmp_path):
    db = tmp_path / 'prices.sqlite'
    conn = _connect(db)
    try:
        for _ in range(5):
            ensure_price_support(conn)
        history_cols = _columns(conn, 'uk_price_history')
        cache_cols = _columns(conn, 'uk_price_fetch_cache')
    finally:
        conn.close()

    assert _expected_history_columns() <= history_cols
    assert 'algorithm_version' in cache_cols
    assert len(history_cols) == len(set(history_cols))


def test_ensure_price_support_upgrades_partial_existing_schema(tmp_path):
    db = tmp_path / 'partial.sqlite'
    conn = _connect(db)
    try:
        conn.executescript("""
            CREATE TABLE uk_price_history (
                id INTEGER PRIMARY KEY,
                card_id TEXT NOT NULL,
                language_code TEXT,
                condition TEXT,
                price_gbp REAL NOT NULL,
                sold_date TEXT NOT NULL,
                listing_url TEXT,
                source TEXT DEFAULT 'ebay_uk',
                confidence_score REAL,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
                raw_title TEXT,
                ebay_item_id TEXT
            );
            CREATE TABLE uk_price_fetch_cache (
                cache_key TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                response_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO uk_price_history(card_id, language_code, price_gbp, sold_date, raw_title, ebay_item_id) VALUES (?, ?, ?, ?, ?, ?)",
            ('base1-1', 'en', 12.34, '2026-01-01', 'Charizard listing', '1234567890'),
        )
        conn.commit()

        ensure_price_support(conn)
        ensure_price_support(conn)
        history_cols = _columns(conn, 'uk_price_history')
        cache_cols = _columns(conn, 'uk_price_fetch_cache')
        row = conn.execute('SELECT raw_title, ebay_item_id FROM uk_price_history WHERE card_id=?', ('base1-1',)).fetchone()
    finally:
        conn.close()

    assert _expected_history_columns() <= history_cols
    assert 'algorithm_version' in cache_cols
    assert row == ('Charizard listing', '1234567890')


def test_ensure_price_support_lightweight_concurrency(tmp_path):
    db = tmp_path / 'concurrent.sqlite'

    def worker() -> set[str]:
        conn = _connect(db)
        try:
            ensure_price_support(conn)
            return _columns(conn, 'uk_price_history')
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [future.result() for future in as_completed(pool.submit(worker) for _ in range(16))]

    assert results
    expected = _expected_history_columns()
    for cols in results:
        assert expected <= cols

    conn = _connect(db)
    try:
        assert expected <= _columns(conn, 'uk_price_history')
        assert 'algorithm_version' in _columns(conn, 'uk_price_fetch_cache')
    finally:
        conn.close()
