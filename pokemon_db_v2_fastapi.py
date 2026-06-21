#!/usr/bin/env python3
"""Tiny local FastAPI service for the v2 Pokémon card database search layer.

Endpoints:
- GET /health
- GET /search?q=charizard&limit=20
- GET /sets/{core_set_id}/cards
- GET /cards/{language_code}/{card_id}
- GET /reports/coverage

This app is read-mostly. It uses the support objects created by
pokemon_db_v2_search_api.py (`v2_card_search_fts` and
`v2_card_detail_api_cache`). If they are missing or stale, startup refreshes
those support objects from the v2 views; it does not mutate raw card facts.
"""
from __future__ import annotations
import json
import os

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pokemon_db_v2_search_api import (  # noqa: E402
    CACHE_TABLE,
    FTS_TABLE,
    connect,
    get_card_detail,
    normalize_row,
    rows,
    scalar,
    search_cards,
    setup_fts,
)
from pokemon_db_v3_config import (  # noqa: E402
    PokemonDBSettings,
    add_common_args,
    public_settings,
    settings_from_args,
    settings_from_env,
    startup_lines,
    validate_settings,
)

DEFAULT_SETTINGS = settings_from_env()
STARTED_AT = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def object_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return bool(scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (name,)))


def ensure_search_support(db: Path, *, reports_dir: Path | None = None) -> dict[str, Any]:
    """Ensure FTS/cache support exists and is row-count aligned with v2 views."""
    conn = connect(db)
    cur = conn.cursor()
    required = [FTS_TABLE, CACHE_TABLE]
    needs_setup = any(not object_exists(cur, name) for name in required)
    v2_rows = scalar(cur, 'SELECT COUNT(*) FROM v2_card_search')
    if not needs_setup:
        fts_rows = scalar(cur, f'SELECT COUNT(*) FROM {FTS_TABLE}')
        cache_rows = scalar(cur, f'SELECT COUNT(*) FROM {CACHE_TABLE}')
        needs_setup = not (fts_rows == cache_rows == v2_rows)
    if needs_setup:
        return {'refreshed': True, **setup_fts(db, reports_dir=reports_dir)}
    return {
        'refreshed': False,
        'database': str(db),
        'fts_table': FTS_TABLE,
        'api_cache_table': CACHE_TABLE,
        'fts_rows': scalar(cur, f'SELECT COUNT(*) FROM {FTS_TABLE}'),
        'api_cache_rows': scalar(cur, f'SELECT COUNT(*) FROM {CACHE_TABLE}'),
        'v2_card_search_rows': v2_rows,
        'row_count_matches': True,
    }


def db_counts(db: Path) -> dict[str, Any]:
    """Fast health counts from materialized support objects only."""
    conn = connect(db)
    cur = conn.cursor()
    out: dict[str, Any] = {}
    for table in (FTS_TABLE, CACHE_TABLE):
        out[table] = scalar(cur, f'SELECT COUNT(*) FROM {table}') if object_exists(cur, table) else None
    out['v2_card_search'] = scalar(cur, 'SELECT COUNT(*) FROM v2_card_search') if object_exists(cur, 'v2_card_search') else None
    out['support_ready'] = bool(out.get(FTS_TABLE) and out.get(FTS_TABLE) == out.get(CACHE_TABLE))
    return out




PRICE_HISTORY_V4_COLUMNS = {
    'raw_title': 'TEXT',
    'bucket': 'TEXT',
    'match_notes': 'TEXT',
    'query': 'TEXT',
    'source_site': 'TEXT',
    'is_recommended_input': 'INTEGER DEFAULT 0',
    'cache_key': 'TEXT',
    'fetched_at': 'TEXT',
}

LANGUAGE_QUERY_HINTS = {
    'en': 'English', 'ja': 'Japanese', 'ko': 'Korean', 'zh-tw': 'Traditional Chinese',
    'zh-cn': 'Simplified Chinese', 'id': 'Indonesian', 'th': 'Thai', 'de': 'German',
    'fr': 'French', 'it': 'Italian', 'es': 'Spanish', 'pt': 'Portuguese',
    'pt-br': 'Brazilian Portuguese', 'es-mx': 'Mexican Spanish',
}

HIGH_VALUE_NAME_TERMS = [
    'Charizard', 'Pikachu', 'Umbreon', 'Espeon', 'Gengar', 'Mew', 'Mewtwo', 'Rayquaza',
    'Lugia', 'Giratina', 'Dragonite', 'Eevee', 'Sylveon', 'Blastoise', 'Venusaur',
    'Arceus', 'Kyogre', 'Groudon', 'Ho-Oh', 'Celebi', 'Darkrai', 'Lucario', 'Gardevoir',
    'Garchomp', 'Metagross', 'Blaziken',
]

HIGH_VALUE_RARITY_TERMS = [
    'rare', 'ultra rare', 'secret rare', 'illustration rare', 'special illustration rare',
    'hyper rare', 'holo rare', ' v', 'vmax', 'vstar', ' ex', ' gx', 'lv.x',
]


def ensure_price_support(conn: sqlite3.Connection) -> None:
    """Create/upgrade local-only price tables without destroying existing data."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uk_price_history (
            id INTEGER PRIMARY KEY,
            card_id TEXT NOT NULL,
            language_code TEXT,
            condition TEXT,
            price_gbp REAL NOT NULL,
            sold_date TEXT NOT NULL,
            listing_url TEXT,
            source TEXT DEFAULT 'ebay_uk',
            confidence_score REAL,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    existing = {r[1] for r in cur.execute('PRAGMA table_info(uk_price_history)').fetchall()}
    for column, ddl in PRICE_HISTORY_V4_COLUMNS.items():
        if column not in existing:
            cur.execute(f'ALTER TABLE uk_price_history ADD COLUMN {column} {ddl}')
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uk_price_fetch_cache (
            cache_key TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            language_code TEXT,
            card_id TEXT,
            response_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            source TEXT DEFAULT 'rapidapi_ebay_average_selling_price'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uk_price_fetch_usage (
            id INTEGER PRIMARY KEY,
            query TEXT NOT NULL,
            language_code TEXT,
            card_id TEXT,
            status TEXT NOT NULL,
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uk_price_scrape_failures (
            id INTEGER PRIMARY KEY,
            card_id TEXT,
            language_code TEXT,
            query TEXT,
            reason TEXT,
            raw_title TEXT,
            listing_url TEXT,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_uk_price_history_card ON uk_price_history(card_id, language_code)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_uk_price_history_bucket ON uk_price_history(bucket, is_recommended_input)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_uk_price_fetch_usage_requested ON uk_price_fetch_usage(requested_at, status)')
    conn.commit()


def current_price_usage(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_price_support(conn)
    cur = conn.cursor()
    monthly_limit = int(os.environ.get('POKEMON_PRICE_MONTHLY_LIMIT', '1400'))
    month_start = dt.datetime.now(dt.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    used_this_month = int(scalar(cur, "SELECT COUNT(*) FROM uk_price_fetch_usage WHERE status = 'ok' AND requested_at >= ?", (month_start,)) or 0)
    return {
        'month_start': month_start,
        'used_this_month': used_this_month,
        'monthly_limit': monthly_limit,
        'remaining_before_guard': max(0, monthly_limit - used_this_month),
        'close_to_guard': used_this_month >= int(monthly_limit * 0.9),
        'guard_reached': used_this_month >= monthly_limit,
    }


def build_price_query(card: dict[str, Any]) -> str:
    name = str(card.get('name') or card.get('card_name') or '').replace('[', ' ').replace(']', ' ').strip()
    number = str(card.get('collector_number') or card.get('local_id') or '').replace('/', ' ').strip()
    set_name = str(card.get('core_set_name') or card.get('resolved_set_name') or card.get('core_set_id') or '').strip()
    language_code = str(card.get('language_code') or '').strip()
    query = name
    if number:
        query += f' {number}'
    if set_name and set_name.lower() not in query.lower():
        query += f' {set_name}'
    if language_code and language_code != 'en':
        query += f' {LANGUAGE_QUERY_HINTS.get(language_code, language_code)}'
    return ' '.join((query + ' Pokémon card').split())


def price_cache_key(query: str, language: str | None, max_results: int) -> str:
    return '|'.join([query.strip().lower(), str(language or '').lower(), str(max_results)])


def price_cache_is_fresh(conn: sqlite3.Connection, cache_key: str) -> bool:
    ensure_price_support(conn)
    cache_ttl_hours = int(os.environ.get('POKEMON_PRICE_CACHE_TTL_HOURS', '168'))
    cur = conn.cursor()
    cur.execute("""SELECT 1 FROM uk_price_fetch_cache WHERE cache_key = ? AND datetime(fetched_at) >= datetime('now', ?)""", (cache_key, f'-{cache_ttl_hours} hours'))
    return cur.fetchone() is not None


def persist_price_history(
    conn: sqlite3.Connection,
    *,
    products: list[dict[str, Any]],
    card_id: str | None,
    language_code: str | None,
    query: str,
    cache_key: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Persist cleaned/enriched listings, keeping non-raw buckets auditable and deduped."""
    ensure_price_support(conn)
    cur = conn.cursor()
    inserted = 0
    duplicates = 0
    skipped = 0
    recommended = 0
    for product in products:
        price = product.get('price_gbp')
        if card_id is None or price is None:
            skipped += 1
            continue
        sold_date = str(product.get('sold_date') or fetched_at[:10])
        listing_url = product.get('listing_url')
        raw_title = product.get('title') or product.get('raw_title') or ''
        bucket = product.get('bucket') or 'raw'
        score = product.get('confidence_score')
        is_recommended_input = 1 if bucket == 'raw' and (score is None or float(score) >= 0.55) else 0
        if is_recommended_input:
            recommended += 1
        cur.execute("""
            SELECT id FROM uk_price_history
            WHERE card_id = ?
              AND COALESCE(language_code, '') = COALESCE(?, '')
              AND COALESCE(listing_url, '') = COALESCE(?, '')
              AND sold_date = ?
              AND ROUND(price_gbp, 2) = ROUND(?, 2)
            LIMIT 1
        """, (card_id, language_code, listing_url, sold_date, price))
        if cur.fetchone():
            duplicates += 1
            continue
        cur.execute("""
            INSERT INTO uk_price_history(
                card_id, language_code, condition, price_gbp, sold_date, listing_url, source,
                confidence_score, raw_title, bucket, match_notes, query, source_site,
                is_recommended_input, cache_key, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            card_id, language_code, product.get('condition'), price, sold_date, listing_url,
            'ebay_uk_sold', score, raw_title, bucket,
            json.dumps(product.get('match_notes') or [], ensure_ascii=False), query,
            'rapidapi_ebay_average_selling_price', is_recommended_input, cache_key, fetched_at,
        ))
        inserted += 1
    if card_id and inserted == 0 and not any(p.get('bucket') == 'raw' and p.get('price_gbp') is not None for p in products):
        cur.execute("""
            INSERT INTO uk_price_scrape_failures(card_id, language_code, query, reason)
            VALUES (?, ?, ?, ?)
        """, (card_id, language_code, query, 'no_language_specific_raw_price_evidence' if language_code and language_code != 'en' else 'no_usable_raw_listings'))
    conn.commit()
    return {'inserted': inserted, 'duplicates': duplicates, 'skipped': skipped, 'recommended_inputs': recommended}

def _public_support_status(status: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in status.items() if k != 'database'}


def create_app(settings: PokemonDBSettings | None = None) -> FastAPI:
    settings = validate_settings(settings or DEFAULT_SETTINGS, require_ui=False)
    app = FastAPI(
        title='SaveRoom Pokémon Card Database v2 API',
        version='0.2.0',
        description='Local API over v2_card_search, v2_card_detail, FTS5, and product-ready image fields.',
    )
    app.state.settings = settings
    app.state.db = settings.db
    app.state.support_status = ensure_search_support(settings.db, reports_dir=settings.reports_dir)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=['GET', 'POST'],
            allow_headers=['*'],
        )
    if settings.ui_dir.exists():
        app.mount('/ui', StaticFiles(directory=str(settings.ui_dir), html=True), name='ui')
    if settings.image_cache_mounted:
        app.mount('/images', StaticFiles(directory=str(settings.image_cache_dir)), name='images')

    @app.get('/', response_class=HTMLResponse)
    def index() -> str:
        return """
<!doctype html><meta charset="utf-8"><title>SaveRoom Pokémon DB API</title>
<h1>SaveRoom Pokémon DB API</h1>
<ul>
  <li><a href="/ui/">Browser search UI</a></li>
  <li><a href="/health">/health</a></li>
  <li><a href="/search?q=charizard&limit=20">/search?q=charizard&limit=20</a></li>
  <li><a href="/search?q=pikachu%20japanese&limit=20">/search?q=pikachu japanese&limit=20</a></li>
  <li><a href="/sets/svp/cards?limit=20">/sets/svp/cards?limit=20</a></li>
  <li><a href="/cards/en/ex3-100">/cards/en/ex3-100</a></li>
  <li><a href="/reports/coverage">/reports/coverage</a></li>
  <li><a href="/docs">OpenAPI docs</a></li>
</ul>
"""

    @app.get('/health')
    def health() -> dict[str, Any]:
        start = time.perf_counter()
        counts = db_counts(app.state.db)
        return {
            'ok': counts['support_ready'],
            'service': 'saveroom-pokemon-v2-api',
            'started_at': STARTED_AT,
            'checked_at': now_utc(),
            'runtime': public_settings(app.state.settings),
            'support_status': _public_support_status(app.state.support_status),
            'local_image_cache': {
                'mounted': app.state.settings.image_cache_mounted,
                'url_prefix': '/images' if app.state.settings.image_cache_mounted else None,
            },
            'counts': counts,
            'elapsed_ms': round((time.perf_counter() - start) * 1000, 3),
        }

    @app.get('/search')
    def search(
        q: str = Query('', description='FTS search query, e.g. charizard or pikachu japanese.'),
        limit: int = Query(20, ge=1, le=200),
        language_code: str | None = Query(None),
        set_id: str | None = Query(None, description='Raw or resolved set id.'),
        core_set_id: str | None = Query(None, description='Normalized core set id.'),
        has_display_image: bool | None = Query(None),
        include_prices: bool = Query(False, description='Include price summary for each result'),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        results, elapsed_ms = search_cards(
            conn,
            q,
            language_code=language_code,
            set_id=set_id,
            core_set_id=core_set_id,
            has_display_image=has_display_image,
            limit=limit,
        )
        if include_prices and results:
            conn2 = conn
            card_ids = [r.get('card_id') for r in results if r.get('card_id')]
            if card_ids:
                placeholders = ','.join('?' * len(card_ids))
                price_rows = rows(conn2, f'''
                    SELECT card_id,
                        SUM(CASE WHEN source='ebay_uk_sold' THEN 1 ELSE 0 END) as sold_n,
                        ROUND(AVG(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2) as sold_avg
                    FROM uk_price_history
                    WHERE card_id IN ({placeholders})
                    GROUP BY card_id
                ''', card_ids)
                price_map = {r['card_id']: r for r in price_rows}
                for r in results:
                    p = price_map.get(r.get('card_id', ''))
                    if p and p['sold_n']:
                        r['price'] = {'sold_listings': p['sold_n'], 'sold_avg': p['sold_avg']}

        return {
            'query': q,
            'filters': {
                'language_code': language_code,
                'set_id': set_id,
                'core_set_id': core_set_id,
                'has_display_image': has_display_image,
            },
            'limit': limit,
            'count': len(results),
            'elapsed_ms': round(elapsed_ms, 3),
            'results': results,
        }

    @app.get('/sets/{core_set_id}/cards')
    def set_cards(
        core_set_id: str,
        q: str = Query('', description='Optional within-set search query.'),
        limit: int = Query(50, ge=1, le=500),
        language_code: str | None = Query(None),
        has_display_image: bool | None = Query(None),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        results, elapsed_ms = search_cards(
            conn,
            q,
            language_code=language_code,
            core_set_id=core_set_id,
            has_display_image=has_display_image,
            limit=limit,
        )
        return {
            'core_set_id': core_set_id,
            'query': q,
            'filters': {
                'language_code': language_code,
                'has_display_image': has_display_image,
            },
            'limit': limit,
            'count': len(results),
            'elapsed_ms': round(elapsed_ms, 3),
            'results': results,
        }

    @app.get('/cards/{language_code}/{card_id}')
    def card_detail(language_code: str, card_id: str) -> dict[str, Any]:
        conn = connect(app.state.db)
        detail, elapsed_ms = get_card_detail(conn, language_code, card_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f'Card not found: {language_code}/{card_id}')
        result = {
            'language_code': language_code,
            'card_id': card_id,
            'elapsed_ms': round(elapsed_ms, 3),
            'detail': detail,
        }
        # Attach price summary
        try:
            cur = conn.cursor()
            cur.execute('''
                SELECT
                    SUM(CASE WHEN source='ebay_uk_sold' THEN 1 ELSE 0 END),
                    ROUND(AVG(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2),
                    ROUND(MIN(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2),
                    ROUND(MAX(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2),
                    SUM(CASE WHEN source='ebay_uk' THEN 1 ELSE 0 END),
                    ROUND(AVG(CASE WHEN source='ebay_uk' THEN price_gbp END), 2)
                FROM uk_price_history WHERE card_id = ?
            ''', (card_id,))
            pr = cur.fetchone()
            if pr and (pr[0] or pr[4]):
                result['prices'] = {
                    'sold_listings': pr[0] or 0,
                    'sold_avg': pr[1],
                    'sold_min': pr[2],
                    'sold_max': pr[3],
                    'active_listings': pr[4] or 0,
                    'active_avg': pr[5],
                }
        except Exception:
            pass
        return result

    @app.get('/reports/coverage')
    def coverage() -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        start = time.perf_counter()
        total = scalar(cur, f'SELECT COUNT(*) FROM {CACHE_TABLE}')
        image = rows(cur, f'''
            SELECT
              COUNT(*) AS total_rows,
              SUM(CASE WHEN has_exact_image=1 THEN 1 ELSE 0 END) AS rows_with_exact_image,
              SUM(CASE WHEN has_display_image=1 THEN 1 ELSE 0 END) AS rows_with_display_image,
              SUM(CASE WHEN has_display_image=0 THEN 1 ELSE 0 END) AS rows_without_display_image
            FROM {CACHE_TABLE}
        ''')[0]
        readiness = rows(cur, f'''
            SELECT bucket, COUNT(*) AS rows FROM (
              SELECT CASE
                WHEN has_display_image=1
                  AND COALESCE(resolved_set_name, core_set_name, resolved_set_id, core_set_id) IS NOT NULL
                  AND (attacks IS NOT NULL OR description IS NOT NULL OR rarity IS NOT NULL OR hp IS NOT NULL OR types IS NOT NULL)
                  AND (COALESCE(provenance_record_count,0) + COALESCE(legacy_provenance_count,0)) > 0
                  THEN 'ready'
                WHEN has_display_image=1
                  AND COALESCE(resolved_set_name, core_set_name, resolved_set_id, core_set_id) IS NOT NULL
                  THEN 'usable'
                WHEN has_display_image=0 THEN 'needs_image'
                WHEN attacks IS NULL AND description IS NULL AND rarity IS NULL AND hp IS NULL AND types IS NULL
                  THEN 'needs_detail_enrichment'
                WHEN (COALESCE(provenance_record_count,0) + COALESCE(legacy_provenance_count,0)) = 0
                  THEN 'provenance_weak'
                ELSE 'not_product_ready'
              END AS bucket
              FROM {CACHE_TABLE}
            ) GROUP BY bucket ORDER BY rows DESC
        ''')
        by_language = rows(cur, f'''
            SELECT language_code,
                   COUNT(*) AS total_rows,
                   SUM(CASE WHEN has_display_image=1 THEN 1 ELSE 0 END) AS rows_with_display_image,
                   SUM(CASE WHEN has_display_image=0 THEN 1 ELSE 0 END) AS rows_without_display_image
            FROM {CACHE_TABLE}
            GROUP BY language_code
            ORDER BY rows_without_display_image DESC, total_rows DESC
        ''')
        display_source_types = rows(cur, f'''
            SELECT COALESCE(display_image_source_type, 'none') AS display_image_source_type,
                   COUNT(*) AS rows
            FROM {CACHE_TABLE}
            GROUP BY COALESCE(display_image_source_type, 'none')
            ORDER BY rows DESC
        ''')
        top_needs_image_sets = rows(cur, f'''
            SELECT language_code, core_set_id, core_set_name, resolved_set_id, resolved_set_name,
                   COUNT(*) AS rows_without_display_image
            FROM {CACHE_TABLE}
            WHERE has_display_image=0
            GROUP BY language_code, core_set_id, core_set_name, resolved_set_id, resolved_set_name
            ORDER BY rows_without_display_image DESC
            LIMIT 25
        ''')
        return {
            'generated_at': now_utc(),
            'database_name': app.state.settings.db.name,
            'total_rows': total,
            'image_coverage': image,
            'readiness_buckets': readiness,
            'by_language': by_language,
            'display_image_source_types': display_source_types,
            'top_needs_image_sets': top_needs_image_sets,
            'elapsed_ms': round((time.perf_counter() - start) * 1000, 3),
        }

    # ── Price endpoints ──────────────────────────────────────────────

    @app.get('/api/prices/summary')
    def price_summary(
        card_id: str = Query(..., description='Card ID to get price summary for'),
        language_code: str | None = Query(None),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()
        where = 'card_id = ?'
        params: list[Any] = [card_id]
        if language_code:
            where += ' AND language_code = ?'
            params.append(language_code)
        cur.execute(f'''
            SELECT
                COUNT(*) as total_listings,
                SUM(CASE WHEN source='ebay_uk_sold' THEN 1 ELSE 0 END) as sold_listings,
                SUM(CASE WHEN source='ebay_uk' THEN 1 ELSE 0 END) as active_listings,
                ROUND(AVG(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2) as avg_sold_price,
                ROUND(MIN(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2) as min_sold_price,
                ROUND(MAX(CASE WHEN source='ebay_uk_sold' THEN price_gbp END), 2) as max_sold_price,
                ROUND(AVG(CASE WHEN source='ebay_uk' THEN price_gbp END), 2) as avg_active_price,
                ROUND(MIN(CASE WHEN source='ebay_uk' THEN price_gbp END), 2) as min_active_price,
                ROUND(MAX(CASE WHEN source='ebay_uk' THEN price_gbp END), 2) as max_active_price
            FROM uk_price_history
            WHERE {where}
        ''', params)
        row = cur.fetchone()
        return {
            'card_id': card_id,
            'language_code': language_code,
            'total_listings': row[0] or 0,
            'sold_listings': row[1] or 0,
            'active_listings': row[2] or 0,
            'sold': {'avg': row[3], 'min': row[4], 'max': row[5]},
            'active': {'avg': row[6], 'min': row[7], 'max': row[8]},
        }

    @app.get('/api/prices/history')
    def price_history(
        card_id: str = Query(..., description='Card ID to get price history for'),
        language_code: str | None = Query(None),
        source: str | None = Query(None, description='Filter: ebay_uk_sold or ebay_uk'),
        bucket: str | None = Query(None, description='Filter: raw, graded, bundle, or noise'),
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()
        where = 'card_id = ?'
        params: list[Any] = [card_id]
        if language_code:
            where += ' AND language_code = ?'
            params.append(language_code)
        if source:
            where += ' AND source = ?'
            params.append(source)
        if bucket:
            where += ' AND bucket = ?'
            params.append(bucket)
        params.append(limit)
        cur.execute(f'''
            SELECT id, card_id, language_code, condition, price_gbp, sold_date, listing_url,
                   source, imported_at, raw_title, bucket, confidence_score, match_notes,
                   query, source_site, is_recommended_input, cache_key, fetched_at
            FROM uk_price_history WHERE {where} ORDER BY id DESC LIMIT ?
        ''', params)
        listings = [dict(zip(
            ['id', 'card_id', 'language_code', 'condition', 'price_gbp', 'sold_date', 'listing_url',
             'source', 'imported_at', 'raw_title', 'bucket', 'confidence_score', 'match_notes',
             'query', 'source_site', 'is_recommended_input', 'cache_key', 'fetched_at'], r
        )) for r in cur.fetchall()]
        return {'card_id': card_id, 'language_code': language_code, 'count': len(listings), 'listings': listings}

    @app.get('/api/prices/top')
    def top_priced_cards(
        limit: int = Query(20, ge=1, le=100),
        source: str | None = Query('ebay_uk_sold'),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()
        cur.execute('''
            SELECT card_id, COUNT(*) as n,
                   ROUND(AVG(price_gbp), 2) as avg_price,
                   ROUND(MIN(price_gbp), 2) as min_price,
                   ROUND(MAX(price_gbp), 2) as max_price
            FROM uk_price_history WHERE source = ?
            GROUP BY card_id HAVING n >= 3 ORDER BY avg_price DESC LIMIT ?
        ''', (source, limit))
        cards = [dict(zip(['card_id', 'listings', 'avg_price', 'min_price', 'max_price'], r))
                 for r in cur.fetchall()]
        return {'source': source, 'count': len(cards), 'cards': cards}


    @app.get('/api/prices/usage')
    def price_usage() -> dict[str, Any]:
        conn = connect(app.state.db)
        usage = current_price_usage(conn)
        cur = conn.cursor()
        month_start = usage['month_start']
        by_status = rows(cur, """
            SELECT status, COUNT(*) AS count
            FROM uk_price_fetch_usage
            WHERE requested_at >= ?
            GROUP BY status ORDER BY count DESC
        """, (month_start,))
        return {'generated_at': now_utc(), **usage, 'by_status_this_month': by_status}

    @app.get('/api/prices/dashboard')
    def price_dashboard(limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_price_support(conn)
        usage = current_price_usage(conn)
        cur = conn.cursor()
        cache_count = int(scalar(cur, 'SELECT COUNT(*) FROM uk_price_fetch_cache') or 0)
        history_count = int(scalar(cur, 'SELECT COUNT(*) FROM uk_price_history') or 0)
        distinct_sold_cards = int(scalar(cur, "SELECT COUNT(DISTINCT card_id) FROM uk_price_history WHERE source='ebay_uk_sold'") or 0)
        distinct_active_cards = int(scalar(cur, "SELECT COUNT(DISTINCT card_id) FROM uk_price_history WHERE source='ebay_uk'") or 0)
        cache_hit_count = int(scalar(cur, "SELECT COUNT(*) FROM uk_price_fetch_cache") or 0)
        live_fetch_count = int(scalar(cur, "SELECT COUNT(*) FROM uk_price_fetch_usage WHERE status='ok'") or 0)
        top_cards = rows(cur, """
            WITH recommended AS (
              SELECT card_id, language_code,
                     COUNT(*) AS listing_count,
                     ROUND(AVG(price_gbp), 2) AS avg_price,
                     ROUND(MIN(price_gbp), 2) AS min_price,
                     ROUND(MAX(price_gbp), 2) AS max_price,
                     ROUND(price_gbp, 2) AS sample_price
              FROM uk_price_history
              WHERE source='ebay_uk_sold' AND COALESCE(is_recommended_input, CASE WHEN bucket='raw' THEN 1 ELSE 0 END)=1
              GROUP BY card_id, language_code
            )
            SELECT r.card_id, r.language_code, c.card_name AS name, c.core_set_name, c.local_id AS collector_number,
                   r.listing_count, r.avg_price, r.min_price, r.max_price
            FROM recommended r
            LEFT JOIN v2_card_search c ON c.card_id = r.card_id AND c.language_code = COALESCE(r.language_code, c.language_code)
            ORDER BY r.avg_price DESC LIMIT ?
        """, (limit,))
        if not top_cards:
            top_cards = rows(cur, """
                SELECT h.card_id, h.language_code, c.card_name AS name, c.core_set_name, c.local_id AS collector_number,
                       COUNT(*) AS listing_count, ROUND(AVG(h.price_gbp), 2) AS avg_price,
                       ROUND(MIN(h.price_gbp), 2) AS min_price, ROUND(MAX(h.price_gbp), 2) AS max_price
                FROM uk_price_history h
                LEFT JOIN v2_card_search c ON c.card_id = h.card_id AND c.language_code = COALESCE(h.language_code, c.language_code)
                WHERE h.source='ebay_uk_sold'
                GROUP BY h.card_id, h.language_code
                ORDER BY avg_price DESC LIMIT ?
            """, (limit,))
        recently_fetched = rows(cur, """
            SELECT cache_key, query, language_code, card_id, fetched_at, source
            FROM uk_price_fetch_cache ORDER BY datetime(fetched_at) DESC LIMIT ?
        """, (limit,))
        recent_failures = rows(cur, """
            SELECT card_id, language_code, query, reason, raw_title, listing_url, imported_at
            FROM uk_price_scrape_failures ORDER BY id DESC LIMIT ?
        """, (limit,))
        bucket_counts = rows(cur, """
            SELECT COALESCE(bucket, 'legacy_unspecified') AS bucket, COUNT(*) AS listings,
                   COUNT(DISTINCT card_id) AS distinct_cards
            FROM uk_price_history GROUP BY COALESCE(bucket, 'legacy_unspecified') ORDER BY listings DESC
        """)
        warning = None
        if usage['guard_reached']:
            warning = 'Local monthly RapidAPI guard has been reached. Live fetches are blocked.'
        elif usage['close_to_guard']:
            warning = 'RapidAPI usage is close to the local monthly guard. Fetch only high-value cards.'
        return {
            'generated_at': now_utc(),
            'usage': usage,
            'counts': {
                'cached_price_queries': cache_count,
                'price_history_rows': history_count,
                'distinct_cards_with_sold_prices': distinct_sold_cards,
                'distinct_cards_with_active_prices': distinct_active_cards,
                'cache_hit_count_available': cache_hit_count,
                'live_fetch_count': live_fetch_count,
            },
            'bucket_counts': bucket_counts,
            'top_priced_cards': top_cards,
            'recently_fetched': recently_fetched,
            'recent_failed_fetches': recent_failures,
            'warning': warning,
        }

    @app.post('/api/prices/batch-estimate')
    async def price_batch_estimate(request: Request) -> dict[str, Any]:
        body = await request.json()
        cards = body.get('cards') or []
        max_results = int(body.get('max_results') or 60)
        if len(cards) > 50:
            raise HTTPException(status_code=400, detail='Batch estimate is limited to 50 visible cards.')
        conn = connect(app.state.db)
        usage = current_price_usage(conn)
        planned = []
        cached = 0
        seen: set[str] = set()
        for card in cards:
            query = build_price_query(card)
            language = card.get('language_code')
            key = price_cache_key(query, language, max_results)
            if key in seen:
                is_cached = True
            else:
                is_cached = price_cache_is_fresh(conn, key)
            seen.add(key)
            if is_cached:
                cached += 1
            planned.append({
                'card_id': card.get('card_id'),
                'language_code': language,
                'name': card.get('name') or card.get('card_name'),
                'query': query,
                'cache_key': key,
                'cached': is_cached,
                'estimated_request_needed': not is_cached,
            })
        estimated_new_requests = sum(1 for p in planned if p['estimated_request_needed'])
        return {
            'generated_at': now_utc(),
            'visible_cards': len(cards),
            'already_cached': cached,
            'estimated_new_requests': estimated_new_requests,
            'usage': usage,
            'allowed': estimated_new_requests <= usage['remaining_before_guard'],
            'max_batch_size': 50,
            'planned': planned,
        }

    @app.get('/api/prices/queue/high-value')
    def high_value_price_queue(limit: int = Query(500, ge=1, le=2000), language_code: str = Query('en')) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()
        name_parts = ' OR '.join(['LOWER(card_name) LIKE ?' for _ in HIGH_VALUE_NAME_TERMS])
        rarity_parts = ' OR '.join(["LOWER(COALESCE(rarity, category, variants, card_name, '')) LIKE ?" for _ in HIGH_VALUE_RARITY_TERMS])
        params: list[Any] = [language_code]
        params.extend([f'%{term.lower()}%' for term in HIGH_VALUE_NAME_TERMS])
        params.extend([f'%{term.lower()}%' for term in HIGH_VALUE_RARITY_TERMS])
        params.extend([f'%{term.lower()}%' for term in HIGH_VALUE_NAME_TERMS])
        params.append(limit)
        candidates = rows(cur, f"""
            SELECT language_code, card_id, card_name AS name, core_set_name, resolved_set_name,
                   local_id AS collector_number, rarity, category, variants, has_display_image
            FROM v2_card_search
            WHERE language_code = ?
              AND LOWER(COALESCE(card_name, '')) NOT LIKE '%energy%'
              AND LOWER(COALESCE(category, '')) NOT LIKE '%trainer%'
              AND (({name_parts}) OR ({rarity_parts}))
            ORDER BY
              CASE WHEN ({name_parts}) THEN 0 ELSE 1 END,
              COALESCE(resolved_release_date, '') DESC,
              card_id
            LIMIT ?
        """, params)
        seen_queries: set[str] = set()
        out = []
        for c in candidates:
            query = build_price_query(c)
            cache_key = price_cache_key(query, c.get('language_code'), 60)
            cached = price_cache_is_fresh(conn, cache_key)
            deduped = query.lower() in seen_queries
            seen_queries.add(query.lower())
            out.append({
                **c,
                'query': query,
                'cache_key': cache_key,
                'cache_status': 'fresh' if cached else 'missing_or_stale',
                'deduped_query': deduped,
                'estimated_request_needed': (not cached) and (not deduped),
            })
        report_dir = app.state.settings.reports_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"v4_high_value_price_queue_{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.csv"
        import csv
        fields = ['card_id', 'language_code', 'name', 'core_set_name', 'collector_number', 'rarity', 'category', 'query', 'cache_status', 'deduped_query', 'estimated_request_needed']
        with report_path.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(out)
        return {
            'generated_at': now_utc(),
            'language_code': language_code,
            'limit': limit,
            'count': len(out),
            'estimated_new_requests': sum(1 for r in out if r['estimated_request_needed']),
            'report_path': str(report_path),
            'candidates': out,
        }

    @app.get('/api/prices/fetch')
    def fetch_price_on_demand(
        query: str = Query(..., description='Search query, e.g. "Charizard 101 Pokémon card"'),
        max_results: int = Query(60, ge=60, le=240),
        language: str | None = Query(None, description='Language code for filtering, e.g. "de" for German'),
        card_id: str | None = Query(None, description='Optional card id for audit/caching context'),
        force_refresh: bool = Query(False, description='Bypass cache and spend a RapidAPI request'),
    ) -> dict[str, Any]:
        """Fetch sold prices from RapidAPI on-demand with cache, guardrail, and cleaned stats."""
        import re
        import statistics
        import requests as req

        def money(v: Any) -> float | None:
            try:
                if v is None or v == '':
                    return None
                return round(float(v), 2)
            except (TypeError, ValueError):
                return None

        def pct(values: list[float], q: float) -> float | None:
            if not values:
                return None
            idx = int(round((len(values) - 1) * q))
            return round(values[max(0, min(idx, len(values) - 1))], 2)

        def stats(values: list[float]) -> dict[str, Any]:
            values = sorted([round(float(v), 2) for v in values if v is not None])
            if not values:
                return {'count': 0}
            return {'count': len(values), 'median': round(statistics.median(values), 2), 'mean': round(statistics.mean(values), 2), 'min': values[0], 'max': values[-1], 'p25': pct(values, 0.25), 'p75': pct(values, 0.75)}

        def classify(title: str) -> tuple[str, list[str]]:
            t = title.lower()
            graded_terms = ['psa', 'bgs', 'cgc', 'ace ', 'tag ', 'graded', 'gem mt', 'gem mint']
            noisy_terms = ['proxy', 'custom', 'fake', 'replica', 'digital', 'code card', 'sleeve', 'coin', 'booster', 'pack ', 'empty', 'jumbo', 'oversized']
            bundle_terms = ['bundle', 'job lot', 'joblot', 'lot of', 'collection', 'set of', 'bulk']
            if any(x in t for x in noisy_terms):
                return 'noise', ['noise_term']
            if any(x in t for x in bundle_terms):
                return 'bundle', ['bundle_or_lot']
            if any(x in t for x in graded_terms) or re.search(r'\b(psa|cgc|bgs|ace|tag)\s*\d{1,2}(\.5)?\b', t):
                return 'graded', ['graded']
            return 'raw', ['raw']

        def token_score(title: str, q: str) -> tuple[float, list[str]]:
            stop = {'pokemon', 'pokémon', 'card', 'tcg', 'english', 'german', 'french', 'italian', 'spanish', 'japanese', 'korean', 'chinese', 'the', 'and', 'of'}
            title_l = title.lower()
            tokens = [x for x in re.findall(r'[a-z0-9]+', q.lower()) if len(x) > 1 and x not in stop]
            if not tokens:
                return 0.0, ['no_query_tokens']
            hits = [x for x in tokens if x in title_l]
            return round(len(hits) / len(tokens), 3), [f'token_match={len(hits)}/{len(tokens)}']

        def cleaned_raw_prices(rows: list[dict[str, Any]]) -> list[float]:
            vals = sorted([r['price_gbp'] for r in rows if r.get('bucket') == 'raw' and r.get('price_gbp') is not None and r.get('confidence_score', 0) >= 0.55])
            vals = [v for v in vals if 2 <= v <= 1000]
            if len(vals) < 4:
                return vals
            q1 = pct(vals, 0.25) or vals[0]
            q3 = pct(vals, 0.75) or vals[-1]
            iqr = max(q3 - q1, 1)
            return [v for v in vals if max(2, q1 - 1.5 * iqr) <= v <= q3 + 1.5 * iqr]

        cache_ttl_hours = int(os.environ.get('POKEMON_PRICE_CACHE_TTL_HOURS', '168'))
        monthly_limit = int(os.environ.get('POKEMON_PRICE_MONTHLY_LIMIT', '1400'))
        cache_key = price_cache_key(query, language, max_results)
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()

        if not force_refresh:
            cur.execute("""SELECT response_json, fetched_at FROM uk_price_fetch_cache WHERE cache_key = ? AND datetime(fetched_at) >= datetime('now', ?)""", (cache_key, f'-{cache_ttl_hours} hours'))
            cached = cur.fetchone()
            if cached:
                data = json.loads(cached[0])
                data['cached'] = True
                data['cache_fetched_at'] = cached[1]
                data['cost_guard'] = {'spent_request': False, 'monthly_limit': monthly_limit}
                return data

        month_start = dt.datetime.now(dt.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur.execute("""SELECT COUNT(*) FROM uk_price_fetch_usage WHERE status = 'ok' AND requested_at >= ?""", (month_start,))
        used_this_month = int(cur.fetchone()[0])
        if used_this_month >= monthly_limit:
            raise HTTPException(status_code=429, detail=f'Local monthly price-fetch guard reached ({used_this_month}/{monthly_limit}).')

        key = os.environ.get('RAPIDAPI_KEY', '')
        if not key:
            for path in ['/tmp/rapidapi_key.txt', '/home/matt/.hermes/hermes-agent/rapidapi_key.txt']:
                try:
                    with open(path) as kf:
                        key = kf.read().strip()
                    if key:
                        print('RAPIDAPI KEY loaded from', path)
                        break
                except FileNotFoundError:
                    continue
        if not key:
            raise HTTPException(status_code=400, detail='RAPIDAPI_KEY not configured')

        print('RAPIDAPI FETCH:', query, 'lang=', language, 'used=', used_this_month, 'limit=', monthly_limit)
        payload = json.dumps({'keywords': query, 'max_search_results': str(max_results), 'site_id': '3', 'remove_outliers': False})
        try:
            resp = req.post('https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems', headers={'Content-Type': 'application/json', 'x-rapidapi-host': 'ebay-average-selling-price.p.rapidapi.com', 'x-rapidapi-key': key}, data=payload, timeout=30)
            print('RAPIDAPI RESPONSE:', resp.status_code, resp.text[:100])
        except Exception as req_err:
            cur.execute('INSERT INTO uk_price_fetch_usage(query, language_code, card_id, status) VALUES (?, ?, ?, ?)', (query, language, card_id, 'request_error'))
            conn.commit()
            raise HTTPException(status_code=502, detail='Request failed: ' + str(req_err))
        if not resp.ok:
            cur.execute('INSERT INTO uk_price_fetch_usage(query, language_code, card_id, status) VALUES (?, ?, ?, ?)', (query, language, card_id, f'http_{resp.status_code}'))
            conn.commit()
            raise HTTPException(status_code=502, detail='RapidAPI error {}: {}'.format(resp.status_code, resp.text[:200]))

        raw_data = resp.json()
        enriched: list[dict[str, Any]] = []
        for prod in (raw_data.get('products', []) or []):
            title = re.sub(r'\s+', ' ', str(prod.get('title') or prod.get('name') or '')).strip()
            price = money(prod.get('sale_price') or prod.get('price'))
            bucket, notes = classify(title)
            score, score_notes = token_score(title, query)
            if price is None:
                notes.append('missing_price')
            if bucket == 'noise':
                score = min(score, 0.35)
            enriched.append({'title': title, 'price_gbp': price, 'sold_date': prod.get('date_sold') or prod.get('sold_date') or prod.get('sale_date'), 'listing_url': prod.get('link') or prod.get('url') or prod.get('item_web_url'), 'condition': prod.get('condition'), 'bucket': bucket, 'confidence_score': score, 'match_notes': notes + score_notes})

        all_prices = [r['price_gbp'] for r in enriched if r.get('price_gbp') is not None and r.get('bucket') != 'noise']
        raw_rows = [r for r in enriched if r.get('bucket') == 'raw']
        graded_rows = [r for r in enriched if r.get('bucket') == 'graded']
        bundle_rows = [r for r in enriched if r.get('bucket') == 'bundle']
        clean_raw = cleaned_raw_prices(enriched)
        clean_stats = stats(clean_raw)
        all_stats = stats(all_prices)
        result = {
            'success': raw_data.get('success', True), 'query': query, 'language': language, 'card_id': card_id, 'cached': False,
            'cost_guard': {'spent_request': True, 'used_this_month_before_request': used_this_month, 'monthly_limit': monthly_limit, 'remaining_before_guard': max(0, monthly_limit - used_this_month - 1)},
            'total_results': raw_data.get('total_results') or raw_data.get('results'), 'products': enriched,
            'summary': {'all_non_noise': all_stats, 'raw_all': stats([r['price_gbp'] for r in raw_rows if r.get('price_gbp') is not None]), 'raw_clean': clean_stats, 'graded': stats([r['price_gbp'] for r in graded_rows if r.get('price_gbp') is not None]), 'bundles': stats([r['price_gbp'] for r in bundle_rows if r.get('price_gbp') is not None]), 'noise_count': len([r for r in enriched if r.get('bucket') == 'noise'])},
            'recommendation': {'basis': 'raw_clean_median' if clean_raw else 'all_non_noise_median', 'typical_raw_price_gbp': clean_stats.get('median') if clean_raw else all_stats.get('median'), 'typical_range_gbp': [clean_stats.get('p25'), clean_stats.get('p75')] if clean_raw else [all_stats.get('p25'), all_stats.get('p75')], 'notes': 'Raw clean excludes graded, bundles/lots, obvious non-card noise, and IQR outliers. Use graded separately.'},
        }
        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        result['history_persistence'] = persist_price_history(
            conn,
            products=enriched,
            card_id=card_id,
            language_code=language,
            query=query,
            cache_key=cache_key,
            fetched_at=fetched_at,
        )
        cur.execute("""INSERT OR REPLACE INTO uk_price_fetch_cache(cache_key, query, language_code, card_id, response_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)""", (cache_key, query, language, card_id, json.dumps(result), fetched_at))
        cur.execute('INSERT INTO uk_price_fetch_usage(query, language_code, card_id, status) VALUES (?, ?, ?, ?)', (query, language, card_id, 'ok'))
        conn.commit()
        return result

    return app


app = create_app(DEFAULT_SETTINGS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run the local SaveRoom Pokémon DB FastAPI service.')
    add_common_args(parser, include_server=True)
    args = parser.parse_args(argv)
    import uvicorn

    settings = validate_settings(settings_from_args(args), require_ui=False)
    selected_app = app if settings == DEFAULT_SETTINGS else create_app(settings)
    for line in startup_lines(settings, selected_app.state.support_status):
        print(f'[pokemon-db-api] {line}', flush=True)
    uvicorn.run(selected_app, host=settings.host, port=settings.port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


