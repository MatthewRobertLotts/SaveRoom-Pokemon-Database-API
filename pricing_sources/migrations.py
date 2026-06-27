"""v11 market evidence schema migrations.

These migrations create the v11 pricing/evidence tables on top of the
existing v10 database. They are idempotent and safe to rerun.

The migrations are embedded in the main FastAPI app (pokemon_db_v2_fastapi.py)
but extracted here for standalone testing.

Migration numbers: v66-v72
"""
from __future__ import annotations

import sqlite3

# v11 market evidence schema migrations.
# Each entry: (version, sql, description)
V11_MIGRATIONS: list[tuple[str, str, str]] = [
    # v66: Source registry
    ('v66', """CREATE TABLE IF NOT EXISTS v11_price_sources (
        source_id TEXT PRIMARY KEY,
        source_code TEXT UNIQUE NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT,
        api_key_required INTEGER NOT NULL DEFAULT 0,
        base_currency TEXT NOT NULL DEFAULT 'USD',
        default_condition TEXT NOT NULL DEFAULT 'unknown',
        default_listing_type TEXT NOT NULL DEFAULT 'market_price',
        capabilities_json TEXT,
        is_enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )""", 'Create v11 price source registry table.'),

    # v67: Raw response cache
    ('v67', """CREATE TABLE IF NOT EXISTS v11_price_source_cache (
        cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        ttl_hours INTEGER NOT NULL DEFAULT 24,
        raw_payload_json TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        query_params_json TEXT,
        http_status INTEGER,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
    )""", 'Create v11 raw response cache table.'),
    ('v67b', 'CREATE INDEX IF NOT EXISTS idx_v11_psc_source_record ON v11_price_source_cache(source_id, source_record_id)',
     'Index for source+record cache lookup.'),
    ('v67c', 'CREATE INDEX IF NOT EXISTS idx_v11_psc_fetched ON v11_price_source_cache(fetched_at)',
     'Index for cache freshness queries.'),

    # v68: Normalised observations
    ('v68', """CREATE TABLE IF NOT EXISTS v11_price_observations (
        observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        currency TEXT NOT NULL,
        amount REAL NOT NULL,
        condition TEXT NOT NULL DEFAULT 'unknown',
        finish TEXT NOT NULL DEFAULT 'unknown',
        printing_label TEXT,
        language TEXT,
        marketplace TEXT NOT NULL DEFAULT 'unknown',
        listing_type TEXT NOT NULL DEFAULT 'unknown',
        raw_title TEXT,
        raw_url TEXT,
        raw_payload_ref TEXT,
        observation_type TEXT NOT NULL DEFAULT 'market_price',
        canonical_printing_id TEXT,
        commercial_variant_id TEXT,
        sellable_sku_id TEXT,
        match_confidence TEXT,
        match_reason TEXT,
        is_usable_for_aggregate INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
    )""", 'Create v11 normalised price observations table.'),
    ('v68b', 'CREATE INDEX IF NOT EXISTS idx_v11_po_source ON v11_price_observations(source_id, source_record_id)',
     'Index for source dedup.'),
    ('v68c', 'CREATE INDEX IF NOT EXISTS idx_v11_po_canonical ON v11_price_observations(canonical_printing_id)',
     'Index for canonical printing lookup.'),
    ('v68d', 'CREATE INDEX IF NOT EXISTS idx_v11_po_variant ON v11_price_observations(commercial_variant_id)',
     'Index for commercial variant lookup.'),
    ('v68e', 'CREATE INDEX IF NOT EXISTS idx_v11_po_sku ON v11_price_observations(sellable_sku_id)',
     'Index for SKU lookup.'),
    ('v68f', 'CREATE INDEX IF NOT EXISTS idx_v11_po_currency ON v11_price_observations(currency)',
     'Index for currency filtering.'),
    ('v68g', 'CREATE INDEX IF NOT EXISTS idx_v11_po_condition ON v11_price_observations(condition)',
     'Index for condition filtering.'),
    ('v68h', 'CREATE INDEX IF NOT EXISTS idx_v11_po_finish ON v11_price_observations(finish)',
     'Index for finish filtering.'),
    ('v68i', 'CREATE INDEX IF NOT EXISTS idx_v11_po_listing_type ON v11_price_observations(listing_type)',
     'Index for listing type filtering.'),
    ('v68j', 'CREATE INDEX IF NOT EXISTS idx_v11_po_fetched ON v11_price_observations(fetched_at)',
     'Index for freshness queries.'),
    ('v68k', 'CREATE INDEX IF NOT EXISTS idx_v11_po_usable ON v11_price_observations(is_usable_for_aggregate)',
     'Index for aggregate filtering.'),
    ('v68l', 'CREATE INDEX IF NOT EXISTS idx_v11_po_match_conf ON v11_price_observations(match_confidence)',
     'Index for confidence filtering.'),

    # v69: Observation-to-identity matches
    ('v69', """CREATE TABLE IF NOT EXISTS v11_price_observation_matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        observation_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        match_confidence TEXT NOT NULL,
        match_reason TEXT NOT NULL,
        match_method TEXT NOT NULL,
        source_set_code TEXT,
        source_collector_number TEXT,
        source_variant TEXT,
        source_language TEXT,
        condition_matched TEXT,
        finish_matched TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (observation_id) REFERENCES v11_price_observations(observation_id)
    )""", 'Create v11 observation-to-identity match table.'),
    ('v69b', 'CREATE INDEX IF NOT EXISTS idx_v11_pom_obs ON v11_price_observation_matches(observation_id)',
     'Index for observation join.'),
    ('v69c', 'CREATE INDEX IF NOT EXISTS idx_v11_pom_target ON v11_price_observation_matches(target_type, target_id)',
     'Index for target lookup.'),
    ('v69d', 'CREATE INDEX IF NOT EXISTS idx_v11_pom_confidence ON v11_price_observation_matches(match_confidence)',
     'Index for confidence filtering.'),

    # v70: Aggregate valuations
    ('v70', """CREATE TABLE IF NOT EXISTS v11_price_aggregates (
        aggregate_id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        currency TEXT NOT NULL,
        listing_type TEXT NOT NULL,
        finish TEXT NOT NULL DEFAULT 'unknown',
        median_price REAL,
        low_price REAL,
        high_price REAL,
        mean_price REAL,
        observation_count INTEGER NOT NULL DEFAULT 0,
        source_count INTEGER NOT NULL DEFAULT 0,
        freshness_days REAL,
        confidence_label TEXT NOT NULL,
        confidence_score REAL,
        confidence_reason TEXT,
        computed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )""", 'Create v11 aggregate valuations table.'),
    ('v70b', 'CREATE INDEX IF NOT EXISTS idx_v11_pa_target ON v11_price_aggregates(target_type, target_id)',
     'Index for aggregate target lookup.'),
    ('v70c', 'CREATE INDEX IF NOT EXISTS idx_v11_pa_currency ON v11_price_aggregates(currency)',
     'Index for currency filtering.'),
    ('v70d', 'CREATE INDEX IF NOT EXISTS idx_v11_pa_listing_type ON v11_price_aggregates(listing_type)',
     'Index for listing type filtering.'),
    ('v70e', 'CREATE INDEX IF NOT EXISTS idx_v11_pa_finish ON v11_price_aggregates(finish)',
     'Index for finish filtering.'),
    ('v70f', 'CREATE INDEX IF NOT EXISTS idx_v11_pa_computed ON v11_price_aggregates(computed_at)',
     'Index for freshness queries.'),
    ('v70g', 'CREATE INDEX IF NOT EXISTS idx_v11_pa_confidence ON v11_price_aggregates(confidence_label)',
     'Index for confidence filtering.'),

    # v71: Refresh run tracking
    ('v71', """CREATE TABLE IF NOT EXISTS v11_price_refresh_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        completed_at TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        observations_created INTEGER DEFAULT 0,
        observations_updated INTEGER DEFAULT 0,
        observations_skipped INTEGER DEFAULT 0,
        cache_rows_created INTEGER DEFAULT 0,
        error_message TEXT,
        error_details TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
    )""", 'Create v11 refresh run tracking table.'),
    ('v71b', 'CREATE INDEX IF NOT EXISTS idx_v11_prr_source ON v11_price_refresh_runs(source_id)',
     'Index for source lookup.'),
    ('v71c', 'CREATE INDEX IF NOT EXISTS idx_v11_prr_status ON v11_price_refresh_runs(status)',
     'Index for status filtering.'),
    ('v71d', 'CREATE INDEX IF NOT EXISTS idx_v11_prr_started ON v11_price_refresh_runs(started_at)',
     'Index for time-based queries.'),

    # v72: Source health tracking
    ('v72', """CREATE TABLE IF NOT EXISTS v11_price_source_health (
        health_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        checked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        status TEXT NOT NULL DEFAULT 'unknown',
        last_success_at TEXT,
        last_failure_at TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        rate_limit_remaining INTEGER,
        rate_limit_reset_at TEXT,
        avg_response_ms REAL,
        last_error_code TEXT,
        last_error_message TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
    )""", 'Create v11 source health tracking table.'),
    ('v72b', 'CREATE INDEX IF NOT EXISTS idx_v11_psh_source ON v11_price_source_health(source_id)',
     'Index for source health lookup.'),
    ('v72c', 'CREATE INDEX IF NOT EXISTS idx_v11_psh_status ON v11_price_source_health(status)',
     'Index for status filtering.'),
]


def apply_v11_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply v11 migrations to a database connection. Returns list of applied versions."""
    cur = conn.cursor()
    # Ensure schema_migrations table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    """)
    applied = {r[0] for r in cur.execute('SELECT version FROM schema_migrations').fetchall()}
    ran: list[str] = []
    for version, sql, desc in V11_MIGRATIONS:
        if version not in applied:
            cur.execute(sql)
            cur.execute(
                'INSERT INTO schema_migrations(version, description) VALUES (?, ?)',
                (version, desc)
            )
            ran.append(version)
    return ran
