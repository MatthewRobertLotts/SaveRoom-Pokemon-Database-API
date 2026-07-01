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
import hmac
import json
import os
import re

import argparse
import datetime as dt
import sqlite3
import sys
import time
import threading
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import warnings
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
from pokemon_db_v5_api_models import (
    ApiKeyCreateV1,
    ApiKeyCreatedResponseV1,
    ApiKeyListResponseV1,
    CanonicalPrintingSummaryV1,
    CardDetailResponseV1,
    CardSearchResponseV1,
    CommercialVariantSummaryV1,
    HealthResponseV1,
    IdentityBuildRunSummaryV1,
    IdentityHealthResponseV1,
    ImageDetailResponseV1,
    InventoryListingDraftCreateRequestV1,
    InventoryListingDraftResponseV1,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryListResponse,
    InventoryLocationChange,
    InventoryLocationList,
    InventoryStatusChange,
    InventoryTransactionCreate,
    InventoryValuation,
    InventoryValuationBreakdown,
    InventoryValuationResponse,
    LanguageListResponseV1,
    ListingAssistantRequestV1,
    ListingAssistantResponseV1,
    ListingDraftCreateRequestV1,
    ListingDraftListResponseV1,
    ListingDraftResponseV1,
    ListingDraftUpdateRequestV1,
    PhysicalItemResponse,
    PriceHistoryResponseV1,
    PriceSummaryResponseV1,
    QuotaStatusResponseV1,
    SellableSKUIdentity,
    SellableSKUSummaryV1,
    SetDetailResponseV1,
    SetListResponseV1,
    TenantCreate,
    TenantDetailResponse,
    TenantListResponse,
    TenantResponse,
    TransactionListResponse,
    TransactionResponse,
    TransactionSummary,
    UserCreate,
    UserListResponse,
    UserResponse,
    DeliveryPolicyArticle,
    DeliveryPolicyCreate,
    DeliveryPolicyListResponse,
    DeliveryPolicyArticleResponse,
    TakedownCaseCreate,
    TakedownCaseListResponse,
    TakedownCaseResolve,
    SignedUrlResponse,
    SignedUrlResponseArticle,
    PhysicalPhotoUploadResponse,
    PhysicalPhotoListResponse,
    PhysicalPhotoUploadResponseArticle,
    PhysicalPhotoDetailResponse,
    PhysicalPhotoItem,
    ScannerScanResponse,  # v7 scanner
    AppReadyCardDetailResponseV1,
    AppReadyCardDetailDataV1,
    AppReadyCardV1,
    AppReadySetV1,
    AppReadyImageV1,
    AppReadyCommercialV1,
    AppReadyPricingV1,
    AppReadyPriceV1,
    AppReadySourceBreakdownV1,
    AppReadyEvidenceSummaryV1,
    AppReadyProviderStatusMapV1,
    AppReadyProviderStatusV1,
    AppReadyMetadataV1,
    AppReadyBatchRequestV1,
    AppReadyBatchResponseV1,
    AppReadyBatchItemV1,
    AppReadyBatchItemErrorV1,
    AppReadyBatchSummaryV1,
    AppReadyBatchDataV1,
    ChartReadyPriceHistoryResponseV1,
    ChartReadyPriceHistoryDataV1,
    ChartReadySeriesV1,
    ChartReadyPointV1,
    ChartReadySummaryV1,
)
from pricing_sources.uk_pricing_model import build_pricing_recommendation

# DEFAULT_SETTINGS removed in v9.1 — call settings_from_env() directly
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
_PRICE_SCHEMA_LOCK = threading.Lock()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return SQLite column names for an internal trusted table name."""
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """Add an internal trusted column definition if it is not already present.

    The table/column/DDL values are constants defined in this module, not user
    input. The duplicate-column guard handles a narrow race where another
    connection migrates the same column between our check and ALTER TABLE.
    """
    if column in _table_columns(conn, table):
        return False
    try:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
        return True
    except sqlite3.OperationalError as exc:
        if 'duplicate column name' in str(exc).lower() and column in _table_columns(conn, table):
            return False
        raise

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
    with _PRICE_SCHEMA_LOCK:
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
        for column, ddl in PRICE_HISTORY_V4_COLUMNS.items():
            _add_column_if_missing(conn, 'uk_price_history', column, ddl)
        for column, ddl in PRICE_HISTORY_V5_COLUMNS.items():
            _add_column_if_missing(conn, 'uk_price_history', column, ddl)
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
        _add_column_if_missing(conn, 'uk_price_fetch_cache', 'algorithm_version', 'TEXT')
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


def _price_object(amount: float | None, *, currency: str = 'GBP', **extra: Any) -> dict[str, Any] | None:
    """Return a small serializable price object for v1 pricing recommendations."""
    if amount is None:
        return None
    # Put amount/currency last so optional metadata (e.g. raw_min/raw_max) can
    # never accidentally overwrite the price object's identity fields.
    return {**extra, 'amount': amount, 'currency': currency}


def build_v1_price_recommendation(summary: dict[str, Any], provider_status_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a v1-safe local UK-only pricing recommendation section.

    This v12 milestone maps existing local GBP price-summary evidence into the
    pure pricing model. It does not call JustTCG, TotalTCG, TCGplayer,
    Cardmarket, HTTP, DB, or environment helpers. Fallback provider blending is
    a future milestone.
    """
    currency = summary.get('currency') or 'GBP'
    raw_median = summary.get('raw_median')
    recommended_raw_count = int(summary.get('recommended_raw_count') or 0)
    evidence_count = int(summary.get('evidence_count') or 0)
    uk_evidence_count = recommended_raw_count or (evidence_count if raw_median is not None else 0)
    primary_uk_price = raw_median if raw_median is not None and uk_evidence_count > 0 else None

    recommendation = build_pricing_recommendation(
        primary_uk_price=primary_uk_price,
        uk_evidence_count=uk_evidence_count,
        fallback_converted_price_gbp=None,
        fallback_provider=None,
        candidate_multipliers=None,
        listing_strategy='balanced',
        provider_status_summary=provider_status_summary or {},
    )
    data = recommendation.to_dict()

    raw_source = summary.get('source')
    primary_obj = _price_object(
        data['primary_uk_price'],
        currency=currency,
        evidence_count=uk_evidence_count,
        source='ebay_uk_sold',
        raw_source=raw_source,
        source_type='local_uk_evidence',
        price_type='sold_completed',
        raw_min=summary.get('raw_min'),
        raw_max=summary.get('raw_max'),
        latest_fetched_at=summary.get('latest_fetched_at'),
    )
    general_obj = _price_object(
        data['general_market_estimate'],
        currency=currency,
        source_type='local_uk_evidence' if data['general_market_estimate'] is not None else None,
    )
    listing_obj = _price_object(
        data['recommended_listing_price'],
        currency=currency,
        strategy='balanced',
    )

    return {
        'currency': currency,
        'region_basis': data['region_basis'],
        'primary_uk_price': primary_obj,
        'uk_adjusted_fallback_price': None,
        'general_market_estimate': general_obj,
        'recommended_listing_price': listing_obj,
        'source_breakdown': data['source_breakdown'],
        'evidence_count': uk_evidence_count,
        'confidence': data['confidence'],
        'confidence_score': data['confidence_score'],
        'confidence_reasons': data['confidence_reasons'],
        'warnings': data['warnings'],
        'calculation_method': 'local_uk_only; ' + data['calculation_method'],
        'adjustment_multiplier': None,
        'adjustment_multiplier_level': None,
        'adjustment_multiplier_sample_size': None,
        'adjustment_basis': None,
        'provider_status_summary': provider_status_summary or {},
    }


PLATFORM_GUIDANCE_V1: dict[str, dict[str, Any]] = {
    'whatnot': {
        'title_limit': 80,
        'description_limit': 500,
        'required_fields': ['title', 'condition', 'quantity'],
        'optional_fields': ['subtitle', 'tags', 'images', 'price'],
        'notes': 'Short stream-safe title; mention condition clearly.',
    },
    'ebay': {
        'title_limit': 80,
        'description_limit': 4000,
        'required_fields': ['title', 'condition', 'item specifics', 'price'],
        'optional_fields': ['subtitle', 'tags', 'images'],
        'notes': 'SEO title; include set, number, rarity, language.',
    },
    'shopify': {
        'title_limit': 120,
        'description_limit': 5000,
        'required_fields': ['title', 'product_type', 'tags', 'price'],
        'optional_fields': ['subtitle', 'images', 'variant mapping'],
        'notes': 'Clean product title; useful tags and SKU/variant mapping.',
    },
    'generic': {
        'title_limit': 120,
        'description_limit': 2000,
        'required_fields': ['title', 'description', 'condition'],
        'optional_fields': ['subtitle', 'tags', 'images', 'price'],
        'notes': 'Reusable listing copy.',
    },
}


def _clean_listing_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _join_listing_parts(parts: list[Any]) -> str:
    return ' '.join(str(part).strip() for part in parts if _clean_listing_text(part))


def _build_listing_title(*, platform: str, title_style: str, name: str, number: str | None,
                         set_name: str | None, rarity: str | None) -> str:
    base_parts = [name, number, set_name, rarity]
    if platform == 'shopify':
        right = _join_listing_parts([set_name, number])
        return f'{name} — {right}' if right else name
    if platform == 'ebay' or title_style == 'seo':
        return _join_listing_parts(base_parts + ['Pokémon Card'])
    if platform == 'whatnot':
        return _join_listing_parts(base_parts)
    return _join_listing_parts([name, number, set_name])


def _listing_tags(*, name: str, set_name: str | None, rarity: str | None, language_code: str | None,
                  platform: str, finish: str | None) -> list[str]:
    tags = ['pokemon-card', platform]
    for value in (name, set_name, rarity, language_code, finish):
        text = _clean_listing_text(value)
        if text:
            tags.append(text.lower().replace(' ', '-'))
    return list(dict.fromkeys(tags))


def _description_bullets(*, card: dict[str, Any], set_section: dict[str, Any], quantity: int,
                         condition: str | None, finish: str | None,
                         pricing: dict[str, Any] | None) -> list[str]:
    bullets = [
        f"Card name: {card.get('name') or 'Unknown'}",
        f"Set: {set_section.get('name') or 'Unknown'}",
        f"Number: {card.get('number') or 'Unknown'}",
        f"Rarity: {card.get('rarity') or 'Unknown'}",
        f"Language: {card.get('language_code') or 'Unknown'}",
    ]
    if condition:
        bullets.append(f'Condition: {condition}')
    if finish:
        bullets.append(f'Finish: {finish}')
    bullets.append(f'Quantity: {quantity}')
    if pricing:
        bullets.append(f"Pricing confidence: {pricing.get('confidence') or 'none'}")
        for warning in pricing.get('warnings') or []:
            bullets.append(f'Pricing note: {warning}')
    return bullets


def _listing_pricing_from_recommendation(recommendation: dict[str, Any], *, pricing_strategy: str) -> dict[str, Any]:
    recommended = recommendation.get('recommended_listing_price') or {}
    general = recommendation.get('general_market_estimate') or {}
    primary = recommendation.get('primary_uk_price') or {}
    warnings_out = list(recommendation.get('warnings') or [])
    if pricing_strategy != 'balanced':
        warnings_out.append(
            f"Pricing strategy {pricing_strategy!r} requested, but this v12 milestone exposes balanced recommendation only."
        )
    return {
        'currency': recommended.get('currency') or general.get('currency') or primary.get('currency') or recommendation.get('currency') or 'GBP',
        'suggested_price': recommended.get('amount'),
        'floor_price': None,
        'ceiling_price': None,
        'confidence': recommendation.get('confidence'),
        'source_summary': {
            'region_basis': recommendation.get('region_basis'),
            'calculation_method': recommendation.get('calculation_method'),
            'evidence_count': recommendation.get('evidence_count', 0),
            'source_breakdown': recommendation.get('source_breakdown') or [],
        },
        'warnings': warnings_out,
        'based_on_recommendation': {
            'recommended_listing_price': recommended or None,
            'general_market_estimate': general or None,
            'primary_uk_price': primary or None,
            'confidence': recommendation.get('confidence'),
        },
    }


def _listing_platform_guidance(platform: str) -> dict[str, Any]:
    return {'platform': platform, **PLATFORM_GUIDANCE_V1[platform]}


def _safe_listing_provider_status() -> dict[str, Any]:
    return {
        'recommendation': {
            'role': 'local_uk_pricing_recommendation',
            'status': 'used',
            'live_enabled': False,
            'notes': 'Listing assistant uses data.recommendation derived from local GBP evidence only.',
        },
        'justtcg': {
            'role': 'fallback_metadata_only',
            'status': 'not_used_for_listing_assistant',
            'live_enabled': False,
            'notes': 'JustTCG pricing is not fetched or used by this endpoint.',
        },
        'totaltcg': {
            'role': 'fallback_future_milestone',
            'status': 'not_used_for_listing_assistant',
            'live_enabled': False,
            'notes': 'TotalTCG pricing is not fetched or used by this endpoint.',
        },
    }


LISTING_DRAFT_COLUMNS = [
    'draft_id',
    'card_key',
    'language_code',
    'card_id',
    'platform',
    'status',
    'title',
    'subtitle',
    'description_json',
    'tags_json',
    'condition',
    'finish',
    'quantity',
    'pricing_json',
    'images_json',
    'commercial_json',
    'platform_guidance_json',
    'provider_status_json',
    'warnings_json',
    'assistant_payload_json',
    'source_assistant_contract',
    'notes',
    'created_at',
    'updated_at',
    'archived_at',
]


def _json_dumps_safe(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _json_loads_safe(value: str | None, default: Any) -> Any:
    if value in (None, ''):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _ensure_listing_drafts_table(conn: sqlite3.Connection) -> None:
    """Create the local listing draft table if needed."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listing_drafts (
            draft_id TEXT PRIMARY KEY,
            card_key TEXT NOT NULL,
            language_code TEXT,
            card_id TEXT,
            platform TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            title TEXT,
            subtitle TEXT,
            description_json TEXT,
            tags_json TEXT,
            condition TEXT,
            finish TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            pricing_json TEXT,
            images_json TEXT,
            commercial_json TEXT,
            platform_guidance_json TEXT,
            provider_status_json TEXT,
            warnings_json TEXT,
            assistant_payload_json TEXT NOT NULL,
            source_assistant_contract TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        )
    """)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_listing_drafts_card_key ON listing_drafts(card_key)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_listing_drafts_status_updated ON listing_drafts(status, updated_at)')
    conn.commit()


def _ensure_inventory_listing_draft_links_table(conn: sqlite3.Connection) -> None:
    """Create the local inventory-to-listing-draft bridge table if needed."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_listing_draft_links (
            id TEXT PRIMARY KEY,
            inventory_item_id TEXT NOT NULL,
            draft_id TEXT NOT NULL,
            card_key TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_inventory_listing_draft_links_item ON inventory_listing_draft_links(inventory_item_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_inventory_listing_draft_links_draft ON inventory_listing_draft_links(draft_id)')
    conn.commit()


def _listing_draft_id() -> str:
    return f'ld_{uuid.uuid4().hex}'


def _inventory_listing_draft_link_id() -> str:
    return f'ildl_{uuid.uuid4().hex}'


def _persist_listing_draft(
    conn: sqlite3.Connection,
    *,
    assistant_data: dict[str, Any],
    request_body: ListingDraftCreateRequestV1,
    draft_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Persist deterministic listing assistant output as a local draft."""
    card = assistant_data.get('card') or {}
    listing = assistant_data.get('listing') or {}
    resolved_draft_id = draft_id or _listing_draft_id()
    resolved_created_at = created_at or now_utc()
    _ensure_listing_drafts_table(conn)
    conn.execute(
        '''
        INSERT INTO listing_drafts (
            draft_id, card_key, language_code, card_id, platform, status,
            title, subtitle, description_json, tags_json, condition, finish, quantity,
            pricing_json, images_json, commercial_json, platform_guidance_json,
            provider_status_json, warnings_json, assistant_payload_json,
            source_assistant_contract, notes, created_at, updated_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            resolved_draft_id,
            card.get('card_key'),
            card.get('language_code'),
            (card.get('card_key') or '').split(':', 1)[1] if ':' in (card.get('card_key') or '') else None,
            request_body.platform,
            'draft',
            listing.get('title'),
            listing.get('subtitle'),
            _json_dumps_safe(listing.get('description_bullets') or []),
            _json_dumps_safe(listing.get('tags') or []),
            listing.get('condition_note') or _clean_listing_text(request_body.condition),
            _clean_listing_text(request_body.finish),
            request_body.quantity,
            _json_dumps_safe(assistant_data.get('pricing')),
            _json_dumps_safe(assistant_data.get('images')),
            _json_dumps_safe(assistant_data.get('commercial')),
            _json_dumps_safe(assistant_data.get('platform_guidance')),
            _json_dumps_safe(assistant_data.get('provider_status') or {}),
            _json_dumps_safe(assistant_data.get('warnings') or []),
            _json_dumps_safe(assistant_data),
            (assistant_data.get('metadata') or {}).get('contract') or 'v12-listing-assistant',
            _clean_listing_text(request_body.notes),
            resolved_created_at,
            resolved_created_at,
            None,
        ),
    )
    row = conn.execute('SELECT * FROM listing_drafts WHERE draft_id = ?', (resolved_draft_id,)).fetchone()
    return _listing_draft_row_to_response(row)


def _listing_draft_row_to_response(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    assistant_payload = _json_loads_safe(d.get('assistant_payload_json'), {})
    listing = {
        'title': d.get('title'),
        'subtitle': d.get('subtitle'),
        'description_bullets': _json_loads_safe(d.get('description_json'), []),
        'condition_note': d.get('condition'),
        'tags': _json_loads_safe(d.get('tags_json'), []),
        'notes': d.get('notes'),
    }
    return {
        'draft_id': d.get('draft_id'),
        'card_key': d.get('card_key'),
        'language_code': d.get('language_code'),
        'card_id': d.get('card_id'),
        'platform': d.get('platform'),
        'status': d.get('status'),
        'listing': listing,
        'pricing': _json_loads_safe(d.get('pricing_json'), None),
        'images': _json_loads_safe(d.get('images_json'), None),
        'commercial': _json_loads_safe(d.get('commercial_json'), None),
        'platform_guidance': _json_loads_safe(d.get('platform_guidance_json'), None),
        'provider_status': _json_loads_safe(d.get('provider_status_json'), {}),
        'warnings': _json_loads_safe(d.get('warnings_json'), []),
        'assistant_payload': assistant_payload,
        'source_assistant_contract': d.get('source_assistant_contract'),
        'condition': d.get('condition'),
        'finish': d.get('finish'),
        'quantity': d.get('quantity'),
        'created_at': d.get('created_at'),
        'updated_at': d.get('updated_at'),
        'archived_at': d.get('archived_at'),
    }


def _listing_draft_metadata() -> dict[str, Any]:
    return {
        'api_version': 'v1',
        'contract': 'v12-listing-draft',
        'generated_at': now_utc(),
    }


def _get_justtcg_price_data(card_key: str) -> dict[str, Any] | None:
    """Fetch JustTCG market price data for a card if access gate allows.

    Returns None if JustTCG is not configured, gate fails, or fetch errors.
    Never raises — failures are logged internally and None is returned.
    """
    try:
        from pricing_sources.justtcg import JustTCGAdapter
        from pricing_sources.provider_access import get_provider_access_status
        from pricing_sources.base import PriceQuery

        config = dict(os.environ)
        decision = get_provider_access_status("justtcg", config)

        if not decision.live_calls_allowed:
            return None

        adapter = JustTCGAdapter()
        query = PriceQuery(
            target_type="sellable_sku",
            target_id=card_key,
        )
        queries = adapter.build_queries(query)
        if not queries:
            return None

        raw = adapter.fetch(queries[0], config=config)
        if not raw:
            return None

        observations = adapter.normalise(raw, query)
        if not observations:
            return None

        # Pick the first observation with the highest confidence match
        matches = adapter.match_observations(observations, query)
        if not matches:
            return None

        best_match = max(matches, key=lambda m: {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNUSABLE": 0}.get(m.match_confidence.value, 0))
        obs = best_match.observation

        return {
            "source_code": "justtcg",
            "currency": obs.currency,
            "amount": obs.amount,
            "condition": obs.condition,
            "finish": obs.finish,
            "printing_label": obs.printing_label,
            "listing_type": obs.listing_type.value,
            "observation_type": obs.observation_type,
            "match_confidence": best_match.match_confidence.value,
            "match_method": best_match.match_method,
            "attribution": "Pricing data provided by JustTCG",
        }
    except Exception:
        # Never let JustTCG failures break the endpoint
        return None


def _get_justtcg_provider_status() -> dict[str, Any]:
    """Return current JustTCG provider status based on access gate."""
    try:
        from pricing_sources.provider_access import get_provider_access_status
        config = dict(os.environ)
        decision = get_provider_access_status("justtcg", config)

        if decision.live_calls_allowed:
            return {
                "role": "supporting_usd_fallback",
                "status": "enabled",
                "live_enabled": True,
                "terms_confirmed": True,
                "notes": "USD market/current pricing. SaveRoom ecosystem apps only. Not for external developer API resale.",
            }
        elif decision.status == "NOT_CONFIGURED":
            return {
                "role": "supporting_usd_fallback",
                "status": "not_configured",
                "live_enabled": False,
                "terms_confirmed": False,
                "notes": "Not configured. Set POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY to enable.",
            }
        else:
            return {
                "role": "supporting_usd_fallback",
                "status": "disabled",
                "live_enabled": False,
                "terms_confirmed": decision.status == "ENABLED_TERMS_CONFIRMED",
                "notes": f"Access gate: {decision.status}. {'; '.join(decision.reasons)}",
            }
    except Exception:
        return {
            "role": "supporting_usd_fallback",
            "status": "disabled",
            "live_enabled": False,
            "terms_confirmed": False,
            "notes": "Access gate check failed.",
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


def v1_card_from_detail(detail: dict[str, Any], conn: sqlite3.Connection, *, include_detail: bool = False, settings: Any = None) -> dict[str, Any]:
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
            'signed_image_url': _generate_card_signed_url(conn, canonical_card_key(language_code, card_id), settings) if settings else None,
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


# ── v9.1 Image Gateway Helpers ──────────────────────────────────────

ALLOWED_IMAGE_SIZES = frozenset({'thumbnail', 'small', 'medium', 'large'})
# v9.1: SIGNED_URL_SECRET moved into PokemonDBSettings
# DERIVATIVES_DIR moved into PokemonDBSettings
# PHYSICAL_PHOTOS_DIR moved into PokemonDBSettings


def _get_signed_url_secret(custom_secret: str | None = None) -> str:
    """Return signed URL HMAC secret.

    Resolution order:
      1. custom_secret argument (from settings.signed_url_secret)
      2. POKEMON_DB_SIGNED_URL_SECRET env var
      3. Ephemeral 64-char secret (development mode only)
      4. RuntimeError in production
    """
    import secrets as _sec
    secret = custom_secret
    if not secret:
        secret = os.environ.get('POKEMON_DB_SIGNED_URL_SECRET', '')
    if not secret:
        env_mode = os.environ.get('POKEMON_DB_ENV', 'development')
        if env_mode == 'development':
            secret = _sec.token_hex(32)
            import sys as _sys
            print('[v9.1] WARNING: Using ephemeral signed URL secret (POKEMON_DB_ENV=development) — URLs invalidated on restart', file=_sys.stderr)
        else:
            raise RuntimeError('POKEMON_DB_SIGNED_URL_SECRET must be set (min 32 chars). Generate: python -c "import secrets; print(secrets.token_hex(32))"')
    elif len(secret) < 32:
        raise RuntimeError('POKEMON_DB_SIGNED_URL_SECRET too short (got %d chars, need >=32 for 128-bit entropy)' % len(secret))
    return secret

def _image_root_dir(custom_root: Path | None = None, fallback_root: Path | None = None) -> Path | None:
    """Return the canonical image root directory.

    Resolution order:
      1. custom_root argument (from settings.image_root)
      2. POKEMON_DB_IMAGE_ROOT env var
      3. fallback_root argument
      4. None (no image_root configured)
    """
    if custom_root is not None:
        if custom_root.exists():
            return custom_root
        return None
    env = os.environ.get('POKEMON_DB_IMAGE_ROOT', '')
    if env:
        return Path(env)
    if fallback_root is not None:
        return fallback_root
    return None

def _ensure_derivatives_dir(custom_root: Path | None = None) -> Path | None:
    r = _image_root_dir(custom_root)
    if r is None:
        return None
    d = r.parent / 'derivatives'
    d.mkdir(parents=True, exist_ok=True)
    return d

def _ensure_physical_photos_dir(custom_root: Path | None = None) -> Path | None:
    r = _image_root_dir(custom_root)
    if r is None:
        return None
    d = r / 'physical_photos'
    d.mkdir(parents=True, exist_ok=True)
    return d

def resolve_image_asset(conn: sqlite3.Connection, image_id: int) -> dict[str, Any] | None:
    """Resolve a stable image_id from catalogue_image_assets.

    Returns dict with image_id, card_key, set_id, language_code, source_type,
    source_language_code, image_path, source_hash, or None if not found.
    """
    if image_id <= 0:
        return None
    cur = conn.cursor()
    row = cur.execute(
        "SELECT image_id, card_key, set_id, language_code, source_type,"
        " source_language_code, local_path, source_hash"
        " FROM catalogue_image_assets WHERE image_id = ?",
        (image_id,)
    ).fetchone()
    if not row:
        return None
    return {
        'image_id': row[0],
        'card_key': row[1],
        'set_id': row[2],
        'language_code': row[3],
        'source_type': row[4],
        'source_language_code': row[5],
        'image_path': re.sub(r'^/?images/', '', str(row[6])).lstrip('/'),
        'source_hash': row[7],
    }




def resolve_preferred_card_image(conn: sqlite3.Connection, card_key: str) -> dict[str, Any] | None:
    """Resolve the preferred image for a card key from catalogue_image_assets.

    Returns the same dict as resolve_image_asset, or None if no image exists.
    """
    cur = conn.cursor()
    row = cur.execute(
        "SELECT image_id, card_key, set_id, language_code, source_type,"
        " source_language_code, local_path, source_hash"
        " FROM catalogue_image_assets WHERE card_key = ?"
        " ORDER BY image_id LIMIT 1",
        (card_key,)
    ).fetchone()
    if not row:
        return None
    return {
        'image_id': row[0],
        'card_key': row[1],
        'set_id': row[2],
        'language_code': row[3],
        'source_type': row[4],
        'source_language_code': row[5],
        'image_path': re.sub(r'^/?images/', '', str(row[6])).lstrip('/'),
        'source_hash': row[7],
    }


def _generate_card_signed_url(
    conn: sqlite3.Connection,
    card_key: str,
    settings: Any,
    *,
    size: str = "medium",
) -> str | None:
    """Generate a controlled signed URL for browser image delivery.

    Returns None when no stable eligible asset exists or the source file
    is not resolvable.  Raises on unexpected signing/configuration errors
    so they surface in logs rather than being silently swallowed.
    """
    asset = resolve_preferred_card_image(conn, card_key)
    if not asset or not asset.get('image_id') or asset['image_id'] <= 0:
        return None

    image_id = asset['image_id']
    image_root = _image_root_dir(settings.image_root, fallback_root=settings.db.parent)
    if not image_root or not image_root.exists():
        return None

    safe_path = _safe_image_path(asset['image_path'], image_root)
    if not safe_path:
        return None

    secret = _get_signed_url_secret(settings.signed_url_secret)
    token, _expires_at = _generate_signed_url(image_id, size, secret)
    return f'/api/v1/images/assets/{image_id}/content?size={size}&token={token}'


def _eval_image_policy(conn: sqlite3.Connection, card_key: str, set_id: str | None,
                       language_code: str, source_type: str | None,
                       image_id: int = 0) -> dict[str, Any]:
    """Evaluate delivery policy for a card image. Most-specific scope wins.

    Precedence: image > card > set > language > source > global
    Returns dict with allowed, reason, attribution.
    """
    cur = conn.cursor()
    # 0) Check image-level policy (highest precedence)
    if image_id:
        row = cur.execute(
            "SELECT external_display_enabled, reason, attribution_text FROM image_delivery_policies WHERE scope_type='image' AND scope_value=?",
            (str(image_id),)
        ).fetchone()
        if row:
            return {'allowed': bool(row[0]), 'reason': row[1], 'attribution': row[2], 'matched_scope': 'image', 'scope_value': str(image_id)}
    # 1) Check card-level policy
    row = cur.execute(
        "SELECT external_display_enabled, reason, attribution_text FROM image_delivery_policies WHERE scope_type='card' AND scope_value=?",
        (card_key,)
    ).fetchone()
    if row:
        return {'allowed': bool(row[0]), 'reason': row[1], 'attribution': row[2], 'matched_scope': 'card', 'scope_value': card_key}

    # 2) Set-level policy
    if set_id:
        row = cur.execute(
            "SELECT external_display_enabled, reason, attribution_text FROM image_delivery_policies WHERE scope_type='set' AND scope_value=?",
            (set_id,)
        ).fetchone()
        if row:
            return {'allowed': bool(row[0]), 'reason': row[1], 'attribution': row[2], 'matched_scope': 'set', 'scope_value': set_id}

    # 3) Language-level policy
    row = cur.execute(
        "SELECT external_display_enabled, reason, attribution_text FROM image_delivery_policies WHERE scope_type='language' AND scope_value=?",
        (language_code,)
    ).fetchone()
    if row:
        return {'allowed': bool(row[0]), 'reason': row[1], 'attribution': row[2], 'matched_scope': 'language', 'scope_value': language_code}

    # 4) Source-level policy
    if source_type:
        row = cur.execute(
            "SELECT external_display_enabled, reason, attribution_text FROM image_delivery_policies WHERE scope_type='source' AND scope_value=?",
            (source_type,)
        ).fetchone()
        if row:
            return {'allowed': bool(row[0]), 'reason': row[1], 'attribution': row[2], 'matched_scope': 'source', 'scope_value': source_type}
        # No explicit policy for this source — check if it's a known/registered source
        known = cur.execute(
            "SELECT 1 FROM v2_card_detail_api_cache WHERE display_image_source_type=? LIMIT 1",
            (source_type,)
        ).fetchone()
        if known:
            # Known source with no explicit policy — falls through to global
            pass
        else:
            # Unregistered/nonexistent source — blocked
            return {'allowed': False, 'reason': f'Unregistered image source: "{source_type}" — no delivery policy',
                    'attribution': None, 'matched_scope': None, 'scope_value': None}
    else:
        # Unknown/null source — blocked.
        return {'allowed': False, 'reason': 'Unknown image source — no delivery policy',
                'attribution': None, 'matched_scope': None, 'scope_value': None}

    # 5) Global default policy
    row = cur.execute(
        "SELECT external_display_enabled, reason, attribution_text FROM image_delivery_policies WHERE scope_type='global' AND scope_value='global'"
    ).fetchone()
    if row:
        return {'allowed': bool(row[0]), 'reason': row[1], 'attribution': row[2], 'matched_scope': 'global', 'scope_value': 'global'}

    # No policy at all — default to disabled
    return {'allowed': False, 'reason': 'No delivery policy configured', 'attribution': None, 'matched_scope': None, 'scope_value': None}


def _safe_image_path(storage_path: str, image_root: Path) -> Path | None:
    """Resolve a storage path securely within the image root.

    Returns None if path escapes or doesn't exist.
    """
    resolved = (image_root / storage_path).resolve()
    try:
        resolved.relative_to(image_root.resolve())
    except ValueError:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _generate_image_hash(filepath: Path) -> str:
    """Generate a deterministic hash from file content."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()[:32]


def _resolve_card_image(conn: sqlite3.Connection, card_key: str) -> dict[str, Any] | None:
    """Resolve a card_key to its canonical local image path.

    Returns dict with image_path, card_key, set_id, language_code, source_type,
    or None if no local image exists.
    """
    lang, cid = parse_card_key(card_key)
    detail, _ = get_card_detail(conn, lang, cid)
    if not detail:
        return None
    images = detail.get('images', {})
    local_url = images.get('local_display_image_url')
    if not local_url:
        return None
    set_info = detail.get('set', {})
    source_type = images.get('display_image_source_type')
    return {
        'image_path': re.sub(r'^/?images/', '', str(local_url)).lstrip('/'),
        'card_key': canonical_card_key(lang, cid),
        'set_id': set_info.get('resolved_set_id') or set_info.get('core_set_id'),
        'language_code': lang,
        'source_type': source_type,
    }


def _generate_signed_url(image_id: int, size: str, secret: str, *, expires_in: int = 3600, api_key_id: int | None = None) -> tuple[str, str]:
    """Generate a signed URL for image delivery.

    Returns (signed_token, expires_at_iso).
    Binds: image_id:size:expires:api_key_id
    """
    expires = int(time.time()) + expires_in
    kid = api_key_id or 0
    message = f'{image_id}:{size}:{expires}:{kid}'
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    token = f'{expires}:{sig}:{image_id}:{size}:{kid}'
    expires_at = dt.datetime.fromtimestamp(expires, tz=dt.UTC).isoformat()
    return token, expires_at


def _verify_signed_url(token: str, secret: str) -> dict[str, Any] | None:
    """Verify a signed URL token. Returns dict with image_id, size, api_key_id, or None."""
    try:
        parts = token.split(':')
        if len(parts) < 5:
            return None
        expires_str, sig, image_id_str, size = parts[0:4]
        kid = parts[4] if len(parts) >= 5 else '0'
        expires = int(expires_str)
        if int(time.time()) > expires:
            return None
        expected_sig = hmac.new(secret.encode(), f'{image_id_str}:{size}:{expires_str}:{kid}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        if size not in ALLOWED_IMAGE_SIZES:
            return None
        return {'image_id': int(image_id_str), 'size': size, 'api_key_id': int(kid) if kid != '0' else None}
    except (ValueError, IndexError):
        return None


def _derive_image(source_path: Path, size: str, image_root: Path) -> Path | None:
    """Generate or retrieve a derivative from the canonical original.

    Uses deterministic cache keys: {hash_of_source}_{size}_{cache_version}
    """
    if size not in ALLOWED_IMAGE_SIZES:
        return None
    source_hash = _generate_image_hash(source_path)
    derivatives_dir = _ensure_derivatives_dir(image_root)
    cache_ver = 1
    deriv_name = f'{source_hash}_{size}_v{cache_ver}.webp'
    deriv_path = derivatives_dir / deriv_name

    if deriv_path.exists():
        return deriv_path

    # Generate derivative
    target_sizes = {
        'thumbnail': (150, 210),
        'small': (245, 342),
        'medium': (350, 489),
        'large': (510, 712),
    }
    tw, th = target_sizes[size]
    try:
        from PIL import Image
        img = Image.open(source_path)
        orig_w, orig_h = img.size
        # Never enlarge beyond original
        tw = min(tw, orig_w)
        th = min(th, orig_h)
        img.thumbnail((tw, th), Image.LANCZOS)
        # Strip metadata
        img_info = img.info
        clean_img = Image.new(img.mode, img.size)
        clean_img.putdata(list(img.getdata()))
        clean_img.save(deriv_path, 'WEBP', quality=82, method=6)
        return deriv_path
    except Exception:
        return None


def _record_delivery_log(*, image_id: int | None = None,
                          card_key: str | None = None, tenant_id: int | None = None,
                          api_key_id: int | None = None, requested_size: str | None = None,
                          policy_decision: str, response_status: int,
                          response_outcome: str, request_id: str | None = None,
                          db_path: str | None = None) -> None:
    """Append a delivery log entry using a dedicated connection.

    Opens its own short-lived connection so that logging is never blocked
    by uncommitted transactions from the caller's connection.
    """
    log_conn = None
    try:
        if db_path is None:
            db_path = str(app.state.db)
        log_conn = sqlite3.connect(str(db_path), timeout=10)
        log_conn.execute("PRAGMA journal_mode=WAL")
        log_conn.execute("PRAGMA busy_timeout=10000")
        log_conn.execute("PRAGMA foreign_keys=ON")
        cur = log_conn.cursor()
        cur.execute(
            'INSERT INTO image_delivery_policy_records'
            '(image_id, card_key, tenant_id, api_key_id, requested_size, '
            'policy_decision, response_status, response_outcome, request_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (image_id, card_key, tenant_id, api_key_id, requested_size,
             policy_decision, response_status, response_outcome, request_id)
        )
        log_conn.commit()
    except Exception as e:
        import logging
        logger = logging.getLogger('pokemon_db_v2_fastapi')
        logger.error('Delivery log write failed: %s (decision=%s, status=%s)',
                     e, policy_decision, response_status, exc_info=True)
    finally:
        if log_conn is not None:
            try:
                log_conn.close()
            except Exception:
                pass


def _takedown_atomic(conn: sqlite3.Connection, *, case_id: int, action_type: str,
                      scope_type: str | None, scope_value: str | None,
                      actor_membership_id: int | None, reason: str | None,
                      policy_enabled: bool | None = None,
                      policy_scope_type: str | None = None,
                      policy_scope_value: str | None = None,
                      previous_policy_json: str | None = None) -> dict[str, Any]:
    """Execute an atomic takedown operation: event + policy update + audit.

    All in one transaction with BEGIN IMMEDIATE.
    When ``previous_policy_json`` is provided, the case row is updated with
    the snapshot so that restore can reconstruct the exact prior state.
    Returns dict with ``success`` and ``event_id``.
    """
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        # Verify case is still open
        case_row = cur.execute(
            "SELECT status FROM takedown_cases WHERE case_id=?",
            (case_id,)
        ).fetchone()
        if not case_row:
            conn.rollback()
            return {'success': False, 'error': f'Takedown case {case_id} not found'}
        if previous_policy_json is not None and case_row['status'] != 'open':
            conn.rollback()
            return {'success': False, 'error': f'Case {case_id} is already {case_row["status"]}'}

        # Append event
        cur.execute(
            'INSERT INTO takedown_events(case_id, action_type, scope_type, scope_value, '
            'actor_membership_id, reason) VALUES (?, ?, ?, ?, ?, ?)',
            (case_id, action_type, scope_type, scope_value, actor_membership_id, reason)
        )
        event_id = cur.lastrowid

        # Store previous policy snapshot if provided
        if previous_policy_json is not None:
            cur.execute(
                "UPDATE takedown_cases SET previous_policy_state=? WHERE case_id=?",
                (previous_policy_json, case_id)
            )

        # Create/update policy if applicable
        if policy_enabled is not None and policy_scope_type and policy_scope_value:
            now_val = now_utc()
            existing = cur.execute(
                "SELECT policy_id FROM image_delivery_policies WHERE scope_type=? AND scope_value=?",
                (policy_scope_type, policy_scope_value)
            ).fetchone()
            if existing:
                cur.execute(
                    "UPDATE image_delivery_policies SET external_display_enabled=?, reason=?, updated_at=? WHERE policy_id=?",
                    (1 if policy_enabled else 0, reason, now_val, existing[0])
                )
            else:
                cur.execute(
                    "INSERT INTO image_delivery_policies(scope_type, scope_value, external_display_enabled, reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (policy_scope_type, policy_scope_value, 1 if policy_enabled else 0, reason, now_val, now_val)
                )

        # Append admin audit
        cur.execute(
            'INSERT INTO admin_audit_log(action, target_resource, details_json, created_at) '
            'VALUES (?, ?, ?, ?)',
            (action_type, f'takedown_event/{event_id}',
             json.dumps({'case_id': case_id, 'scope_type': scope_type, 'scope_value': scope_value,
                         'policy_enabled': policy_enabled}),
             now_utc())
        )
        conn.commit()
        return {'success': True, 'event_id': event_id}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'error': str(e)}


def _get_safe_image_path(card_key: str, image_root: Path, conn: sqlite3.Connection) -> Path | None:
    """Resolve a card's local image safely, preventing path traversal."""
    resolved = resolve_card_local_path(card_key, conn)
    if not resolved:
        return None
    return _safe_image_path(str(resolved), image_root)


CACHE_VERSION = 1
CACHE_CLEANUP_RUNNING = False


def _get_derivative_cache_key(source_path: Path, size: str) -> str:
    source_hash = _generate_image_hash(source_path)
    return f'{source_hash}_{size}_v{CACHE_VERSION}'


def _aggregate_delivery_log(conn: sqlite3.Connection, *, target_date: str | None = None) -> dict[str, Any]:
    """Aggregate delivery log entries into daily summary rows.

    Aggregates by tenant_id, api_key_id, card_key, policy_decision.
    Deletes raw aggregated rows only after successful insert.
    Idempotent: repeated calls with the same date are safe.
    Failed aggregation preserves raw records.
    Returns dict with rows_aggregated, rows_deleted.
    """
    cur = conn.cursor()
    if target_date is None:
        target_date = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).strftime('%Y-%m-%d')

    # Count raw rows for target date
    cur.execute(
        "SELECT COUNT(*) FROM image_delivery_policy_records WHERE date(created_at) = ?",
        (target_date,)
    )
    rows_found = cur.fetchone()[0]
    if rows_found == 0:
        return {'rows_aggregated': 0, 'rows_deleted': 0, 'target_date': target_date}

    try:
        # First, compute the aggregation from raw records
        cur.execute("""
            SELECT
                date(created_at) AS agg_date,
                COALESCE(tenant_id, 0) AS tenant_id,
                COALESCE(api_key_id, 0) AS api_key_id,
                COALESCE(card_key, '') AS card_key,
                policy_decision,
                COUNT(*) AS new_count
            FROM image_delivery_policy_records
            WHERE date(created_at) = ?
            GROUP BY date(created_at), COALESCE(tenant_id, 0), COALESCE(api_key_id, 0),
                     COALESCE(card_key, ''), policy_decision
        """, (target_date,))
        groups = cur.fetchall()
        rows_aggregated = 0
        for g in groups:
            agg_date, tenant_id, api_key_id, card_key, policy_decision, new_count = g
            # Upsert: add to existing count or insert new
            cur.execute("""
                INSERT INTO image_delivery_daily_aggregation
                    (agg_date, tenant_id, api_key_id, card_key, policy_decision, count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(agg_date, tenant_id, api_key_id, card_key, policy_decision)
                DO UPDATE SET count = count + excluded.count
            """, (agg_date, tenant_id, api_key_id, card_key, policy_decision, new_count))
            rows_aggregated += 1
        conn.commit()

        # Delete raw rows only after successful aggregation
        cur.execute(
            "DELETE FROM image_delivery_policy_records WHERE date(created_at) = ?",
            (target_date,)
        )
        rows_deleted = cur.rowcount
        conn.commit()

        return {'rows_aggregated': rows_aggregated, 'rows_deleted': rows_deleted, 'target_date': target_date}
    except Exception:
        conn.rollback()
        return {'rows_aggregated': 0, 'rows_deleted': 0, 'target_date': target_date, 'error': 'aggregation_failed'}


def _delivery_log_cleanup(conn: sqlite3.Connection, *, retention_days: int = 30) -> dict[str, Any]:
    """Aggregate and clean up expired delivery log entries.

    1. Aggregates raw entries older than retention_days into daily summary.
    2. Deletes raw entries only after successful aggregation.
    Returns dict with aggregate and cleanup stats.
    """
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=retention_days)
    target_dates = set()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT date(created_at) FROM image_delivery_policy_records WHERE date(created_at) < ?",
        (cutoff.strftime('%Y-%m-%d'),)
    )
    for row in cur.fetchall():
        target_dates.add(row[0])

    total_agg = 0
    total_del = 0
    for d in sorted(target_dates):
        result = _aggregate_delivery_log(conn, target_date=d)
        total_agg += result['rows_aggregated']
        total_del += result['rows_deleted']

    return {'rows_aggregated': total_agg, 'rows_deleted': total_del, 'retention_days': retention_days}


# ── Rate limiting helpers ───────────────────────────────────────────

class _RateLimitBucket:
    def __init__(self, max_burst: int = 60, window_sec: int = 60):
        self.max_burst = max_burst
        self.window_sec = window_sec
        self._buckets: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        now_val = time.time()
        bucket = self._buckets.get(key, [])
        bucket = [t for t in bucket if now_val - t < self.window_sec]
        if len(bucket) >= self.max_burst:
            self._buckets[key] = bucket
            return False
        bucket.append(now_val)
        self._buckets[key] = bucket
        return True

    def remaining(self, key: str) -> int:
        now_val = time.time()
        bucket = self._buckets.get(key, [])
        bucket = [t for t in bucket if now_val - t < self.window_sec]
        return max(0, self.max_burst - len(bucket))


_IMAGE_RATE_LIMITER = _RateLimitBucket(max_burst=120, window_sec=60)
_KEY_RATE_LIMITER = _RateLimitBucket(max_burst=200, window_sec=60)


# ── Persistent quota tracking (per-hour/per-day) ────────────────────

_QUOTA_HOURLY_LIMIT = 1000   # max successful deliveries per hour per identity
_QUOTA_DAILY_LIMIT = 5000    # max successful deliveries per day per identity


from dataclasses import dataclass


@dataclass(frozen=True)
class _QuotaWindow:
    """A single quota window row."""
    window_kind: str          # 'hour' or 'day'
    window_start: str         # ISO datetime, inclusive
    window_end: str           # ISO datetime, exclusive


def quota_windows(now_val: dt.datetime | None = None, *, hourly_limit: int = 1000, daily_limit: int = 5000) -> tuple[_QuotaWindow, _QuotaWindow]:
    """Compute the current hourly and daily quota windows.

    Accepts an injected ``now_val`` for deterministic testing.
    Both windows are derived from the same timestamp so that a request
    crossing a boundary still gets consistent hour/day windows.
    """
    if now_val is None:
        now_val = dt.datetime.now(dt.UTC)
    hour_start = now_val.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + dt.timedelta(hours=1)
    day_start = now_val.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + dt.timedelta(days=1)
    return (
        _QuotaWindow('hour', hour_start.isoformat(), hour_end.isoformat()),
        _QuotaWindow('day', day_start.isoformat(), day_end.isoformat()),
    )


def quota_identity_for_access(access_identity: str, identity_type: str) -> str:
    """Return a deterministic quota identity string.

    API-key requests and signed-token requests issued by the same key
    share one quota pool when the identity encodes the same issuer.
    Currently the identity is the access_identity token itself; this
    can be refined when multi-key issuer tracking is added.
    """
    return access_identity


def _check_and_increment_quota(conn: sqlite3.Connection, access_identity: str,
                               identity_type: str, *,
                               hourly_limit: int, daily_limit: int,
                               now_val: dt.datetime | None = None) -> dict[str, Any]:
    """Atomically check and increment persistent image delivery quota.

    Returns dict with ``allowed``, ``hourly_count``, ``daily_count``,
    ``hourly_limit``, ``daily_limit``.

    If over quota returns ``{'allowed': False, 'reason': ...}``.
    The call is performed inside a single ``BEGIN IMMEDIATE``
    transaction -- two concurrent requests share the same lock and
    cannot both pass when only one slot remains.
    """
    hour_win, day_win = quota_windows(now_val)
    cur = conn.cursor()

    # BEGIN IMMEDIATE -- acquire the write lock immediately
    cur.execute("BEGIN IMMEDIATE")
    try:
        # -- Hourly window -------------------------------------------------
        row = cur.execute(
            "SELECT successful_delivery_count FROM image_delivery_quota_windows "
            "WHERE access_identity=? AND identity_type=? AND window_kind='hour' AND window_start=?",
            (access_identity, identity_type, hour_win.window_start)
        ).fetchone()
        if row:
            hourly_count = row[0]
        else:
            hourly_count = 0
            cur.execute(
                "INSERT INTO image_delivery_quota_windows"
                "(access_identity, identity_type, window_kind, window_start, window_end,"
                " successful_delivery_count, created_at, updated_at) "
                "VALUES (?, ?, 'hour', ?, ?, 0, ?, ?)",
                (access_identity, identity_type, hour_win.window_start, hour_win.window_end,
                 now_utc(), now_utc())
            )

        # -- Daily window --------------------------------------------------
        row = cur.execute(
            "SELECT successful_delivery_count FROM image_delivery_quota_windows "
            "WHERE access_identity=? AND identity_type=? AND window_kind='day' AND window_start=?",
            (access_identity, identity_type, day_win.window_start)
        ).fetchone()
        if row:
            daily_count = row[0]
        else:
            daily_count = 0
            cur.execute(
                "INSERT INTO image_delivery_quota_windows"
                "(access_identity, identity_type, window_kind, window_start, window_end,"
                " successful_delivery_count, created_at, updated_at) "
                "VALUES (?, ?, 'day', ?, ?, 0, ?, ?)",
                (access_identity, identity_type, day_win.window_start, day_win.window_end,
                 now_utc(), now_utc())
            )

        # -- Threshold check (inside the lock) -----------------------------
        if hourly_count >= hourly_limit:
            conn.commit()
            return {'allowed': False, 'reason': 'hourly_quota_exceeded',
                    'hourly_count': hourly_count, 'daily_count': daily_count,
                    'hourly_limit': hourly_limit, 'daily_limit': daily_limit}
        if daily_count >= daily_limit:
            conn.commit()
            return {'allowed': False, 'reason': 'daily_quota_exceeded',
                    'hourly_count': hourly_count, 'daily_count': daily_count,
                    'hourly_limit': hourly_limit, 'daily_limit': daily_limit}

        # -- Increment both in one transaction -----------------------------
        cur.execute(
            "UPDATE image_delivery_quota_windows "
            "SET successful_delivery_count = successful_delivery_count + 1, updated_at=? "
            "WHERE access_identity=? AND identity_type=? AND window_kind='hour' AND window_start=?",
            (now_utc(), access_identity, identity_type, hour_win.window_start)
        )
        cur.execute(
            "UPDATE image_delivery_quota_windows "
            "SET successful_delivery_count = successful_delivery_count + 1, updated_at=? "
            "WHERE access_identity=? AND identity_type=? AND window_kind='day' AND window_start=?",
            (now_utc(), access_identity, identity_type, day_win.window_start)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {'allowed': True, 'hourly_count': hourly_count + 1, 'daily_count': daily_count + 1,
            'hourly_limit': hourly_limit, 'daily_limit': daily_limit}


def _quota_cleanup(conn: sqlite3.Connection, *, retention_days: int = 7) -> int:
    """Remove quota window rows older than retention_days."""
    cur = conn.cursor()
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=retention_days)).isoformat()
    cur.execute("DELETE FROM image_delivery_quotas WHERE window_start < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def resolve_card_local_path(card_key: str, conn: sqlite3.Connection) -> Path | None:
    """Resolve a card key to its local filesystem image path.

    Returns a Path relative to the image root, or None if not found.
    """
    image_info = resolve_preferred_card_image(conn, card_key)
    if not image_info or not image_info.get('image_path'):
        return None
    return Path(image_info['image_path'])


async def get_settings(request: Request) -> PokemonDBSettings:
    """FastAPI dependency to inject PokemonDBSettings into endpoints.

    Usage:
        async def my_route(settings: PokemonDBSettings = Depends(get_settings)):
            ...

    This allows tests to override via:
        app.dependency_overrides[get_settings] = lambda: test_settings
    """
    return request.app.state.settings


def create_app(settings: PokemonDBSettings | None = None) -> FastAPI:
    if settings is None:
        settings = settings_from_env()
    settings = validate_settings(settings, require_ui=False)
    app = FastAPI(
        title='SaveRoom Pokémon Card Database v2 API',
        version='0.2.0',
        description='Local API over v2_card_search, v2_card_detail, FTS5, and product-ready image fields.',
    )
    app.state.settings = settings
    app.state.db = settings.db
    if not settings.skip_search_setup:
        app.state.support_status = ensure_search_support(settings.db, reports_dir=settings.reports_dir)
    else:
        app.state.support_status = {'refreshed': False, 'database': str(settings.db), 'fts_table': 'v2_card_search_fts', 'api_cache_table': 'v2_card_detail_api_cache', 'fts_rows': 0, 'api_cache_rows': 0, 'v2_card_search_rows': 0, 'row_count_matches': True}

    # Price schema is prepared at startup so normal read paths do not need to
    # perform first-use ALTER TABLE work under concurrent request load.
    with closing(connect(str(settings.db))) as price_conn:
        ensure_price_support(price_conn)

    # Invalidate stale price cache entries with non-Latin query terms
    # (e.g., Japanese text in queries that return 0 eBay results)
    try:
        with closing(connect(str(settings.db))) as check_conn:
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
        print(f'[v9.1] Raw static /images mount removed. All image delivery now goes through GET /api/v1/images/assets/{{image_id}}/content (authenticated, policy-gated).')

    # v11 market evidence endpoints
    with closing(connect(app.state.db)) as v11_conn:
        from pricing_sources.migrations import apply_v11_migrations
        apply_v11_migrations(v11_conn)
    from pricing_sources.router import v11_pricing_router
    app.include_router(v11_pricing_router)

    # v1 API foundation: optional API key auth + request logging.
    with closing(connect(app.state.db)) as conn:
        ensure_v1_api_support(conn)

    async def require_v1_api_key(request: Request) -> dict[str, Any]:
        require_key = settings.require_api_key or os.environ.get('POKEMON_DB_REQUIRE_API_KEY', '').strip().lower() in {'1', 'true', 'yes', 'on'}
        if not require_key:
            request.state.api_key_id = None
            request.state.api_scopes = ['cards:read', 'images:read']
            auth_result = {'api_key_id': None, 'scopes': ['cards:read', 'images:read'], 'auth_required': False, 'membership_id': None}
            request.state.auth_dict = auth_result
            return auth_result
        raw_key = request.headers.get('x-api-key') or ''
        auth = request.headers.get('authorization') or ''
        if not raw_key and auth.lower().startswith('bearer '):
            raw_key = auth.split(' ', 1)[1].strip()
        if not raw_key:
            raise v1_error(401, 'api_key_required', 'API key required for /api/v1 routes.', {'header': 'X-API-Key'})
        key_hash = sha256_text(raw_key)
        with closing(connect(app.state.db)) as conn:
            ensure_v1_api_support(conn)
            ensure_inventory_support(conn)
            cur = conn.cursor()
            row = cur.execute('SELECT id, scopes, is_active, membership_id FROM developer_api_keys WHERE key_hash=? LIMIT 1', (key_hash,)).fetchone()
            if not row or not row['is_active']:
                raise v1_error(401, 'invalid_api_key', 'Invalid or inactive API key.', None)
            scopes = json.loads(row['scopes'] or '[]') if row['scopes'] else []
            membership_id = row['membership_id']
            # Also fetch scopes from api_key_scopes table
            scope_rows = cur.execute('SELECT scope FROM api_key_scopes WHERE key_id=?', (row['id'],)).fetchall()
            normalized_scopes = set(scopes) | {sr[0] for sr in scope_rows}
            # A key with membership_id=NULL must have admin:all to access anything
            if not membership_id and 'admin:all' not in normalized_scopes and 'admin' not in normalized_scopes:
                raise v1_error(403, 'insufficient_scope',
                               'API key without tenant membership requires admin:all scope.',
                               {'required_scope': 'admin:all'})
            cur.execute('UPDATE developer_api_keys SET last_used_at=CURRENT_TIMESTAMP WHERE id=?', (row['id'],))
            conn.commit()
            request.state.api_key_id = row['id']
            request.state.api_scopes = list(normalized_scopes)
            auth_result = {'api_key_id': row['id'], 'scopes': list(normalized_scopes),
                           'auth_required': True, 'membership_id': membership_id}
            request.state.auth_dict = auth_result
            return auth_result

    @app.middleware('http')
    async def v1_request_logger(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path.startswith('/api/v1'):
            try:
                with closing(connect(app.state.db)) as conn:
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
        return {'data': {'ok': counts['support_ready'], 'service': 'saveroom-pokemon-api', 'version': 'v1', 'started_at': STARTED_AT, 'checked_at': now_utc(), 'counts': counts, 'support_status': _public_support_status(app.state.support_status), 'auth': {'api_key_required': settings.require_api_key or os.environ.get('POKEMON_DB_REQUIRE_API_KEY', '').strip().lower() in {'1', 'true', 'yes', 'on'}}}}

    @app.get('/api/v1/readiness', summary='Readiness check for normal API traffic')
    def v1_readiness(_: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
        counts = db_counts(app.state.db)
        image_root = _image_root_dir(settings.image_root, fallback_root=settings.db.parent)
        checks = {
            'database_reachable': True,
            'support_ready': bool(counts['support_ready']),
            'required_schema_present': bool(counts['v2_card_search_fts'] and counts['v2_card_detail_api_cache']),
            'image_root_available': bool(image_root and image_root.exists()),
            'configuration_valid': True,
        }
        ready = all(checks.values())
        return {'data': {'ready': ready, 'service': 'saveroom-pokemon-api', 'checked_at': now_utc(), 'checks': checks}}

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
        data = [v1_card_from_detail(r, conn, settings=app.state.settings) for r in detail_rows]
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

    # ── /api/v1/cards detail (v12 app-ready) ───────────────────────────
    # Declared BEFORE the catch-all {card_key:path} route so /detail is not
    # swallowed by the path converter.

    @app.get('/api/v1/cards/{card_key:path}/detail', response_model=AppReadyCardDetailResponseV1)
    def v12_app_ready_card_detail(
        card_key: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """v12 app-ready card detail endpoint.

        Returns a consumer-ready payload combining canonical identity, set info,
        image manifest, commercial variants/SKUs, UK-first pricing summary shell,
        provider status, and warnings.

        Pricing summary shape follows the corrected UK-first external pricing
        strategy. Live UK eBay sold/completed pricing is not yet implemented —
        primary_price will be null until a real UK external source is connected.
        No external API calls are made by this endpoint.
        """
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        cur = conn.cursor()

        # ── card existence check ────────────────────────────────────────
        cur.execute('SELECT 1 FROM v2_card_detail_api_cache WHERE language_code=? AND card_id=? LIMIT 1', (language_code, card_id))
        if not cur.fetchone():
            conn.close()
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})

        detail, _elapsed_ms = get_card_detail(conn, language_code, card_id)
        if detail is None:
            conn.close()
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})

        card_info = detail.get('card') or {}
        set_info = detail.get('set') or {}
        images = detail.get('images') or {}
        card_k = canonical_card_key(language_code, card_id)
        en_name = get_en_name(conn, language_code, card_id, detail.get('name'))

        # ── canonical printing / identity ───────────────────────────────
        cur.execute('''
            SELECT cp.* FROM v10_canonical_printings cp
            JOIN v10_canonical_printing_cards l ON cp.canonical_printing_id = l.canonical_printing_id
            WHERE l.card_key = ?
            LIMIT 1
        ''', (card_k,))
        cp_row = cur.fetchone()
        cp_dict: dict[str, Any] | None = None
        variants: list[dict[str, Any]] = []
        skus: list[dict[str, Any]] = []
        ext_refs: list[dict[str, Any]] = []
        if cp_row:
            cp_dict = dict(cp_row)
            cp_id = cp_dict.get('canonical_printing_id')
            cur.execute('SELECT * FROM v10_commercial_variants WHERE canonical_printing_id = ?', (cp_id,))
            variants = [dict(r) for r in cur.fetchall()]
            if variants:
                cv_ids = [v['commercial_variant_id'] for v in variants]
                placeholders = ','.join('?' * len(cv_ids))
                cur.execute(f'SELECT * FROM v10_sellable_skus WHERE commercial_variant_id IN ({placeholders})', cv_ids)
                skus = [dict(r) for r in cur.fetchall()]
            cur.execute('''
                SELECT * FROM v10_external_references
                WHERE entity_type = 'canonical_printing' AND entity_id = ?
            ''', (cp_id,))
            ext_refs = [dict(r) for r in cur.fetchall()]

        # ── image manifest ──────────────────────────────────────────────
        signed_url = _generate_card_signed_url(conn, card_k, app.state.settings) if app.state.settings else None
        image_out = {
            'primary_image_url': images.get('exact_image_url') or images.get('display_image_url'),
            'thumbnail_url': None,
            'signed_image_url': signed_url,
            'has_local_image': bool(images.get('has_exact_image') or images.get('has_display_image')),
            'image_policy_status': 'signed_gateway' if signed_url else 'no_image',
            'missing_image': not bool(images.get('has_exact_image') or images.get('has_display_image')),
            'fallbacks': [],
        }

        # ── pricing summary (UK-first shell, no live source) ───────────
        price_evidence = v1_price_summary(conn, language_code, card_id)
        has_price_evidence = price_evidence.get('evidence_count', 0) > 0
        warnings_list: list[str] = []
        warnings_list.append('UK eBay sold/completed source is not yet live. No headline UK market estimate available.')

        primary_price = None
        fallback_price = None
        source_breakdown: list[dict[str, Any]] = []
        confidence: str | None = 'NONE'
        existing_source: str | None = None

        if has_price_evidence:
            existing_source = price_evidence.get('source', 'tcgdex')
            fallback_price = {
                'amount': price_evidence.get('raw_median'),
                'currency': price_evidence.get('currency', 'GBP'),
                'region': 'UK' if existing_source == 'ebay_uk_sold' else None,
                'price_type': 'market_existing_local',
                'source': existing_source,
                'evidence_count': price_evidence.get('evidence_count', 0),
                'confidence': 'LOW',
            }
            source_breakdown.append({
                'tier': 3 if existing_source == 'tcgdex' else 2,
                'source': existing_source,
                'currency': price_evidence.get('currency', 'GBP'),
                'price_type': 'market',
                'evidence_count': price_evidence.get('evidence_count', 0),
                'median_gbp': price_evidence.get('raw_median'),
                'low_gbp': price_evidence.get('raw_min'),
                'high_gbp': price_evidence.get('raw_max'),
                'sample_date': price_evidence.get('latest_fetched_at'),
            })
            confidence = 'LOW'
            warnings_list.append(
                'Fallback evidence is existing local data, not UK sold-market evidence.'
            )

        evidence_summary = {
            'total_evidence': price_evidence.get('evidence_count', 0),
            'uk_evidence': price_evidence.get('evidence_count', 0) if existing_source == 'ebay_uk_sold' else 0,
            'uk_tier_1_source': 'ebay_uk' if existing_source == 'ebay_uk_sold' else None,
            'has_uk_sold_evidence': existing_source == 'ebay_uk_sold',
            'has_converted_evidence': False,
            'oldest_evidence_date': None,
            'newest_evidence_date': price_evidence.get('latest_fetched_at'),
        }

        pricing_out = {
            'primary_price': primary_price,
            'fallback_price': fallback_price,
            'source_breakdown': source_breakdown,
            'evidence_summary': evidence_summary,
            'confidence': confidence,
            'warnings': warnings_list,
            'last_refresh': now_utc(),
        }

        # ── provider status ─────────────────────────────────────────────
        provider_status = {
            'uk_ebay_sold': {
                'role': 'primary_uk_market_evidence',
                'status': 'planned',
                'live_enabled': False,
                'terms_confirmed': False,
                'notes': 'UK eBay sold/completed external evidence in GBP. Not yet implemented.',
            },
            'tcgdex': {
                'role': 'existing_local_source',
                'status': 'available',
                'live_enabled': True,
                'terms_confirmed': False,
                'notes': 'Free keyless source. Current local evidence base. Not UK sold evidence.',
            },
            "justtcg": _get_justtcg_provider_status(),
            'cardmarket': {
                'role': 'supporting_eu_fallback',
                'status': 'blocked_access_closed',
                'live_enabled': False,
                'terms_confirmed': False,
                'notes': 'Cardmarket direct API not currently accepting applications.',
            },
            'tcgplayer': {
                'role': 'supporting_usd_fallback',
                'status': 'blocked_pending_access',
                'live_enabled': False,
                'terms_confirmed': False,
                'notes': 'TCGplayer API access is partner/gated. Blocked pending approved access.',
            },
        }

        # ── assemble response ───────────────────────────────────────────
        card_section = {
            'card_key': card_k,
            'card_id': card_id,
            'canonical_printing_id': cp_dict.get('canonical_printing_id') if cp_dict else None,
            'name': detail.get('name'),
            'name_english': en_name,
            'language_code': language_code,
            'number': detail.get('collector_number'),
            'rarity': card_info.get('rarity') or cp_dict.get('rarity') if cp_dict else card_info.get('rarity'),
            'supertype': card_info.get('category'),
            'subtypes': None,
        }
        set_section = {
            'set_id': set_info.get('resolved_set_id') or set_info.get('raw_set_id'),
            'set_code': set_info.get('core_set_id'),
            'name': set_info.get('resolved_set_name'),
            'localized_name': set_info.get('core_set_name'),
            'release_date': set_info.get('release_date'),
            'language_code': language_code,
        }
        commercial_section = {
            'canonical_printing': cp_dict,
            'commercial_variants': variants,
            'sellable_skus': skus,
            'external_references': ext_refs,
        }

        metadata = {
            'api_version': 'v1',
            'contract': 'v12-app-ready-card-detail',
            'generated_at': now_utc(),
            'request': {'card_key': card_key},
        }

        conn.close()
        return {
            'data': {
                'card': card_section,
                'set': set_section,
                'images': image_out,
                'commercial': commercial_section,
                'pricing': pricing_out,
                'provider_status': provider_status,
            },
            'warnings': warnings_list,
            'metadata': metadata,
        }

    # ── /api/v1/cards/detail/batch (v12 app-ready batch) ──────────────
    # Declared BEFORE the catch-all {card_key:path} route so /detail/batch
    # is not swallowed by the path converter.

    @app.post('/api/v1/cards/detail/batch', response_model=AppReadyBatchResponseV1)
    def v12_app_ready_card_detail_batch(
        request: AppReadyBatchRequestV1,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """v12 app-ready card detail batch endpoint.

        Accepts up to 50 card keys and returns per-item detail payloads
        with the same shape as the single-card /detail endpoint.
        Item-level errors are reported inline so partial success is
        representable. No external API calls are made.
        """
        items: list[dict[str, Any]] = []
        for card_key in request.card_keys:
            try:
                single = v12_app_ready_card_detail(card_key, _)
                detail = single['data']

                if not request.include_pricing:
                    detail['pricing'] = None
                if not request.include_commercial:
                    detail['commercial'] = None
                if not request.include_images:
                    detail['images'] = None

                items.append({
                    'card_key': card_key,
                    'status': 'ok',
                    'detail': detail,
                    'error': None,
                })
            except HTTPException as exc:
                items.append({
                    'card_key': card_key,
                    'status': 'error',
                    'detail': None,
                    'error': {
                        'code': exc.detail.get('code', 'request_error') if isinstance(exc.detail, dict) else 'request_error',
                        'message': exc.detail.get('message', str(exc.detail)) if isinstance(exc.detail, dict) else str(exc.detail),
                    },
                })

        ok_count = sum(1 for i in items if i['status'] == 'ok')
        err_count = sum(1 for i in items if i['status'] == 'error')
        return {
            'data': {
                'items': items,
                'summary': {
                    'requested': len(request.card_keys),
                    'returned': ok_count,
                    'errors': err_count,
                },
            },
            'warnings': [
                'UK eBay sold/completed source is not yet live. Batch results may only include fallback/local evidence.',
            ],
            'metadata': {
                'api_version': 'v1',
                'contract': 'v12-app-ready-card-detail-batch',
                'generated_at': now_utc(),
                'max_batch_size': 50,
                'request': {
                    'count': len(request.card_keys),
                    'include_pricing': request.include_pricing,
                    'include_commercial': request.include_commercial,
                    'include_images': request.include_images,
                },
            },
        }

    @app.get('/api/v1/cards/{card_key:path}', response_model=CardDetailResponseV1)
    def v1_card_detail(card_key: str, _: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        detail, _elapsed_ms = get_card_detail(conn, language_code, card_id)
        if detail is None:
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})
        return {'data': v1_card_from_detail(detail, conn, include_detail=True, settings=app.state.settings)}

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
        card_k = canonical_card_key(language_code, card_id)
        # Gateway URL — controlled card-key compatibility route
        gateway_url = f'/api/v1/images/card/{card_k}/content?size=medium'
        signed_url = _generate_card_signed_url(conn, card_k, app.state.settings) if app.state.settings else None
        return {
            'data': {
                'has_exact_image': bool(images.get('has_exact_image')),
                'has_display_image': bool(images.get('has_display_image')),
                'exact_image_url': images.get('exact_image_url'),
                'display_image_url': images.get('display_image_url'),
                'local_display_image_url': gateway_url,  # gateway, not raw path
                'signed_image_url': signed_url,
                'local_display_image_cache_profile': images.get('local_display_image_cache_profile'),
                'local_display_image_bytes': images.get('local_display_image_bytes'),
                'display_image_source_type': images.get('display_image_source_type'),
                'display_image_source_language_code': display_lang,
                'language_matches_card': (display_lang in (None, '', language_code)),
            },
            'card_key': card_k,
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

        summary = v1_price_summary(conn, language_code, card_id)

        # Attempt JustTCG fetch (disabled by default, gated)
        justtcg_data = None
        try:
            justtcg_data = _get_justtcg_price_data(canonical_card_key(language_code, card_id))
        except Exception:
            pass  # Never let JustTCG failures break the endpoint
        justtcg_status = _get_justtcg_provider_status()
        summary['recommendation'] = build_v1_price_recommendation(summary, {'justtcg': justtcg_status})

        # If JustTCG returned data, add to source_breakdown as supporting source
        if justtcg_data is not None:
            summary.setdefault("justtcg_fallback", justtcg_data)
            summary["justtcg_provider_status"] = justtcg_status

        response = {
            'data': summary,
            'card_key': canonical_card_key(language_code, card_id),
            'language_code': language_code,
            'card_id': card_id,
            'justtcg_provider_status': justtcg_status,
        }

        # Apply exposure policy — conservative default: treat all v1 API
        # traffic as external developer surface. Internal/customer app
        # exposure can be enabled later via trusted surface detection.
        try:
            from pricing_sources.exposure_policy import (
                apply_pricing_exposure_policy,
                SURFACE_EXTERNAL_DEVELOPER_API,
            )
            response = apply_pricing_exposure_policy(response, SURFACE_EXTERNAL_DEVELOPER_API)
        except Exception:
            pass  # Never let exposure policy break the endpoint

        return response

    # ── /api/v1/listings/assist (v12 listing assistant) ───────────────

    @app.post('/api/v1/listings/assist/cards/{card_key:path}', response_model=ListingAssistantResponseV1)
    def v12_listing_assistant(
        card_key: str,
        body: ListingAssistantRequestV1,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """Build deterministic listing-ready data from local v1 card/pricing state.

        This endpoint does not call marketplace APIs, provider APIs, HTTP
        endpoints, or LLMs. Pricing is derived from the local v12
        ``data.recommendation`` shape only.
        """
        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        cur = conn.cursor()
        card_k = canonical_card_key(language_code, card_id)

        try:
            cur.execute('SELECT 1 FROM v2_card_detail_api_cache WHERE language_code=? AND card_id=? LIMIT 1', (language_code, card_id))
            if not cur.fetchone():
                raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': card_k})

            detail, _elapsed_ms = get_card_detail(conn, language_code, card_id)
            if detail is None:
                raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': card_k})

            card_info = detail.get('card') or {}
            set_info = detail.get('set') or {}
            images = detail.get('images') or {}
            en_name = get_en_name(conn, language_code, card_id, detail.get('name'))

            cur.execute('''
                SELECT cp.* FROM v10_canonical_printings cp
                JOIN v10_canonical_printing_cards l ON cp.canonical_printing_id = l.canonical_printing_id
                WHERE l.card_key = ?
                LIMIT 1
            ''', (card_k,))
            cp_row = cur.fetchone()
            cp_dict = dict(cp_row) if cp_row else None
            variants: list[dict[str, Any]] = []
            skus: list[dict[str, Any]] = []
            if cp_dict:
                cur.execute('SELECT * FROM v10_commercial_variants WHERE canonical_printing_id = ?', (cp_dict.get('canonical_printing_id'),))
                variants = [dict(r) for r in cur.fetchall()]
                if variants:
                    cv_ids = [v['commercial_variant_id'] for v in variants]
                    placeholders = ','.join('?' * len(cv_ids))
                    cur.execute(f'SELECT * FROM v10_sellable_skus WHERE commercial_variant_id IN ({placeholders})', cv_ids)
                    skus = [dict(r) for r in cur.fetchall()]

            card_name = en_name or detail.get('name') or card_id
            set_name = set_info.get('resolved_set_name') or set_info.get('core_set_name') or set_info.get('raw_set_id')
            rarity = card_info.get('rarity') or (cp_dict or {}).get('rarity')
            number = detail.get('collector_number') or detail.get('local_id')
            card_section = {
                'card_key': card_k,
                'name': card_name,
                'language_code': language_code,
                'set_id': set_info.get('resolved_set_id') or set_info.get('raw_set_id') or set_info.get('core_set_id'),
                'set_name': set_name,
                'number': number,
                'rarity': rarity,
            }

            recommendation: dict[str, Any] | None = None
            pricing_section: dict[str, Any] | None = None
            if body.include_pricing:
                price_summary = v1_price_summary(conn, language_code, card_id)
                recommendation = build_v1_price_recommendation(price_summary, {})
                pricing_section = _listing_pricing_from_recommendation(
                    recommendation,
                    pricing_strategy=body.pricing_strategy,
                )

            title = _build_listing_title(
                platform=body.platform,
                title_style=body.title_style,
                name=card_name,
                number=number,
                set_name=set_name,
                rarity=rarity,
            )
            condition = _clean_listing_text(body.condition)
            finish = _clean_listing_text(body.finish)
            subtitle = _join_listing_parts([set_name, number, rarity, condition]) or None
            listing_section = {
                'title': title[:PLATFORM_GUIDANCE_V1[body.platform]['title_limit']],
                'subtitle': subtitle,
                'description_bullets': _description_bullets(
                    card=card_section,
                    set_section={'name': set_name},
                    quantity=body.quantity,
                    condition=condition,
                    finish=finish,
                    pricing=pricing_section,
                ),
                'condition_note': condition,
                'tags': _listing_tags(
                    name=card_name,
                    set_name=set_name,
                    rarity=rarity,
                    language_code=language_code,
                    platform=body.platform,
                    finish=finish,
                ),
            }

            images_section = None
            if body.include_images:
                signed_url = _generate_card_signed_url(conn, card_k, app.state.settings) if app.state.settings else None
                gateway_url = f'/api/v1/images/card/{card_k}/content?size=medium'
                primary_image = signed_url or gateway_url if bool(images.get('has_exact_image') or images.get('has_display_image')) else None
                image_candidates = [url for url in [signed_url, gateway_url if primary_image else None] if url]
                images_section = {
                    'primary_image': primary_image,
                    'image_candidates': list(dict.fromkeys(image_candidates)),
                }

            commercial_section = None
            if body.include_commercial:
                commercial_section = {
                    'canonical_printing_id': (cp_dict or {}).get('canonical_printing_id'),
                    'commercial_variant_id': variants[0].get('commercial_variant_id') if variants else None,
                    'sellable_sku_id': skus[0].get('sellable_sku_id') if skus else None,
                }

            warnings_out = list((pricing_section or {}).get('warnings') or [])
            if not body.include_pricing:
                warnings_out.append('Pricing omitted because include_pricing=false.')
            if body.notes:
                warnings_out.append('Request notes are retained only as metadata; listing copy remains deterministic.')

            metadata = {
                'api_version': 'v1',
                'contract': 'v12-listing-assistant',
                'generated_at': now_utc(),
                'request': {
                    'card_key': card_k,
                    'platform': body.platform,
                    'pricing_strategy': body.pricing_strategy,
                    'title_style': body.title_style,
                    'quantity': body.quantity,
                    'include_images': body.include_images,
                    'include_pricing': body.include_pricing,
                    'include_commercial': body.include_commercial,
                },
            }

            return {
                'data': {
                    'card': card_section,
                    'listing': listing_section,
                    'pricing': pricing_section,
                    'images': images_section,
                    'commercial': commercial_section,
                    'platform_guidance': _listing_platform_guidance(body.platform),
                    'provider_status': _safe_listing_provider_status(),
                    'warnings': warnings_out,
                    'metadata': metadata,
                },
                'warnings': warnings_out,
                'metadata': metadata,
            }
        finally:
            conn.close()


    # ── /api/v1/listings/drafts (v12 local draft persistence) ──────────

    @app.post('/api/v1/listings/drafts/cards/{card_key:path}', response_model=ListingDraftResponseV1, status_code=201)
    def v12_create_listing_draft(
        card_key: str,
        body: ListingDraftCreateRequestV1,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        '''Generate listing assistant output and persist it as a local draft.'''
        assistant_response = v12_listing_assistant(card_key, body, _)
        assistant_data = assistant_response['data']
        conn = connect(app.state.db)
        try:
            draft = _persist_listing_draft(conn, assistant_data=assistant_data, request_body=body)
            conn.commit()
            return {'data': draft, 'metadata': _listing_draft_metadata()}
        finally:
            conn.close()

    @app.get('/api/v1/listings/drafts', response_model=ListingDraftListResponseV1)
    def v12_list_listing_drafts(
        include_archived: bool = Query(True, description='Include archived local drafts.'),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        try:
            _ensure_listing_drafts_table(conn)
            where = '' if include_archived else "WHERE status != 'archived'"
            total = int(conn.execute(f'SELECT COUNT(*) FROM listing_drafts {where}').fetchone()[0])
            rows = conn.execute(
                f'SELECT * FROM listing_drafts {where} ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?',
                (limit, offset),
            ).fetchall()
            data = [_listing_draft_row_to_response(row) for row in rows]
            return {
                'data': data,
                'pagination': {
                    'limit': limit,
                    'offset': offset,
                    'count': len(data),
                    'total': total,
                    'has_more': offset + len(data) < total,
                },
                'metadata': _listing_draft_metadata(),
            }
        finally:
            conn.close()

    @app.get('/api/v1/listings/drafts/{draft_id}', response_model=ListingDraftResponseV1)
    def v12_get_listing_draft(
        draft_id: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        try:
            _ensure_listing_drafts_table(conn)
            row = conn.execute('SELECT * FROM listing_drafts WHERE draft_id = ?', (draft_id,)).fetchone()
            if row is None:
                raise v1_error(404, 'listing_draft_not_found', 'Listing draft not found.', {'draft_id': draft_id})
            return {'data': _listing_draft_row_to_response(row), 'metadata': _listing_draft_metadata()}
        finally:
            conn.close()

    @app.patch('/api/v1/listings/drafts/{draft_id}', response_model=ListingDraftResponseV1)
    def v12_update_listing_draft(
        draft_id: str,
        body: ListingDraftUpdateRequestV1,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        try:
            _ensure_listing_drafts_table(conn)
            row = conn.execute('SELECT * FROM listing_drafts WHERE draft_id = ?', (draft_id,)).fetchone()
            if row is None:
                raise v1_error(404, 'listing_draft_not_found', 'Listing draft not found.', {'draft_id': draft_id})
            current = dict(row)
            assistant_payload = _json_loads_safe(current.get('assistant_payload_json'), {})
            listing_payload = assistant_payload.setdefault('listing', {}) if isinstance(assistant_payload, dict) else {}

            updates: dict[str, Any] = {}
            if body.title is not None:
                updates['title'] = _clean_listing_text(body.title)
                listing_payload['title'] = updates['title']
            if body.subtitle is not None:
                updates['subtitle'] = _clean_listing_text(body.subtitle)
                listing_payload['subtitle'] = updates['subtitle']
            if body.description_bullets is not None:
                updates['description_json'] = _json_dumps_safe(body.description_bullets)
                listing_payload['description_bullets'] = body.description_bullets
            if body.tags is not None:
                updates['tags_json'] = _json_dumps_safe(body.tags)
                listing_payload['tags'] = body.tags
            if body.condition is not None:
                updates['condition'] = _clean_listing_text(body.condition)
                listing_payload['condition_note'] = updates['condition']
            if body.finish is not None:
                updates['finish'] = _clean_listing_text(body.finish)
            if body.quantity is not None:
                updates['quantity'] = body.quantity
                if isinstance(assistant_payload, dict):
                    assistant_payload.setdefault('metadata', {}).setdefault('draft_updates', {})['quantity'] = body.quantity
            if body.notes is not None:
                updates['notes'] = _clean_listing_text(body.notes)
            if body.status is not None:
                updates['status'] = body.status
                updates['archived_at'] = now_utc() if body.status == 'archived' else None

            updates['assistant_payload_json'] = _json_dumps_safe(assistant_payload)
            updates['updated_at'] = now_utc()
            assignments = ', '.join(f'{key} = ?' for key in updates)
            conn.execute(
                f'UPDATE listing_drafts SET {assignments} WHERE draft_id = ?',
                [*updates.values(), draft_id],
            )
            conn.commit()
            updated = conn.execute('SELECT * FROM listing_drafts WHERE draft_id = ?', (draft_id,)).fetchone()
            return {'data': _listing_draft_row_to_response(updated), 'metadata': _listing_draft_metadata()}
        finally:
            conn.close()

    @app.post('/api/v1/listings/drafts/{draft_id}/archive', response_model=ListingDraftResponseV1)
    def v12_archive_listing_draft(
        draft_id: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        try:
            _ensure_listing_drafts_table(conn)
            row = conn.execute('SELECT * FROM listing_drafts WHERE draft_id = ?', (draft_id,)).fetchone()
            if row is None:
                raise v1_error(404, 'listing_draft_not_found', 'Listing draft not found.', {'draft_id': draft_id})
            archived_at = now_utc()
            conn.execute(
                'UPDATE listing_drafts SET status = ?, archived_at = ?, updated_at = ? WHERE draft_id = ?',
                ('archived', archived_at, archived_at, draft_id),
            )
            conn.commit()
            updated = conn.execute('SELECT * FROM listing_drafts WHERE draft_id = ?', (draft_id,)).fetchone()
            return {'data': _listing_draft_row_to_response(updated), 'metadata': _listing_draft_metadata()}
        finally:
            conn.close()


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

    # ── /api/v1/prices/chart (v12 chart-ready) ───────────────────────

    @app.get('/api/v1/prices/chart/cards/{card_key:path}', response_model=ChartReadyPriceHistoryResponseV1)
    def v12_chart_ready_price_history(
        card_key: str,
        bucket_size: str = Query('day', description='Time bucket: day, week, month'),
        source: str | None = Query(None, description='Filter to one source (e.g. ebay_uk_sold)'),
        include_non_recommended: bool = Query(False, description='Include non-recommended evidence'),
        limit: int = Query(365, ge=1, le=365, description='Max points per series'),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """v12 chart-ready price history endpoint.

        Returns time-bucketed price series from existing local evidence
        only. No external API calls. Suitable for rendering price charts
        in the web tracker, inventory views, and listing assistant.
        """
        if bucket_size not in ('day', 'week', 'month'):
            raise v1_error(400, 'invalid_bucket_size', 'bucket_size must be day, week, or month.', {'allowed': ['day', 'week', 'month']})

        language_code, card_id = parse_card_key(card_key)
        conn = connect(app.state.db)
        ensure_price_support(conn)
        cur = conn.cursor()

        cur.execute('SELECT 1 FROM v2_card_detail_api_cache WHERE language_code=? AND card_id=? LIMIT 1', (language_code, card_id))
        if not cur.fetchone():
            raise v1_error(404, 'card_not_found', 'Card not found.', {'card_key': canonical_card_key(language_code, card_id)})

        # Build evidence filter
        wh = 'card_id = ? AND language_code = ?'
        pr: list[Any] = [card_id, language_code]
        if source:
            wh += ' AND source = ?'
            pr.append(source)
        if not include_non_recommended:
            wh += ' AND COALESCE(is_recommended_input, 0) = 1'

        # Fetch evidence rows
        cur.execute(
            f'SELECT sold_date, price_gbp, source FROM uk_price_history WHERE {wh} ORDER BY sold_date, source',
            pr,
        )
        rows = cur.fetchall()

        card_k = canonical_card_key(language_code, card_id)

        if not rows:
            return {
                'data': {
                    'card_key': card_k,
                    'series': [],
                    'summary': {
                        'has_uk_sold_evidence': False,
                        'has_fallback_evidence': False,
                        'primary_source_live': False,
                        'point_count': 0,
                    },
                },
                'warnings': [
                    'UK eBay sold/completed source is not yet live.',
                    'Chart uses existing local fallback evidence only.',
                    'No price evidence available for this card.',
                ],
                'metadata': {
                    'api_version': 'v1',
                    'contract': 'v12-chart-ready-price-history',
                    'generated_at': now_utc(),
                    'request': {
                        'card_key': card_k,
                        'bucket_size': bucket_size,
                        'source': source,
                        'include_non_recommended': include_non_recommended,
                        'limit': limit,
                    },
                },
            }

        # Group by source
        from collections import defaultdict
        by_source: dict[str, list[tuple[str, float]]] = defaultdict(list)
        all_sources: set[str] = set()
        for sold_date, price_gbp, src in rows:
            by_source[src].append((sold_date, price_gbp))
            all_sources.add(src)

        # Bucket function
        def _bucket_key(date_str: str) -> str:
            if bucket_size == 'day':
                return date_str
            try:
                d = dt.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                return date_str
            if bucket_size == 'week':
                # ISO week Monday
                offset = d.weekday()
                monday = d - dt.timedelta(days=offset)
                return monday.isoformat()
            else:  # month
                return f'{d.year:04d}-{d.month:02d}-01'

        # Percentile helper
        def _percentile(sorted_vals: list[float], pct: float) -> float | None:
            if not sorted_vals:
                return None
            idx = pct * (len(sorted_vals) - 1)
            lo = int(idx)
            hi = min(lo + 1, len(sorted_vals) - 1)
            frac = idx - lo
            return round(sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo]), 2)

        # Confidence from evidence count
        def _confidence(count: int) -> str:
            if count >= 10:
                return 'MEDIUM'
            if count >= 3:
                return 'LOW'
            return 'VERY_LOW'

        # Build series
        series_list: list[dict[str, Any]] = []
        total_points = 0
        for src in sorted(by_source.keys()):
            items = by_source[src]
            # Group by bucket
            buckets: dict[str, list[float]] = defaultdict(list)
            for date_str, price in items:
                bk = _bucket_key(date_str)
                buckets[bk].append(price)

            points: list[dict[str, Any]] = []
            for bk in sorted(buckets.keys()):
                prices = sorted(buckets[bk])
                median = _percentile(prices, 0.5)
                low = _percentile(prices, 0.1)
                high = _percentile(prices, 0.9)
                ev_count = len(prices)
                points.append({
                    'date': bk,
                    'median': median,
                    'low': low,
                    'high': high,
                    'evidence_count': ev_count,
                    'confidence': _confidence(ev_count),
                })

            # Apply limit
            if len(points) > limit:
                points = points[-limit:]

            total_points += len(points)
            series_list.append({
                'source': src,
                'currency': 'GBP',
                'price_type': 'market_existing_local',
                'region': 'UK' if 'uk' in src.lower() else None,
                'points': points,
            })

        has_uk_sold = 'ebay_uk_sold' in all_sources
        has_fallback = len(all_sources) > 0

        return {
            'data': {
                'card_key': card_k,
                'series': series_list,
                'summary': {
                    'has_uk_sold_evidence': has_uk_sold,
                    'has_fallback_evidence': has_fallback,
                    'primary_source_live': False,
                    'point_count': total_points,
                },
            },
            'warnings': [
                'UK eBay sold/completed source is not yet live.',
                'Chart uses existing local fallback evidence only.',
            ],
            'metadata': {
                'api_version': 'v1',
                'contract': 'v12-chart-ready-price-history',
                'generated_at': now_utc(),
                'request': {
                    'card_key': card_k,
                    'bucket_size': bucket_size,
                    'source': source,
                    'include_non_recommended': include_non_recommended,
                    'limit': limit,
                },
            },
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
            ('v28', """CREATE TABLE IF NOT EXISTS tenants (
                tenant_id INTEGER PRIMARY KEY,
                tenant_name TEXT NOT NULL,
                tenant_slug TEXT NOT NULL UNIQUE,
                is_active INTEGER DEFAULT 1,
                config_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create multi-tenant table.'),
            ('v28b', """INSERT OR IGNORE INTO tenants(tenant_id, tenant_name, tenant_slug)
                VALUES (1, 'Default Tenant', 'default')""", 'Insert default tenant for single-user mode.'),
            ('v29', """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                username TEXT NOT NULL,
                email TEXT,
                hashed_password TEXT,
                role TEXT DEFAULT 'viewer',
                is_active INTEGER DEFAULT 1,
                api_key TEXT,
                api_key_scopes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create users table with tenant scope.'),
            ('v29b', 'CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_tenant ON users(tenant_id, username)', 'Unique username per tenant.'),
            ('v30', """CREATE TABLE IF NOT EXISTS physical_items (
                item_id TEXT PRIMARY KEY,
                sku_id INTEGER NOT NULL,
                certification_number TEXT,
                certification_company TEXT,
                certification_grade REAL,
                certification_qualifier TEXT,
                item_condition TEXT DEFAULT 'Near Mint',
                acquired_date TEXT,
                acquired_price REAL,
                acquired_currency TEXT DEFAULT 'GBP',
                acquired_source TEXT,
                acquired_source_reference TEXT,
                location_code TEXT DEFAULT 'Unknown',
                location_detail TEXT,
                status TEXT DEFAULT 'owned',
                notes TEXT,
                tenant_id INTEGER DEFAULT 1,
                created_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create physical item instances table.'),
            ('v30b', 'CREATE UNIQUE INDEX IF NOT EXISTS idx_certification_unique ON physical_items(certification_company, certification_number) WHERE certification_number IS NOT NULL', 'Unique constraint on certification.'),
            ('v30c', 'CREATE INDEX IF NOT EXISTS idx_physical_items_sku ON physical_items(sku_id)', 'Index for SKU lookup.'),
            ('v30d', 'CREATE INDEX IF NOT EXISTS idx_physical_items_tenant ON physical_items(tenant_id)', 'Index for tenant isolation.'),
            ('v30e', 'CREATE INDEX IF NOT EXISTS idx_physical_items_status ON physical_items(status)', 'Index for status filtering.'),
            ('v30f', 'CREATE INDEX IF NOT EXISTS idx_physical_items_location ON physical_items(location_code)', 'Index for location lookup.'),
            ('v31', """CREATE TABLE IF NOT EXISTS item_images (
                image_id INTEGER PRIMARY KEY,
                item_id TEXT NOT NULL,
                image_type TEXT,
                image_url TEXT,
                image_local_path TEXT,
                is_primary INTEGER DEFAULT 0,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT
            )""", 'Create item images table.'),
            ('v31b', 'CREATE INDEX IF NOT EXISTS idx_item_images_item ON item_images(item_id)', 'Index for image lookup by item.'),
            ('v32', """CREATE TABLE IF NOT EXISTS inventory_transactions (
                transaction_id INTEGER PRIMARY KEY,
                item_id TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity INTEGER DEFAULT 1,
                from_location TEXT,
                to_location TEXT,
                from_status TEXT,
                to_status TEXT,
                price REAL,
                currency TEXT DEFAULT 'GBP',
                counterparty TEXT,
                counterparty_id TEXT,
                reference TEXT,
                notes TEXT,
                price_observation_id INTEGER,
                price_snapshot_id INTEGER,
                tenant_id INTEGER DEFAULT 1,
                created_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create immutable inventory transaction log.'),
            ('v32b', 'CREATE INDEX IF NOT EXISTS idx_inventory_transactions_item ON inventory_transactions(item_id)', 'Index for item transaction lookup.'),
            ('v32c', 'CREATE INDEX IF NOT EXISTS idx_inventory_transactions_tenant ON inventory_transactions(tenant_id)', 'Index for tenant isolation on transactions.'),
            ('v32d', 'CREATE INDEX IF NOT EXISTS idx_inventory_transactions_type ON inventory_transactions(transaction_type)', 'Index for transaction type filtering.'),
            ('v32e', 'CREATE INDEX IF NOT EXISTS idx_inventory_transactions_created ON inventory_transactions(created_at)', 'Index for chronological ordering.'),
            ('v33', """CREATE TABLE IF NOT EXISTS inventory_snapshots (
                snapshot_id INTEGER PRIMARY KEY,
                item_id TEXT NOT NULL,
                current_location TEXT,
                current_status TEXT,
                current_condition TEXT,
                last_transaction_id INTEGER,
                as_of_date TEXT DEFAULT CURRENT_TIMESTAMP,
                tenant_id INTEGER DEFAULT 1
            )""", 'Create denormalized inventory snapshot for performance.'),
            ('v33b', 'CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_item ON inventory_snapshots(item_id)', 'Index for snapshot lookup by item.'),
            ('v33c', 'CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_tenant ON inventory_snapshots(tenant_id)', 'Index for tenant isolation on snapshots.'),
            ('v34', """CREATE TABLE IF NOT EXISTS tenant_memberships (
                membership_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
                UNIQUE(user_id, tenant_id)
            )""", 'Create tenant memberships table connecting users to tenants with roles.'),
            ('v34b', 'CREATE INDEX IF NOT EXISTS idx_tenant_memberships_user ON tenant_memberships(user_id)', 'Index for user membership lookup.'),
            ('v34c', 'CREATE INDEX IF NOT EXISTS idx_tenant_memberships_tenant ON tenant_memberships(tenant_id)', 'Index for tenant membership lookup.'),
            ('v35', """CREATE TABLE IF NOT EXISTS api_key_scopes (
                key_id INTEGER NOT NULL,
                scope TEXT NOT NULL,
                PRIMARY KEY (key_id, scope),
                FOREIGN KEY (key_id) REFERENCES developer_api_keys(id) ON DELETE CASCADE
            )""", 'Create normalised API key scopes table.'),
            ('v35b', 'CREATE INDEX IF NOT EXISTS idx_api_key_scopes_key ON api_key_scopes(key_id)', 'Index for API key scope lookup.'),
            ('v36', """CREATE TABLE IF NOT EXISTS admin_audit_log (
                log_id INTEGER PRIMARY KEY,
                principal_key_id INTEGER,
                action TEXT NOT NULL,
                target_tenant_id INTEGER,
                target_resource TEXT,
                request_id TEXT,
                result TEXT,
                details_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (principal_key_id) REFERENCES developer_api_keys(id)
            )""", 'Create immutable admin audit log table.'),
            ('v36b', 'CREATE INDEX IF NOT EXISTS idx_admin_audit_log_principal ON admin_audit_log(principal_key_id)', 'Index for principal lookup.'),
            ('v36c', 'CREATE INDEX IF NOT EXISTS idx_admin_audit_log_tenant ON admin_audit_log(target_tenant_id)', 'Index for tenant audit lookup.'),
            ('v36d', 'CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action ON admin_audit_log(action)', 'Index for action type lookup.'),
            ('v37', """CREATE TABLE IF NOT EXISTS idempotency_records (
                tenant_id INTEGER NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_status INTEGER,
                resource_type TEXT,
                resource_id TEXT,
                response_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                PRIMARY KEY (tenant_id, operation, idempotency_key),
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
            )""", 'Create idempotency records table for safe retries.'),
            ('v37b', 'CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_records(expires_at)', 'Index for idempotency expiry cleanup.'),
            ('v38', """CREATE TABLE IF NOT EXISTS maintenance_audit (
                audit_id INTEGER PRIMARY KEY,
                table_name TEXT NOT NULL,
                row_pk TEXT NOT NULL,
                reason TEXT NOT NULL,
                original_values_json TEXT,
                replacement_values_json TEXT,
                operator TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""", 'Create maintenance audit table for ledger repair records.'),
            ('v39', 'ALTER TABLE physical_items ADD COLUMN revision INTEGER DEFAULT 0', 'Add optimistic locking revision column to physical_items.'),
            ('v40', 'ALTER TABLE physical_items ADD COLUMN archived_at TEXT', 'Add soft delete timestamp to physical_items.'),
            ('v41', 'ALTER TABLE physical_items ADD COLUMN archived_by TEXT', 'Add archive operator column to physical_items.'),
            ('v42', 'ALTER TABLE physical_items ADD COLUMN archive_reason TEXT', 'Add archive reason column to physical_items.'),
            ('v43', 'ALTER TABLE inventory_snapshots ADD COLUMN revision INTEGER DEFAULT 0', 'Add revision column to inventory_snapshots for consistency.'),
            ('v44', """CREATE TRIGGER IF NOT EXISTS reject_update_inventory_transactions
                BEFORE UPDATE ON inventory_transactions
            BEGIN
                SELECT RAISE(ABORT, 'UPDATEs are not allowed on inventory_transactions');
            END""", 'Add immutability trigger: reject UPDATEs on inventory_transactions.'),
            ('v44b', """CREATE TRIGGER IF NOT EXISTS reject_delete_inventory_transactions
                BEFORE DELETE ON inventory_transactions
            BEGIN
                SELECT RAISE(ABORT, 'DELETEs are not allowed on inventory_transactions');
            END""", 'Add immutability trigger: reject DELETEs on inventory_transactions.'),
            ('v45', """CREATE TRIGGER IF NOT EXISTS reject_update_admin_audit_log
                BEFORE UPDATE ON admin_audit_log
            BEGIN
                SELECT RAISE(ABORT, 'UPDATEs are not allowed on admin_audit_log');
            END""", 'Add immutability trigger: reject UPDATEs on admin_audit_log.'),
            ('v45b', """CREATE TRIGGER IF NOT EXISTS reject_delete_admin_audit_log
                BEFORE DELETE ON admin_audit_log
            BEGIN
                SELECT RAISE(ABORT, 'DELETEs are not allowed on admin_audit_log');
            END""", 'Add immutability trigger: reject DELETEs on admin_audit_log.'),
            ('v46', "CREATE TABLE IF NOT EXISTS image_delivery_policies (policy_id INTEGER PRIMARY KEY AUTOINCREMENT, scope_type TEXT NOT NULL CHECK (scope_type IN ('global', 'source', 'language', 'set', 'card', 'image')), scope_value TEXT NOT NULL, external_display_enabled INTEGER NOT NULL CHECK (external_display_enabled IN (0, 1)), reason TEXT, attribution_text TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), UNIQUE(scope_type, scope_value), CHECK ((scope_type = 'global' AND scope_value = 'global') OR (scope_type <> 'global' AND length(trim(scope_value)) > 0)))", 'Create image delivery policy table.'),
            ('v46b', "INSERT OR IGNORE INTO image_delivery_policies(scope_type, scope_value, external_display_enabled, reason) VALUES ('global', 'global', 1, 'Default: catalogue images enabled by design')",
                         'Seed explicit global default policy.'),
            ('v47', "CREATE TABLE IF NOT EXISTS takedown_cases (case_id INTEGER PRIMARY KEY AUTOINCREMENT, requester_identity TEXT NOT NULL, requester_contact TEXT NOT NULL, rights_description TEXT, status TEXT NOT NULL CHECK (status IN ('open', 'under_review', 'resolved', 'rejected')), opened_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), resolved_at TEXT, resolution_summary TEXT)",
                     'Create append-only takedown case registry.'),
            ('v48', "CREATE TABLE IF NOT EXISTS takedown_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, action_type TEXT NOT NULL CHECK (action_type IN ('case_opened', 'disabled', 'restored', 'replaced', 'case_resolved', 'case_rejected')), scope_type TEXT CHECK (scope_type IS NULL OR scope_type IN ('global', 'source', 'language', 'set', 'card', 'image')), scope_value TEXT, actor_membership_id INTEGER, reason TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), FOREIGN KEY(case_id) REFERENCES takedown_cases(case_id) ON DELETE RESTRICT, FOREIGN KEY(actor_membership_id) REFERENCES tenant_memberships(membership_id) ON DELETE RESTRICT, CHECK ((scope_type IS NULL AND scope_value IS NULL) OR (scope_type IS NOT NULL AND scope_value IS NOT NULL AND length(trim(scope_value)) > 0)))", 'Create immutable takedown event audit log.'),
            ('v48b', "CREATE TRIGGER IF NOT EXISTS reject_update_takedown_events BEFORE UPDATE ON takedown_events BEGIN SELECT RAISE(ABORT, 'Cannot update takedown events'); END", 'Reject UPDATEs on takedown_events.'),
            ('v48c', "CREATE TRIGGER IF NOT EXISTS reject_delete_takedown_events BEFORE DELETE ON takedown_events BEGIN SELECT RAISE(ABORT, 'Cannot delete takedown events'); END", 'Reject DELETEs on takedown_events.'),
            ('v49', "CREATE TABLE IF NOT EXISTS image_delivery_policy_records (record_id INTEGER PRIMARY KEY AUTOINCREMENT, image_id INTEGER, card_key TEXT, tenant_id INTEGER, api_key_id INTEGER, requested_size TEXT, policy_decision TEXT NOT NULL, response_status INTEGER NOT NULL, response_outcome TEXT NOT NULL, request_id TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))", 'Create image delivery log for abuse monitoring.'),
            ('v49b', "CREATE INDEX IF NOT EXISTS idx_delivery_log_created ON image_delivery_policy_records(created_at)", 'Index for time-based delivery log queries.'),
            ('v49c', "CREATE INDEX IF NOT EXISTS idx_delivery_log_card ON image_delivery_policy_records(card_key)", 'Index for card-based delivery log queries.'),
            ('v49d', "CREATE INDEX IF NOT EXISTS idx_delivery_log_tenant ON image_delivery_policy_records(tenant_id)", 'Index for tenant-based delivery log queries.'),
            ('v50', "CREATE TABLE IF NOT EXISTS derivative_cache (cache_id INTEGER PRIMARY KEY AUTOINCREMENT, source_image_id INTEGER, source_hash TEXT NOT NULL, size TEXT NOT NULL CHECK (size IN ('thumbnail', 'small', 'medium', 'large')), cache_version INTEGER NOT NULL DEFAULT 1, local_path TEXT NOT NULL, file_bytes INTEGER NOT NULL DEFAULT 0, mime_type TEXT NOT NULL DEFAULT 'image/webp', created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), UNIQUE(source_hash, size, cache_version))", 'Create deterministic derivative cache table.'),
            ('v50b', "CREATE INDEX IF NOT EXISTS idx_derivative_cache_source ON derivative_cache(source_image_id)", 'Index for derivative lookup by source image.'),
            ('v51', "CREATE TABLE IF NOT EXISTS physical_item_photos (photo_id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, tenant_id INTEGER NOT NULL, uploaded_by TEXT, original_filename TEXT, storage_path TEXT NOT NULL, mime_type TEXT NOT NULL DEFAULT 'image/jpeg', file_bytes INTEGER, is_published INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), FOREIGN KEY (item_id) REFERENCES physical_items(item_id) ON DELETE CASCADE)", 'Create tenant-isolated physical item photo table.'),
            ('v51b', "CREATE INDEX IF NOT EXISTS idx_physical_item_photos_item ON physical_item_photos(item_id)", 'Index for photo lookup by item.'),
            ('v51c', "CREATE INDEX IF NOT EXISTS idx_physical_item_photos_tenant ON physical_item_photos(tenant_id)", 'Index for tenant isolation on photos.'),
            ('v52', "CREATE TABLE IF NOT EXISTS image_delivery_quotas (quota_id INTEGER PRIMARY KEY AUTOINCREMENT, access_identity TEXT NOT NULL, identity_type TEXT NOT NULL CHECK (identity_type IN ('api_key', 'signed_url', 'tenant')), window_start TEXT NOT NULL, window_end TEXT NOT NULL, hourly_count INTEGER NOT NULL DEFAULT 0, daily_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), UNIQUE(access_identity, window_start))",
             'Create per-identity image delivery quota table.'),
            ('v52b', "CREATE INDEX IF NOT EXISTS idx_image_delivery_quotas_identity ON image_delivery_quotas(access_identity)", 'Index for quota lookup by identity.'),
            ('v52c', "CREATE INDEX IF NOT EXISTS idx_image_delivery_quotas_window ON image_delivery_quotas(window_start, window_end)", 'Index for quota cleanup by time window.'),
            ('v53', "CREATE TABLE IF NOT EXISTS image_delivery_daily_aggregation (agg_id INTEGER PRIMARY KEY AUTOINCREMENT, agg_date TEXT NOT NULL, tenant_id INTEGER, api_key_id INTEGER, card_key TEXT, policy_decision TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), UNIQUE(agg_date, tenant_id, api_key_id, card_key, policy_decision))",
             'Create daily delivery log aggregation table.'),
            ('v53b', "CREATE INDEX IF NOT EXISTS idx_delivery_agg_date ON image_delivery_daily_aggregation(agg_date)", 'Index for date-based aggregation queries.'),
            ('v54', """
                CREATE TABLE IF NOT EXISTS catalogue_image_assets (
                    image_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_key TEXT NOT NULL,
                    set_id TEXT,
                    language_code TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_language_code TEXT,
                    local_path TEXT NOT NULL,
                    source_hash TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(card_key, source_type, source_language_code, language_code)
                )
            """, 'Stable catalogue image identity — explicit PK, not rowid.'),
            ('v54b', """
                INSERT OR IGNORE INTO catalogue_image_assets
                    (card_key, set_id, language_code, source_type, source_language_code, local_path)
                SELECT
                    language_code || ':' || card_id,
                    resolved_set_id,
                    language_code,
                    COALESCE(display_image_source_type, 'unknown'),
                    display_image_source_language_code,
                    local_display_image_url
                FROM v2_card_detail_api_cache
                WHERE has_display_image = 1
                  AND local_display_image_url IS NOT NULL
                  AND trim(local_display_image_url) != ''
                ORDER BY language_code, card_id
            """, 'Backfill catalogue_image_assets from existing card cache.'),

            ('v55', '''
                CREATE TABLE IF NOT EXISTS image_delivery_quota_windows (
                    quota_window_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    access_identity TEXT NOT NULL,
                    identity_type TEXT NOT NULL,
                    window_kind TEXT NOT NULL
                        CHECK (window_kind IN ('hour', 'day')),
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    successful_delivery_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE (access_identity, identity_type, window_kind, window_start)
                )
            ''', 'Create corrected image delivery quota windows table (separate hour/day rows).'),
            ('v55b', '''
                CREATE INDEX IF NOT EXISTS idx_quota_windows_lookup
                ON image_delivery_quota_windows (access_identity, identity_type, window_kind, window_start)
            ''', 'Index for quota window lookup.'),

            ('v56', '''
                ALTER TABLE takedown_cases ADD COLUMN scope_type TEXT
            ''', 'Add scope_type to takedown_cases (v9.1).'),
            ('v56b', '''
                ALTER TABLE takedown_cases ADD COLUMN scope_value TEXT
            ''', 'Add scope_value to takedown_cases (v9.1).'),
            ('v56c', '''
                ALTER TABLE takedown_cases ADD COLUMN previous_policy_state TEXT
            ''', 'Add previous_policy_state JSON snapshot to takedown_cases (v9.1).'),
            ('v57', '''
                CREATE TABLE IF NOT EXISTS card_image_hashes (
                    card_key TEXT PRIMARY KEY,
                    language_code TEXT NOT NULL,
                    card_id TEXT NOT NULL,
                    image_hash TEXT NOT NULL,
                    cache_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''', 'Create image hash table for Phase 1 scanner.'),
            ('v57b', 'CREATE INDEX IF NOT EXISTS idx_card_image_hashes_hash ON card_image_hashes(image_hash)', 'Index for image hash lookup.'),
            # ── v10: Canonical commercial identity foundation ───────────────────
            ('v58', "CREATE TABLE IF NOT EXISTS v10_canonical_printings ("
                "canonical_printing_id TEXT PRIMARY KEY, "
                "canonical_key TEXT UNIQUE NOT NULL, "
                "game TEXT NOT NULL DEFAULT 'pokemon_tcg', "
                "core_set_id TEXT NOT NULL, "
                "set_id TEXT, "
                "set_code TEXT, "
                "collector_number TEXT, "
                "collector_number_sort TEXT, "
                "canonical_name TEXT NOT NULL, "
                "name_english TEXT, "
                "primary_language TEXT NOT NULL, "
                "card_kind TEXT, "
                "rarity TEXT, "
                "first_seen_source TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'active', "
                "confidence_score REAL NOT NULL, "
                "confidence_label TEXT NOT NULL, "
                "confidence_reason TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                ")", 'Create v10 canonical printing identity table.'),
            ('v58b', 'CREATE INDEX IF NOT EXISTS idx_v10_cp_core_set ON v10_canonical_printings(core_set_id, collector_number_sort)', 'Index for set+number lookup on canonical printings.'),
            ('v58c', 'CREATE INDEX IF NOT EXISTS idx_v10_cp_name ON v10_canonical_printings(canonical_name)', 'Index for name lookup on canonical printings.'),
            ('v58d', 'CREATE INDEX IF NOT EXISTS idx_v10_cp_confidence ON v10_canonical_printings(confidence_label)', 'Index for confidence filtering.'),
            ('v59', "CREATE TABLE IF NOT EXISTS v10_canonical_printing_cards ("
                "canonical_printing_id TEXT NOT NULL, "
                "card_key TEXT NOT NULL, "
                "language_code TEXT NOT NULL, "
                "source_card_id TEXT, "
                "match_method TEXT NOT NULL, "
                "confidence_score REAL NOT NULL, "
                "confidence_reason TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "PRIMARY KEY (canonical_printing_id, card_key)"
                ")", 'Create v10 canonical-to-source-card link table.'),
            ('v59b', 'CREATE INDEX IF NOT EXISTS idx_v10_cpc_card_key ON v10_canonical_printing_cards(card_key)', 'Index for reverse card-to-canonical lookup.'),
            ('v60', "CREATE TABLE IF NOT EXISTS v10_commercial_variants ("
                "commercial_variant_id TEXT PRIMARY KEY, "
                "canonical_printing_id TEXT NOT NULL, "
                "variant_key TEXT UNIQUE NOT NULL, "
                "language_code TEXT NOT NULL, "
                "finish TEXT NOT NULL DEFAULT 'unknown', "
                "variant_type TEXT NOT NULL DEFAULT 'standard', "
                "stamp TEXT, "
                "edition TEXT, "
                "is_reverse_holo INTEGER NOT NULL DEFAULT 0, "
                "is_holo INTEGER, "
                "is_promo INTEGER NOT NULL DEFAULT 0, "
                "market_region TEXT, "
                "status TEXT NOT NULL DEFAULT 'active', "
                "confidence_score REAL NOT NULL, "
                "confidence_label TEXT NOT NULL, "
                "confidence_reason TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                ")", 'Create v10 commercial variant table.'),
            ('v60b', 'CREATE INDEX IF NOT EXISTS idx_v10_cv_canonical ON v10_commercial_variants(canonical_printing_id)', 'Index for variant-to-canonical lookup.'),
            ('v60c', 'CREATE INDEX IF NOT EXISTS idx_v10_cv_language ON v10_commercial_variants(language_code)', 'Index for language filtering.'),
            ('v60d', 'CREATE INDEX IF NOT EXISTS idx_v10_cv_finish ON v10_commercial_variants(finish)', 'Index for finish filtering.'),
            ('v61', "CREATE TABLE IF NOT EXISTS v10_sellable_skus ("
                "sellable_sku_id TEXT PRIMARY KEY, "
                "commercial_variant_id TEXT NOT NULL, "
                "sku_key TEXT UNIQUE NOT NULL, "
                "item_class TEXT NOT NULL DEFAULT 'single_card', "
                "condition_policy TEXT NOT NULL DEFAULT 'raw_conditioned', "
                "display_title TEXT NOT NULL, "
                "pricing_key TEXT, "
                "inventory_enabled INTEGER NOT NULL DEFAULT 1, "
                "listing_enabled INTEGER NOT NULL DEFAULT 1, "
                "scanner_enabled INTEGER NOT NULL DEFAULT 1, "
                "status TEXT NOT NULL DEFAULT 'active', "
                "confidence_score REAL NOT NULL, "
                "confidence_label TEXT NOT NULL, "
                "confidence_reason TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                ")", 'Create v10 sellable SKU table.'),
            ('v61b', 'CREATE INDEX IF NOT EXISTS idx_v10_sku_variant ON v10_sellable_skus(commercial_variant_id)', 'Index for SKU-to-variant lookup.'),
            ('v61c', 'CREATE INDEX IF NOT EXISTS idx_v10_sku_item_class ON v10_sellable_skus(item_class)', 'Index for item class filtering.'),
            ('v62', "CREATE TABLE IF NOT EXISTS v10_external_references ("
                "external_reference_id TEXT PRIMARY KEY, "
                "entity_type TEXT NOT NULL, "
                "entity_id TEXT NOT NULL, "
                "source_name TEXT NOT NULL, "
                "source_entity_type TEXT, "
                "source_identifier TEXT NOT NULL, "
                "source_url TEXT, "
                "match_method TEXT NOT NULL, "
                "confidence_score REAL NOT NULL, "
                "confidence_label TEXT NOT NULL, "
                "confidence_reason TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "status TEXT NOT NULL DEFAULT 'active', "
                "UNIQUE(entity_type, entity_id, source_name, source_identifier)"
                ")", 'Create v10 external reference mapping table.'),
            ('v62b', 'CREATE INDEX IF NOT EXISTS idx_v10_er_entity ON v10_external_references(entity_type, entity_id)', 'Index for entity reference lookup.'),
            ('v63', "CREATE TABLE IF NOT EXISTS v10_identity_build_runs ("
                "build_run_id TEXT PRIMARY KEY, "
                "started_at TEXT NOT NULL, "
                "finished_at TEXT, "
                "status TEXT NOT NULL, "
                "source_db_path TEXT, "
                "algorithm_version TEXT NOT NULL DEFAULT '1.0.0', "
                "cards_seen INTEGER DEFAULT 0, "
                "canonical_printings_created INTEGER DEFAULT 0, "
                "commercial_variants_created INTEGER DEFAULT 0, "
                "sellable_skus_created INTEGER DEFAULT 0, "
                "external_references_created INTEGER DEFAULT 0, "
                "warnings_count INTEGER DEFAULT 0, "
                "errors_count INTEGER DEFAULT 0, "
                "notes TEXT"
                ")", 'Create v10 identity build run tracking table.'),
            ('v64', "CREATE TABLE IF NOT EXISTS v10_identity_build_events ("
                "event_id TEXT PRIMARY KEY, "
                "build_run_id TEXT NOT NULL, "
                "severity TEXT NOT NULL, "
                "entity_type TEXT, "
                "entity_id TEXT, "
                "message TEXT NOT NULL, "
                "details_json TEXT, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                ")", 'Create v10 identity build event log table.'),
            ('v65', "CREATE TABLE IF NOT EXISTS v10_inventory_sku_links ("
                "link_id TEXT PRIMARY KEY, "
                "sellable_sku_id TEXT NOT NULL, "
                "legacy_sku_id INTEGER NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
                "UNIQUE(sellable_sku_id, legacy_sku_id)"
                ")", 'Create v10-to-legacy SKU bridge table for inventory compatibility.'),
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

    # Run migrations at startup (skipped when skip_search_setup=True — for tests)
    if not settings.skip_search_setup:
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
        token = request.query_params.get('token')
        token_image_request = token and (
            request.url.path.startswith('/api/v1/images/assets/')
            or request.url.path.startswith('/api/v1/images/card/')
        )
        if request.url.path.startswith('/api/v1') and not request.url.path.startswith('/api/v1/admin') and not token_image_request:
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
                'mounted': False,
                'url_prefix': None,
                'gateway': '/api/v1/images/assets/{image_id}/content' if app.state.settings.image_cache_mounted else None,
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

        # Inject signed_image_url into each result's images dict
        for r in results:
            imgs = r.get('images') or {}
            card_key = r.get('language_code', '') + ':' + r.get('card_id', '')
            signed = _generate_card_signed_url(conn, card_key, app.state.settings) if app.state.settings else None
            imgs['signed_image_url'] = signed
            r['images'] = imgs

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
        # Inject signed_image_url into each result's images dict
        for r in results:
            imgs = r.get('images') or {}
            card_key = imgs.get('card_key') or (r.get('language_code', '') + ':' + r.get('card_id', ''))
            signed = _generate_card_signed_url(conn, card_key, app.state.settings) if app.state.settings else None
            imgs['signed_image_url'] = signed
            r['images'] = imgs
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
            raise HTTPException(status_code=503, detail={
                'code': 'pricing_provider_not_configured',
                'message': 'Live pricing is unavailable because the pricing provider is not configured.',
            })

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

    # ═══════════════════════════════════════════════════════════════════
    # v9 — Inventory & Tenant Management
    # ═══════════════════════════════════════════════════════════════════

    # ── Helpers ──────────────────────────────────────────────────────

    def ensure_inventory_support(conn: sqlite3.Connection) -> None:
        """Ensure inventory tables exist and v9 support objects are ready.
        Tables are created by migration framework; this handles complex
        operations not expressible as single SQL statements."""
        cur = conn.cursor()
        # Add membership_id to developer_api_keys if not present (SQLite ALTER TABLE)
        existing_cols = {r[1] for r in cur.execute('PRAGMA table_info(developer_api_keys)').fetchall()}
        if 'membership_id' not in existing_cols:
            cur.execute('ALTER TABLE developer_api_keys ADD COLUMN membership_id INTEGER REFERENCES tenant_memberships(membership_id)')
            conn.commit()
        # Ensure default user and membership exist (idempotent)
        ensure_v9_defaults(conn)

    def ensure_v9_defaults(conn: sqlite3.Connection) -> None:
        """Create default user and tenant_membership for single-user mode.
        Idempotent: safe to re-run."""
        cur = conn.cursor()
        # Check users table exists
        users_exists = cur.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()[0] > 0
        tenant_memberships_exists = cur.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tenant_memberships'"
        ).fetchone()[0] > 0
        if not (users_exists and tenant_memberships_exists):
            return  # Tables not yet created by migration

        # Create or resolve default user
        user_row = cur.execute(
            "SELECT user_id FROM users WHERE username='system' LIMIT 1"
        ).fetchone()
        if not user_row:
            cur.execute(
                "INSERT INTO users(tenant_id, username, email, role, is_active) "
                "VALUES (1, 'system', 'system@saveroom.local', 'admin', 1)"
            )
            user_id = cur.lastrowid
        else:
            user_id = user_row['user_id']

        # Create admin membership for default tenant
        existing = cur.execute(
            "SELECT membership_id FROM tenant_memberships WHERE user_id=? AND tenant_id=?",
            (user_id, 1)
        ).fetchone()
        if not existing:
            cur.execute(
                "INSERT INTO tenant_memberships(user_id, tenant_id, role) VALUES (?, ?, 'admin')",
                (user_id, 1)
            )
            membership_id = cur.lastrowid
            # Link all existing active API keys to this membership if they have no membership_id
            cur.execute(
                "UPDATE developer_api_keys SET membership_id=? WHERE membership_id IS NULL AND is_active=1",
                (membership_id,)
            )
        conn.commit()

    def _validate_status_transition(from_status: str, to_status: str, transaction_type: str) -> str | None:
        """Validate a status transition. Returns None if valid, or error message.
        
        The transaction_type parameter is the event type from the endpoint.
        Maps common status-name usage to the correct event type."""
        valid = {
            ('owned', 'consigned'): 'consigned_out',
            ('owned', 'sold'): 'sold',
            ('owned', 'lost'): 'marked_lost',
            ('consigned', 'owned'): 'consignment_returned',
            ('consigned', 'sold'): 'sold',
            ('consigned', 'lost'): 'marked_lost',
            ('lost', 'owned'): 'found',
            ('lost', 'written_off'): 'written_off',
            ('owned', 'owned'): 'location_moved',
            ('consigned', 'consigned'): 'location_moved',
        }
        key = (from_status, to_status)
        expected_type = valid.get(key)
        if expected_type is None:
            return f"Invalid transition: {from_status} → {to_status}"
        # Accept the expected_type OR the to_status name as the transaction type
        if transaction_type not in (expected_type, to_status, 'location_moved', 'metadata_corrected'):
            return f"Transition {from_status} → {to_status} requires type '{expected_type}', not '{transaction_type}'"
        return None

    def _get_transaction_type(to_status: str, from_status: str) -> str:
        """Map a status change to the standardized transaction type."""
        mapping = {
            ('owned', 'consigned'): 'consigned_out',
            ('owned', 'sold'): 'sold',
            ('owned', 'lost'): 'marked_lost',
            ('consigned', 'owned'): 'consignment_returned',
            ('consigned', 'sold'): 'sold',
            ('consigned', 'lost'): 'marked_lost',
            ('lost', 'owned'): 'found',
            ('lost', 'written_off'): 'written_off',
        }
        return mapping.get((from_status, to_status), to_status)

    def require_scope(*scopes: str):
        """Dependency factory: require at least one of the given scopes."""
        def _check(auth: dict[str, Any] = Depends(require_v1_api_key)) -> dict[str, Any]:
            if not auth.get('auth_required'):
                return auth
            user_scopes = auth.get('scopes', [])
            if 'admin:all' in user_scopes or 'admin' in user_scopes:
                return auth
            for s in scopes:
                if s in user_scopes:
                    return auth
            raise v1_error(403, 'insufficient_scope',
                           f'Required scope: {", ".join(sorted(scopes))}',
                           {'required_scopes': sorted(scopes), 'user_scopes': user_scopes})
        return _check

    def get_tenant_from_key(auth: dict[str, Any]) -> int:
        """Resolve tenant_id from API key's membership_id."""
        membership_id = auth.get('membership_id') if isinstance(auth, dict) else getattr(auth, 'membership_id', None)
        if membership_id:
            conn = connect(app.state.db)
            cur = conn.cursor()
            row = cur.execute(
                'SELECT tenant_id FROM tenant_memberships WHERE membership_id=?',
                (membership_id,)
            ).fetchone()
            conn.close()
            if row:
                return row['tenant_id']
        # Fallback for admin keys or auth-disabled mode
        return 1

    def build_sku_identity(conn: sqlite3.Connection, sku_id: int) -> dict[str, Any] | None:
        """Build a SellableSKUIdentity by joining sellable_skus with canonical_printings."""
        cur = conn.cursor()
        row = cur.execute("""
            SELECT s.sku_id, s.sku_key, s.language_code, s.condition_code,
                   c.set_code, c.collector_number, c.name_english
            FROM sellable_skus s
            LEFT JOIN canonical_printings c ON c.printing_id = s.printing_id
            WHERE s.sku_id = ?
        """, (sku_id,)).fetchone()
        if not row:
            return None
        return {
            'sku_id': row['sku_id'],
            'sku_key': row['sku_key'],
            'language_code': row['language_code'],
            'condition_code': row['condition_code'],
            'set_code': row[4],
            'collector_number': row[5],
            'name_english': row[6],
        }

    def resolve_inventory_listing_source(conn: sqlite3.Connection, item_id: str, tenant_id: int) -> dict[str, Any]:
        """Resolve a physical inventory item to local listing-draft source data."""
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT p.*, s.condition_code, s.sku_key, s.language_code AS sku_language_code,
                   c.canonical_card_key, c.name_english,
                   cv.finish AS variant_finish
            FROM physical_items p
            LEFT JOIN sellable_skus s ON s.sku_id = p.sku_id
            LEFT JOIN canonical_printings c ON c.printing_id = s.printing_id
            LEFT JOIN commercial_variants cv ON cv.variant_id = s.variant_id
            WHERE p.item_id = ? AND p.tenant_id = ?
            """,
            (item_id, tenant_id),
        ).fetchone()
        if not row:
            raise v1_error(404, 'item_not_found', 'Physical item not found.', {'item_id': item_id})

        data = dict(row)
        card_key = _clean_listing_text(data.get('canonical_card_key'))
        if not card_key:
            raise v1_error(
                409,
                'inventory_item_missing_card_key',
                'Inventory item cannot be converted to a listing draft because its SKU has no canonical card key.',
                {'item_id': item_id, 'sku_id': data.get('sku_id')},
            )

        status = (data.get('status') or '').strip().lower()
        quantity_available = 1 if status in {'owned', 'consigned'} else 0
        return {
            'item_id': data.get('item_id'),
            'sku_id': data.get('sku_id'),
            'sku_key': data.get('sku_key'),
            'card_key': card_key,
            'quantity_available': quantity_available,
            'condition': _clean_listing_text(data.get('item_condition')) or _clean_listing_text(data.get('condition_code')),
            'finish': _clean_listing_text(data.get('variant_finish')),
            'status': data.get('status'),
        }

    def get_item_snapshot(conn: sqlite3.Connection, item_id: str, tenant_id: int) -> dict[str, Any] | None:
        """Get current snapshot for a physical item. Falls back to the item itself."""
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM inventory_snapshots WHERE item_id=? AND tenant_id=? ORDER BY snapshot_id DESC LIMIT 1",
            (item_id, tenant_id),
        ).fetchone()
        if row:
            return dict(row)
        return None

    def record_transaction(
        conn: sqlite3.Connection,
        item_id: str,
        transaction_type: str,
        tenant_id: int,
        *,
        quantity: int = 1,
        from_location: str | None = None,
        to_location: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        price: float | None = None,
        currency: str = 'GBP',
        counterparty: str | None = None,
        reference: str | None = None,
        notes: str | None = None,
        price_observation_id: int | None = None,
        price_snapshot_id: int | None = None,
        created_by: str = 'system',
        expected_revision: int | None = None,
    ) -> int:
        """Record an immutable inventory transaction and update the snapshot atomically.
        
        Uses BEGIN IMMEDIATE for write isolation. Increments revision.
        If expected_revision is provided, the UPDATE is conditional on that revision
        and returns 0 if the revision doesn't match (caller must handle conflict).
        """
        cur = conn.cursor()
        # Insert transaction
        cur.execute("""
            INSERT INTO inventory_transactions(
                item_id, transaction_type, quantity,
                from_location, to_location, from_status, to_status,
                price, currency, counterparty, reference, notes,
                price_observation_id, price_snapshot_id,
                tenant_id, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_id, transaction_type, quantity,
            from_location, to_location, from_status, to_status,
            price, currency, counterparty, reference, notes,
            price_observation_id, price_snapshot_id,
            tenant_id, created_by,
        ))
        txn_id = cur.lastrowid
        # Update physical item revision (conditional if expected_revision provided)
        if expected_revision is not None:
            cur.execute("""
                UPDATE physical_items SET revision = revision + 1, updated_at = ?
                WHERE item_id=? AND tenant_id=? AND revision=?
            """, (now_utc(), item_id, tenant_id, expected_revision))
            if cur.rowcount == 0:
                raise Exception("Revision conflict - item was modified")
        else:
            cur.execute("""
                UPDATE physical_items SET revision = revision + 1, updated_at = ?
                WHERE item_id=? AND tenant_id=?
            """, (now_utc(), item_id, tenant_id))
        # UPSERT snapshot
        cur.execute("""
            INSERT INTO inventory_snapshots(
                item_id, current_location, current_status, current_condition,
                last_transaction_id, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item_id,
            to_location or from_location,
            to_status or from_status,
            None,
            txn_id,
            tenant_id,
        ))
        conn.commit()
        return txn_id

    def get_current_valuation(conn: sqlite3.Connection, tenant_id: int) -> dict[str, Any]:
        """Calculate current inventory valuation using v8 pricing evidence.
        
        Properly separates:
        - acquisition_cost_total_minor (what was paid to acquire)
        - current_market_value_total_minor (v8 price snapshots)
        - realised_sales_total_minor (what was received on sale)
        
        Never makes external RapidAPI requests.
        """
        cur = conn.cursor()
        # Get all items for the tenant
        items = cur.execute(
            "SELECT item_id, sku_id, certification_company, item_condition, status, "
            "acquired_price, acquired_currency "
            "FROM physical_items WHERE tenant_id=?",
            (tenant_id,),
        ).fetchall()

        valued_count = 0
        unvalued_count = 0
        stale_count = 0
        acquisition_cost_total = 0.0
        market_value_total = 0.0
        realised_sales_total = 0.0

        for item in items:
            sku_id = item['sku_id']
            status = item['status']
            acquired_price = item['acquired_price'] or 0.0
            
            # Track acquisition cost (only for owned/consigned items)
            if status in ('owned', 'consigned'):
                acquisition_cost_total += acquired_price
            
            # Track realised sales
            if status == 'sold':
                # Find sale price from transactions
                sale_row = cur.execute(
                    "SELECT price FROM inventory_transactions "
                    "WHERE item_id=? AND tenant_id=? AND transaction_type='sold' "
                    "ORDER BY transaction_id DESC LIMIT 1",
                    (item['item_id'], tenant_id)
                ).fetchone()
                if sale_row and sale_row['price']:
                    realised_sales_total += sale_row['price']
                continue  # Sold items don't get market valuation
            
            # Try to find latest price snapshot for this SKU
            snapshot = cur.execute("""
                SELECT recommended_price, calculated_at
                FROM price_snapshots
                WHERE sku_id=? AND price_type='raw'
                ORDER BY calculated_at DESC LIMIT 1
            """, (sku_id,)).fetchone()

            if snapshot and snapshot['recommended_price']:
                market_value_total += snapshot['recommended_price']
                valued_count += 1
                # Check staleness
                if snapshot['calculated_at']:
                    try:
                        from datetime import datetime, timezone
                        snap_dt = datetime.fromisoformat(snapshot['calculated_at'])
                        if snap_dt.tzinfo is None:
                            snap_dt = snap_dt.replace(tzinfo=timezone.utc)
                        age_days = (datetime.now(timezone.utc) - snap_dt).days
                        if age_days >= 7:
                            stale_count += 1
                    except (ValueError, TypeError):
                        stale_count += 1
            else:
                unvalued_count += 1

        total_items = len(items)
        acquisition_cost_total_minor = round(acquisition_cost_total * 100)
        current_market_value_total_minor = round(market_value_total * 100)
        realised_sales_total_minor = round(realised_sales_total * 100)

        return {
            'currency': 'GBP',
            'acquisition_cost_total_minor': acquisition_cost_total_minor,
            'current_market_value_total_minor': current_market_value_total_minor,
            'realised_sales_total_minor': realised_sales_total_minor,
            'valued_item_count': valued_count,
            'unvalued_item_count': unvalued_count,
            'stale_valuation_count': stale_count,
            'valuation_source': 'v8 price snapshots',
            'external_requests_used': 0,
            'total_items': total_items,
        }

    # ── Inventory Endpoints ──────────────────────────────────────────

    @app.get('/api/v1/inventory/items', response_model=InventoryListResponse)
    def v1_list_inventory(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        status: str | None = Query(None, description='Filter by status (owned, consigned, sold, etc.)'),
        location_code: str | None = Query(None, description='Filter by location code'),
        q: str | None = Query(None, description='Search in notes and acquired source'),
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        where = ['tenant_id = ?']
        params: list[Any] = [tenant_id]
        if status:
            where.append('status = ?')
            params.append(status)
        if location_code:
            where.append('location_code = ?')
            params.append(location_code)
        if q:
            where.append('(notes LIKE ? OR acquired_source LIKE ? OR item_id LIKE ?)')
            q_param = f'%{q}%'
            params.extend([q_param, q_param, q_param])

        where_sql = ' AND '.join(where)
        total = int(cur.execute(
            f'SELECT COUNT(*) FROM physical_items WHERE {where_sql}', params
        ).fetchone()[0])

        rows_result = cur.execute(
            f'SELECT * FROM physical_items WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?',
            params + [limit, offset]
        ).fetchall()

        data = []
        for r in rows_result:
            d = dict(r)
            sku_identity = build_sku_identity(conn, d['sku_id'])
            # Get latest transaction
            last_txn = cur.execute(
                "SELECT * FROM inventory_transactions WHERE item_id=? AND tenant_id=? ORDER BY transaction_id DESC LIMIT 1",
                (d['item_id'], tenant_id),
            ).fetchone()
            # Get images
            images = cur.execute(
                "SELECT * FROM item_images WHERE item_id=? ORDER BY is_primary DESC, image_id",
                (d['item_id'],),
            ).fetchall()
            data.append({
                'item_id': d['item_id'],
                'sku_id': d['sku_id'],
                'sku_identity': sku_identity,
                'revision': d.get('revision', 0),
                'certification_number': d['certification_number'],
                'certification_company': d['certification_company'],
                'certification_grade': d['certification_grade'],
                'certification_qualifier': d['certification_qualifier'],
                'item_condition': d['item_condition'],
                'acquired_date': d['acquired_date'],
                'acquired_price': d['acquired_price'],
                'acquired_currency': d['acquired_currency'],
                'acquired_source': d['acquired_source'],
                'acquired_source_reference': d['acquired_source_reference'],
                'location_code': d['location_code'],
                'location_detail': d['location_detail'],
                'status': d['status'],
                'notes': d['notes'],
                'current_value': None,
                'current_value_currency': 'GBP',
                'images': [dict(img) for img in images],
                'last_transaction': dict(last_txn) if last_txn else None,
                'tenant_id': d['tenant_id'],
                'created_by': d['created_by'],
                'created_at': d['created_at'],
                'updated_at': d['updated_at'],
            })

        return {'data': data, 'pagination': {'limit': limit, 'offset': offset, 'count': len(data), 'total': total, 'has_more': offset + len(data) < total}}

    @app.post('/api/v1/inventory/items', response_model=InventoryItemResponse)
    def v1_create_inventory_item(
        body: InventoryItemCreate,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        import uuid
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        # Verify SKU exists
        sku_row = cur.execute("SELECT 1 FROM sellable_skus WHERE sku_id=?", (body.sku_id,)).fetchone()
        if not sku_row:
            raise v1_error(400, 'invalid_sku', f'SKU {body.sku_id} not found in sellable_skus.',
                           {'sku_id': body.sku_id})

        # Verify certification uniqueness if provided
        if body.certification_number and body.certification_company:
            existing = cur.execute(
                "SELECT item_id FROM physical_items WHERE certification_company=? AND certification_number=?",
                (body.certification_company, body.certification_number),
            ).fetchone()
            if existing:
                raise v1_error(409, 'certification_conflict',
                               f'Item with {body.certification_company} #{body.certification_number} already exists.',
                               {'existing_item_id': existing['item_id']})

        item_id = str(uuid.uuid4())
        now = now_utc()

        cur.execute("""
            INSERT INTO physical_items(
                item_id, sku_id, certification_number, certification_company,
                certification_grade, certification_qualifier, item_condition,
                acquired_date, acquired_price, acquired_currency,
                acquired_source, acquired_source_reference,
                location_code, location_detail, status, notes,
                tenant_id, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_id, body.sku_id, body.certification_number, body.certification_company,
            body.certification_grade, body.certification_qualifier, body.item_condition,
            body.acquired_date, body.acquired_price, body.acquired_currency,
            body.acquired_source, body.acquired_source_reference,
            body.location_code, body.location_detail, body.status, body.notes,
            tenant_id, 'api', now, now,
        ))

        # Record acquisition transaction
        record_transaction(
            conn, item_id, 'acquired', tenant_id,
            to_location=body.location_code,
            to_status=body.status,
            price=body.acquired_price,
            currency=body.acquired_currency,
            notes=f'Acquired from {body.acquired_source or "unknown source"}',
            price_observation_id=body.price_observation_id,
            price_snapshot_id=body.price_snapshot_id,
            created_by='api',
        )

        sku_identity = build_sku_identity(conn, body.sku_id)
        return {'data': {
            'item_id': item_id, 'sku_id': body.sku_id,
            'sku_identity': sku_identity,
            'revision': 0,
            'certification_number': body.certification_number,
            'certification_company': body.certification_company,
            'certification_grade': body.certification_grade,
            'certification_qualifier': body.certification_qualifier,
            'item_condition': body.item_condition,
            'acquired_date': body.acquired_date,
            'acquired_price': body.acquired_price,
            'acquired_currency': body.acquired_currency,
            'acquired_source': body.acquired_source,
            'acquired_source_reference': body.acquired_source_reference,
            'location_code': body.location_code,
            'location_detail': body.location_detail,
            'status': body.status,
            'notes': body.notes,
            'current_value': None,
            'current_value_currency': 'GBP',
            'images': [],
            'last_transaction': None,
            'tenant_id': tenant_id,
            'created_by': 'api',
            'created_at': now,
            'updated_at': now,
        }}

    @app.post('/api/v1/inventory/items/{item_id}/listing-draft', response_model=InventoryListingDraftResponseV1, status_code=201)
    def v12_create_inventory_listing_draft(
        item_id: str,
        body: InventoryListingDraftCreateRequestV1,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        '''Create a local listing draft from a physical inventory item.'''
        conn = connect(app.state.db)
        try:
            ensure_inventory_support(conn)
            tenant_id = get_tenant_from_key(_)
            source = resolve_inventory_listing_source(conn, item_id, tenant_id)

            quantity_available = source.get('quantity_available')
            requested_quantity = body.quantity if body.quantity is not None else 1
            if quantity_available is not None and requested_quantity > quantity_available:
                raise v1_error(
                    409,
                    'inventory_quantity_unavailable',
                    'Requested listing draft quantity exceeds available inventory quantity.',
                    {
                        'item_id': item_id,
                        'quantity_requested': requested_quantity,
                        'quantity_available': quantity_available,
                    },
                )

            condition = _clean_listing_text(body.condition) or source.get('condition')
            finish = _clean_listing_text(body.finish) or source.get('finish')
            draft_request = ListingDraftCreateRequestV1(
                platform=body.platform,
                condition=condition,
                finish=finish,
                quantity=requested_quantity,
                include_images=body.include_images,
                include_pricing=body.include_pricing,
                include_commercial=body.include_commercial,
                pricing_strategy=body.pricing_strategy,
                title_style=body.title_style,
                notes=body.notes,
            )
            assistant_response = v12_listing_assistant(source['card_key'], draft_request, _)
            draft = _persist_listing_draft(
                conn,
                assistant_data=assistant_response['data'],
                request_body=draft_request,
            )
            _ensure_inventory_listing_draft_links_table(conn)
            link_created_at = now_utc()
            conn.execute(
                '''
                INSERT INTO inventory_listing_draft_links (
                    id, inventory_item_id, draft_id, card_key, quantity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    _inventory_listing_draft_link_id(),
                    item_id,
                    draft['draft_id'],
                    source['card_key'],
                    requested_quantity,
                    link_created_at,
                ),
            )
            conn.commit()
            return {
                'data': {
                    'draft': draft,
                    'inventory_source': {
                        'item_id': item_id,
                        'card_key': source['card_key'],
                        'quantity_requested': requested_quantity,
                        'quantity_available': quantity_available,
                        'condition': condition,
                        'finish': finish,
                        'linked': True,
                    },
                },
                'metadata': {
                    'api_version': 'v1',
                    'contract': 'v12-inventory-listing-draft-bridge',
                    'generated_at': now_utc(),
                },
            }
        finally:
            conn.close()

    @app.get('/api/v1/inventory/items/{item_id}', response_model=InventoryItemResponse)
    def v1_get_inventory_item(
        item_id: str,
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        row = cur.execute(
            "SELECT * FROM physical_items WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id),
        ).fetchone()
        if not row:
            raise v1_error(404, 'item_not_found', 'Physical item not found.', {'item_id': item_id})

        d = dict(row)
        sku_identity = build_sku_identity(conn, d['sku_id'])
        last_txn = cur.execute(
            "SELECT * FROM inventory_transactions WHERE item_id=? AND tenant_id=? ORDER BY transaction_id DESC LIMIT 1",
            (item_id, tenant_id),
        ).fetchone()
        images = cur.execute(
            "SELECT * FROM item_images WHERE item_id=? ORDER BY is_primary DESC, image_id",
            (item_id,),
        ).fetchall()

        # Try to get current value from price snapshots
        snapshot = cur.execute("""
            SELECT recommended_price FROM price_snapshots
            WHERE sku_id=? AND price_type='raw'
            ORDER BY calculated_at DESC LIMIT 1
        """, (d['sku_id'],)).fetchone()
        current_value = snapshot['recommended_price'] if snapshot else None

        return {'data': {
            'item_id': d['item_id'], 'sku_id': d['sku_id'],
            'sku_identity': sku_identity,
            'revision': d.get('revision', 0),
            'certification_number': d['certification_number'],
            'certification_company': d['certification_company'],
            'certification_grade': d['certification_grade'],
            'certification_qualifier': d['certification_qualifier'],
            'item_condition': d['item_condition'],
            'acquired_date': d['acquired_date'],
            'acquired_price': d['acquired_price'],
            'acquired_currency': d['acquired_currency'],
            'acquired_source': d['acquired_source'],
            'acquired_source_reference': d['acquired_source_reference'],
            'location_code': d['location_code'],
            'location_detail': d['location_detail'],
            'status': d['status'],
            'notes': d['notes'],
            'current_value': current_value,
            'current_value_currency': 'GBP',
            'images': [dict(img) for img in images],
            'last_transaction': dict(last_txn) if last_txn else None,
            'tenant_id': d['tenant_id'],
            'created_by': d['created_by'],
            'created_at': d['created_at'],
            'updated_at': d['updated_at'],
        }}

    @app.put('/api/v1/inventory/items/{item_id}')
    def v1_update_inventory_item(
        item_id: str,
        body: InventoryItemUpdate,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        row = cur.execute(
            "SELECT * FROM physical_items WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id),
        ).fetchone()
        if not row:
            raise v1_error(404, 'item_not_found', 'Physical item not found.', {'item_id': item_id})

        updates = []
        params: list[Any] = []
        if body.item_condition is not None:
            updates.append('item_condition = ?')
            params.append(body.item_condition)
        if body.notes is not None:
            updates.append('notes = ?')
            params.append(body.notes)
        # location_code and location_detail are NOT allowed via PUT — use PATCH /location
        if body.location_code is not None:
            raise v1_error(400, 'field_not_allowed',
                           'Location changes must use PATCH /api/v1/inventory/items/{item_id}/location.',
                           {'field': 'location_code'})
        if body.location_detail is not None:
            raise v1_error(400, 'field_not_allowed',
                           'Location changes must use PATCH /api/v1/inventory/items/{item_id}/location.',
                           {'field': 'location_detail'})

        if not updates:
            return {'data': {'updated': False, 'reason': 'no_fields_to_update'}}

        updates.append('updated_at = ?')
        params.append(now_utc())
        params.extend([item_id, tenant_id])

        cur.execute(
            f'UPDATE physical_items SET {", ".join(updates)} WHERE item_id=? AND tenant_id=?',
            params,
        )
        conn.commit()
        return {'data': {'updated': True, 'item_id': item_id}}

    @app.patch('/api/v1/inventory/items/{item_id}/status')
    def v1_change_item_status(
        item_id: str,
        body: InventoryStatusChange,
        request: Request,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        # Read If-Match header for revision-based concurrency
        if_match = request.headers.get('If-Match', '')
        expected_revision = None
        try:
            expected_revision = int(if_match) if if_match else None
        except (ValueError, TypeError):
            pass

        row = cur.execute(
            "SELECT status, location_code, revision FROM physical_items WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id),
        ).fetchone()
        if not row:
            raise v1_error(404, 'item_not_found', 'Physical item not found.', {'item_id': item_id})

        old_status = row['status']
        old_revision = row['revision']

        # Validate transition
        error = _validate_status_transition(old_status, body.status, body.status)
        if error:
            raise v1_error(400, 'invalid_transition', error,
                           {'current_status': old_status, 'target_status': body.status})

        # If client provided revision, require it matches
        if expected_revision is not None and expected_revision != old_revision:
            raise v1_error(409, 'conflict',
                           f'Item was modified. Current revision: {old_revision}, expected: {expected_revision}',
                           {'current_revision': old_revision, 'expected_revision': expected_revision})

        # Use conditional UPDATE for atomicity (avoids explicit BEGIN IMMEDIATE lock)
        cur.execute(
            'UPDATE physical_items SET status=?, updated_at=?, revision=revision+1 WHERE item_id=? AND tenant_id=? AND revision=?',
            (body.status, now_utc(), item_id, tenant_id, old_revision),
        )
        if cur.rowcount == 0:
            # Re-read current revision
            rev_row = cur.execute(
                "SELECT revision FROM physical_items WHERE item_id=? AND tenant_id=?",
                (item_id, tenant_id)
            ).fetchone()
            current_rev = rev_row['revision'] if rev_row else old_revision
            raise v1_error(409, 'conflict',
                           f'Conflict - item was modified',
                           {'current_revision': current_rev})

        record_transaction(
            conn, item_id, _get_transaction_type(body.status, old_status), tenant_id,
            from_status=old_status,
            to_status=body.status,
            to_location=row['location_code'],
            price=body.price,
            currency=body.currency,
            counterparty=body.counterparty,
            reference=body.reference,
            notes=body.notes or f'Status changed: {old_status} → {body.status}',
            price_observation_id=body.price_observation_id,
            price_snapshot_id=body.price_snapshot_id,
            created_by='api',
        )
        # Re-read new revision
        new_row = cur.execute(
            "SELECT revision FROM physical_items WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id)
        ).fetchone()
        new_revision = new_row['revision'] if new_row else old_revision + 1

        return {'data': {
            'item_id': item_id, 'old_status': old_status,
            'new_status': body.status,
            'transaction_created': True,
            'revision': new_row['revision'] if new_row else old_revision + 1,
        }}

    @app.patch('/api/v1/inventory/items/{item_id}/location')
    def v1_change_item_location(
        item_id: str,
        body: InventoryLocationChange,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        row = cur.execute(
            "SELECT location_code, status FROM physical_items WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id),
        ).fetchone()
        if not row:
            raise v1_error(404, 'item_not_found', 'Physical item not found.', {'item_id': item_id})

        old_location = row['location_code']
        cur.execute(
            'UPDATE physical_items SET location_code=?, location_detail=?, updated_at=? WHERE item_id=? AND tenant_id=?',
            (body.location_code, body.location_detail, now_utc(), item_id, tenant_id),
        )

        record_transaction(
            conn, item_id, 'moved', tenant_id,
            from_location=old_location,
            to_location=body.location_code,
            to_status=row['status'],
            notes=body.notes or f'Moved from {old_location} to {body.location_code}',
            created_by='api',
        )

        return {'data': {
            'item_id': item_id, 'old_location': old_location,
            'new_location': body.location_code,
            'transaction_created': True,
        }}

    @app.get('/api/v1/inventory/items/{item_id}/transactions', response_model=TransactionListResponse)
    def v1_get_item_transactions(
        item_id: str,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        total = int(cur.execute(
            "SELECT COUNT(*) FROM inventory_transactions WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id),
        ).fetchone()[0])

        rows_result = cur.execute(
            "SELECT * FROM inventory_transactions WHERE item_id=? AND tenant_id=? ORDER BY transaction_id DESC LIMIT ? OFFSET ?",
            (item_id, tenant_id, limit, offset),
        ).fetchall()

        data = [dict(r) for r in rows_result]
        return {'data': data, 'pagination': {'limit': limit, 'offset': offset, 'count': len(data), 'total': total, 'has_more': offset + len(data) < total}}

    @app.post('/api/v1/inventory/items/{item_id}/transactions')
    def v1_add_manual_transaction(
        item_id: str,
        body: InventoryTransactionCreate,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        row = cur.execute(
            "SELECT status, location_code FROM physical_items WHERE item_id=? AND tenant_id=?",
            (item_id, tenant_id),
        ).fetchone()
        if not row:
            raise v1_error(404, 'item_not_found', 'Physical item not found.', {'item_id': item_id})

        txn_id = record_transaction(
            conn, item_id, body.transaction_type, tenant_id,
            quantity=body.quantity,
            to_location=body.to_location,
            to_status=body.to_status,
            price=body.price,
            currency=body.currency,
            counterparty=body.counterparty,
            reference=body.reference,
            notes=body.notes,
            price_observation_id=body.price_observation_id,
            price_snapshot_id=body.price_snapshot_id,
            created_by='api',
        )

        # Also update physical item if to_status or to_location are provided
        if body.to_status:
            cur.execute(
                'UPDATE physical_items SET status=?, updated_at=? WHERE item_id=? AND tenant_id=?',
                (body.to_status, now_utc(), item_id, tenant_id),
            )
        if body.to_location:
            cur.execute(
                'UPDATE physical_items SET location_code=?, updated_at=? WHERE item_id=? AND tenant_id=?',
                (body.to_location, now_utc(), item_id, tenant_id),
            )
        conn.commit()

        return {'data': {'transaction_id': txn_id, 'item_id': item_id, 'transaction_type': body.transaction_type, 'created': True}}

    @app.get('/api/v1/inventory/transactions', response_model=TransactionListResponse)
    def v1_list_transactions(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        transaction_type: str | None = Query(None, description='Filter by transaction type'),
        item_id: str | None = Query(None, description='Filter by item ID'),
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        where = ['tenant_id = ?']
        params: list[Any] = [tenant_id]
        if transaction_type:
            where.append('transaction_type = ?')
            params.append(transaction_type)
        if item_id:
            where.append('item_id = ?')
            params.append(item_id)

        where_sql = ' AND '.join(where)
        total = int(cur.execute(
            f'SELECT COUNT(*) FROM inventory_transactions WHERE {where_sql}', params
        ).fetchone()[0])

        rows_result = cur.execute(
            f'SELECT * FROM inventory_transactions WHERE {where_sql} ORDER BY transaction_id DESC LIMIT ? OFFSET ?',
            params + [limit, offset],
        ).fetchall()

        data = [dict(r) for r in rows_result]
        return {'data': data, 'pagination': {'limit': limit, 'offset': offset, 'count': len(data), 'total': total, 'has_more': offset + len(data) < total}}

    @app.get('/api/v1/inventory/locations')
    def v1_list_locations(
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant_id = get_tenant_from_key(_)

        rows_result = cur.execute("""
            SELECT location_code, COUNT(*) as item_count,
                   GROUP_CONCAT(DISTINCT status) as status_list
            FROM physical_items
            WHERE tenant_id=?
            GROUP BY location_code
            ORDER BY item_count DESC
        """, (tenant_id,)).fetchall()

        locations = []
        for r in rows_result:
            statuses = r['status_list'].split(',') if r['status_list'] else []
            status_summary: dict[str, int] = {}
            for s in statuses:
                s = s.strip()
                if s:
                    status_summary[s] = status_summary.get(s, 0) + 1
            locations.append({
                'location_code': r['location_code'],
                'item_count': r['item_count'],
                'status_summary': status_summary,
            })

        return {'data': locations}

    @app.get('/api/v1/inventory/valuation', response_model=InventoryValuationResponse)
    def v1_inventory_valuation(
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        tenant_id = get_tenant_from_key(_)
        valuation = get_current_valuation(conn, tenant_id)
        return {'data': valuation}

    # ── Tenant Endpoints ─────────────────────────────────────────────
    # Admin tenant management under /api/v1/admin/tenants
    
    @app.post('/api/v1/admin/tenants', response_model=TenantDetailResponse)
    def v1_admin_create_tenant(
        body: TenantCreate,
        request: Request,
        _: dict[str, Any] = Depends(require_scope('admin:all')),
    ) -> dict[str, Any]:
        """Create a tenant atomically with owner membership.
        
        Request body may include owner info:
        {
          "tenant_name": "...",
          "tenant_slug": "...",
          "is_active": true,
          "owner": {
            "username": "...",
            "email": "..."
          }
        }
        """
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        # Check slug uniqueness
        existing = cur.execute("SELECT 1 FROM tenants WHERE tenant_slug=?", (body.tenant_slug,)).fetchone()
        if existing:
            raise v1_error(409, 'tenant_slug_conflict',
                           f'Tenant slug "{body.tenant_slug}" already exists.',
                           {'tenant_slug': body.tenant_slug})
        cur.execute('BEGIN IMMEDIATE')
        try:
            cur.execute(
                'INSERT INTO tenants(tenant_name, tenant_slug, is_active) VALUES (?, ?, ?)',
                (body.tenant_name, body.tenant_slug, 1 if body.is_active else 0),
            )
            tenant_id = cur.lastrowid
            
            # Resolve or create owner user
            owner_username = getattr(body, 'owner_username', None) or 'admin'
            owner_email = getattr(body, 'owner_email', None)
            user_row = cur.execute(
                "SELECT user_id FROM users WHERE username=? LIMIT 1",
                (owner_username,)
            ).fetchone()
            if not user_row:
                cur.execute(
                    "INSERT INTO users(tenant_id, username, email, role, is_active) "
                    "VALUES (?, ?, ?, 'admin', 1)",
                    (tenant_id, owner_username, owner_email)
                )
                user_id = cur.lastrowid
            else:
                user_id = user_row['user_id']
            
            # Create admin membership
            cur.execute(
                "INSERT INTO tenant_memberships(user_id, tenant_id, role) VALUES (?, ?, 'admin')",
                (user_id, tenant_id)
            )
            
            # Write admin audit log
            cur.execute(
                "INSERT INTO admin_audit_log(principal_key_id, action, target_tenant_id, target_resource, result) "
                "VALUES (?, 'create_tenant', ?, ?, 'created')",
                (request.state.api_key_id, tenant_id, f'tenant:{body.tenant_slug}')
            )
            
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        
        row = cur.execute('SELECT * FROM tenants WHERE tenant_id=?', (tenant_id,)).fetchone()
        return {'data': dict(row)}
    
    @app.get('/api/v1/admin/tenants', response_model=TenantListResponse)
    def v1_admin_list_tenants(
        _: dict[str, Any] = Depends(require_scope('admin:all')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        rows_result = cur.execute('SELECT * FROM tenants ORDER BY tenant_id').fetchall()
        return {'data': [dict(r) for r in rows_result]}
    
    @app.get('/api/v1/admin/tenants/{slug}', response_model=TenantDetailResponse)
    def v1_admin_get_tenant(
        slug: str,
        _: dict[str, Any] = Depends(require_scope('admin:all', 'admin:tenant')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        row = cur.execute('SELECT * FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not row:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        return {'data': dict(row)}
    
    @app.get('/api/v1/admin/tenants/{slug}/keys')
    def v1_admin_list_tenant_keys(
        slug: str,
        _: dict[str, Any] = Depends(require_scope('admin:all', 'admin:tenant')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant = cur.execute('SELECT tenant_id FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not tenant:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        # Find keys through memberships
        rows_result = cur.execute("""
            SELECT dk.id, dk.label, dk.scopes, dk.is_active, dk.created_at, dk.last_used_at
            FROM developer_api_keys dk
            JOIN tenant_memberships tm ON dk.membership_id = tm.membership_id
            WHERE tm.tenant_id = ?
            ORDER BY dk.id
        """, (tenant['tenant_id'],)).fetchall()
        return {'data': [dict(r) for r in rows_result]}
    
    @app.post('/api/v1/admin/tenants/{slug}/keys')
    def v1_admin_create_tenant_key(
        slug: str,
        body: ApiKeyCreateV1,
        request: Request,
        _: dict[str, Any] = Depends(require_scope('admin:all', 'admin:tenant')),
    ) -> dict[str, Any]:
        import secrets, hashlib
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        tenant = cur.execute('SELECT tenant_id FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not tenant:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        # Find first admin membership for this tenant
        membership = cur.execute("""
            SELECT membership_id FROM tenant_memberships
            WHERE tenant_id=? AND role IN ('admin', 'manager')
            ORDER BY membership_id LIMIT 1
        """, (tenant['tenant_id'],)).fetchone()
        if not membership:
            raise v1_error(400, 'no_admin_membership',
                           f'No admin membership found for tenant "{slug}".',
                           {'tenant_slug': slug})
        raw_key = f'sr-{secrets.token_hex(20)}'
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        cur.execute(
            'INSERT INTO developer_api_keys(key_hash, label, scopes, monthly_quota, is_active, membership_id) '
            'VALUES (?, ?, ?, ?, 1, ?)',
            (key_hash, body.label or f'API key for {slug}',
             json.dumps(body.scopes), body.monthly_quota, membership['membership_id'])
        )
        conn.commit()
        return {'data': {'id': cur.lastrowid, 'key': raw_key, 'label': body.label,
                         'scopes': body.scopes, 'is_active': True}}
    
    @app.post('/api/v1/admin/keys/{key_id}/deactivate')
    def v1_admin_deactivate_key(
        key_id: int,
        request: Request,
        _: dict[str, Any] = Depends(require_scope('admin:all', 'admin:tenant')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        ensure_inventory_support(conn)
        cur = conn.cursor()
        cur.execute('UPDATE developer_api_keys SET is_active=0 WHERE id=?', (key_id,))
        if cur.rowcount == 0:
            raise v1_error(404, 'key_not_found', 'API key not found.', {'key_id': key_id})
        # Write admin audit log
        cur.execute(
            "INSERT INTO admin_audit_log(principal_key_id, action, target_resource, result) "
            "VALUES (?, 'deactivate_key', ?, 'deactivated')",
            (request.state.api_key_id, f'key:{key_id}')
        )
        conn.commit()
        return {'data': {'deactivated': True, 'key_id': key_id}}
    
    # Legacy tenant endpoints (keep for backward compatibility)
    
    @app.get('/api/v1/tenants', response_model=TenantListResponse)
    def v1_list_tenants(
        _: dict[str, Any] = Depends(require_scope('admin:tenant', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        rows_result = cur.execute('SELECT * FROM tenants ORDER BY tenant_id').fetchall()
        return {'data': [dict(r) for r in rows_result]}

    @app.post('/api/v1/tenants', response_model=TenantDetailResponse)
    def v1_create_tenant(
        body: TenantCreate,
        _: dict[str, Any] = Depends(require_scope('admin:tenant', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        # Check slug uniqueness
        existing = cur.execute("SELECT 1 FROM tenants WHERE tenant_slug=?", (body.tenant_slug,)).fetchone()
        if existing:
            raise v1_error(409, 'tenant_slug_conflict',
                           f'Tenant slug "{body.tenant_slug}" already exists.',
                           {'tenant_slug': body.tenant_slug})
        cur.execute(
            'INSERT INTO tenants(tenant_name, tenant_slug, is_active) VALUES (?, ?, ?)',
            (body.tenant_name, body.tenant_slug, 1 if body.is_active else 0),
        )
        conn.commit()
        row = cur.execute('SELECT * FROM tenants WHERE tenant_id=?', (cur.lastrowid,)).fetchone()
        return {'data': dict(row)}

    @app.get('/api/v1/tenants/{slug}', response_model=TenantDetailResponse)
    def v1_get_tenant(
        slug: str,
        _: dict[str, Any] = Depends(require_scope('admin:tenant', 'admin:all', 'admin', 'read:inventory')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        row = cur.execute('SELECT * FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not row:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        return {'data': dict(row)}

    @app.get('/api/v1/tenants/{slug}/users', response_model=UserListResponse)
    def v1_list_tenant_users(
        slug: str,
        _: dict[str, Any] = Depends(require_scope('admin:tenant', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        tenant = cur.execute('SELECT tenant_id FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not tenant:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        rows_result = cur.execute(
            'SELECT * FROM users WHERE tenant_id=? ORDER BY user_id', (tenant['tenant_id'],)
        ).fetchall()
        return {'data': [dict(r) for r in rows_result]}

    @app.post('/api/v1/tenants/{slug}/users', response_model=UserListResponse)
    def v1_add_tenant_user(
        slug: str,
        body: UserCreate,
        _: dict[str, Any] = Depends(require_scope('admin:tenant', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        import hashlib, secrets
        conn = connect(app.state.db)
        cur = conn.cursor()
        tenant = cur.execute('SELECT tenant_id FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not tenant:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        tenant_id = tenant['tenant_id']

        # Check username uniqueness within tenant
        existing = cur.execute(
            "SELECT 1 FROM users WHERE tenant_id=? AND username=?",
            (tenant_id, body.username),
        ).fetchone()
        if existing:
            raise v1_error(409, 'username_conflict',
                           f'Username "{body.username}" already exists in this tenant.',
                           {'username': body.username, 'tenant_slug': slug})

        hashed_pw = hashlib.sha256(body.password.encode()).hexdigest() if body.password else ''
        cur.execute(
            'INSERT INTO users(tenant_id, username, email, hashed_password, role, is_active) VALUES (?, ?, ?, ?, ?, ?)',
            (tenant_id, body.username, body.email, hashed_pw, body.role, 1 if body.is_active else 0),
        )
        conn.commit()
        rows_result = cur.execute(
            'SELECT * FROM users WHERE tenant_id=? ORDER BY user_id', (tenant_id,)
        ).fetchall()
        return {'data': [dict(r) for r in rows_result]}

    @app.delete('/api/v1/tenants/{slug}/users/{user_id}')
    def v1_remove_tenant_user(
        slug: str,
        user_id: int,
        _: dict[str, Any] = Depends(require_scope('admin:tenant', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        tenant = cur.execute('SELECT tenant_id FROM tenants WHERE tenant_slug=?', (slug,)).fetchone()
        if not tenant:
            raise v1_error(404, 'tenant_not_found', 'Tenant not found.', {'slug': slug})
        cur.execute(
            'DELETE FROM users WHERE user_id=? AND tenant_id=?',
            (user_id, tenant['tenant_id']),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise v1_error(404, 'user_not_found', 'User not found.', {'user_id': user_id, 'tenant_slug': slug})
        return {'data': {'deleted': True, 'user_id': user_id, 'tenant_slug': slug}}

    # ── v9.1 Image Gateway ───────────────────────────────────────────

    @app.get('/api/v1/images/assets/{image_id}/content')
    def v1_image_content(
        image_id: int,
        size: str = Query('medium', pattern='^(thumbnail|small|medium|large)$'),
        token: str | None = Query(None, description='Signed URL token (alternative to API key)'),
        request: Request = None,
    ) -> Response:
        """Deliver a card image through the controlled gateway."""
        # Auth info is stored on request.state by require_v1_api_key
        api_key_id = getattr(request.state, 'api_key_id', None)
        api_scopes = getattr(request.state, 'api_scopes', [])

        conn = connect(app.state.db)
        cur = conn.cursor()

        # Verify access
        access_identity = None
        if token:
            if len(token.split(':')) < 5:
                raise v1_error(403, 'invalid_token', 'Invalid or expired signed URL token.', {})
            secret = _get_signed_url_secret(settings.signed_url_secret)
            verified = _verify_signed_url(token, secret)
            if not verified:
                raise v1_error(403, 'invalid_token', 'Invalid or expired signed URL token.', {})
            if verified.get('image_id') != image_id or verified.get('size') != size:
                raise v1_error(403, 'invalid_token', 'Signed URL token does not match requested image.', {})
            access_identity = f'signed:{verified["image_id"]}'
        else:
            if 'images:read' not in api_scopes:
                _record_delivery_log(image_id=image_id, card_key=None,
                                     api_key_id=api_key_id,
                                     requested_size=size, policy_decision='insufficient_scope',
                                     response_status=403, response_outcome='auth_failed')
                raise v1_error(403, 'insufficient_scope', 'Requires images:read scope.', {})
            access_identity = f'key:{api_key_id}'

        # Rate limit
        if not _IMAGE_RATE_LIMITER.check(f'img:{access_identity}'):
            _record_delivery_log(image_id=image_id, card_key=None,
                                 api_key_id=api_key_id,
                                 requested_size=size, policy_decision='rate_limited',
                                 response_status=429, response_outcome='rate_limited',
                                 request_id=getattr(request.state, 'request_id', None))
            raise v1_error(429, 'rate_limited', 'Image request rate limit exceeded. Try again shortly.', {})

        # Resolve image from DB — never from client-supplied paths
        image_root = _image_root_dir(settings.image_root, fallback_root=settings.db.parent)
        if not image_root or not image_root.exists():
            _record_delivery_log(image_id=image_id, card_key=None,
                                 api_key_id=api_key_id,
                                 policy_decision='no_image_root', response_status=500,
                                 response_outcome='server_error')
            raise v1_error(500, 'image_root_missing', 'Image storage not available.', {})

        # Resolve image identity from the real database rowid
        card_key = None
        local_path = None
        source_type = None
        language_code = None
        set_id = None

        if image_id > 0:
            # Deterministic lookup via stable image_id (rowid)
            asset = resolve_image_asset(conn, image_id)
            if asset:
                safe = _safe_image_path(asset['image_path'], image_root)
                if safe:
                    local_path = safe
                    card_key = asset['card_key']
                    source_type = asset['source_type']
                    language_code = asset['language_code']
                    set_id = asset['set_id']

        if not local_path:
            # Fallback: resolve by card_key query param (compatibility)
            card_key_param = request.query_params.get('card_key', '')
            if card_key_param:
                info = resolve_preferred_card_image(conn, card_key_param)
                if info:
                    card_key = info['card_key']
                    safe = _safe_image_path(info['image_path'], image_root)
                    if safe:
                        local_path = safe
                        source_type = info.get('source_type')
                        language_code = info.get('language_code')
                        set_id = info.get('set_id')



        if not local_path:
            _record_delivery_log(image_id=image_id, card_key=card_key,
                                 api_key_id=api_key_id,
                                 requested_size=size, policy_decision='not_found',
                                 db_path=str(settings.db),
                                 response_status=404, response_outcome='no_image')
            raise v1_error(404, 'image_not_found', 'No image found for the given identifier.', {'image_id': image_id})

        # Policy check
        policy = _eval_image_policy(conn, card_key or '', set_id, language_code or '', source_type, image_id)
        if not policy['allowed']:
            _record_delivery_log(image_id=image_id, card_key=card_key,
                                 api_key_id=api_key_id,
                                 requested_size=size, policy_decision=policy['matched_scope'] or 'blocked',
                                 db_path=str(settings.db),
                                 response_status=403, response_outcome='policy_blocked',
                                 request_id=getattr(request.state, 'request_id', None))
            raise v1_error(403, 'image_disabled',
                           'Image delivery blocked by policy.',
                           {'reason': policy['reason'], 'scope': policy['matched_scope']})

        # Generate or retrieve derivative
        deriv_path = _derive_image(local_path, size, image_root)
        if not deriv_path or not deriv_path.exists():
            deriv_path = local_path

        mime_type = 'image/webp' if deriv_path.suffix.lower() in ('.webp',) else 'image/jpeg'
        file_bytes = deriv_path.stat().st_size
        file_mod = dt.datetime.fromtimestamp(deriv_path.stat().st_mtime, tz=dt.UTC)

        etag = hashlib.md5(open(deriv_path, 'rb').read()).hexdigest()[:16]

        # Persistent quota check (per-hour/per-day limits)
        # NOTE: executed AFTER bytes are ready, so failed resolutions/policies don't consume quota
        identity_type = 'api_key' if api_key_id else 'signed_url'
        qid = quota_identity_for_access(access_identity, identity_type)
        quota = _check_and_increment_quota(conn, qid, identity_type,
                                           hourly_limit=settings.image_hourly_delivery_limit,
                                           daily_limit=settings.image_daily_delivery_limit)
        if not quota['allowed']:
            _record_delivery_log(image_id=image_id, card_key=None,
                                 api_key_id=api_key_id,
                                 requested_size=size, policy_decision=quota['reason'],
                                 response_status=429, response_outcome='quota_exceeded',
                                 request_id=getattr(request.state, 'request_id', None),
                                 db_path=str(settings.db))
            raise v1_error(429, quota['reason'],
                           f'Image delivery quota exceeded: {quota["reason"].replace("_", " ")}. '
                           f'Hourly: {quota["hourly_count"]}/{quota["hourly_limit"]}, '
                           f'Daily: {quota["daily_count"]}/{quota["daily_limit"]}.', {})

        _record_delivery_log(image_id=image_id, card_key=card_key,
                             api_key_id=api_key_id,
                             requested_size=size, policy_decision='delivered',
                             response_status=200, response_outcome='ok',
                             request_id=getattr(request.state, 'request_id', None),
                             db_path=str(settings.db))

        return Response(
            content=open(deriv_path, 'rb').read(),
            media_type=mime_type,
            headers={
                'Content-Type': mime_type,
                'Content-Length': str(file_bytes),
                'Content-Disposition': 'inline',
                'ETag': f'"{etag}"',
                'Last-Modified': file_mod.strftime('%a, %d %b %Y %H:%M:%S GMT'),
                'Cache-Control': 'public, max-age=604800, immutable',
                'X-Content-Type-Options': 'nosniff',
            },
        )

    # ── Compatibility route: /cards/{card_key}/content ────────────────

    @app.get('/api/v1/images/card/{card_key:path}/content')
    def v1_card_image_content(
        card_key: str,
        size: str = Query('medium', pattern='^(thumbnail|small|medium|large)$'),
        token: str | None = Query(None, description='Signed URL token (alternative to API key)'),
        request: Request = None,
    ) -> Response:
        """Controlled card image delivery by card_key — same gateway semantics."""
        # Auth info from request.state
        api_key_id = getattr(request.state, 'api_key_id', None)
        api_scopes = getattr(request.state, 'api_scopes', [])

        conn = connect(app.state.db)
        cur = conn.cursor()

        # Verify access
        access_identity = None
        if token:
            if len(token.split(':')) < 5:
                raise v1_error(403, 'invalid_token', 'Invalid or expired signed URL token.', {})
            secret = _get_signed_url_secret(settings.signed_url_secret)
            verified = _verify_signed_url(token, secret)
            if not verified:
                raise v1_error(403, 'invalid_token', 'Invalid or expired signed URL token.', {})
            if verified.get('size') != size:
                raise v1_error(403, 'invalid_token', 'Signed URL token does not match requested size.', {})
            access_identity = f'signed:{verified["image_id"]}'
        else:
            if 'images:read' not in api_scopes:
                raise v1_error(403, 'insufficient_scope', 'Requires images:read scope.', {})
            access_identity = f'key:{api_key_id}'

        # Resolve card image
        image_root = _image_root_dir(settings.image_root, fallback_root=settings.db.parent)
        if not image_root or not image_root.exists():
            raise v1_error(500, 'image_root_missing', 'Image storage not available.', {})
        info = resolve_preferred_card_image(conn, card_key)
        if not info:
            raise v1_error(404, 'image_not_found', 'No image found for card_key.', {'card_key': card_key})
        local_path = _safe_image_path(info['image_path'], image_root)
        if not local_path:
            raise v1_error(404, 'image_not_found', 'Image file not found.', {'card_key': card_key})

        # Policy check
        resolved_image_id = int(info.get('image_id') or 0)
        policy = _eval_image_policy(conn, card_key, info.get('set_id'), info.get('language_code', ''), info.get('source_type'), resolved_image_id)
        if not policy['allowed']:
            _record_delivery_log(image_id=0, card_key=card_key, api_key_id=api_key_id,
                                 requested_size=size, policy_decision=policy['matched_scope'] or 'blocked',
                                 db_path=str(settings.db),
                                 response_status=403, response_outcome='policy_blocked')
            raise v1_error(403, 'image_disabled', 'Image delivery blocked by policy.',
                           {'reason': policy['reason'], 'scope': policy['matched_scope']})

        # Derivative
        deriv_path = _derive_image(local_path, size, image_root)
        if not deriv_path or not deriv_path.exists():
            deriv_path = local_path

        mime_type = 'image/webp' if deriv_path.suffix.lower() in ('.webp',) else 'image/jpeg'
        file_bytes = deriv_path.stat().st_size

        # Quota check (after bytes ready — failed policy/resolution doesn't consume)
        identity_type = 'api_key' if api_key_id else 'signed_url'
        qid = quota_identity_for_access(access_identity, identity_type)
        quota = _check_and_increment_quota(conn, qid, identity_type,
                                           hourly_limit=settings.image_hourly_delivery_limit,
                                           daily_limit=settings.image_daily_delivery_limit)
        if not quota['allowed']:
            _record_delivery_log(image_id=0, card_key=card_key,
                                 api_key_id=api_key_id,
                                 requested_size=size, policy_decision=quota['reason'],
                                 response_status=429, response_outcome='quota_exceeded',
                                 db_path=str(settings.db))
            raise v1_error(429, quota['reason'], f'Image delivery quota exceeded.', {})

        _record_delivery_log(image_id=0, card_key=card_key, api_key_id=api_key_id,
                             requested_size=size, policy_decision='delivered',
                             db_path=str(settings.db),
                             response_status=200, response_outcome='ok')

        return Response(content=open(deriv_path, 'rb').read(), media_type=mime_type,
                        headers={'Content-Type': mime_type, 'Content-Length': str(file_bytes),
                                 'Content-Disposition': 'inline', 'X-Content-Type-Options': 'nosniff'})

# ── Signed URL endpoint ──────────────────────────────────────────

    @app.post('/api/v1/images/assets/signed-url', response_model=SignedUrlResponseArticle)
    def v1_image_signed_url(
        image_id: int = Query(..., description='Image ID'),
        size: str = Query('medium', pattern='^(thumbnail|small|medium|large)$'),
        expires_in: int = Query(3600, ge=300, le=86400, description='Seconds until expiry (300-86400)'),
        _auth: dict[str, Any] = Depends(require_scope('images:read', 'cards:read')),
    ) -> dict[str, Any]:
        """Generate a signed URL for browser/mobile image access.

        Signed URLs are still subject to policy evaluation at delivery time.
        """
        # Validate image exists before signing
        conn = connect(app.state.db)
        asset = resolve_image_asset(conn, image_id)
        if not asset:
            raise v1_error(404, 'image_not_found', 'No image found for the given image_id.', {'image_id': image_id})
        secret = _get_signed_url_secret(settings.signed_url_secret)
        token, expires_at = _generate_signed_url(image_id, size, secret, expires_in=expires_in, api_key_id=getattr(request.state, 'api_key_id', None))
        url = f'/api/v1/images/assets/{image_id}/content?size={size}&token={token}'
        return {
            'data': {
                'url': url,
                'expires_at': expires_at,
                'image_id': image_id,
                'size': size,
            }
        }

    # ── Admin: image delivery policies ────────────────────────────────

    @app.get('/api/v1/admin/images/policies', response_model=DeliveryPolicyListResponse)
    def v1_admin_list_image_policies(
        _auth: dict[str, Any] = Depends(require_scope('images:admin', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        rows_result = conn.execute(
            'SELECT * FROM image_delivery_policies ORDER BY scope_type, scope_value'
        ).fetchall()
        return {'data': [dict(r) for r in rows_result]}

    @app.post('/api/v1/admin/images/policies', response_model=DeliveryPolicyArticleResponse)
    def v1_admin_create_image_policy(
        body: DeliveryPolicyCreate,
        request: Request,
        _auth: dict[str, Any] = Depends(require_scope('images:admin', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        now_val = now_utc()
        try:
            cur.execute(
                "INSERT INTO image_delivery_policies(scope_type, scope_value, external_display_enabled, reason, attribution_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (body.scope_type, body.scope_value, 1 if body.external_display_enabled else 0,
                 body.reason, body.attribution_text, now_val, now_val)
            )
            policy_id = cur.lastrowid
            # Audit
            cur.execute(
                "INSERT INTO admin_audit_log(action, target_resource, details_json, created_at) VALUES (?, ?, ?, ?)",
                ('create_policy', f'image_delivery_policies/{policy_id}',
                 json.dumps({'scope_type': body.scope_type, 'scope_value': body.scope_value,
                             'external_display_enabled': body.external_display_enabled}),
                 now_val))
            conn.commit()
            row = cur.execute('SELECT * FROM image_delivery_policies WHERE policy_id=?', (policy_id,)).fetchone()
            return {'data': dict(row)}
        except sqlite3.IntegrityError as e:
            raise v1_error(409, 'policy_conflict', f'Policy already exists: {e}', {})

    @app.put('/api/v1/admin/images/policies/global')
    def v1_admin_set_global_policy(
        body: DeliveryPolicyUpdate,
        request: Request,
        _auth: dict[str, Any] = Depends(require_scope('admin:all')),
    ) -> dict[str, Any]:
        """Set the global emergency image switch. Requires strongest admin scope."""
        conn = connect(app.state.db)
        cur = conn.cursor()
        now_val = now_utc()
        cur.execute(
            "UPDATE image_delivery_policies SET external_display_enabled=?, reason=?, updated_at=? WHERE scope_type='global' AND scope_value='global'",
            (1 if body.external_display_enabled else 0, body.reason, now_val)
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO image_delivery_policies(scope_type, scope_value, external_display_enabled, reason, attribution_text, created_at, updated_at) VALUES ('global', 'global', ?, ?, NULL, ?, ?)",
                (1 if body.external_display_enabled else 0, body.reason, now_val, now_val)
            )
        cur.execute(
            "INSERT INTO admin_audit_log(action, target_resource, details_json, created_at) VALUES (?, ?, ?, ?)",
            ('set_global_policy', 'global',
             json.dumps({'external_display_enabled': body.external_display_enabled, 'reason': body.reason}),
             now_val))
        conn.commit()
        row = cur.execute("SELECT * FROM image_delivery_policies WHERE scope_type='global' AND scope_value='global'").fetchone()
        return {'data': dict(row)}

    # ── Admin: takedown cases ─────────────────────────────────────────

    @app.get('/api/v1/admin/images/takedown/cases', response_model=TakedownCaseListResponse)
    def v1_admin_list_takedown_cases(
        include_events: bool = Query(False, description='Include events per case'),
        _auth: dict[str, Any] = Depends(require_scope('images:admin', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        rows_result = conn.execute(
            'SELECT * FROM takedown_cases ORDER BY opened_at DESC'
        ).fetchall()
        cases = []
        for r in rows_result:
            case = dict(r)
            if include_events:
                events = conn.execute(
                    'SELECT * FROM takedown_events WHERE case_id=? ORDER BY created_at', (r['case_id'],)
                ).fetchall()
                case['events'] = [dict(e) for e in events]
            cases.append(case)
        return {'data': cases}

    @app.post('/api/v1/admin/images/takedown/cases')
    def v1_admin_create_takedown_case(
        body: TakedownCaseCreate,
        request: Request,
        _auth: dict[str, Any] = Depends(require_scope('images:admin', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            now_val = now_utc()

            # Duplicate guard: reject if open/under_review case exists for same scope
            existing = cur.execute(
                "SELECT case_id, status FROM takedown_cases "
                "WHERE scope_type=? AND scope_value=? AND status IN ('open', 'under_review') "
                "LIMIT 1",
                (body.scope_type, body.scope_value)
            ).fetchone()
            if existing:
                conn.rollback()
                raise v1_error(409, 'duplicate_takedown',
                               f'An active takedown case already exists for this scope.',
                               {'existing_case_id': existing['case_id'], 'status': existing['status']})

            # Capture previous policy state
            prev_row = cur.execute(
                "SELECT external_display_enabled, reason, attribution_text "
                "FROM image_delivery_policies WHERE scope_type=? AND scope_value=?",
                (body.scope_type, body.scope_value)
            ).fetchone()
            prev_policy_state = None
            if prev_row:
                prev_policy_state = json.dumps({
                    'external_display_enabled': int(prev_row[0]),
                    'reason': prev_row[1],
                    'attribution_text': prev_row[2],
                })

            # Create case
            cur.execute(
                'INSERT INTO takedown_cases'
                '(requester_identity, requester_contact, rights_description, status, opened_at,'
                ' scope_type, scope_value, previous_policy_state) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (body.requester_identity, body.requester_contact,
                 body.rights_description, 'open', now_val,
                 body.scope_type, body.scope_value, prev_policy_state)
            )
            case_id = cur.lastrowid

            # Apply disabled policy
            cur.execute(
                "INSERT OR REPLACE INTO image_delivery_policies"
                "(scope_type, scope_value, external_display_enabled, reason, created_at, updated_at) "
                "VALUES (?, ?, 0, ?, ?, ?)",
                (body.scope_type, body.scope_value,
                 f'Takedown case #{case_id}: {body.rights_description or body.requester_identity}',
                 now_val, now_val)
            )

            # Append opening event
            cur.execute(
                'INSERT INTO takedown_events(case_id, action_type, scope_type, scope_value, reason, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (case_id, 'case_opened', body.scope_type, body.scope_value,
                 body.rights_description or 'Takedown request', now_val)
            )

            # Admin audit
            cur.execute(
                "INSERT INTO admin_audit_log(action, target_resource, details_json, created_at) VALUES (?, ?, ?, ?)",
                ('create_takedown_case', f'takedown_cases/{case_id}',
                 json.dumps({'requester': body.requester_identity, 'contact': body.requester_contact,
                             'scope_type': body.scope_type, 'scope_value': body.scope_value,
                             'previous_policy_state': prev_policy_state}),
                 now_val))

            conn.commit()
        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            raise v1_error(500, 'takedown_create_failed', str(e))

        # Read result
        row = cur.execute('SELECT * FROM takedown_cases WHERE case_id=?', (case_id,)).fetchone()
        events = conn.execute(
            'SELECT * FROM takedown_events WHERE case_id=? ORDER BY created_at', (case_id,)
        ).fetchall()
        result = dict(row)
        result['events'] = [dict(e) for e in events]
        return {'data': result}

    @app.put('/api/v1/admin/images/takedown/cases/{case_id}/resolve')
    def v1_admin_resolve_takedown_case(
        case_id: int,
        body: TakedownCaseResolve,
        request: Request,
        _auth: dict[str, Any] = Depends(require_scope('images:admin', 'admin:all', 'admin')),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            case = cur.execute(
                'SELECT * FROM takedown_cases WHERE case_id=?', (case_id,)
            ).fetchone()
            if not case:
                conn.rollback()
                raise v1_error(404, 'case_not_found', 'Takedown case not found.', {'case_id': case_id})

            case_dict = dict(case)
            now_val = now_utc()
            membership_id = _auth.get('membership_id')

            if body.resolution == 'restore':
                # Already-resolved guard
                if case_dict['status'] != 'open':
                    conn.rollback()
                    raise v1_error(409, 'case_not_open',
                                   f'Case {case_id} is already {case_dict["status"]}.',
                                   {'case_id': case_id, 'current_status': case_dict['status']})

                # Restore exact previous policy from snapshot
                prev_state_json = case_dict.get('previous_policy_state')
                if prev_state_json:
                    prev = json.loads(prev_state_json)
                    cur.execute(
                        "UPDATE image_delivery_policies SET external_display_enabled=?, reason=?, attribution_text=?, updated_at=? "
                        "WHERE scope_type=? AND scope_value=?",
                        (prev['external_display_enabled'], prev['reason'],
                         prev.get('attribution_text'), now_val,
                         case_dict['scope_type'], case_dict['scope_value'])
                    )
                else:
                    # No previous policy existed — remove the temporary override
                    cur.execute(
                        "DELETE FROM image_delivery_policies WHERE scope_type=? AND scope_value=? "
                        "AND reason LIKE 'Takedown case #%'",
                        (case_dict['scope_type'], case_dict['scope_value'])
                    )

                # Update case status
                cur.execute(
                    "UPDATE takedown_cases SET status='resolved', resolved_at=?, resolution_summary=? WHERE case_id=?",
                    (now_val, body.resolution_summary, case_id)
                )

                # Append restore event
                cur.execute(
                    'INSERT INTO takedown_events(case_id, action_type, scope_type, scope_value, '
                    'actor_membership_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (case_id, 'restored', case_dict['scope_type'], case_dict['scope_value'],
                     membership_id, body.resolution_summary, now_val)
                )

                # Admin audit
                cur.execute(
                    "INSERT INTO admin_audit_log(action, target_resource, details_json, created_at) VALUES (?, ?, ?, ?)",
                    ('restore_takedown_case', f'takedown_cases/{case_id}',
                     json.dumps({'resolution': 'restore', 'previous_policy_state': prev_state_json}), now_val))

                conn.commit()

            elif body.resolution == 'remove':
                scope_type = case_dict.get('scope_type') or 'source'
                scope_value = case_dict.get('scope_value')
                if not scope_value:
                    events = cur.execute(
                        "SELECT scope_type, scope_value FROM takedown_events "
                        "WHERE case_id=? AND action_type IN ('disabled', 'case_opened') AND scope_type IS NOT NULL LIMIT 1",
                        (case_id,)
                    ).fetchone()
                    if events:
                        scope_type = events[0]
                        scope_value = events[1]

                # Disable policy via _takedown_atomic (which does its own BEGIN IMMEDIATE)
                # Rollback this outer transaction first
                conn.commit()  # complete the empty outer
                # Let _takedown_atomic manage its own transaction
                conn2 = connect(app.state.db)
                _takedown_atomic(conn2, case_id=case_id, action_type='disabled',
                                 scope_type=scope_type, scope_value=scope_value,
                                 actor_membership_id=membership_id,
                                 reason=body.resolution_summary or 'Takedown',
                                 policy_enabled=False,
                                 policy_scope_type=scope_type, policy_scope_value=scope_value)
                conn2.close()
                # Now update case status in the original connection
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE takedown_cases SET status='resolved', resolved_at=?, resolution_summary=? WHERE case_id=?",
                    (now_val, body.resolution_summary, case_id)
                )
                cur2.execute(
                    'INSERT INTO takedown_events(case_id, action_type, reason, actor_membership_id, created_at) VALUES (?, ?, ?, ?, ?)',
                    (case_id, 'case_resolved', body.resolution_summary, membership_id, now_val)
                )
                conn.commit()
            else:
                conn.rollback()
                raise v1_error(400, 'invalid_resolution', 'Resolution must be "restore" or "remove".', {})

        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            raise v1_error(500, 'takedown_resolve_failed', str(e))

        row = cur.execute('SELECT * FROM takedown_cases WHERE case_id=?', (case_id,)).fetchone()
        events_list = conn.execute(
            'SELECT * FROM takedown_events WHERE case_id=? ORDER BY created_at', (case_id,)
        ).fetchall()
        result = dict(row)
        result['events'] = [dict(e) for e in events_list]
        return {'data': result}

    # ── Health/diagnostics endpoint for image gateway ─────────────────

    @app.get('/api/v1/images/health')
    def v1_image_gateway_health(
        _auth: dict[str, Any] = Depends(require_scope('images:read', 'cards:read')),
    ) -> dict[str, Any]:
        """Image gateway health check."""
        conn = connect(app.state.db)
        cur = conn.cursor()
        root = _image_root_dir(settings.image_root, fallback_root=settings.db.parent)
        deriv_dir = _ensure_derivatives_dir(settings.image_root or settings.db.parent)
        policy_count = cur.execute('SELECT COUNT(*) FROM image_delivery_policies').fetchone()[0]
        log_count_24h = cur.execute(
            "SELECT COUNT(*) FROM image_delivery_policy_records WHERE created_at >= datetime('now', '-1 day')"
        ).fetchone()[0]
        return {
            'gateway_active': True,
            'static_mount_removed': True,
            'image_root_exists': root is not None and root.exists(),
            'derivatives_dir_exists': deriv_dir.exists(),
            'policy_count': policy_count,
            'delivery_logs_24h': log_count_24h,
            'allowed_sizes': list(ALLOWED_IMAGE_SIZES),
        }

    # ── Physical item photo upload/list/retrieve/delete ──────────────

    @app.post('/api/v1/inventory/items/{item_id}/photos', response_model=PhysicalPhotoUploadResponseArticle)
    def v1_upload_item_photo(
        item_id: str,
        file: UploadFile = File(..., description='Image file (JPEG, PNG, WebP)'),
        publish: bool = Query(False, description='Mark photo as published'),
        request: Request = None,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        _auth = getattr(request.state, 'auth_dict', None) or {}
        tenant_id = get_tenant_from_key(_auth)

        # Verify item exists and belongs to this tenant
        with closing(connect(app.state.db)) as conn:
            ensure_inventory_support(conn)
            cur = conn.cursor()
            item = cur.execute(
                "SELECT 1 FROM physical_items WHERE item_id=? AND tenant_id=?",
                (item_id, tenant_id)
            ).fetchone()
        if not item:
            raise v1_error(404, 'item_not_found', 'Item not found in this tenant.', {})

        # Validate file type
        allowed_mime = {'image/jpeg', 'image/png', 'image/webp'}
        if file.content_type not in allowed_mime:
            raise v1_error(400, 'invalid_file_type',
                           f'Invalid file type: {file.content_type}. Allowed: {", ".join(sorted(allowed_mime))}.', {})

        # Read and validate file
        try:
            contents = file.file.read()
            file_size = len(contents)
            if file_size > 10 * 1024 * 1024:  # 10MB limit
                raise v1_error(400, 'file_too_large', 'File exceeds 10MB limit.', {'file_bytes': file_size})

            # Validate image decoding
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(contents))
            img.verify()
        except HTTPException:
            raise
        except Exception:
            raise v1_error(400, 'invalid_image', 'Uploaded file is not a valid image or is corrupted.', {})
        finally:
            try:
                file.file.close()
            except Exception:
                pass

        # Store to physical photos directory
        import uuid
        ext = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}.get(file.content_type, '.bin')
        stored_name = f'{uuid.uuid4()}{ext}'
        photo_dir = _ensure_physical_photos_dir(settings.image_root or settings.db.parent)
        tenant_dir = photo_dir / str(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        storage_path = tenant_dir / stored_name
        with open(storage_path, 'wb') as f:
            f.write(contents)

        photo_id: int | None = None
        now_val = now_utc()
        try:
            with closing(connect(app.state.db)) as conn:
                ensure_inventory_support(conn)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO physical_item_photos(item_id, tenant_id, uploaded_by, original_filename, storage_path, mime_type, file_bytes, is_published, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item_id, tenant_id, _auth.get('api_key_id') if _auth else None,
                     file.filename or stored_name, str(storage_path),
                     file.content_type, file_size, 1 if publish else 0, now_val)
                )
                photo_id = cur.lastrowid
                conn.commit()
        except Exception:
            try:
                storage_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return {
            'data': {
                'photo_id': photo_id,
                'item_id': item_id,
                'tenant_id': tenant_id,
                'original_filename': file.filename or stored_name,
                'mime_type': file.content_type,
                'file_bytes': file_size,
                'created_at': now_val,
            }
        }

    @app.get('/api/v1/inventory/items/{item_id}/photos', response_model=PhysicalPhotoListResponse)
    def v1_list_item_photos(
        item_id: str,
        request: Request = None,
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> dict[str, Any]:
        tenant_id = get_tenant_from_key(getattr(request.state, 'auth_dict', None) or {})
        with closing(connect(app.state.db)) as conn:
            cur = conn.cursor()
            rows_result = cur.execute(
                "SELECT * FROM physical_item_photos WHERE item_id=? AND tenant_id=? ORDER BY created_at DESC",
                (item_id, tenant_id)
            ).fetchall()
        return {'data': [dict(r) for r in rows_result]}

    @app.get('/api/v1/inventory/items/{item_id}/photos/{photo_id}')
    def v1_get_item_photo(
        item_id: str,
        photo_id: int,
        request: Request = None,
        _: dict[str, Any] = Depends(require_scope('read:inventory', 'cards:read')),
    ) -> Response:
        tenant_id = get_tenant_from_key(getattr(request.state, 'auth_dict', None) or {})
        with closing(connect(app.state.db)) as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT * FROM physical_item_photos WHERE photo_id=? AND item_id=? AND tenant_id=?",
                (photo_id, item_id, tenant_id)
            ).fetchone()
        if not row:
            raise v1_error(404, 'photo_not_found', 'Photo not found.', {})
        storage_path = row['storage_path']
        if not os.path.exists(storage_path):
            raise v1_error(404, 'photo_file_missing', 'Photo file not found on disk.', {})
        mime = row['mime_type']
        with open(storage_path, 'rb') as f:
            content = f.read()
        return Response(content=content, media_type=mime, headers={
            'Content-Type': mime,
            'Content-Disposition': 'inline',
            'X-Content-Type-Options': 'nosniff',
        })

    @app.delete('/api/v1/inventory/items/{item_id}/photos/{photo_id}')
    def v1_delete_item_photo(
        item_id: str,
        photo_id: int,
        request: Request = None,
        _: dict[str, Any] = Depends(require_scope('write:inventory', 'admin')),
    ) -> dict[str, Any]:
        tenant_id = get_tenant_from_key(getattr(request.state, 'auth_dict', None) or {})
        with closing(connect(app.state.db)) as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT storage_path FROM physical_item_photos WHERE photo_id=? AND item_id=? AND tenant_id=?",
                (photo_id, item_id, tenant_id)
            ).fetchone()
            if not row:
                raise v1_error(404, 'photo_not_found', 'Photo not found.', {})
            storage_path = row['storage_path']
            # Archive the photo (soft delete — keep record)
            cur.execute(
                "UPDATE physical_item_photos SET is_published=0 WHERE photo_id=?",
                (photo_id,)
            )
            conn.commit()
        # Delete file from disk
        if os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except OSError:
                pass  # File deletion failure is non-fatal
        return {'data': {'deleted': True, 'photo_id': photo_id, 'item_id': item_id}}

    # ── /api/v1/scanner/scan ─────────────────────────────────────────────

    def _compute_average_hash(image_bytes: bytes, hash_size: int = 8) -> int:
        """Compute average hash from raw image bytes using PIL."""
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert('L').resize((hash_size, hash_size), Image.Resampling.BILINEAR)
        pixels = list(img.getdata())
        mean = sum(pixels) / len(pixels)
        bits = 0
        for i, p in enumerate(pixels):
            if p > mean:
                bits |= (1 << i)
        return bits

    @app.post('/api/v1/scanner/scan')
    async def v1_scanner_scan(
        file: UploadFile = File(..., description='Image file to scan'),
        limit: int = Query(5, ge=1, le=20, description='Max matches to return'),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        """Scan a card image and find matches via perceptual hash.

        Phase 1 implementation: hash-based matching only.
        Returns card_key matches sorted by hash distance (lower = better match).
        """
        # Read image bytes
        image_bytes = await file.read()
        if len(image_bytes) == 0:
            raise v1_error(400, 'empty_image', 'No image data provided.', {})

        # Compute hash
        try:
            query_hash = _compute_average_hash(image_bytes)
        except Exception as e:
            raise v1_error(422, 'invalid_image', f'Could not process image: {str(e)}', {})

        # Find matches via hash distance
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('SELECT card_key, language_code, card_id, image_hash FROM card_image_hashes')

        matches = []
        for row in cur.fetchall():
            try:
                stored_hash = int(row['image_hash'], 16)
                dist = (query_hash ^ stored_hash).bit_count()
                if dist <= 10:  # Only include reasonably close matches
                    matches.append({
                        'card_key': row['card_key'],
                        'language_code': row['language_code'],
                        'card_id': row['card_id'],
                        'distance': dist,
                    })
            except (ValueError, TypeError):
                continue

        matches.sort(key=lambda x: x['distance'])
        result_matches = matches[:limit]

        # Add confidence labels
        for m in result_matches:
            if m['distance'] <= 5:
                m['confidence'] = 'high'
            elif m['distance'] <= 10:
                m['confidence'] = 'medium'
            else:
                m['confidence'] = 'low'

        return {
            'data': result_matches,
            'query_image_size': len(image_bytes),
            'hash_computed': format(query_hash, '016x'),
        }

    # ── v10 identity endpoints ────────────────────────────────────────────

    @app.get('/api/v1/identity/health', response_model=IdentityHealthResponseV1)
    def v1_identity_health(
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> IdentityHealthResponseV1:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM v10_canonical_printings')
        cp_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_canonical_printing_cards')
        link_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_commercial_variants')
        cv_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_sellable_skus')
        sku_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_external_references')
        er_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_identity_build_runs')
        run_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_canonical_printings WHERE confidence_label = ?', ('HIGH',))
        high_conf = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_canonical_printings WHERE confidence_label = ?', ('MEDIUM',))
        med_conf = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_canonical_printings WHERE confidence_label = ?', ('LOW',))
        low_conf = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM v10_commercial_variants WHERE finish = ?', ('unknown',))
        unknown_finish = cur.fetchone()[0]

        last_run: IdentityBuildRunSummaryV1 | None = None
        cur.execute('SELECT * FROM v10_identity_build_runs ORDER BY started_at DESC LIMIT 1')
        row = cur.fetchone()
        if row:
            last_run = IdentityBuildRunSummaryV1(
                build_run_id=row['build_run_id'],
                started_at=row['started_at'],
                status=row['status'],
                algorithm_version=row['algorithm_version'],
                canonical_printings_created=row['canonical_printings_created'],
                commercial_variants_created=row['commercial_variants_created'],
                sellable_skus_created=row['sellable_skus_created'],
                notes=row.get('notes'),
            )
        conn.close()
        return IdentityHealthResponseV1(
            canonical_printings=cp_count,
            card_links=link_count,
            commercial_variants=cv_count,
            sellable_skus=sku_count,
            external_references=er_count,
            build_runs=run_count,
            last_build_run=last_run,
            high_confidence=high_conf,
            medium_confidence=med_conf,
            low_confidence=low_conf,
            unknown_finish=unknown_finish,
        )

    @app.get('/api/v1/identity/canonical-printings', response_model=None)
    def v1_identity_canonical_printings(
        q: str = Query(None),
        core_set_id: str | None = Query(None),
        set_id: str | None = Query(None),
        collector_number: str | None = Query(None),
        language: str | None = Query(None, alias='language_code'),
        confidence_label: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        conditions: list[str] = []
        params: list[Any] = []
        if q:
            conditions.append('(cp.canonical_name LIKE ? OR cp.canonical_key LIKE ?)')
            like_q = f'%{q}%'
            params.extend([like_q, like_q])
        if core_set_id:
            conditions.append('cp.core_set_id = ?')
            params.append(core_set_id)
        if set_id:
            conditions.append('cp.set_id = ?')
            params.append(set_id)
        if collector_number:
            conditions.append('cp.collector_number = ?')
            params.append(collector_number)
        if language:
            conditions.append('cp.primary_language = ?')
            params.append(language)
        if confidence_label:
            conditions.append('cp.confidence_label = ?')
            params.append(confidence_label)

        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        sql = f"""
            SELECT cp.* FROM v10_canonical_printings cp
            {where}
            ORDER BY cp.core_set_id, cp.collector_number_sort
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        # Attach confidence info
        for r in rows:
            r['confidence'] = {
                'score': r['confidence_score'],
                'label': r['confidence_label'],
                'reason': r['confidence_reason'],
            }
        conn.close()
        return {'data': rows, 'meta': {'limit': limit, 'offset': offset, 'count': len(rows)}}

    @app.get('/api/v1/identity/canonical-printings/{canonical_printing_id}')
    def v1_identity_canonical_printing_detail(
        canonical_printing_id: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('SELECT * FROM v10_canonical_printings WHERE canonical_printing_id = ?', (canonical_printing_id,))
        row = cur.fetchone()
        if not row:
            raise v1_error(404, 'not_found', f'Canonical printing {canonical_printing_id} not found.', None)
        cp = dict(row)
        cp['confidence'] = {
            'score': cp['confidence_score'],
            'label': cp['confidence_label'],
            'reason': cp['confidence_reason'],
        }
        # Get linked cards
        cur.execute('SELECT * FROM v10_canonical_printing_cards WHERE canonical_printing_id = ?', (canonical_printing_id,))
        cp['linked_cards'] = [dict(r) for r in cur.fetchall()]
        # Get variants
        cur.execute('SELECT * FROM v10_commercial_variants WHERE canonical_printing_id = ?', (canonical_printing_id,))
        variants = []
        for r in cur.fetchall():
            v = dict(r)
            v['confidence'] = {
                'score': v['confidence_score'],
                'label': v['confidence_label'],
                'reason': v['confidence_reason'],
            }
            variants.append(v)
        cp['commercial_variants'] = variants
        conn.close()
        return {'data': cp}

    @app.get('/api/v1/identity/sellable-skus')
    def v1_identity_sellable_skus(
        q: str = Query(None),
        item_class: str | None = Query(None),
        language: str | None = Query(None, alias='language_code'),
        status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        conditions: list[str] = []
        params: list[Any] = []
        if q:
            conditions.append('(s.display_title LIKE ? OR s.sku_key LIKE ?)')
            like_q = f'%{q}%'
            params.extend([like_q, like_q])
        if item_class:
            conditions.append('s.item_class = ?')
            params.append(item_class)
        if language:
            conditions.append("""
                s.commercial_variant_id IN (
                    SELECT cv.commercial_variant_id FROM v10_commercial_variants cv
                    WHERE cv.language_code = ?
                )
            """)
            params.append(language)
        if status:
            conditions.append('s.status = ?')
            params.append(status)

        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        sql = f"""
            SELECT s.* FROM v10_sellable_skus s
            {where}
            ORDER BY s.sku_key
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cur.execute(sql, tuple(params))
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d['confidence'] = {
                'score': d['confidence_score'],
                'label': d['confidence_label'],
                'reason': d['confidence_reason'],
            }
            rows.append(d)
        conn.close()
        return {'data': rows, 'meta': {'limit': limit, 'offset': offset, 'count': len(rows)}}

    @app.get('/api/v1/identity/sellable-skus/{sellable_sku_id}')
    def v1_identity_sellable_sku_detail(
        sellable_sku_id: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        cur.execute('SELECT * FROM v10_sellable_skus WHERE sellable_sku_id = ?', (sellable_sku_id,))
        row = cur.fetchone()
        if not row:
            raise v1_error(404, 'not_found', f'Sellable SKU {sellable_sku_id} not found.', None)
        sku = dict(row)
        sku['confidence'] = {
            'score': sku['confidence_score'],
            'label': sku['confidence_label'],
            'reason': sku['confidence_reason'],
        }
        conn.close()
        return {'data': sku}

    @app.get('/api/v1/identity/cards/{card_key:path}')
    def v1_identity_card_lookup(
        card_key: str,
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        # Find linked canonical printing for this card
        cur.execute('''
            SELECT cp.* FROM v10_canonical_printings cp
            JOIN v10_canonical_printing_cards l ON cp.canonical_printing_id = l.canonical_printing_id
            WHERE l.card_key = ?
        ''', (card_key,))
        cp_row = cur.fetchone()
        if not cp_row:
            conn.close()
            return {
                'data': {
                    'card_key': card_key,
                    'mapped': False,
                    'warnings': [f'No identity mapping found for card {card_key}.'],
                }
            }
        cp = dict(cp_row)
        cp['confidence'] = {
            'score': cp['confidence_score'],
            'label': cp['confidence_label'],
            'reason': cp['confidence_reason'],
        }
        cp_id = cp['canonical_printing_id']
        # Get variants
        cur.execute('SELECT * FROM v10_commercial_variants WHERE canonical_printing_id = ?', (cp_id,))
        variants = [dict(r) for r in cur.fetchall()]
        # Get SKUs via variants
        cur.execute('''
            SELECT * FROM v10_sellable_skus
            WHERE commercial_variant_id IN (
                SELECT commercial_variant_id FROM v10_commercial_variants
                WHERE canonical_printing_id = ?
            )
        ''', (cp_id,))
        skus = [dict(r) for r in cur.fetchall()]
        # Get external references
        cur.execute('''
            SELECT * FROM v10_external_references
            WHERE entity_type = 'canonical_printing' AND entity_id = ?
        ''', (cp_id,))
        refs = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {'data': {
            'card_key': card_key,
            'mapped': True,
            'canonical_printing': cp,
            'commercial_variants': variants,
            'sellable_skus': skus,
            'external_references': refs,
        }}

    @app.get('/api/v1/identity/external-references')
    def v1_identity_external_references(
        entity_type: str | None = Query(None),
        entity_id: str | None = Query(None),
        source_name: str | None = Query(None),
        source_identifier: str | None = Query(None),
        confidence_label: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _: dict[str, Any] = Depends(require_v1_api_key),
    ) -> dict[str, Any]:
        conn = connect(app.state.db)
        cur = conn.cursor()
        conditions: list[str] = []
        params: list[Any] = []
        if entity_type:
            conditions.append('entity_type = ?')
            params.append(entity_type)
        if entity_id:
            conditions.append('entity_id = ?')
            params.append(entity_id)
        if source_name:
            conditions.append('source_name = ?')
            params.append(source_name)
        if source_identifier:
            conditions.append('source_identifier = ?')
            params.append(source_identifier)
        if confidence_label:
            conditions.append('confidence_label = ?')
            params.append(confidence_label)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        sql = f"SELECT * FROM v10_external_references{where} ORDER BY entity_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {'data': rows, 'meta': {'limit': limit, 'offset': offset, 'count': len(rows)}}


    return app


app = create_app(settings_from_env())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run the local SaveRoom Pokémon DB FastAPI service.')
    add_common_args(parser, include_server=True)
    args = parser.parse_args(argv)
    import uvicorn

    settings = validate_settings(settings_from_args(args), require_ui=False)
    selected_app = create_app(settings)
    for line in startup_lines(settings, selected_app.state.support_status):
        print(f'[pokemon-db-api] {line}', flush=True)
    uvicorn.run(selected_app, host=settings.host, port=settings.port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


