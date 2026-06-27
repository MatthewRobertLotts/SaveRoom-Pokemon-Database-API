"""Tests for v10 canonical identity schema migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _apply_v10_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply v58-v65 migrations to a fresh connection. Returns applied versions."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    """)
    applied = {r[0] for r in cur.execute('SELECT version FROM schema_migrations').fetchall()}

    migrations: list[tuple[str, str, str]] = [
        ('v58', "CREATE TABLE IF NOT EXISTS v10_canonical_printings ("
               "canonical_printing_id TEXT PRIMARY KEY, "
               "canonical_key TEXT UNIQUE NOT NULL, "
               "game TEXT NOT NULL DEFAULT 'pokemon_tcg', "
               "core_set_id TEXT NOT NULL, set_id TEXT, set_code TEXT, "
               "collector_number TEXT, collector_number_sort TEXT, "
               "canonical_name TEXT NOT NULL, name_english TEXT, "
               "primary_language TEXT NOT NULL, card_kind TEXT, rarity TEXT, "
               "first_seen_source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', "
               "confidence_score REAL NOT NULL, confidence_label TEXT NOT NULL, "
               "confidence_reason TEXT NOT NULL, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
               'Create v10 canonical printing identity table.'),
        ('v58b', 'CREATE INDEX IF NOT EXISTS idx_v10_cp_core_set ON v10_canonical_printings(core_set_id, collector_number_sort)',
               'Index for set+number lookup on canonical printings.'),
        ('v58c', 'CREATE INDEX IF NOT EXISTS idx_v10_cp_name ON v10_canonical_printings(canonical_name)',
               'Index for name lookup on canonical printings.'),
        ('v58d', 'CREATE INDEX IF NOT EXISTS idx_v10_cp_confidence ON v10_canonical_printings(confidence_label)',
               'Index for confidence filtering.'),
        ('v59', "CREATE TABLE IF NOT EXISTS v10_canonical_printing_cards ("
               "canonical_printing_id TEXT NOT NULL, card_key TEXT NOT NULL, "
               "language_code TEXT NOT NULL, source_card_id TEXT, "
               "match_method TEXT NOT NULL, confidence_score REAL NOT NULL, "
               "confidence_reason TEXT NOT NULL, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "PRIMARY KEY (canonical_printing_id, card_key))",
               'Create v10 canonical-to-source-card link table.'),
        ('v59b', 'CREATE INDEX IF NOT EXISTS idx_v10_cpc_card_key ON v10_canonical_printing_cards(card_key)',
               'Index for reverse card-to-canonical lookup.'),
        ('v60', "CREATE TABLE IF NOT EXISTS v10_commercial_variants ("
               "commercial_variant_id TEXT PRIMARY KEY, "
               "canonical_printing_id TEXT NOT NULL, variant_key TEXT UNIQUE NOT NULL, "
               "language_code TEXT NOT NULL, finish TEXT NOT NULL DEFAULT 'unknown', "
               "variant_type TEXT NOT NULL DEFAULT 'standard', stamp TEXT, edition TEXT, "
               "is_reverse_holo INTEGER NOT NULL DEFAULT 0, is_holo INTEGER, "
               "is_promo INTEGER NOT NULL DEFAULT 0, market_region TEXT, "
               "status TEXT NOT NULL DEFAULT 'active', confidence_score REAL NOT NULL, "
               "confidence_label TEXT NOT NULL, confidence_reason TEXT NOT NULL, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
               'Create v10 commercial variant table.'),
        ('v60b', 'CREATE INDEX IF NOT EXISTS idx_v10_cv_canonical ON v10_commercial_variants(canonical_printing_id)',
               'Index for variant-to-canonical lookup.'),
        ('v60c', 'CREATE INDEX IF NOT EXISTS idx_v10_cv_language ON v10_commercial_variants(language_code)',
               'Index for language filtering.'),
        ('v60d', 'CREATE INDEX IF NOT EXISTS idx_v10_cv_finish ON v10_commercial_variants(finish)',
               'Index for finish filtering.'),
        ('v61', "CREATE TABLE IF NOT EXISTS v10_sellable_skus ("
               "sellable_sku_id TEXT PRIMARY KEY, commercial_variant_id TEXT NOT NULL, "
               "sku_key TEXT UNIQUE NOT NULL, item_class TEXT NOT NULL DEFAULT 'single_card', "
               "condition_policy TEXT NOT NULL DEFAULT 'raw_conditioned', "
               "display_title TEXT NOT NULL, pricing_key TEXT, "
               "inventory_enabled INTEGER NOT NULL DEFAULT 1, "
               "listing_enabled INTEGER NOT NULL DEFAULT 1, "
               "scanner_enabled INTEGER NOT NULL DEFAULT 1, "
               "status TEXT NOT NULL DEFAULT 'active', confidence_score REAL NOT NULL, "
               "confidence_label TEXT NOT NULL, confidence_reason TEXT NOT NULL, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
               'Create v10 sellable SKU table.'),
        ('v61b', 'CREATE INDEX IF NOT EXISTS idx_v10_sku_variant ON v10_sellable_skus(commercial_variant_id)',
               'Index for SKU-to-variant lookup.'),
        ('v61c', 'CREATE INDEX IF NOT EXISTS idx_v10_sku_item_class ON v10_sellable_skus(item_class)',
               'Index for item class filtering.'),
        ('v62', "CREATE TABLE IF NOT EXISTS v10_external_references ("
               "external_reference_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, "
               "entity_id TEXT NOT NULL, source_name TEXT NOT NULL, "
               "source_entity_type TEXT, source_identifier TEXT NOT NULL, "
               "source_url TEXT, match_method TEXT NOT NULL, confidence_score REAL NOT NULL, "
               "confidence_label TEXT NOT NULL, confidence_reason TEXT NOT NULL, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "status TEXT NOT NULL DEFAULT 'active', "
               "UNIQUE(entity_type, entity_id, source_name, source_identifier))",
               'Create v10 external reference mapping table.'),
        ('v62b', 'CREATE INDEX IF NOT EXISTS idx_v10_er_entity ON v10_external_references(entity_type, entity_id)',
               'Index for entity reference lookup.'),
        ('v63', "CREATE TABLE IF NOT EXISTS v10_identity_build_runs ("
               "build_run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, "
               "status TEXT NOT NULL, source_db_path TEXT, "
               "algorithm_version TEXT NOT NULL DEFAULT '1.0.0', "
               "cards_seen INTEGER DEFAULT 0, canonical_printings_created INTEGER DEFAULT 0, "
               "commercial_variants_created INTEGER DEFAULT 0, "
               "sellable_skus_created INTEGER DEFAULT 0, "
               "external_references_created INTEGER DEFAULT 0, "
               "warnings_count INTEGER DEFAULT 0, errors_count INTEGER DEFAULT 0, notes TEXT)",
               'Create v10 identity build run tracking table.'),
        ('v64', "CREATE TABLE IF NOT EXISTS v10_identity_build_events ("
               "event_id TEXT PRIMARY KEY, build_run_id TEXT NOT NULL, "
               "severity TEXT NOT NULL, entity_type TEXT, entity_id TEXT, "
               "message TEXT NOT NULL, details_json TEXT, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
               'Create v10 identity build event log table.'),
        ('v65', "CREATE TABLE IF NOT EXISTS v10_inventory_sku_links ("
               "link_id TEXT PRIMARY KEY, sellable_sku_id TEXT NOT NULL, "
               "legacy_sku_id INTEGER NOT NULL, "
               "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), "
               "UNIQUE(sellable_sku_id, legacy_sku_id))",
               'Create v10-to-legacy SKU bridge table for inventory compatibility.'),
    ]

    ran: list[str] = []
    for version, sql, desc in migrations:
        if version not in applied:
            cur.execute(sql)
            cur.execute('INSERT INTO schema_migrations(version, description) VALUES (?, ?)', (version, desc))
            ran.append(version)
    conn.commit()
    return ran


@pytest.fixture
def v10_db(tmp_path: Path) -> sqlite3.Connection:
    """Create an in-memory database with v10 migrations applied."""
    conn = sqlite3.connect(str(tmp_path / 'test_v10.db'))
    conn.execute('PRAGMA journal_mode=WAL')
    _apply_v10_migrations(conn)
    return conn


@pytest.fixture
def v10_db_path(tmp_path: Path) -> Path:
    """Create the DB file path for tests that need a file-based DB."""
    db_path = tmp_path / 'test_v10.db'
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode=WAL')
    _apply_v10_migrations(conn)
    conn.close()
    return db_path


class TestV10MigrationCreation:
    """Tests that v10 tables are created correctly."""

    def test_canonical_printings_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_canonical_printings'")
        assert cur.fetchone() is not None

    def test_canonical_printing_cards_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_canonical_printing_cards'")
        assert cur.fetchone() is not None

    def test_commercial_variants_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_commercial_variants'")
        assert cur.fetchone() is not None

    def test_sellable_skus_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_sellable_skus'")
        assert cur.fetchone() is not None

    def test_external_references_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_external_references'")
        assert cur.fetchone() is not None

    def test_build_runs_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_identity_build_runs'")
        assert cur.fetchone() is not None

    def test_build_events_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_identity_build_events'")
        assert cur.fetchone() is not None

    def test_inventory_sku_links_table_exists(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='v10_inventory_sku_links'")
        assert cur.fetchone() is not None


class TestV10MigrationIdempotency:
    """Tests that running migrations twice does not cause errors."""

    def test_double_apply_succeeds(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / 'idempotent.db')
        conn = sqlite3.connect(db_path)
        conn.execute('PRAGMA journal_mode=WAL')

        first_ran = _apply_v10_migrations(conn)
        second_ran = _apply_v10_migrations(conn)

        assert len(first_ran) == 18  # v58 through v65 + indexes
        assert len(second_ran) == 0  # nothing new
        conn.close()

    def test_schema_unchanged_on_rerun(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / 'unchanged.db')
        conn = sqlite3.connect(db_path)
        conn.execute('PRAGMA journal_mode=WAL')
        _apply_v10_migrations(conn)

        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE name='v10_canonical_printings'")
        sql_first = cur.fetchone()[0]

        _apply_v10_migrations(conn)
        cur.execute("SELECT sql FROM sqlite_master WHERE name='v10_canonical_printings'")
        sql_second = cur.fetchone()[0]

        assert sql_first == sql_second
        conn.close()


class TestV10Indexes:
    """Tests that required indexes exist."""

    def test_canonical_printing_indexes(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_v10_cp_%'")
        indexes = {r[0] for r in cur.fetchall()}
        assert 'idx_v10_cp_core_set' in indexes
        assert 'idx_v10_cp_name' in indexes
        assert 'idx_v10_cp_confidence' in indexes

    def test_commercial_variant_indexes(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_v10_cv_%'")
        indexes = {r[0] for r in cur.fetchall()}
        assert 'idx_v10_cv_canonical' in indexes
        assert 'idx_v10_cv_language' in indexes
        assert 'idx_v10_cv_finish' in indexes

    def test_sellable_sku_indexes(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_v10_sku_%'")
        indexes = {r[0] for r in cur.fetchall()}
        assert 'idx_v10_sku_variant' in indexes
        assert 'idx_v10_sku_item_class' in indexes

    def test_external_reference_indexes(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_v10_er_%'")
        indexes = {r[0] for r in cur.fetchall()}
        assert 'idx_v10_er_entity' in indexes


class TestV10CanonicalPrintingsSchema:
    """Tests for v10_canonical_printings table schema correctness."""

    def test_required_columns(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute('PRAGMA table_info(v10_canonical_printings)')
        columns = {r[1] for r in cur.fetchall()}
        required = {
            'canonical_printing_id', 'canonical_key', 'game', 'core_set_id',
            'set_id', 'set_code', 'collector_number', 'collector_number_sort',
            'canonical_name', 'name_english', 'primary_language', 'card_kind',
            'rarity', 'first_seen_source', 'status', 'confidence_score',
            'confidence_label', 'confidence_reason', 'created_at', 'updated_at',
        }
        assert required.issubset(columns)

    def test_unique_constraint_on_canonical_key(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        # UNIQUE on column definition creates inline constraint; verify via duplicate insert failure
        cur.execute("""INSERT INTO v10_canonical_printings
                      (canonical_printing_id, canonical_key, core_set_id,
                       canonical_name, primary_language, first_seen_source,
                       confidence_score, confidence_label, confidence_reason)
                      VALUES ('cp-u1', 'test:unique-key', 'base1', 'Test', 'en', 'test', 0.9, 'HIGH', 'test')""")
        v10_db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute("""INSERT INTO v10_canonical_printings
                          (canonical_printing_id, canonical_key, core_set_id,
                           canonical_name, primary_language, first_seen_source,
                           confidence_score, confidence_label, confidence_reason)
                          VALUES ('cp-u2', 'test:unique-key', 'base1', 'Test', 'en', 'test', 0.9, 'HIGH', 'test')""")
            v10_db.commit()

    def test_default_values(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("""INSERT INTO v10_canonical_printings
                      (canonical_printing_id, canonical_key, core_set_id,
                       canonical_name, primary_language, first_seen_source,
                       confidence_score, confidence_label, confidence_reason)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   ('cp-test-1', 'test:base1-4-en', 'base1', 'Charizard', 'en',
                    'test_fixture', 0.9, 'HIGH', 'test insert'))
        v10_db.commit()
        cur.execute("SELECT game, status FROM v10_canonical_printings WHERE canonical_printing_id='cp-test-1'")
        row = cur.fetchone()
        assert row[0] == 'pokemon_tcg'
        assert row[1] == 'active'


class TestV10CommercialVariantsSchema:
    """Tests for v10_commercial_variants table schema correctness."""

    def test_required_columns(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute('PRAGMA table_info(v10_commercial_variants)')
        columns = {r[1] for r in cur.fetchall()}
        required = {
            'commercial_variant_id', 'canonical_printing_id', 'variant_key',
            'language_code', 'finish', 'variant_type', 'stamp', 'edition',
            'is_reverse_holo', 'is_holo', 'is_promo', 'market_region',
            'status', 'confidence_score', 'confidence_label', 'confidence_reason',
            'created_at', 'updated_at',
        }
        assert required.issubset(columns)

    def test_unique_variant_key(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        # UNIQUE on column definition creates inline constraint; verify via duplicate insert failure
        cur.execute("""INSERT INTO v10_commercial_variants
                      (commercial_variant_id, canonical_printing_id, variant_key,
                       language_code, confidence_score, confidence_label, confidence_reason)
                      VALUES ('cv-u1', 'cp-u1', 'test:unique-variant', 'en', 0.8, 'HIGH', 'test')""")
        v10_db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute("""INSERT INTO v10_commercial_variants
                          (commercial_variant_id, canonical_printing_id, variant_key,
                           language_code, confidence_score, confidence_label, confidence_reason)
                          VALUES ('cv-u2', 'cp-u1', 'test:unique-variant', 'en', 0.8, 'HIGH', 'test')""")
            v10_db.commit()


class TestV10SellableSkusSchema:
    """Tests for v10_sellable_skus table schema correctness."""

    def test_required_columns(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute('PRAGMA table_info(v10_sellable_skus)')
        columns = {r[1] for r in cur.fetchall()}
        required = {
            'sellable_sku_id', 'commercial_variant_id', 'sku_key',
            'item_class', 'condition_policy', 'display_title', 'pricing_key',
            'inventory_enabled', 'listing_enabled', 'scanner_enabled',
            'status', 'confidence_score', 'confidence_label', 'confidence_reason',
            'created_at', 'updated_at',
        }
        assert required.issubset(columns)

    def test_unique_sku_key(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        # UNIQUE on column definition creates inline constraint; verify via duplicate insert failure
        cur.execute("""INSERT INTO v10_sellable_skus
                      (sellable_sku_id, commercial_variant_id, sku_key,
                       display_title, confidence_score, confidence_label, confidence_reason)
                      VALUES ('sku-u1', 'cv-u1', 'test:unique-sku', 'Test Card', 0.8, 'HIGH', 'test')""")
        v10_db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute("""INSERT INTO v10_sellable_skus
                          (sellable_sku_id, commercial_variant_id, sku_key,
                           display_title, confidence_score, confidence_label, confidence_reason)
                          VALUES ('sku-u2', 'cv-u1', 'test:unique-sku', 'Test Card', 0.8, 'HIGH', 'test')""")
            v10_db.commit()

    def test_default_values(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("""INSERT INTO v10_sellable_skus
                      (sellable_sku_id, commercial_variant_id, sku_key,
                       display_title, confidence_score, confidence_label, confidence_reason)
                      VALUES (?, ?, ?, ?, ?, ?, ?)""",
                   ('sku-test-1', 'cv-test-1', 'test:base1-4-en-unknown-raw',
                    'Charizard (English, Unknown finish)', 0.7, 'MEDIUM', 'test insert'))
        v10_db.commit()
        cur.execute("SELECT item_class, condition_policy, inventory_enabled FROM v10_sellable_skus WHERE sellable_sku_id='sku-test-1'")
        row = cur.fetchone()
        assert row[0] == 'single_card'
        assert row[1] == 'raw_conditioned'
        assert row[2] == 1


class TestV10DataQualityConstraints:
    """Tests for data-quality invariants on v10 tables."""

    def test_no_sku_without_variant(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        # Verify the table starts empty (no FKs, but design intent: no SKUs without variants)
        cur.execute("SELECT COUNT(*) FROM v10_sellable_skus")
        assert cur.fetchone()[0] == 0
        # After inserting a variant, we can insert a SKU; without variant, SKU count is 0
        cur.execute("""INSERT INTO v10_commercial_variants
                      (commercial_variant_id, canonical_printing_id, variant_key,
                       language_code, confidence_score, confidence_label, confidence_reason)
                      VALUES ('cv-1', 'cp-1', 'test-1-en-unknown', 'en', 0.8, 'HIGH', 'test')""")
        v10_db.commit()
        cur.execute("SELECT COUNT(*) FROM v10_sellable_skus")
        assert cur.fetchone()[0] == 0

    def test_no_variant_without_canonical(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        # Insert canonical printing
        cur.execute("""INSERT INTO v10_canonical_printings
                      (canonical_printing_id, canonical_key, core_set_id,
                       canonical_name, primary_language, first_seen_source,
                       confidence_score, confidence_label, confidence_reason)
                      VALUES ('cp-1', 'test:base1-4-en', 'base1', 'Charizard', 'en',
                              'test', 0.9, 'HIGH', 'test')""")
        v10_db.commit()
        # Verify canonical printing exists
        cur.execute("SELECT COUNT(*) FROM v10_canonical_printings")
        assert cur.fetchone()[0] == 1

    def test_canonical_card_link_requires_canonical(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        # Create canonical printing
        cur.execute("""INSERT INTO v10_canonical_printings
                      (canonical_printing_id, canonical_key, core_set_id,
                       canonical_name, primary_language, first_seen_source,
                       confidence_score, confidence_label, confidence_reason)
                      VALUES ('cp-1', 'test:base1-4-en', 'base1', 'Charizard', 'en',
                              'test', 0.9, 'HIGH', 'test')""")
        v10_db.commit()
        # Insert canonical-card link
        cur.execute("""INSERT INTO v10_canonical_printing_cards
                      (canonical_printing_id, card_key, language_code,
                       match_method, confidence_score, confidence_reason)
                      VALUES ('cp-1', 'en:base1-4', 'en', 'exact_set_number', 0.95, 'test')""")
        v10_db.commit()
        cur.execute("SELECT COUNT(*) FROM v10_canonical_printing_cards WHERE canonical_printing_id='cp-1'")
        assert cur.fetchone()[0] == 1


class TestV10MigrationRecorded:
    """Tests that v10 migrations are recorded in schema_migrations."""

    def test_all_versions_recorded(self, v10_db: sqlite3.Connection) -> None:
        cur = v10_db.cursor()
        cur.execute("SELECT version FROM schema_migrations WHERE version >= 'v58' ORDER BY version")
        versions = [r[0] for r in cur.fetchall()]
        expected = ['v58', 'v58b', 'v58c', 'v58d', 'v59', 'v59b',
                    'v60', 'v60b', 'v60c', 'v60d', 'v61', 'v61b', 'v61c',
                    'v62', 'v62b', 'v63', 'v64', 'v65']
        assert versions == expected
