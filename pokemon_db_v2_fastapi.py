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
import hashlib
import json
import os
import re

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pokemon_db_v2_search_api import (  # noqa: E402
    CACHE_TABLE,
    FTS_TABLE,
    SEARCH_COLUMNS,
    autocomplete_suggestions,
    build_match_query,
    build_match_query_with_synonyms,
    connect,
    expand_synonyms,
    fuzzy_search_names,
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
from pokemon_db_v5_api_models import (  # noqa: E402
    ApiKeyCreateV1,
    ApiKeyCreatedResponseV1,
    ApiKeyListResponseV1,
    CardDetailResponseV1,
    CardSearchResponseV1,
    HealthResponseV1,
    ImageDetailResponseV1,
    LanguageListResponseV1,
    PriceHistoryResponseV1,
    PriceSummaryResponseV1,
    QuotaStatusResponseV1,
    SetDetailResponseV1,
    SetListResponseV1,
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

PRICE_HISTORY_V5_COLUMNS = {
    'condition_normalized': 'TEXT',
    'is_played': 'INTEGER DEFAULT 0',
    'postage_cost': 'REAL',
    'ebay_item_id': 'TEXT',
    'currency': 'TEXT DEFAULT \'GBP\'',
}

PRICING_ALGORITHM_VERSION = 'pricing-v8.0'

# eBay condition → standard TCG condition mapping
# Standard scale: Mint, Near Mint, Excellent, Played, Poor
CONDITION_MAP = {
    'brand new':      ('Mint', 0),
    'new':            ('Mint', 0),
    'new (other)':    ('Near Mint', 0),
    'nicht bewertet': ('Excellent', 0),
    'pre-owned':      ('Excellent', 0),
    'used':           ('Played', 0),
}

# Title keywords that suggest played/heavily played condition
PLAYED_TITLE_KEYWORDS = [
    'played', 'damage', 'damaged', 'crease', 'creased', 'bent', 'marked',
    'scratched', 'wear', 'worn', 'poor', 'heavy play', 'hp ', 'moderate',
]

# eBay item ID pattern in listing URLs
EBAY_ITEM_ID_RE = re.compile(r'/itm/(\d+)')

# Configurable pricing thresholds
PRICING_CONFIG = {
    'fallback_min_exact_matches': 3,
    'postage_high_threshold': 10.0,
    'postage_abnormal_threshold': 25.0,
    'condition_excluded_from_raw': {'Played', 'Poor'},
    'condition_uncertainty_label': 'Unknown',
    'confidence_high_min_exact': 10,
    'confidence_medium_min_exact': 3,
    'confidence_low_max_observations': 3,
    'iqr_multiplier': 1.5,
    'price_min_gbp': 2.0,
    'price_max_gbp': 1000.0,
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
    for column, ddl in PRICE_HISTORY_V5_COLUMNS.items():
        if column not in existing:
            cur.execute(f'ALTER TABLE uk_price_history ADD COLUMN {column} {ddl}')
    # v8: Add algorithm_version to cache table
    existing_cache = {r[1] for r in cur.execute('PRAGMA table_info(uk_price_fetch_cache)').fetchall()}
    if 'algorithm_version' not in existing_cache:
        cur.execute('ALTER TABLE uk_price_fetch_cache ADD COLUMN algorithm_version TEXT')
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uk_price_fetch_cache (
            cache_key TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            language_code TEXT,
            card_id TEXT,
            response_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            source TEXT DEFAULT 'rapidapi_ebay_average_selling_price',
            algorithm_version TEXT
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


def ensure_v1_api_support(conn: sqlite3.Connection) -> None:
    """Create non-destructive API-key/request-log groundwork for v1 routes."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS developer_api_keys (
            id INTEGER PRIMARY KEY,
            key_hash TEXT NOT NULL UNIQUE,
            label TEXT,
            scopes TEXT,
            monthly_quota INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_used_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_request_log (
            id INTEGER PRIMARY KEY,
            api_key_id INTEGER,
            route TEXT,
            method TEXT,
            status_code INTEGER,
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            elapsed_ms REAL,
            client_host_hash TEXT,
            FOREIGN KEY(api_key_id) REFERENCES developer_api_keys(id)
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_developer_api_keys_hash ON developer_api_keys(key_hash)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_api_request_log_requested ON api_request_log(requested_at)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_api_request_log_key_requested ON api_request_log(api_key_id, requested_at)')
    conn.commit()


def v1_error(status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={'error': {'code': code, 'message': message, 'details': details or {}}})


def parse_card_key(card_key: str) -> tuple[str, str]:
    """Parse canonical `language:card_id` or URL-path alias `language/card_id`."""
    key = (card_key or '').strip()
    if ':' in key:
        language_code, card_id = key.split(':', 1)
    elif '/' in key:
        language_code, card_id = key.split('/', 1)
    else:
        raise v1_error(400, 'invalid_card_key', 'Card key must be {language_code}:{card_id}.', {'card_key': card_key})
    language_code = language_code.strip().lower()
    card_id = card_id.strip()
    if not language_code or not card_id or '/' in language_code or ':' in language_code:
        raise v1_error(400, 'invalid_card_key', 'Card key must be {language_code}:{card_id}.', {'card_key': card_key})
    return language_code, card_id


def canonical_card_key(language_code: str, card_id: str) -> str:
    return f'{language_code}:{card_id}'


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def v1_price_summary(conn: sqlite3.Connection, language_code: str, card_id: str) -> dict[str, Any]:
    """Return price evidence summary for a card.

    First tries same-language data. If none found, falls back to English data
    since eBay UK is predominantly English. This ensures all cards with fetched
    price data show results regardless of their language.
    """
    ensure_price_support(conn)
    cur = conn.cursor()

    # Try same-language data first
    result = _query_price_summary(cur, card_id, language_code)
    if result['evidence_count'] > 0:
        return result

    # Fall back to English data if no same-language results
    if language_code != 'en':
        result = _query_price_summary(cur, card_id, 'en')
        if result['evidence_count'] > 0:
            result['note'] = 'price_data_from_english_ebay'
            return result

    # No data at all
    return {
        'currency': 'GBP', 'evidence_count': 0, 'recommended_raw_count': 0,
        'raw_median': None, 'raw_min': None, 'raw_max': None,
        'graded_count': 0, 'bundle_count': 0, 'noise_count': 0,
        'latest_fetched_at': None, 'source': None,
        'no_evidence_reason': 'no_price_evidence_available',
        'by_condition': {}, 'with_postage': False,
    }


def _query_price_summary(cur: sqlite3.Cursor, card_id: str, language_code: str) -> dict[str, Any]:
    """Query price summary for a specific card_id and language_code."""
    params = (card_id, language_code)
    row = cur.execute("""
        SELECT
            COUNT(*) AS evidence_count,
            SUM(CASE WHEN COALESCE(is_recommended_input,0)=1 THEN 1 ELSE 0 END) AS recommended_raw_count,
            ROUND(MIN(CASE WHEN COALESCE(is_recommended_input,0)=1 THEN price_gbp END), 2) AS raw_min,
            ROUND(MAX(CASE WHEN COALESCE(is_recommended_input,0)=1 THEN price_gbp END), 2) AS raw_max,
            SUM(CASE WHEN bucket='graded' THEN 1 ELSE 0 END) AS graded_count,
            SUM(CASE WHEN bucket='bundle' THEN 1 ELSE 0 END) AS bundle_count,
            SUM(CASE WHEN bucket='noise' THEN 1 ELSE 0 END) AS noise_count,
            MAX(fetched_at) AS latest_fetched_at,
            MAX(source_site) AS source
        FROM uk_price_history
        WHERE card_id = ? AND language_code = ?
    """, params).fetchone()
    prices = [r[0] for r in cur.execute("""
        SELECT price_gbp
        FROM uk_price_history
        WHERE card_id = ? AND language_code = ? AND COALESCE(is_recommended_input,0)=1
        ORDER BY price_gbp
    """, params).fetchall()]
    evidence_count = int(row[0] or 0) if row else 0
    if not evidence_count:
        return {
            'currency': 'GBP', 'evidence_count': 0, 'recommended_raw_count': 0,
            'raw_median': None, 'raw_min': None, 'raw_max': None,
            'graded_count': 0, 'bundle_count': 0, 'noise_count': 0,
            'latest_fetched_at': None, 'source': None,
            'by_condition': {}, 'with_postage': False,
        }
    median = None
    if prices:
        mid = len(prices) // 2
        median = round(prices[mid], 2) if len(prices) % 2 else round((prices[mid - 1] + prices[mid]) / 2, 2)
    # Include condition-normalized breakdown
    cond_rows = cur.execute("""
        SELECT COALESCE(condition_normalized, 'unknown') AS normalized_condition,
               COUNT(*) AS listing_count,
               ROUND(AVG(price_gbp), 2) AS avg_price
        FROM uk_price_history
        WHERE card_id = ? AND language_code = ? AND COALESCE(is_recommended_input,0)=1
        GROUP BY normalized_condition
        ORDER BY listing_count DESC
    """, params).fetchall()
    by_condition = {r[0]: {'count': r[1], 'avg_price': r[2]} for r in cond_rows}
    return {
        'currency': 'GBP', 'evidence_count': evidence_count,
        'recommended_raw_count': int(row[1] or 0), 'raw_median': median,
        'raw_min': row[2], 'raw_max': row[3], 'graded_count': int(row[4] or 0),
        'bundle_count': int(row[5] or 0), 'noise_count': int(row[6] or 0),
        'latest_fetched_at': row[7], 'source': row[8], 'no_evidence_reason': None,
        'by_condition': by_condition, 'with_postage': False,
    }


def get_en_name(conn: sqlite3.Connection, language_code: str, card_id: str, local_name: str) -> str | None:
    """Look up the English name for a card from the translation table."""
    if language_code == 'en':
        return local_name
    cur = conn.cursor()
    row = cur.execute(
        'SELECT en_name FROM card_name_translations WHERE card_id = ? AND language_code = ? AND source != \'untranslated\' LIMIT 1',
        (card_id, language_code),
    ).fetchone()
    return row[0] if row else None


def v1_card_from_detail(detail: dict[str, Any], conn: sqlite3.Connection, *, include_detail: bool = False) -> dict[str, Any]:
    language_code = detail.get('language_code')
    card_id = detail.get('card_id')
    images = detail.get('images') or {}
    set_info = detail.get('set') or {}
    card_info = detail.get('card') or {}
    display_lang = images.get('display_image_source_language_code')
    local_name = detail.get('name')
    en_name = get_en_name(conn, language_code, card_id, local_name)
    out: dict[str, Any] = {
        'card_key': canonical_card_key(language_code, card_id),
        'language': {'code': language_code, 'name': detail.get('language_name')},
        'card_id': card_id,
        'local_id': detail.get('collector_number'),
        'collector_number': detail.get('collector_number'),
        'name': local_name,
        'name_english': en_name,
        'set': {
            'set_id': set_info.get('resolved_set_id') or set_info.get('raw_set_id'),
            'core_set_id': set_info.get('core_set_id'),
            'name': set_info.get('resolved_set_name'),
            'core_name': set_info.get('core_set_name'),
            'series': set_info.get('series'),
            'release_date': set_info.get('release_date'),
        },
        'images': {
            'has_exact_image': bool(images.get('has_exact_image')),
            'has_display_image': bool(images.get('has_display_image')),
            'exact_image_url': images.get('exact_image_url'),
            'display_image_url': images.get('display_image_url'),
            'local_display_image_url': images.get('local_display_image_url'),
            'local_display_image_cache_profile': images.get('local_display_image_cache_profile'),
            'local_display_image_bytes': images.get('local_display_image_bytes'),
            'display_image_source_type': images.get('display_image_source_type'),
            'display_image_source_language_code': display_lang,
            'language_matches_card': (display_lang in (None, '', language_code)),
        },
        'price': v1_price_summary(conn, language_code, card_id),
        'price_query': build_price_query({
            'card_id': card_id,
            'language_code': language_code,
            'name': local_name,
            'name_english': en_name,
            'card_name': detail.get('name'),
            'collector_number': detail.get('collector_number'),
            'local_id': detail.get('collector_number'),
            'core_set_name': set_info.get('core_set_name'),
            'resolved_set_name': set_info.get('resolved_set_name'),
            'core_set_id': set_info.get('core_set_id'),
            'rarity': card_info.get('rarity'),
            'types': card_info.get('types'),
        }, conn),
    }
    if include_detail:
        provenance = detail.get('provenance') or {}
        v2_count = provenance.get('v2_count')
        legacy_count = provenance.get('legacy_count')
        out.update({
            'category': card_info.get('category'),
            'hp': card_info.get('hp'),
            'types': card_info.get('types'),
            'rarity': card_info.get('rarity'),
            'stage': card_info.get('stage'),
            'illustrator': card_info.get('illustrator'),
            'regulation_mark': card_info.get('regulation_mark'),
            'variants': card_info.get('variants'),
            'legal': card_info.get('legal'),
            'rules_text': detail.get('rules_text'),
            'provenance': {
                'v2_record_count': v2_count,
                'legacy_record_count': legacy_count,
                'total_count': (v2_count or 0) + (legacy_count or 0),
            },
        })
    return out


def build_price_query(card: dict[str, Any], conn: sqlite3.Connection | None = None) -> str:
    """Build a clean eBay-optimized price search query.

    Produces queries like:
      "Charizard CP6-011"  (with number + set code)
      "Mewtwo CP6"         (fallback — number or set code only)

    Uses English name since eBay UK is predominantly English.
    No "Pokemon" prefix, no "Pokémon card" suffix, no rarity/types keywords
    — these clutter eBay's algorithm and reduce precision.
    """
    card_id = str(card.get('card_id') or '').strip()
    language_code = str(card.get('language_code') or '').strip()

    # If name_english not in card dict, look it up from DB
    name_english_raw = card.get('name_english') or card.get('en_name') or ''
    if not name_english_raw and conn and card_id and language_code and language_code != 'en':
        cur = conn.cursor()
        row = cur.execute(
            'SELECT en_name FROM card_name_translations WHERE card_id = ? AND language_code = ? AND source != \'untranslated\' LIMIT 1',
            (card_id, language_code),
        ).fetchone()
        if row:
            name_english_raw = row[0]

    # Always use English name — eBay UK is predominantly English
    name = str(
        name_english_raw
        or card.get('name')
        or card.get('card_name')
        or ''
    )
    # Strip parenthetical suffixes like "(Expansion Pack 20th 50)"
    name = re.sub(r'\s*\([^)]*\)\s*', ' ', name)
    # Strip MediaWiki/bracket artifacts
    name = name.replace('[', ' ').replace(']', ' ').strip()

    number = str(card.get('collector_number') or card.get('local_id') or '').strip()
    core_set_id = str(card.get('core_set_id') or '').strip()
    set_name = str(card.get('core_set_name') or card.get('resolved_set_name') or '').strip()

    # Clean set_name: strip Korean/Japanese/Chinese characters — they confuse eBay UK
    # which is English-only
    set_name_clean = set_name
    if conn:
        pass  # Keep for potential future use

    # Strip non-Latin text from set name for fallback
    if set_name:
        # Remove CJK characters
        set_name_en_only = re.sub(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\uac00-\ud7af]', '', set_name).strip()
        if set_name_en_only:
            set_name = set_name_en_only
        else:
            # If nothing left after stripping non-Latin, don't use set_name at all
            set_name = ''

    # Primary query: "{Name} {SetCode}-{Number}"
    parts: list[str] = [name]

    # Format: "CP6-011" — the setcode-number combo
    code_number = ''
    if core_set_id and core_set_id.lower() not in ('', 'none') and number:
        code_number = f'{core_set_id}-{number}'
        parts.append(code_number)
    elif core_set_id and core_set_id.lower() not in ('', 'none'):
        parts.append(core_set_id)
    elif number:
        parts.append(number)
    elif set_name:
        # Only use first 2 words of set name as last resort
        set_words = set_name.split()[:2]
        if set_words:
            parts.extend(set_words)

    query = ' '.join(parts)

    return query


def price_cache_key(query: str, language: str | None, max_results: int) -> str:
    return '|'.join([query.strip().lower(), str(language or '').lower(), str(max_results)])


def price_cache_is_fresh(conn: sqlite3.Connection, cache_key: str) -> bool:
    ensure_price_support(conn)
    cache_ttl_hours = int(os.environ.get('POKEMON_PRICE_CACHE_TTL_HOURS', '168'))
    cur = conn.cursor()
    cur.execute("""SELECT 1 FROM uk_price_fetch_cache WHERE cache_key = ? AND datetime(fetched_at) >= datetime('now', ?)""", (cache_key, f'-{cache_ttl_hours} hours'))
    return cur.fetchone() is not None


def normalize_listing_condition(
    ebay_condition: str | None,
    title: str,
) -> tuple[str | None, bool]:
    """Normalize eBay condition string to standard TCG condition scale.

    Returns (condition_normalized, is_played).
    - condition_normalized: Mint, Near Mint, Excellent, Played, Poor, or None
    - is_played: True if the title suggests played/heavily played condition

    Also checks the listing title for keywords that suggest played condition
    even if the eBay condition field doesn't indicate it.
    """
    if not ebay_condition and not title:
        return None, False

    title_lower = title.lower()
    is_played = any(kw in title_lower for kw in PLAYED_TITLE_KEYWORDS)

    if not ebay_condition:
        return ('Played' if is_played else None), is_played

    ebay_lower = ebay_condition.strip().lower()
    normalized, _ = CONDITION_MAP.get(ebay_lower, (None, 0))

    if normalized is None:
        return ('Played' if is_played else None), is_played

    # Upgrade Played to Excellent if only the title suggests it but eBay says Pre-owned/New
    if is_played and normalized in ('Excellent', 'Near Mint', 'Mint'):
        # eBay says good condition but title says played — keep eBay's verdict
        return normalized, True

    return normalized, is_played


def extract_ebay_item_id(listing_url: str | None, title: str | None = None) -> str | None:
    """Extract eBay item ID from a listing URL or title."""
    if listing_url:
        m = EBAY_ITEM_ID_RE.search(listing_url)
        if m:
            return m.group(1)
    return None


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
    """Persist cleaned/enriched listings, keeping non-raw buckets auditable and deduped.

    v8: Preserves the actual target card language instead of forcing 'en'.
    The listing titles are in English (eBay UK), but the target card identity
    retains its original language for accurate card matching.
    """
    ensure_price_support(conn)
    cur = conn.cursor()
    inserted = 0
    duplicates = 0
    skipped = 0
    recommended = 0
    # v8: Use the actual target card language — do not force 'en'
    effective_lang = language_code or 'en'
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
        # Extract ebay_item_id from URL or product data
        ebay_item_id = product.get('ebay_item_id') or extract_ebay_item_id(listing_url)
        # Dedup: prefer ebay_item_id when available, fall back to URL+price+date combo
        if ebay_item_id:
            cur.execute("""SELECT id FROM uk_price_history WHERE ebay_item_id = ? LIMIT 1""", (ebay_item_id,))
        else:
            cur.execute("""
                SELECT id FROM uk_price_history
                WHERE card_id = ?
                  AND COALESCE(language_code, '') = ?
                  AND COALESCE(listing_url, '') = COALESCE(?, '')
                  AND sold_date = ?
                  AND ROUND(price_gbp, 2) = ROUND(?, 2)
                LIMIT 1
            """, (card_id, effective_lang, listing_url, sold_date, price))
        if cur.fetchone():
            duplicates += 1
            continue
        cur.execute("""
            INSERT INTO uk_price_history(
                card_id, language_code, condition, price_gbp, sold_date, listing_url, source,
                confidence_score, raw_title, bucket, match_notes, query, source_site,
                is_recommended_input, cache_key, fetched_at,
                condition_normalized, is_played, postage_cost, ebay_item_id, currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            card_id, effective_lang, product.get('condition'), price, sold_date, listing_url,
            'ebay_uk_sold', score, raw_title, bucket,
            json.dumps(product.get('match_notes') or [], ensure_ascii=False), query,
            'rapidapi_ebay_average_selling_price', is_recommended_input, cache_key, fetched_at,
            product.get('condition_normalized'), int(product.get('is_played', False)),
            product.get('postage_cost'), ebay_item_id, product.get('currency', 'GBP'),
        ))
        inserted += 1
    # Only record failure if we truly got no usable results at all
    if card_id and inserted == 0 and not any(p.get('bucket') == 'raw' and p.get('price_gbp') is not None for p in products):
        cur.execute("""
            INSERT INTO uk_price_scrape_failures(card_id, language_code, query, reason)
            VALUES (?, ?, ?, ?)
        """, (card_id, effective_lang, query, 'no_usable_raw_listings'))
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

    # Invalidate stale price cache entries with non-Latin query terms
    # (e.g., Japanese text in queries that return 0 eBay results)
    try:
        check_conn = connect(str(settings.db))
        check_cur = check_conn.cursor()
        check_cur.execute("SELECT rowid, cache_key FROM uk_price_fetch_cache")
        cleaned = 0
        for check_row in check_cur.fetchall():
            q = check_row[1].split('|')[0]
            if any(0x3040 <= ord(c) <= 0x309F or 0x30A0 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF for c in q):
                check_cur.execute("DELETE FROM uk_price_fetch_cache WHERE rowid = ?", (check_row[0],))
                cleaned += 1
        if cleaned:
            check_conn.commit()
            print(f'[pokemon-db-api] Cleaned {cleaned} stale cache entries with non-Latin queries')
        check_conn.close()
    except Exception as exc:
        print(f'[pokemon-db-api] Cache cleanup skipped: {exc}')

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


    # v1 API foundation: optional API key auth + request logging.
    with connect(app.state.db) as conn:
        ensure_v1_api_support(conn)

    async def require_v1_api_key(request: Request) -> dict[str, Any]:
        require_key = os.environ.get('POKEMON_DB_REQUIRE_API_KEY', '').strip().lower() in {'1', 'true', 'yes', 'on'}
        if not require_key:
            request.state.api_key_id = None
            return {'api_key_id': None, 'scopes': ['cards:read'], 'auth_required': False}
        raw_key = request.headers.get('x-api-key') or ''
        auth = request.headers.get('authorization') or ''
        if not raw_key and auth.lower().startswith('bearer '):
            raw_key = auth.split(' ', 1)[1].strip()
        if not raw_key:
            raise v1_error(401, 'api_key_required', 'API key required for /api/v1 routes.', {'header': 'X-API-Key'})
        key_hash = sha256_text(raw_key)
        conn = connect(app.state.db)
        ensure_v1_api_support(conn)
        cur = conn.cursor()
        row = cur.execute('SELECT id, scopes, is_active FROM developer_api_keys WHERE key_hash=? LIMIT 1', (key_hash,)).fetchone()
        if not row or not row['is_active']:
            raise v1_error(401, 'invalid_api_key', 'Invalid or inactive API key.', None)
        scopes = json.loads(row['scopes'] or '[]') if row['scopes'] else []
        if scopes and 'cards:read' not in scopes and 'admin' not in scopes:
            raise v1_error(403, 'insufficient_scope', 'API key does not include cards:read scope.', {'required_scope': 'cards:read'})
        cur.execute('UPDATE developer_api_keys SET last_used_at=CURRENT_TIMESTAMP WHERE id=?', (row['id'],))
        conn.commit()
        request.state.api_key_id = row['id']
        return {'api_key_id': row['id'], 'scopes': scopes, 'auth_required': True}

    @app.middleware('http')
    async def v1_request_logger(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path.startswith('/api/v1'):
            try:
                conn = connect(app.state.db)
                ensure_v1_api_support(conn)
                client_host = request.client.host if request.client else None
                client_hash = sha256_text(client_host) if client_host else None
                conn.execute(
                    'INSERT INTO api_request_log(api_key_id, route, method, status_code, elapsed_ms, client_host_hash) VALUES (?, ?, ?, ?, ?, ?)',
                    (getattr(request.state, 'api_key_id', None), request.url.path, request.method, response.status_code, round((time.perf_counter() - start) * 1000, 3), client_hash),
                )
                conn.commit()
            except Exception:
                pass
        return response

    @app.exception_handler(HTTPException)
    async def v1_http_exception_handler(request: Request, exc: HTTPException):
        from fastapi.responses import JSONResponse
        if request.url.path.startswith('/api/v1'):
            detail = exc.detail
            if isinstance(detail, dict) and 'error' in detail:
                return JSONResponse(status_code=exc.status_code, content=detail)
            return JSONResponse(status_code=exc.status_code, content={'error': {'code': 'http_error', 'message': str(detail), 'details': {}}})
        return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})

    @app.get('/api/v1/health', response_model=HealthResponseV1)
    def v1_health(_: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
        counts = db_counts(app.state.db)
        return {'data': {'ok': counts['support_ready'], 'service': 'saveroom-pokemon-api', 'version': 'v1', 'started_at': STARTED_AT, 'checked_at': now_utc(), 'counts': counts, 'support_status': _public_support_status(app.state.support_status), 'auth': {'api_key_required': os.environ.get('POKEMON_DB_REQUIRE_API_KEY', '').strip().lower() in {'1', 'true', 'yes', 'on'}}}}

    @app.get('/api/v1/search/cards', response_model=CardSearchResponseV1)
    def v1_search_cards(
        q: str = Query('', description='Optional FTS search query.'),
        language_code: str | None = Query(None),
        set_id: str | None = Query(None, description='Raw or resolved set id.'),
        core_set_id: str | None = Query(None),
        has_display_image: bool | None = Query(None),
        has_price: bool | None = Query(None, description='Filter by same-language local price evidence only.'),
        limit: int = Query(50, ge=1),
        offset: int = Query(0, ge=0),
        sort: str = Query('relevance'),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        if limit > 200:
            raise v1_error(400, 'invalid_limit', 'Limit may not exceed 200.', {'max_limit': 200, 'requested_limit': limit})
        if offset < 0:
            raise v1_error(400, 'invalid_offset', 'Offset must be non-negative.', {'requested_offset': offset})
        if sort not in {'relevance', 'default'}:
            raise v1_error(400, 'unsupported_sort', 'Unsupported sort value.', {'allowed': ['relevance', 'default']})
        conn = connect(app.state.db)
        cur = conn.cursor()
        # Expand synonyms and build FTS query in one step
        match = build_match_query_with_synonyms(q, conn) if q.strip() else ''
        params: list[Any] = []
        count_params: list[Any] = []
        with_sql = ''
        join = ''
        rank_expr = '0.0 AS rank'
        if match:
            candidate_limit = max((limit + offset) * 100, 5000)
            with_sql = f'''WITH hits AS (
  SELECT language_code, card_id, bm25({FTS_TABLE}) AS rank
  FROM {FTS_TABLE}
  WHERE {FTS_TABLE} MATCH ?
  ORDER BY rank
  LIMIT ?
)'''
            params.extend([match, candidate_limit])
            count_params.extend([match, candidate_limit])
            join = 'JOIN hits h ON h.language_code=s.language_code AND h.card_id=s.card_id'
            rank_expr = 'h.rank AS rank'
        where = []
        if language_code:
            where.append('s.language_code = ?')
            params.append(language_code)
            count_params.append(language_code)
        if set_id:
            where.append('(s.resolved_set_id = ? OR s.raw_set_id = ?)')
            params.extend([set_id, set_id])
            count_params.extend([set_id, set_id])
        if core_set_id:
            where.append('s.core_set_id = ?')
            params.append(core_set_id)
            count_params.append(core_set_id)
        if has_display_image is not None:
            where.append('s.has_display_image = ?')
            params.append(1 if has_display_image else 0)
            count_params.append(1 if has_display_image else 0)
        if has_price is not None:
            exists_sql = 'EXISTS (SELECT 1 FROM uk_price_history ph WHERE ph.card_id=s.card_id AND ph.language_code=s.language_code)'
            where.append(exists_sql if has_price else f'NOT {exists_sql}')
        where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
        total = int(cur.execute(f'''{with_sql}
SELECT COUNT(*) FROM {CACHE_TABLE} s {join} {where_sql}
''', count_params).fetchone()[0])
        data_sql = f'''{with_sql}
SELECT {', '.join('s.' + c for c in SEARCH_COLUMNS)}, {rank_expr}
FROM {CACHE_TABLE} s
{join}
{where_sql}
ORDER BY
  CASE WHEN s.has_display_image=1 THEN 0 ELSE 1 END,
  rank ASC,
  CASE WHEN s.language_code='en' THEN 0 WHEN s.language_code='ja' THEN 1 ELSE 2 END,
  s.language_code,
  s.resolved_set_id,
  s.local_id_sort,
  s.card_id
LIMIT ? OFFSET ?
'''
        params.extend([limit, offset])
        detail_rows = [normalize_row(dict(r)) for r in cur.execute(data_sql, params).fetchall()]
        data = [v1_card_from_detail(r, conn) for r in detail_rows]
        return {'data': data, 'pagination': {'limit': limit, 'offset': offset, 'count': len(data), 'total': total, 'has_more': offset + len(data) < total}}

    # ── /api/v1/search/autocomplete ────────────────────────────────────

    @app.get('/api/v1/search/autocomplete')
    def v1_search_autocomplete(
        q: str = Query(..., description='Partial search query (min 2 chars).', min_length=2),
        limit: int = Query(10, ge=1, le=20),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """Autocomplete suggestions for card search.

        Returns matching card names, set names, and synonym expansions
        based on partial input. Useful for search-as-you-type UI.
        """
        conn = connect(app.state.db)
        suggestions = autocomplete_suggestions(q, conn, limit=limit)
        return {'data': suggestions}

    # ── /api/v1/search/fuzzy ───────────────────────────────────────────

    @app.get('/api/v1/search/fuzzy')
    def v1_search_fuzzy(
        q: str = Query(..., description='Fuzzy search query (min 3 chars).', min_length=3),
        limit: int = Query(10, ge=1, le=50),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """Fuzzy search for cards using trigram similarity.

        Catches misspellings and partial matches that exact FTS would miss.
        E.g., "charzard" → Charizard, "pikachuu" → Pikachu.

        Returns cards sorted by similarity score.
        """
        conn = connect(app.state.db)
        results = fuzzy_search_names(q, conn, limit=limit)
        return {'data': results}

    @app.get('/api/v1/cards/{card_key:path}', response_model=CardDetailResponseV1)
    def v1_card_detail(card_key: str, _: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        detail, _elapsed_ms = get_card_detail(conn, language_code, card_id)
        if detail is None:
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})
        return {'data': v1_card_from_detail(detail, conn, include_detail=True)}

    # ── /api/v1/sets ─────────────────────────────────────────────────

    @app.get('/api/v1/sets', response_model=SetListResponseV1)
    def v1_list_sets(
        language_code: str | None = Query(None),
        q: str | None = Query(None, description='Optional name search filter.'),
        limit: int = Query(50, ge=1),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        if limit > 200:
            raise v1_error(400, 'invalid_limit', 'Limit may not exceed 200.', {'max_limit': 200})
        if offset < 0:
            raise v1_error(400, 'invalid_offset', 'Offset must be non-negative.')
        conn = connect(app.state.db)
        cur = conn.cursor()
        where: list[str] = []
        params: list[Any] = []
        if language_code:
            where.append('s.language_code = ?')
            params.append(language_code)
        if q:
            where.append('LOWER(s.name) LIKE ?')
            params.append(f'%{q.lower()}%')
        where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
        total = int(cur.execute(f'SELECT COUNT(DISTINCT s.set_id) FROM sets s {where_sql}', params).fetchone()[0])
        set_cols = 's.set_id, s.name, s.series_name, s.release_date, s.logo_url, s.symbol_url, s.abbreviation, s.official_count, s.total_count, s.normal_count, s.holo_count, s.reverse_count, s.first_ed_count, s.language_code'
        cur.execute(
            f'SELECT {set_cols}, l.name AS language_name, (SELECT COUNT(*) FROM cards c WHERE c.set_id = s.set_id AND c.language_code = s.language_code) AS card_count '
            f'FROM sets s LEFT JOIN languages l ON l.code = s.language_code {where_sql} '
            f'GROUP BY s.set_id ORDER BY s.release_date DESC, s.set_id LIMIT ? OFFSET ?',
            params + [limit, offset]
        )
        sets_out = []
        for r in cur.fetchall():
            d = dict(r)
            sets_out.append({
                'set_id': d.get('set_id'), 'core_set_id': d.get('set_id'),
                'name': d.get('name'), 'core_name': d.get('name'),
                'series': d.get('series_name'), 'release_date': d.get('release_date'),
                'logo_url': d.get('logo_url'), 'symbol_url': d.get('symbol_url'),
                'abbreviation': d.get('abbreviation'), 'official_count': d.get('official_count'),
                'total_count': d.get('total_count'), 'normal_count': d.get('normal_count'),
                'holo_count': d.get('holo_count'), 'reverse_count': d.get('reverse_count'),
                'first_ed_count': d.get('first_ed_count'), 'language_code': d.get('language_code'),
                'language_name': d.get('language_name'), 'card_count': d.get('card_count'),
            })
        return {'data': sets_out, 'pagination': {'limit': limit, 'offset': offset, 'count': len(sets_out), 'total': total, 'has_more': offset + len(sets_out) < total}}

    @app.get('/api/v1/sets/{set_id:path}', response_model=SetDetailResponseV1)
    def v1_set_detail(
        set_id: str,
        language_code: str | None = Query(None),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        wh = 'set_id = ?'
        pr: list[Any] = [set_id]
        if language_code:
            wh += ' AND language_code = ?'
            pr.append(language_code)
        set_cols = 's.set_id, s.name, s.series_name, s.release_date, s.logo_url, s.symbol_url, s.abbreviation, s.official_count, s.total_count, s.normal_count, s.holo_count, s.reverse_count, s.first_ed_count, s.language_code'
        cur.execute(
            f'SELECT {set_cols}, l.name AS language_name, (SELECT COUNT(*) FROM cards c WHERE c.set_id = s.set_id AND c.language_code = s.language_code) AS card_count '
            f'FROM sets s LEFT JOIN languages l ON l.code = s.language_code WHERE {wh} LIMIT 1',
            pr
        )
        r = cur.fetchone()
        if not r:
            raise v1_error(404, 'set_not_found', 'Set not found.', {'set_id': set_id})
        d = dict(r)
        return {'data': {
            'set_id': d.get('set_id'), 'core_set_id': d.get('set_id'),
            'name': d.get('name'), 'core_name': d.get('name'),
            'series': d.get('series_name'), 'release_date': d.get('release_date'),
            'logo_url': d.get('logo_url'), 'symbol_url': d.get('symbol_url'),
            'abbreviation': d.get('abbreviation'), 'official_count': d.get('official_count'),
            'total_count': d.get('total_count'), 'normal_count': d.get('normal_count'),
            'holo_count': d.get('holo_count'), 'reverse_count': d.get('reverse_count'),
            'first_ed_count': d.get('first_ed_count'), 'language_code': d.get('language_code'),
            'language_name': d.get('language_name'), 'card_count': d.get('card_count'),
        }}

    # ── /api/v1/languages ─────────────────────────────────────────────

    @app.get('/api/v1/languages', response_model=LanguageListResponseV1)
    def v1_list_languages(
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('SELECT code, name, set_count, card_count FROM languages ORDER BY code')
        languages = [{'code': r[0], 'name': r[1], 'set_count': r[2], 'card_count': r[3]} for r in cur.fetchall()]
        return {'data': languages}

    # ── /api/v1/images/cards/{card_key} ───────────────────────────────

    @app.get('/api/v1/images/cards/{card_key:path}', response_model=ImageDetailResponseV1)
    def v1_card_images(
        card_key: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        detail, _ = get_card_detail(conn, language_code, card_id)
        if detail is None:
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})
        images = detail.get('images') or {}
        display_lang = images.get('display_image_source_language_code')
        return {
            'data': {
                'has_exact_image': bool(images.get('has_exact_image')),
                'has_display_image': bool(images.get('has_display_image')),
                'exact_image_url': images.get('exact_image_url'),
                'display_image_url': images.get('display_image_url'),
                'local_display_image_url': images.get('local_display_image_url'),
                'local_display_image_cache_profile': images.get('local_display_image_cache_profile'),
                'local_display_image_bytes': images.get('local_display_image_bytes'),
                'display_image_source_type': images.get('display_image_source_type'),
                'display_image_source_language_code': display_lang,
                'language_matches_card': (display_lang in (None, '', language_code)),
            },
            'card_key': canonical_card_key(language_code, card_id),
            'language_code': language_code,
            'card_id': card_id,
        }

    # ── /api/v1/prices ────────────────────────────────────────────────

    @app.get('/api/v1/prices/cards/{card_key:path}', response_model=PriceSummaryResponseV1)
    def v1_card_price_summary(
        card_key: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM v2_card_detail_api_cache WHERE language_code=? AND card_id=? LIMIT 1', (language_code, card_id))
        if not cur.fetchone():
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})
        return {
            'data': v1_price_summary(conn, language_code, card_id),
            'card_key': canonical_card_key(language_code, card_id),
            'language_code': language_code,
            'card_id': card_id,
        }

    @app.get('/api/v1/prices/history/cards/{card_key:path}', response_model=PriceHistoryResponseV1)
    def v1_card_price_history(
        card_key: str,
        bucket: str | None = Query(None, description='Filter: raw, graded, bundle, noise'),
        source: str | None = Query(None, description='Filter: ebay_uk_sold, ebay_uk'),
        condition: str | None = Query(None, description='Filter by normalized condition: Mint, Near Mint, Excellent, Played, Poor'),
        limit: int = Query(50, ge=1),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        if limit > 200:
            raise v1_error(400, 'invalid_limit', 'Limit may not exceed 200.', {'max_limit': 200})
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM v2_card_detail_api_cache WHERE language_code=? AND card_id=? LIMIT 1', (language_code, card_id))
        if not cur.fetchone():
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})
        wh = 'card_id = ? AND language_code = ?'
        pr: list[Any] = [card_id, language_code]
        if bucket:
            wh += ' AND bucket = ?'
            pr.append(bucket)
        if source:
            wh += ' AND source = ?'
            pr.append(source)
        if condition:
            wh += ' AND condition_normalized = ?'
            pr.append(condition)
        total = int(cur.execute(f'SELECT COUNT(*) FROM uk_price_history WHERE {wh}', pr).fetchone()[0])
        pr.extend([limit, offset])
        cur.execute(
            'SELECT id, card_id, language_code, condition, condition_normalized, is_played, price_gbp, sold_date, listing_url, '
            'source, imported_at, raw_title, bucket, confidence_score, match_notes, query, '
            'source_site, is_recommended_input, cache_key, fetched_at, postage_cost, ebay_item_id, currency '
            f'FROM uk_price_history WHERE {wh} ORDER BY id DESC LIMIT ? OFFSET ?',
            pr
        )
        cols = ['id', 'card_id', 'language_code', 'condition', 'condition_normalized', 'is_played', 'price_gbp', 'sold_date', 'listing_url',
                'source', 'imported_at', 'raw_title', 'bucket', 'confidence_score', 'match_notes',
                'query', 'source_site', 'is_recommended_input', 'cache_key', 'fetched_at',
                'postage_cost', 'ebay_item_id', 'currency']
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return {
            'data': rows,
            'pagination': {'limit': limit, 'offset': offset, 'count': len(rows), 'total': total, 'has_more': offset + len(rows) < total},
            'card_key': canonical_card_key(language_code, card_id),
            'language_code': language_code,
            'card_id': card_id,
        }

    # ── /api/v1/admin/keys ────────────────────────────────────────────

    def require_admin_scope(auth: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
        if not auth.get('auth_required'):
            return auth
        scopes = auth.get('scopes', [])
        if 'admin' not in scopes:
            raise v1_error(403, 'insufficient_scope', 'Admin scope required.', {'required_scope': 'admin'})
        return auth

    @app.post('/api/v1/admin/keys', response_model=ApiKeyCreatedResponseV1)
    async def v1_admin_create_key(
        body: ApiKeyCreateV1,
        _: dict[str, Any] = Depends(require_admin_scope),
    ) -> dict[str, Any]:
        import secrets
        raw_key = secrets.token_urlsafe(48)
        key_hash = sha256_text(raw_key)
        conn = connect(app.state.db)
        ensure_v1_api_support(conn)
        cur = conn.cursor()
        scopes_json = json.dumps(body.scopes or ['cards:read'])
        cur.execute(
            'INSERT INTO developer_api_keys(key_hash, label, scopes, monthly_quota) VALUES (?, ?, ?, ?)',
            (key_hash, body.label, scopes_json, body.monthly_quota),
        )
        conn.commit()
        key_id = cur.lastrowid
        return {'data': {'id': key_id, 'key': raw_key, 'label': body.label,
                          'scopes': body.scopes or ['cards:read'],
                          'monthly_quota': body.monthly_quota,
                          'is_active': True, 'created_at': now_utc()}}

    @app.get('/api/v1/admin/keys', response_model=ApiKeyListResponseV1)
    def v1_admin_list_keys(
        _: dict[str, Any] = Depends(require_admin_scope),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_v1_api_support(conn)
        cur = conn.cursor()
        cur.execute('SELECT id, label, scopes, monthly_quota, is_active, created_at, last_used_at FROM developer_api_keys ORDER BY id DESC')
        keys_out = []
        for r in cur.fetchall():
            scopes = json.loads(r['scopes'] or '[]') if r['scopes'] else []
            keys_out.append({'id': r['id'], 'label': r['label'], 'scopes': scopes,
                             'monthly_quota': r['monthly_quota'], 'is_active': bool(r['is_active']),
                             'created_at': r['created_at'], 'last_used_at': r['last_used_at']})
        return {'data': keys_out}

    @app.post('/api/v1/admin/keys/{key_id}/deactivate')
    def v1_admin_deactivate_key(
        key_id: int,
        _: dict[str, Any] = Depends(require_admin_scope),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_v1_api_support(conn)
        cur = conn.cursor()
        cur.execute('UPDATE developer_api_keys SET is_active=0 WHERE id=?', (key_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise v1_error(404, 'api_key_not_found', 'API key not found.', {'key_id': key_id})
        return {'data': {'id': key_id, 'is_active': False}}

    @app.get('/api/v1/admin/quota', response_model=QuotaStatusResponseV1)
    def v1_admin_quota_status(
        key_id: int = Query(...),
        _: dict[str, Any] = Depends(require_admin_scope),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_v1_api_support(conn)
        cur = conn.cursor()
        cur.execute('SELECT id, monthly_quota FROM developer_api_keys WHERE id=?', (key_id,))
        row = cur.fetchone()
        if not row:
            raise v1_error(404, 'api_key_not_found', 'API key not found.', {'key_id': key_id})
        now_dt = dt.datetime.now(dt.timezone.utc)
        window_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now_dt.month == 12:
            window_end = now_dt.replace(year=now_dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            window_end = now_dt.replace(month=now_dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        cur.execute('SELECT COUNT(*) FROM api_request_log WHERE api_key_id=? AND requested_at >= ? AND requested_at < ?',
                    (key_id, window_start.isoformat(), window_end.isoformat()))
        used = int(cur.fetchone()[0])
        monthly_quota = row['monthly_quota']
        remaining = max(0, monthly_quota - used) if monthly_quota else None
        return {'data': {'api_key_id': key_id, 'monthly_quota': monthly_quota,
                          'used_this_month': used, 'remaining': remaining,
                          'window_start': window_start.isoformat(),
                          'window_end': window_end.isoformat()}}

    # ── DB migration/version support ──────────────────────────────────

    def ensure_migration_support(conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY,
                version TEXT NOT NULL UNIQUE,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        """)
        conn.commit()

    def apply_migrations(conn: sqlite3.Connection) -> list[str]:
        ensure_migration_support(conn)
        # Ensure price table columns exist before index migrations run
        ensure_price_support(conn)
        cur = conn.cursor()
        applied = {r[0] for r in cur.execute('SELECT version FROM schema_migrations').fetchall()}
        migrations: list[tuple[str, str, str]] = [
            ('v1', 'CREATE INDEX IF NOT EXISTS idx_cards_language_set ON cards(language_code, set_id)', 'Add language+set index to cards table.'),
            ('v2', 'CREATE INDEX IF NOT EXISTS idx_uk_price_history_card_lang ON uk_price_history(card_id, language_code)', 'Add card+lang index to uk_price_history.'),
            ('v3', 'CREATE INDEX IF NOT EXISTS idx_api_request_log_key_route ON api_request_log(api_key_id, route)', 'Add key+route index to api_request_log.'),
            ('v4', """CREATE TABLE IF NOT EXISTS card_name_translations (
                id INTEGER PRIMARY KEY,
                card_id TEXT NOT NULL,
                language_code TEXT NOT NULL,
                local_name TEXT NOT NULL,
                en_name TEXT NOT NULL,
                source TEXT NOT NULL,
                UNIQUE(card_id, language_code)
            )""", 'Create translation layer table for non-English card names.'),
            ('v5', 'CREATE INDEX IF NOT EXISTS idx_translations_card_lang ON card_name_translations(card_id, language_code)', 'Add index to translation table.'),
            ('v6', 'CREATE INDEX IF NOT EXISTS idx_translations_local ON card_name_translations(language_code, local_name)', 'Add local name index to translation table.'),
            ('v7', 'CREATE INDEX IF NOT EXISTS idx_uk_price_history_ebay_item ON uk_price_history(ebay_item_id)', 'Add index for dedup by eBay item ID.'),
            ('v8', 'CREATE INDEX IF NOT EXISTS idx_uk_price_history_condition ON uk_price_history(condition_normalized)', 'Add index for condition-filtered queries.'),
            ('v9', """CREATE TABLE IF NOT EXISTS price_observations (
                observation_id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL,
                provider_item_id TEXT,
                target_card_key TEXT NOT NULL,
                target_language_code TEXT,
                observation_type TEXT NOT NULL DEFAULT 'active_listing',
                title TEXT,
                item_price REAL,
                postage_price REAL,
                delivered_price REAL,
                currency TEXT DEFAULT 'GBP',
                seller_location TEXT,
                item_location TEXT,
                listing_status TEXT,
                source_timestamp TEXT,
                captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
                raw_payload_hash TEXT,
                raw_payload_json TEXT,
                algorithm_version TEXT
            )""", 'Create immutable price observations table for v8 evidence foundation.'),
            ('v10', """CREATE TABLE IF NOT EXISTS price_observation_matches (
                match_id INTEGER PRIMARY KEY,
                observation_id INTEGER NOT NULL,
                target_card_key TEXT NOT NULL,
                printing_id INTEGER,
                sku_id INTEGER,
                matching_class TEXT NOT NULL,
                matching_score REAL,
                matched_set_code TEXT,
                matched_collector_number TEXT,
                matched_language TEXT,
                matched_variant TEXT,
                condition_normalized TEXT,
                grader TEXT,
                grade_value REAL,
                eligible_raw INTEGER DEFAULT 0,
                eligible_graded INTEGER DEFAULT 0,
                exclusion_reason TEXT,
                resolver_version TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create interpretation table linking observations to card identities.'),
            ('v11', """CREATE TABLE IF NOT EXISTS price_calculation_runs (
                run_id INTEGER PRIMARY KEY,
                target_card_key TEXT NOT NULL,
                target_language_code TEXT,
                algorithm_version TEXT NOT NULL,
                query_primary TEXT,
                query_fallback TEXT,
                primary_request_count INTEGER DEFAULT 0,
                fallback_request_count INTEGER DEFAULT 0,
                total_observations INTEGER DEFAULT 0,
                exact_matches INTEGER DEFAULT 0,
                variant_matches INTEGER DEFAULT 0,
                identity_unknown INTEGER DEFAULT 0,
                no_matches INTEGER DEFAULT 0,
                raw_eligible_count INTEGER DEFAULT 0,
                graded_eligible_count INTEGER DEFAULT 0,
                excluded_count INTEGER DEFAULT 0,
                configuration_json TEXT,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                status TEXT DEFAULT 'pending'
            )""", 'Create calculation run tracking table.'),
            ('v12', """CREATE TABLE IF NOT EXISTS price_snapshots (
                snapshot_id INTEGER PRIMARY KEY,
                run_id INTEGER,
                target_card_key TEXT NOT NULL,
                printing_id INTEGER,
                sku_id INTEGER,
                price_type TEXT NOT NULL,
                grader TEXT,
                grade_value REAL,
                currency TEXT DEFAULT 'GBP',
                recommended_price REAL,
                median_price REAL,
                mean_price REAL,
                p25 REAL,
                p75 REAL,
                minimum_price REAL,
                maximum_price REAL,
                sample_size INTEGER,
                confidence_score REAL,
                confidence_label TEXT,
                calculated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                algorithm_version TEXT
            )""", 'Create reproducible published-price snapshots table.'),
            ('v13', 'CREATE INDEX IF NOT EXISTS idx_price_observations_target ON price_observations(target_card_key, target_language_code)', 'Index for looking up observations by card.'),
            ('v14', 'CREATE INDEX IF NOT EXISTS idx_price_observations_provider ON price_observations(source_name, provider_item_id)', 'Index for provider dedup.'),
            ('v15', 'CREATE INDEX IF NOT EXISTS idx_price_observation_matches_obs ON price_observation_matches(observation_id)', 'Index for joining matches to observations.'),
            ('v16', 'CREATE INDEX IF NOT EXISTS idx_price_observation_matches_target ON price_observation_matches(target_card_key)', 'Index for match lookup by card.'),
            ('v17', 'CREATE INDEX IF NOT EXISTS idx_price_snapshots_target ON price_snapshots(target_card_key)', 'Index for price snapshot lookup.'),
            ('v18', """CREATE TABLE IF NOT EXISTS canonical_printings (
                printing_id INTEGER PRIMARY KEY,
                canonical_card_key TEXT NOT NULL,
                source_card_id TEXT,
                language_code TEXT NOT NULL,
                set_id TEXT,
                set_code TEXT,
                collector_number TEXT,
                collector_number_normalized TEXT,
                printed_total INTEGER,
                name_localized TEXT,
                name_english TEXT,
                release_date TEXT,
                rarity TEXT,
                is_promo INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create canonical printing identity table.'),
            ('v18b', 'CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_printings_unique ON canonical_printings(canonical_card_key, language_code, set_code, collector_number_normalized)', 'Add unique constraint for canonical printing identity.'),
            ('v19', """CREATE TABLE IF NOT EXISTS commercial_variants (
                variant_id INTEGER PRIMARY KEY,
                printing_id INTEGER NOT NULL,
                finish TEXT DEFAULT 'normal',
                edition TEXT,
                stamp TEXT,
                parallel_type TEXT,
                is_first_edition INTEGER DEFAULT 0,
                is_unlimited INTEGER DEFAULT 1,
                variant_label TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create commercial variant model.'),
            ('v20', """CREATE TABLE IF NOT EXISTS sellable_skus (
                sku_id INTEGER PRIMARY KEY,
                printing_id INTEGER NOT NULL,
                variant_id INTEGER,
                language_code TEXT NOT NULL,
                condition_code TEXT NOT NULL,
                sku_key TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create sellable SKU table for deterministic valuation buckets.'),
            ('v20b', 'CREATE UNIQUE INDEX IF NOT EXISTS idx_sellable_skus_key_unique ON sellable_skus(sku_key)', 'Add unique constraint for SKU key.'),
            ('v21', """CREATE TABLE IF NOT EXISTS external_references (
                external_reference_id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                external_id TEXT,
                external_url TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                confidence REAL DEFAULT 1.0,
                status TEXT DEFAULT 'active'
            )""", 'Create generic external reference table for printing/variant/SKU/observation links.'),
            ('v22', 'CREATE INDEX IF NOT EXISTS idx_canonical_printings_card ON canonical_printings(canonical_card_key)', 'Index for canonical printing lookup.'),
            ('v23', 'CREATE INDEX IF NOT EXISTS idx_canonical_printings_set ON canonical_printings(set_code, collector_number_normalized)', 'Index for set+number lookup.'),
            ('v24', 'CREATE INDEX IF NOT EXISTS idx_commercial_variants_printing ON commercial_variants(printing_id)', 'Index for variant lookup by printing.'),
            ('v25', 'CREATE INDEX IF NOT EXISTS idx_sellable_skus_printing ON sellable_skus(printing_id)', 'Index for SKU lookup by printing.'),
            ('v26', 'CREATE INDEX IF NOT EXISTS idx_sellable_skus_key ON sellable_skus(sku_key)', 'Index for deterministic SKU key lookup.'),
            ('v27', 'CREATE INDEX IF NOT EXISTS idx_external_references_entity ON external_references(entity_type, entity_id)', 'Index for external reference lookup.'),
        ]
        ran: list[str] = []
        for version, sql, desc in migrations:
            if version not in applied:
                cur.execute(sql)
                cur.execute('INSERT INTO schema_migrations(version, description) VALUES (?, ?)', (version, desc))
                ran.append(version)
        # Rebuild FTS index if translation table was just created (v4) or if explicitly needed
        # Check if FTS table has name_english column; if not, rebuild
        cur.execute("SELECT COUNT(*) FROM pragma_table_info('v2_card_search_fts') WHERE name='name_english'")
        has_name_english = cur.fetchone()[0] > 0
        if not has_name_english:
            print('Rebuilding FTS index with name_english column...')
            try:
                from pokemon_db_v2_search_api import setup_fts
                setup_fts(app.state.db)
                print('FTS index rebuilt successfully.')
            except Exception as e:
                print(f'WARNING: FTS rebuild failed: {e}')
        conn.commit()
        return ran

    # Run migrations at startup
    with connect(app.state.db) as conn:
        ran = apply_migrations(conn)
        if ran:
            print(f'DB migrations applied: {ran}')

    # ── Translation coverage endpoint ───────────────────────────────────

    @app.get('/api/v1/i18n/coverage')
    def v1_i18n_coverage(_: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('''
            SELECT language_code,
                   COUNT(*) as total,
                   SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) as translated,
                   ROUND(100.0 * SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
            FROM card_name_translations
            GROUP BY language_code
            ORDER BY COUNT(*) DESC
        ''')
        by_language = []
        for row in cur.fetchall():
            by_language.append({
                'language_code': row[0],
                'total': row[1],
                'translated': row[2],
                'coverage_pct': row[3],
            })
        cur.execute('SELECT COUNT(*) FROM card_name_translations WHERE source = \'untranslated\'')
        total_untranslated = cur.fetchone()[0]
        return {
            'data': {
                'by_language': by_language,
                'total_untranslated': total_untranslated,
            }
        }

    # ── Quota enforcement middleware ───────────────────────────────────

    @app.middleware('http')
    async def v1_quota_enforcer(request: Request, call_next):
        if request.url.path.startswith('/api/v1') and not request.url.path.startswith('/api/v1/admin'):
            try:
                auth = await require_v1_api_key(request)
                request.state._v1_auth = auth
                api_key_id = auth.get('api_key_id')
                if api_key_id and auth.get('auth_required'):
                    conn = connect(app.state.db)
                    ensure_v1_api_support(conn)
                    cur = conn.cursor()
                    cur.execute('SELECT monthly_quota FROM developer_api_keys WHERE id=?', (api_key_id,))
                    row = cur.fetchone()
                    if row and row['monthly_quota']:
                        now_dt = dt.datetime.now(dt.timezone.utc)
                        ws = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                        if now_dt.month == 12:
                            we = now_dt.replace(year=now_dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                        else:
                            we = now_dt.replace(month=now_dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
                        cur.execute('SELECT COUNT(*) FROM api_request_log WHERE api_key_id=? AND requested_at >= ? AND requested_at < ?',
                                    (api_key_id, ws.isoformat(), we.isoformat()))
                        used = int(cur.fetchone()[0])
                        if used >= row['monthly_quota']:
                            from fastapi.responses import JSONResponse
                            return JSONResponse(status_code=429, content={'error': {'code': 'quota_exceeded', 'message': 'Monthly API quota exceeded.', 'details': {'monthly_quota': row['monthly_quota'], 'used': used}}})
            except HTTPException:
                pass
        response = await call_next(request)
        return response

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
            SELECT id, card_id, language_code, condition, condition_normalized, is_played, price_gbp, sold_date, listing_url,
                   source, imported_at, raw_title, bucket, confidence_score, match_notes,
                   query, source_site, is_recommended_input, cache_key, fetched_at, postage_cost, ebay_item_id, currency
            FROM uk_price_history WHERE {where} ORDER BY id DESC LIMIT ?
        ''', params)
        listings = [dict(zip(
            ['id', 'card_id', 'language_code', 'condition', 'condition_normalized', 'is_played', 'price_gbp', 'sold_date', 'listing_url',
             'source', 'imported_at', 'raw_title', 'bucket', 'confidence_score', 'match_notes',
             'query', 'source_site', 'is_recommended_input', 'cache_key', 'fetched_at',
             'postage_cost', 'ebay_item_id', 'currency'], r
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
            query = build_price_query(card, conn)
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
            query = build_price_query(c, conn)
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
        import time
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

        def classify(title: str) -> tuple[str, list[str], float | None]:
            """Classify listing bucket and extract grade value if graded.

            Returns (bucket, notes, grade_value).
            grade_value is the numeric grade (e.g. 10, 9.5) for graded cards, None for others.
            """
            t = title.lower()
            graded_terms = ['psa', 'bgs', 'cgc', 'ace ', 'tag ', 'graded', 'gem mt', 'gem mint']
            noisy_terms = ['proxy', 'custom', 'fake', 'replica', 'digital', 'code card', 'sleeve', 'coin', 'booster', 'pack ', 'empty', 'jumbo', 'oversized']
            bundle_terms = ['bundle', 'job lot', 'joblot', 'lot of', 'collection', 'set of', 'bulk']
            if any(x in t for x in noisy_terms):
                return 'noise', ['noise_term'], None
            if any(x in t for x in bundle_terms):
                return 'bundle', ['bundle_or_lot'], None
            # Check for graded — extract numeric grade
            grade_match = re.search(r'\b(psa|cgc|bgs|ace|tag)\s*(\d{1,2}(?:\.5)?)\b', t)
            if grade_match:
                grade_val = float(grade_match.group(2))
                return 'graded', ['graded'], grade_val
            if any(x in t for x in graded_terms):
                # Found a graded term but couldn't extract a number
                return 'graded', ['graded'], None
            return 'raw', ['raw'], None

        def token_score(title: str, q: str) -> tuple[float, list[str]]:
            stop = {'pokemon', 'pokémon', 'card', 'tcg', 'english', 'german', 'french', 'italian', 'spanish', 'japanese', 'korean', 'chinese', 'the', 'and', 'of'}
            title_l = title.lower()
            tokens = [x for x in re.findall(r'[a-z0-9]+', q.lower()) if len(x) > 1 and x not in stop]
            if not tokens:
                return 0.0, ['no_query_tokens']
            hits = [x for x in tokens if x in title_l]
            return round(len(hits) / len(tokens), 3), [f'token_match={len(hits)}/{len(tokens)}']

        def cleaned_raw_prices(rows: list[dict[str, Any]]) -> list[float]:
            """v8: Only exact_match raw listings with acceptable condition enter the recommendation.

            Filters (in order):
            1. bucket == 'raw'
            2. exact_match identity (set code + collector number)
            3. condition not in excluded set (Played/Poor)
            4. postage not abnormal
            5. price within sane range
            6. IQR outlier trimming
            """
            cfg = PRICING_CONFIG
            excluded_conditions = cfg['condition_excluded_from_raw']
            vals = []
            for r in rows:
                if r.get('bucket') != 'raw':
                    continue
                if r.get('price_gbp') is None:
                    continue
                # v8: exact_match only for primary recommendation
                if r.get('matching_score') != 'exact_match':
                    continue
                # v8: condition exclusion
                cond = r.get('condition_normalized')
                if cond in excluded_conditions:
                    continue
                # v8: postage exclusion — abnormal postage excluded from price population
                postage = r.get('postage_cost')
                if postage is not None and postage > cfg['postage_abnormal_threshold']:
                    continue
                # v8: confidence score sanity
                if r.get('confidence_score', 0) < 0.3:
                    continue
                vals.append(r['price_gbp'])
            vals = sorted([v for v in vals if cfg['price_min_gbp'] <= v <= cfg['price_max_gbp']])
            if len(vals) < 4:
                return vals
            q1 = pct(vals, 0.25) or vals[0]
            q3 = pct(vals, 0.75) or vals[-1]
            iqr = max(q3 - q1, 1)
            return [v for v in vals if max(cfg['price_min_gbp'], q1 - cfg['iqr_multiplier'] * iqr) <= v <= q3 + cfg['iqr_multiplier'] * iqr]

        def extract_set_code_and_number(title: str) -> tuple[str | None, str | None]:
            """Extract set code and collector number from listing title.

            Matches patterns like "sv03-223", "CP6-011", "Base Set 2 1/130",
            "CP6 085/087", "085/087 CP6", "5/102", "SWSH12-TG01".
            Returns (set_code, collector_number) or (None, None).
            collector_number may contain variant notation like "085/087".
            """
            # Pattern: set code + hyphen + number/tag (e.g., "CP6-011", "sv03-223", "SWSH12-TG01", "SV-P-001")
            m = re.search(r'\b([A-Za-z0-9-]{2,6})-(\d{1,4}(?:/\d{1,4})?|[A-Za-z]{1,2}\d{1,3})\b', title)
            if m:
                return m.group(1), m.group(2)
            # Pattern: set code + space + number with optional variant (e.g., "CP6 085/087", "CP6 085")
            # Set code must contain at least one LETTER and one digit (to avoid matching "228 197")
            m = re.search(r'\b([A-Za-z]+\d[A-Za-z0-9]*)\s+(\d{1,4}(?:/\d{1,4})?)\b', title)
            if m:
                return m.group(1), m.group(2)
            # Pattern: variant notation number/setcode (e.g., "085/087 CP6")
            # Set code must contain at least one digit (to avoid matching words like "Holo")
            m = re.search(r'\b(\d{1,4}/\d{1,4})\s+([A-Za-z]+\d+[A-Za-z0-9]*)\b', title)
            if m:
                return m.group(2), m.group(1)
            # Pattern: number/number (e.g., "1/130", "5/102") — also look for set code in nearby context
            m = re.search(r'\b(\d{1,4})/(\d{1,4})\b', title)
            if m:
                number = m.group(1)
                after_title = title[m.end():]
                # Search more broadly after the / number — skip through words to find any set code
                # e.g. "125/197 Holo Double Rare - Sv03: Obsidian" → Sv03 is the set code after words
                sc = re.search(r'\b([A-Za-z]+\d+[A-Za-z0-9]*)\b', after_title)
                if sc:
                    return sc.group(1).upper(), number
                before_title = title[:m.start()]
                sc = re.search(r'\b([A-Za-z]+\d+[A-Za-z0-9]*)\s+$', before_title)
                if sc:
                    return sc.group(1).upper(), number
                return None, number
            # Pattern: standalone "No. 123" or "#123"
            m = re.search(r'(?:No\.?|#)\s*(\d{1,4})\b', title, re.IGNORECASE)
            if m:
                return None, m.group(1)
            # Fallback: extract number and set code independently from title
            # Extract any fraction number like "125/197" or standalone "125"
            num = None
            m = re.search(r'(?:^|[#\s])(\d{1,4})(?:/\d{1,4})?', title)
            if m:
                num = m.group(1)
            # Extract set code — must contain at least one letter AND one digit
            m = re.search(r'\b([A-Za-z]+\d+[A-Za-z0-9]*)\b', title)
            set_code = m.group(1).upper() if m else None
            return set_code, num

        def compute_matching_score(title: str, card_set_code: str | None, card_number: str | None) -> tuple[str, str, list[str]]:
            """Score how well a listing title matches the target card.

            Returns (match_type, match_code, match_notes).
            match_type: 'exact_match', 'variant_match', 'identity_unknown', or 'no_match'
            match_code: the set-code-number found, or ''

            v8 identity logic:
            - exact_match: set code AND collector number match (including variant notation
              like "085/087" where the target number is one of the variants).
            - variant_match: set matches but collector number differs, or number matches
              but set differs.
            - identity_unknown: the listing lacks enough structured identity to prove or
              reject an exact match (no set code or number found in title).
            - no_match: the listing contains conflicting identity evidence (different set
              and different number, or explicitly mismatched).
            """
            listing_set_code, listing_number = extract_set_code_and_number(title)

            # Normalise for comparison: strip leading zeros from card number
            card_num_norm = card_number.lstrip('0') if card_number else None
            listing_num_norm = listing_number.lstrip('0') if listing_number else None

            # Handle variant notation: "085/087" — target "085" should match
            listing_variants = set()
            if listing_number and '/' in listing_number:
                listing_variants = {v.lstrip('0') for v in listing_number.split('/')}
            elif listing_number:
                listing_variants = {listing_num_norm}

            card_variants = set()
            if card_number and '/' in card_number:
                card_variants = {v.lstrip('0') for v in card_number.split('/')}
            elif card_number:
                card_variants = {card_num_norm}

            # 1. Both set code and number present in listing
            if listing_set_code and listing_number and card_set_code and card_number:
                set_match = listing_set_code.lower() == card_set_code.lower()
                # Number match: either exact or variant overlap
                num_match = bool(card_variants & listing_variants)
                if set_match and num_match:
                    return 'exact_match', f'{card_set_code}-{card_number}', ['exact_set_code_number']
                if set_match and not num_match:
                    return 'variant_match', f'{listing_set_code}-{listing_number}', ['same_set_different_number']
                if not set_match and num_match:
                    return 'variant_match', f'{listing_set_code}-{listing_number}', ['same_number_different_set']
                # Both present but both differ — conflicting identity
                return 'no_match', f'{listing_set_code}-{listing_number}', ['conflicting_set_and_number']

            # 2. Set code only (listing has set but no number)
            if listing_set_code and card_set_code and listing_set_code.lower() == card_set_code.lower():
                if not listing_number and not card_number:
                    return 'exact_match', listing_set_code, ['exact_set_code_only']
                if not listing_number:
                    return 'identity_unknown', listing_set_code, ['set_code_match_no_number_in_listing']

            # 3. Number only (listing has number but no set code)
            if listing_number and card_number and bool(card_variants & listing_variants):
                if not listing_set_code and not card_set_code:
                    return 'exact_match', listing_number, ['exact_number_only']
                if not listing_set_code:
                    return 'identity_unknown', listing_number, ['number_match_no_set_in_listing']

            # 4. Listing has neither set code nor number
            if not listing_set_code and not listing_number:
                return 'identity_unknown', '', ['no_set_code_or_number_in_title']

            # 5. Listing has set code but it doesn't match card's set code
            if listing_set_code and card_set_code and listing_set_code.lower() != card_set_code.lower():
                if not card_number and not listing_number:
                    return 'no_match', f'{listing_set_code}', ['different_set_no_number']
                return 'no_match', f'{listing_set_code}-{listing_number or "?"}', ['different_set']

            return 'identity_unknown', '', ['insufficient_identity_evidence']

        def build_fallback_query(primary_query: str) -> str:
            """Build a fallback query by removing only the collector number suffix.

            v8: Only remove the trailing number portion (e.g., "-085" or " 085/087"),
            not the set code. The set code must always be preserved.
            """
            # Try to remove just the number part after a set-code combo: "CP6-085" → "CP6"
            m = re.search(r'-(\d{1,4}(?:/\d{1,4})?)$', primary_query)
            if m:
                return primary_query[:m.start()]
            # Try removing " NNN/NNN" or " NNN" at the end (standalone number)
            m = re.search(r'\s+(\d{1,4}(?:/\d{1,4})?)$', primary_query)
            if m:
                return primary_query[:m.start()]
            return primary_query

        cache_ttl_hours = int(os.environ.get('POKEMON_PRICE_CACHE_TTL_HOURS', '168'))
        monthly_limit = int(os.environ.get('POKEMON_PRICE_MONTHLY_LIMIT', '1400'))
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()

        # Extract set code and number from the card for matching
        card_set_code_for_matching = None
        card_number_for_matching = None

        # When card_id is provided, auto-generate the correct query using build_price_query
        # This ensures non-English cards always get English eBay search terms
        query_used = query  # Track which query actually fetched the data

        # Normalize card_id: strip language prefix (e.g., "en:sv03-125" → "sv03-125")
        # The DB stores card_id without the language prefix in v2_card_detail_api_cache
        lookup_card_id = card_id
        if card_id and ':' in card_id:
            lookup_card_id = card_id.split(':', 1)[1]

        # Normalize case: DB uses uppercase card_ids like "CP6-085", normalize lookup to match
        if lookup_card_id:
            # SQLite BINARY compare is case-sensitive for TEXT; try both original and uppercase
            lookup_card_id_upper = lookup_card_id.upper()
        else:
            lookup_card_id_upper = None

        if card_id and language and language != 'en':
            cur.execute("""
                SELECT card_name, core_set_name, core_set_id, local_id, types, rarity
                FROM v2_card_detail_api_cache
                WHERE LOWER(card_id) = LOWER(?) AND language_code = ? LIMIT 1
            """, (lookup_card_id, language))
            card_row = cur.fetchone()
            if card_row:
                card_data = {
                    'card_id': card_id,
                    'language_code': language,
                    'name': card_row[0],
                    'card_name': card_row[0],
                    'core_set_name': card_row[1],
                    'core_set_id': card_row[2],
                    'collector_number': card_row[3],
                    'local_id': card_row[3],
                    'types': card_row[4],
                    'rarity': card_row[5],
                }
                generated_query = build_price_query(card_data, conn)
                if generated_query:
                    query = generated_query
                    query_used = generated_query
                card_set_code_for_matching = card_row[2]  # core_set_id
                card_number_for_matching = card_row[3]  # local_id
        elif card_id and language == 'en':
            # For English cards, try to look up set code and number too
            for fld in ['core_set_id', 'local_id']:
                if not hasattr(fld, 'fake'):
                    pass
            cur.execute("""
                SELECT core_set_id, local_id, card_name
                FROM v2_card_detail_api_cache
                WHERE LOWER(card_id) = LOWER(?) AND language_code = 'en' LIMIT 1
            """, (lookup_card_id,))
            card_row = cur.fetchone()
            if card_row:
                card_set_code_for_matching = card_row[0]
                card_number_for_matching = card_row[1]

        # Build fallback query for multi-query strategy
        fallback_query = build_fallback_query(query)

        # Cache key must be computed AFTER query override above
        cache_key = price_cache_key(query, language, max_results)

        # ── Cache check ────────────────────────────────────────────────
        if not force_refresh:
            cur.execute("""SELECT response_json, fetched_at, algorithm_version FROM uk_price_fetch_cache WHERE cache_key = ? AND datetime(fetched_at) >= datetime('now', ?)""", (cache_key, f'-{cache_ttl_hours} hours'))
            cached = cur.fetchone()
            if cached:
                # v8: Only return cache if algorithm version matches
                version_matches = cached[2] == PRICING_ALGORITHM_VERSION
                if version_matches:
                    data = json.loads(cached[0])
                    data['cached'] = True
                    data['cache_fetched_at'] = cached[1]
                    data['cost_guard'] = {'spent_request': False, 'monthly_limit': monthly_limit}
                    return data
                print(f'[PRICE_DEBUG] Cache version mismatch: {cached[2]!r} vs {PRICING_ALGORITHM_VERSION!r}, refreshing', flush=True)

        # ── Monthly usage guardrail ────────────────────────────────────
        month_start = dt.datetime.now(dt.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur.execute("""SELECT COUNT(*) FROM uk_price_fetch_usage WHERE status = 'ok' AND requested_at >= ?""", (month_start,))
        used_this_month = int(cur.fetchone()[0])
        if used_this_month >= monthly_limit:
            raise HTTPException(status_code=429, detail=f'Local monthly price-fetch guard reached ({used_this_month}/{monthly_limit}).')

        # ── RapidAPI call ──────────────────────────────────────────────
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

        def do_rapidapi_fetch(search_query: str, request_label: str) -> dict[str, Any] | None:
            """Execute a single RapidAPI fetch."""
            print(f'[PRICE_DEBUG] {request_label}: \"{search_query}\"', flush=True)
            payload = json.dumps({'keywords': search_query, 'max_search_results': str(max_results), 'site_id': '3', 'remove_outliers': False})
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    resp = req.post(
                        'https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems',
                        headers={'Content-Type': 'application/json', 'x-rapidapi-host': 'ebay-average-selling-price.p.rapidapi.com', 'x-rapidapi-key': key},
                        data=payload, timeout=30
                    )
                    print(f'RAPIDAPI RESPONSE: {resp.status_code} {resp.text[:100]}')
                    if resp.ok or resp.status_code not in (429, 503):
                        if resp.ok:
                            return resp.json()
                        return None
                    wait = (attempt + 1) * 5
                    print(f'RAPIDAPI retry {attempt+1}/{max_retries}: status={resp.status_code}, waiting {wait}s')
                    time.sleep(wait)
                except Exception as req_err:
                    if attempt == max_retries - 1:
                        print(f'RAPIDAPI connection error, final: {req_err}')
                        return None
                    wait = (attempt + 1) * 5
                    print(f'RAPIDAPI connection error, retry {attempt+1}/{max_retries}: {req_err}, waiting {wait}s')
                    time.sleep(wait)
            return None

        # Primary query
        raw_data = do_rapidapi_fetch(query, 'Query 1 (primary)')
        if raw_data is None:
            cur.execute('INSERT INTO uk_price_fetch_usage(query, language_code, card_id, status) VALUES (?, ?, ?, ?)', (query, language, card_id, 'request_error'))
            conn.commit()
            raise HTTPException(status_code=502, detail='RapidAPI request failed for primary query.')

        # ── Process primary results ────────────────────────────────────
        def enrich_products(raw_data: dict[str, Any], search_query: str) -> list[dict[str, Any]]:
            """Enrich a batch of products from RapidAPI."""
            results: list[dict[str, Any]] = []
            for prod in (raw_data.get('products', []) or []):
                title = re.sub(r'\s+', ' ', str(prod.get('title') or prod.get('name') or '')).strip()
                price = money(prod.get('sale_price') or prod.get('price'))
                bucket, notes, grade_value = classify(title)
                score, score_notes = token_score(title, search_query)
                if price is None:
                    notes.append('missing_price')
                if bucket == 'noise':
                    score = min(score, 0.35)
                ebay_condition = prod.get('condition')
                listing_url = prod.get('link') or prod.get('url') or prod.get('item_web_url')
                cond_normalized, is_played = normalize_listing_condition(ebay_condition, title)
                postage = money(prod.get('shipping_cost') or prod.get('postage_cost'))
                # Variant isolation: compute matching_score
                match_type, match_code, match_notes_list = compute_matching_score(
                    title, card_set_code_for_matching, card_number_for_matching
                )
                postage_flag = postage is not None and postage > 10.0
                results.append({
                    'title': title, 'price_gbp': price,
                    'sold_date': prod.get('date_sold') or prod.get('sold_date') or prod.get('sale_date'),
                    'listing_url': listing_url,
                    'condition': ebay_condition,
                    'condition_normalized': cond_normalized,
                    'is_played': is_played,
                    'postage_cost': postage,
                    'ebay_item_id': str(prod.get('item_id') or '') or extract_ebay_item_id(listing_url),
                    'currency': 'GBP',
                    'bucket': bucket, 'confidence_score': score,
                    'match_notes': notes + score_notes + match_notes_list,
                    'grade_value': grade_value,
                    'matching_score': match_type,
                    'matching_code': match_code,
                    'postage_flag': postage_flag,
                })
            return results

        enriched = enrich_products(raw_data, query)

        # Count raw results from primary query
        primary_raw_count = len([r for r in enriched if r.get('bucket') == 'raw'])
        print(f'[PRICE_DEBUG] Query 1 results: total={len(enriched)}, raw={primary_raw_count}', flush=True)

        # ── Multi-query fallback ──────────────────────────────────────
        # v8: Trigger fallback based on eligible exact matches, not raw count
        used_fallback = False
        fallback_products = None
        primary_exact_count = len([r for r in enriched if r.get('matching_score') == 'exact_match' and r.get('bucket') == 'raw'])
        fallback_min_exact = PRICING_CONFIG['fallback_min_exact_matches']
        if primary_exact_count < fallback_min_exact and fallback_query != query:
            print(f'[PRICE_DEBUG] Primary exact matches: {primary_exact_count} (threshold: {fallback_min_exact}) — trying fallback: \"{fallback_query}\"', flush=True)
            fallback_data = do_rapidapi_fetch(fallback_query, 'Query 2 (fallback)')
            if fallback_data:
                fallback_products = fallback_data.get('products', []) or []
                # Enrich fallback products
                fallback_enriched = enrich_products(fallback_data, fallback_query)
                fallback_raw_count = len([r for r in fallback_enriched if r.get('bucket') == 'raw'])
                print(f'[PRICE_DEBUG] Query 2 (fallback) results: total={len(fallback_enriched)}, raw={fallback_raw_count}', flush=True)

                # v8: Merge by ebay_item_id when available, then title fallback
                existing_item_ids = {r.get('ebay_item_id', '') for r in enriched if r.get('ebay_item_id')}
                existing_titles = {r['title'].lower() for r in enriched if not r.get('ebay_item_id')}
                for r in fallback_enriched:
                    item_id = r.get('ebay_item_id', '')
                    if item_id and item_id in existing_item_ids:
                        continue
                    if not item_id and r['title'].lower() in existing_titles:
                        continue
                    enriched.append(r)
                    if item_id:
                        existing_item_ids.add(item_id)
                    else:
                        existing_titles.add(r['title'].lower())

                query_used = fallback_query
                query = fallback_query  # Update for persistence
                used_fallback = True

        total_raw_count = len([r for r in enriched if r.get('bucket') == 'raw'])
        print(f'[PRICE_DEBUG] After merge: total={len(enriched)}, raw={total_raw_count}', flush=True)

        # ── Stats computation ──────────────────────────────────────────
        all_prices = [r['price_gbp'] for r in enriched if r.get('price_gbp') is not None and r.get('bucket') != 'noise']
        raw_rows = [r for r in enriched if r.get('bucket') == 'raw']
        graded_rows = [r for r in enriched if r.get('bucket') == 'graded']
        bundle_rows = [r for r in enriched if r.get('bucket') == 'bundle']
        clean_raw = cleaned_raw_prices(enriched)
        clean_stats = stats(clean_raw)
        raw_all_stats = stats([r['price_gbp'] for r in raw_rows if r.get('price_gbp') is not None])
        all_stats = stats(all_prices)

        # ── Graded price sanity checks ─────────────────────────────────
        raw_median = clean_stats.get('median') if clean_raw else (raw_all_stats.get('median') if raw_all_stats.get('count', 0) > 0 else None)
        graded_prices = [r for r in graded_rows if r.get('price_gbp') is not None]
        graded_outliers_excluded = 0
        graded_outlier_reasons: list[str] = []
        graded_clean_prices: list[float] = []

        if raw_median and graded_prices:
            grade_thresholds = {
                # Multiplier thresholds: (min_mult, max_mult)
                'PSA 10': (2.5, 5.0),
                'PSA 9': (1.5, 3.0),
                'PSA 8': (1.0, 2.0),
                'PSA 7': (0.7, 1.5),
                'BGS 10': (3.0, 6.0),
                'BGS 9.5': (2.0, 4.0),
                'BGS 9': (1.5, 3.0),
                'CGC 10': (3.0, 6.0),
                'CGC 9.5': (2.0, 4.0),
                'CGC 9': (1.5, 3.0),
            }
            for gp in graded_prices:
                gv = gp.get('grade_value')
                price_val = gp['price_gbp']
                if gv is not None and price_val is not None:
                    # Determine expected multipliers based on grade
                    expected_min = raw_median * 0.7 * (gv / 7.0)  # Scale from base 1x at grade 7
                    expected_max = raw_median * 2.0 * (gv / 7.0)  # Scale from base 2x at grade 7
                    # Explicit thresholds for common grades
                    title_lower = gp.get('title', '').lower()
                    grade_key = None
                    for gk in sorted(grade_thresholds.keys(), reverse=True):
                        gk_lower = gk.lower()
                        gk_parts = gk_lower.split()
                        if gk_parts[0] in title_lower:
                            # Check if the numbers match
                            expected_num = float(gk_parts[1])
                            if gv is not None and abs(gv - expected_num) < 0.1:
                                grade_key = gk
                                break
                    if grade_key and grade_key in grade_thresholds:
                        min_mult, max_mult = grade_thresholds[grade_key]
                        expected_min = raw_median * min_mult
                        expected_max = raw_median * max_mult
                    else:
                        # Generic scaling
                        expected_min = raw_median * max(0.5, gv * 0.2)
                        expected_max = raw_median * min(10.0, gv * 0.6)
                    # Check if price exceeds expected range by >2x
                    if price_val > expected_max * 2:
                        graded_outliers_excluded += 1
                        graded_outlier_reasons.append(
                            f'{gp.get("grade_value_display") or f"Grade {gv}"} at £{price_val:.2f} — beyond threshold £{expected_max:.2f}'
                        )
                        continue
                graded_clean_prices.append(price_val)

        graded_clean_stats = stats(graded_clean_prices) if graded_clean_prices else {'count': 0}
        if graded_outliers_excluded:
            print(f'[PRICE_DEBUG] Graded outliers excluded: {graded_outliers_excluded}', flush=True)
            for reason in graded_outlier_reasons:
                print(f'[PRICE_DEBUG]   {reason}', flush=True)
        print(f'[PRICE_DEBUG] Graded found: {len(graded_prices)} → median £{graded_clean_stats.get("median", "N/A")}', flush=True)

        # ── Variant isolation / confidence (v8) ────────────────────────
        exact_match_count = len([r for r in enriched if r.get('matching_score') == 'exact_match'])
        variant_match_count = len([r for r in enriched if r.get('matching_score') == 'variant_match'])
        identity_unknown_count = len([r for r in enriched if r.get('matching_score') == 'identity_unknown'])
        no_match_count = len([r for r in enriched if r.get('matching_score') == 'no_match'])
        # Count exclusions
        condition_excluded = len([r for r in enriched if r.get('bucket') == 'raw' and r.get('matching_score') == 'exact_match' and r.get('condition_normalized') in PRICING_CONFIG['condition_excluded_from_raw']])
        postage_excluded = len([r for r in enriched if r.get('bucket') == 'raw' and r.get('matching_score') == 'exact_match' and r.get('postage_cost') is not None and r.get('postage_cost') > PRICING_CONFIG['postage_abnormal_threshold']])
        identity_excluded = len([r for r in enriched if r.get('bucket') == 'raw' and r.get('matching_score') != 'exact_match'])
        duplicate_count = len(enriched) - len({r.get('ebay_item_id', '') or r['title'].lower() for r in enriched})

        # v8 confidence: component-based
        confidence_score = 0.0
        confidence_reasons = []
        confidence_weaknesses = []
        if exact_match_count >= PRICING_CONFIG['confidence_high_min_exact']:
            confidence_score = min(0.95, 0.7 + exact_match_count * 0.02)
            confidence_reasons.append(f'{exact_match_count} exact matches')
        elif exact_match_count >= PRICING_CONFIG['confidence_medium_min_exact']:
            confidence_score = min(0.7, 0.4 + exact_match_count * 0.08)
            confidence_reasons.append(f'{exact_match_count} exact matches')
        else:
            confidence_score = max(0.1, 0.1 + exact_match_count * 0.1)
            confidence_weaknesses.append(f'Only {exact_match_count} exact matches')

        if identity_unknown_count > exact_match_count:
            confidence_score *= 0.8
            confidence_weaknesses.append(f'{identity_unknown_count} listings with unknown identity')

        if used_fallback:
            confidence_score *= 0.85
            confidence_weaknesses.append('Fallback query required')

        if condition_excluded > 0:
            confidence_weaknesses.append(f'{condition_excluded} excluded for condition')

        confidence_score = round(min(1.0, max(0.0, confidence_score)), 2)
        if confidence_score >= 0.7:
            confidence = 'HIGH'
        elif confidence_score >= 0.4:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        print(f'[PRICE_DEBUG] Exact: {exact_match_count}, Variant: {variant_match_count}, Unknown: {identity_unknown_count}, NoMatch: {no_match_count}, Confidence: {confidence} ({confidence_score})', flush=True)

        # Debug: raw median
        clean_raw_count = len(clean_raw)
        if clean_raw:
            print(f'[PRICE_DEBUG] Raw median: £{clean_stats.get("median")} ({clean_raw_count} listings)', flush=True)

        # ── Build response ─────────────────────────────────────────────
        result = {
            'success': raw_data.get('success', True),
            'query': query,  # The query actually used
            'query_used': query_used,
            'language': language,
            'card_id': card_id,
            'cached': False,
            'algorithm_version': PRICING_ALGORITHM_VERSION,
            'cost_guard': {
                'spent_request': True,
                'used_this_month_before_request': used_this_month,
                'monthly_limit': monthly_limit,
                'remaining_before_guard': max(0, monthly_limit - used_this_month - 1),
            },
            'total_results': raw_data.get('total_results') or raw_data.get('results'),
            'products': enriched,
            'summary': {
                'raw_clean': clean_stats,
                'raw_all': raw_all_stats,
                'graded': graded_clean_stats,
                'graded_raw_all': stats([r['price_gbp'] for r in graded_rows if r.get('price_gbp') is not None]),
                'bundles': stats([r['price_gbp'] for r in bundle_rows if r.get('price_gbp') is not None]),
                'noise_count': len([r for r in enriched if r.get('bucket') == 'noise']),
            },
            'recommendation': {
                'basis': 'raw_exact_match_median',
                'typical_raw_price_gbp': clean_stats.get('median') if clean_raw else None,
                'typical_range_gbp': [clean_stats.get('p25'), clean_stats.get('p75')] if clean_raw else None,
                'notes': 'v8: Only exact-match raw listings with acceptable condition enter the recommendation. Played/Poor excluded. Abnormal postage excluded. IQR trimming applied last.',
            },
            # v8 Enhanced transparency markers
            'matching': {
                'confidence': confidence,
                'confidence_score': confidence_score,
                'confidence_reasons': confidence_reasons,
                'confidence_weaknesses': confidence_weaknesses,
                'exact_match_listings': exact_match_count,
                'variant_match_listings': variant_match_count,
                'identity_unknown_listings': identity_unknown_count,
                'no_match_listings': no_match_count,
            },
            'selection': {
                'raw_eligible': len(clean_raw),
                'graded_eligible': len(graded_clean_prices),
                'duplicates_excluded': duplicate_count,
                'condition_excluded': condition_excluded,
                'postage_excluded': postage_excluded,
                'identity_excluded': identity_excluded,
            },
            'source': {
                'provider': 'RapidAPI eBay Average Selling Price',
                'observation_type': 'active_listing',
                'description': 'eBay marketplace listing observations',
            },
            'outliers': {
                'graded_outliers_excluded': graded_outliers_excluded,
                'graded_outlier_reasons': graded_outlier_reasons,
            },
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
        # v8: Store algorithm version with cache for version-aware cache invalidation
        cur.execute("""INSERT OR REPLACE INTO uk_price_fetch_cache(cache_key, query, language_code, card_id, response_json, fetched_at, algorithm_version) VALUES (?, ?, ?, ?, ?, ?, ?)""", (cache_key, query, language, card_id, json.dumps(result), fetched_at, PRICING_ALGORITHM_VERSION))
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


