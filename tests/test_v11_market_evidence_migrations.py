"""Tests for v11 market evidence schema migrations.

Verifies that migrations are idempotent, create all expected tables
and indexes, and preserve existing data on rerun.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pricing_sources.migrations import apply_v11_migrations, V11_MIGRATIONS


@pytest.fixture
def db(tmp_path):
    """Create a fresh SQLite database for migration testing."""
    conn = sqlite3.connect(str(tmp_path / "test_v11.sqlite"))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


@pytest.fixture
def migrated_db(db):
    """Apply v11 migrations to a fresh database."""
    apply_v11_migrations(db)
    return db


class TestV11MigrationCreation:
    """Test that migrations create all expected tables and indexes."""

    def test_all_migrations_have_unique_versions(self):
        versions = [m[0] for m in V11_MIGRATIONS]
        assert len(versions) == len(set(versions)), "Duplicate migration versions"

    def test_migrations_are_sorted(self):
        versions = [m[0] for m in V11_MIGRATIONS]
        # Simple version sort check (v66, v67, v67b, v68, ...)
        assert versions == sorted(versions), "Migrations not in sorted order"

    def test_all_migrations_have_descriptions(self):
        for version, sql, desc in V11_MIGRATIONS:
            assert desc, f"Migration {version} missing description"
            assert len(desc) > 5, f"Migration {version} description too short"

    def test_expected_table_migrations_present(self):
        """Verify that all 7 base table migrations exist."""
        table_versions = [f"v{i}" for i in range(66, 73)]
        versions = [m[0] for m in V11_MIGRATIONS]
        for tv in table_versions:
            assert tv in versions, f"Missing base table migration: {tv}"


class TestV11MigrationApplication:
    """Test that migrations apply correctly to a database."""

    def test_migrations_create_tables(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'v11_%'")
        tables = {r[0] for r in cur.fetchall()}
        expected = {
            'v11_price_sources',
            'v11_price_source_cache',
            'v11_price_observations',
            'v11_price_observation_matches',
            'v11_price_aggregates',
            'v11_price_refresh_runs',
            'v11_price_source_health',
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_migrations_create_indexes(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_v11_%'")
        indexes = {r[0] for r in cur.fetchall()}
        # Check a sample of critical indexes
        expected_indexes = {
            'idx_v11_psc_source_record',
            'idx_v11_po_source',
            'idx_v11_po_canonical',
            'idx_v11_po_variant',
            'idx_v11_po_sku',
            'idx_v11_pom_target',
            'idx_v11_pa_target',
            'idx_v11_prr_source',
            'idx_v11_psh_source',
        }
        assert expected_indexes.issubset(indexes), f"Missing indexes: {expected_indexes - indexes}"

    def test_migrations_record_in_schema_migrations(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("SELECT version FROM schema_migrations WHERE version LIKE 'v11%' OR version LIKE 'v6%' OR version LIKE 'v7%'")
        applied = {r[0] for r in cur.fetchall()}
        # v66-v72 should be recorded
        for v in ['v66', 'v67', 'v68', 'v69', 'v70', 'v71', 'v72']:
            assert v in applied, f"Migration {v} not recorded in schema_migrations"

    def test_source_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_sources)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'source_id', 'source_code', 'source_name', 'source_url',
            'api_key_required', 'base_currency', 'default_condition',
            'default_listing_type', 'capabilities_json', 'is_enabled',
            'created_at', 'updated_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_cache_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_source_cache)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'cache_id', 'source_id', 'source_record_id', 'fetched_at',
            'ttl_hours', 'raw_payload_json', 'payload_hash',
            'query_params_json', 'http_status', 'created_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_observations_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_observations)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'observation_id', 'source_id', 'source_record_id', 'observed_at',
            'fetched_at', 'currency', 'amount', 'condition', 'finish',
            'printing_label', 'language', 'marketplace', 'listing_type',
            'raw_title', 'raw_url', 'raw_payload_ref', 'observation_type',
            'canonical_printing_id', 'commercial_variant_id', 'sellable_sku_id',
            'match_confidence', 'match_reason', 'is_usable_for_aggregate',
            'created_at', 'updated_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_matches_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_observation_matches)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'match_id', 'observation_id', 'target_type', 'target_id',
            'match_confidence', 'match_reason', 'match_method',
            'source_set_code', 'source_collector_number', 'source_variant',
            'source_language', 'condition_matched', 'finish_matched', 'created_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_aggregates_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_aggregates)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'aggregate_id', 'target_type', 'target_id', 'currency',
            'listing_type', 'finish', 'median_price', 'low_price', 'high_price',
            'mean_price', 'observation_count', 'source_count', 'freshness_days',
            'confidence_label', 'confidence_score', 'confidence_reason',
            'computed_at', 'created_at', 'updated_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_refresh_runs_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_refresh_runs)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'run_id', 'source_id', 'target_type', 'target_id',
            'started_at', 'completed_at', 'status',
            'observations_created', 'observations_updated', 'observations_skipped',
            'cache_rows_created', 'error_message', 'error_details', 'created_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_source_health_table_has_expected_columns(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute("PRAGMA table_info(v11_price_source_health)")
        cols = {r[1] for r in cur.fetchall()}
        expected = {
            'health_id', 'source_id', 'checked_at', 'status',
            'last_success_at', 'last_failure_at', 'consecutive_failures',
            'rate_limit_remaining', 'rate_limit_reset_at', 'avg_response_ms',
            'last_error_code', 'last_error_message', 'created_at', 'updated_at'
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"


class TestV11MigrationIdempotency:
    """Test that migrations can be safely rerun."""

    def test_rerun_is_noop(self, migrated_db):
        """Running migrations again should apply nothing."""
        applied = apply_v11_migrations(migrated_db)
        assert applied == [], f"Rerun applied unexpected migrations: {applied}"

    def test_rerun_preserves_data(self, migrated_db):
        """Rerun should not delete or modify existing data."""
        cur = migrated_db.cursor()
        # Insert a source
        cur.execute(
            "INSERT INTO v11_price_sources (source_id, source_code, source_name) VALUES (?, ?, ?)",
            ('test-1', 'test_source', 'Test Source')
        )
        cur.execute(
            "INSERT INTO v11_price_observations (source_id, source_record_id, observed_at, currency, amount, listing_type) VALUES (?, ?, ?, ?, ?, ?)",
            ('test-1', 'card-1', '2026-06-27T00:00:00Z', 'USD', 10.0, 'market_price')
        )
        migrated_db.commit()

        # Rerun migrations
        apply_v11_migrations(migrated_db)

        # Verify data still exists
        cur.execute("SELECT COUNT(*) FROM v11_price_sources WHERE source_id = 'test-1'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM v11_price_observations WHERE source_id = 'test-1'")
        assert cur.fetchone()[0] == 1

    def test_rerun_on_already_migrated_db(self, db):
        """Apply migrations twice, second time should be empty."""
        applied1 = apply_v11_migrations(db)
        assert len(applied1) > 0, "First run should apply migrations"

        applied2 = apply_v11_migrations(db)
        assert applied2 == [], "Second run should apply nothing"

    def test_migration_versions_start_at_66(self):
        """Verify v11 migrations start at v66 (after v10's v65)."""
        versions = [m[0] for m in V11_MIGRATIONS if len(m[0]) == 3 and m[0][1:].isdigit()]
        base_versions = [int(v[1:]) for v in versions]
        assert min(base_versions) >= 66, "v11 migrations should start at v66"


class TestV11ForeignKeyIntegrity:
    """Test that foreign key relationships work correctly."""

    def test_cache_references_source(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute(
            "INSERT INTO v11_price_sources (source_id, source_code, source_name) VALUES (?, ?, ?)",
            ('src-1', 'test_src', 'Test')
        )
        cur.execute(
            "INSERT INTO v11_price_source_cache (source_id, source_record_id, raw_payload_json, payload_hash) VALUES (?, ?, ?, ?)",
            ('src-1', 'card-1', '{"test": true}', 'abc123')
        )
        migrated_db.commit()
        cur.execute("SELECT COUNT(*) FROM v11_price_source_cache WHERE source_id = 'src-1'")
        assert cur.fetchone()[0] == 1

    def test_observation_references_source(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute(
            "INSERT INTO v11_price_sources (source_id, source_code, source_name) VALUES (?, ?, ?)",
            ('src-2', 'test_src2', 'Test2')
        )
        cur.execute(
            "INSERT INTO v11_price_observations (source_id, source_record_id, observed_at, currency, amount, listing_type) VALUES (?, ?, ?, ?, ?, ?)",
            ('src-2', 'card-2', '2026-06-27T00:00:00Z', 'USD', 5.0, 'market_price')
        )
        migrated_db.commit()
        cur.execute("SELECT amount FROM v11_price_observations WHERE source_id = 'src-2'")
        assert cur.fetchone()[0] == 5.0

    def test_match_references_observation(self, migrated_db):
        cur = migrated_db.cursor()
        cur.execute(
            "INSERT INTO v11_price_sources (source_id, source_code, source_name) VALUES (?, ?, ?)",
            ('src-3', 'test_src3', 'Test3')
        )
        cur.execute(
            "INSERT INTO v11_price_observations (source_id, source_record_id, observed_at, currency, amount, listing_type) VALUES (?, ?, ?, ?, ?, ?)",
            ('src-3', 'card-3', '2026-06-27T00:00:00Z', 'USD', 5.0, 'market_price')
        )
        obs_id = cur.lastrowid
        cur.execute(
            "INSERT INTO v11_price_observation_matches (observation_id, target_type, target_id, match_confidence, match_reason, match_method) VALUES (?, ?, ?, ?, ?, ?)",
            (obs_id, 'canonical_printing', 'cp-test', 'HIGH', 'test match', 'set_code+collector_number')
        )
        migrated_db.commit()
        cur.execute("SELECT COUNT(*) FROM v11_price_observation_matches WHERE observation_id = ?", (obs_id,))
        assert cur.fetchone()[0] == 1
