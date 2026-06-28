"""Tests for v11.1 cross-source comparison API endpoint.

Uses a temporary SQLite DB with v11 aggregate rows.
No live providers. No secrets. No external calls.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from pricing_sources.migrations import apply_v11_migrations


@pytest.fixture
def comparison_api_db(tmp_path):
    """Create a test database with v10 + v11 schema and aggregate rows."""
    db_path = str(tmp_path / "test_comparison_api.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Create v10 tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS v10_canonical_printings (
            canonical_printing_id TEXT PRIMARY KEY,
            canonical_key TEXT UNIQUE NOT NULL,
            game TEXT NOT NULL DEFAULT 'pokemon_tcg',
            core_set_id TEXT NOT NULL,
            set_id TEXT,
            set_code TEXT,
            collector_number TEXT,
            collector_number_sort TEXT,
            canonical_name TEXT NOT NULL,
            name_english TEXT,
            primary_language TEXT NOT NULL,
            card_kind TEXT,
            rarity TEXT,
            first_seen_source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE IF NOT EXISTS v10_commercial_variants (
            commercial_variant_id TEXT PRIMARY KEY,
            canonical_printing_id TEXT NOT NULL,
            variant_key TEXT UNIQUE NOT NULL,
            language_code TEXT NOT NULL,
            finish TEXT NOT NULL DEFAULT 'unknown',
            variant_type TEXT NOT NULL DEFAULT 'standard',
            confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE IF NOT EXISTS v10_sellable_skus (
            sellable_sku_id TEXT PRIMARY KEY,
            commercial_variant_id TEXT NOT NULL,
            sku_key TEXT UNIQUE NOT NULL,
            item_class TEXT NOT NULL DEFAULT 'single_card',
            display_title TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE IF NOT EXISTS v2_card_detail_api_cache (
            language_code TEXT NOT NULL,
            card_id TEXT NOT NULL,
            name TEXT,
            PRIMARY KEY (language_code, card_id)
        );
    """)

    # Insert test data
    conn.executescript("""
        INSERT INTO v10_canonical_printings
            (canonical_printing_id, canonical_key, core_set_id, set_id, set_code,
             collector_number, collector_number_sort, canonical_name, name_english,
             primary_language, first_seen_source, confidence_score, confidence_label,
             confidence_reason)
        VALUES
            ('cp-001', 'pk_tcg:swsh3-136-en', 'swsh3', 'swsh3', 'swsh3',
             '136', '000136', 'Furret', 'Furret', 'en', 'test', 0.85, 'HIGH', 'test');

        INSERT INTO v10_commercial_variants
            (commercial_variant_id, canonical_printing_id, variant_key, language_code,
             finish, variant_type, confidence_score, confidence_label, confidence_reason)
        VALUES
            ('cv-001', 'cp-001', 'swsh3-136-en-unknown', 'en', 'unknown', 'standard',
             0.8, 'HIGH', 'test');

        INSERT INTO v10_sellable_skus
            (sellable_sku_id, commercial_variant_id, sku_key, item_class,
             display_title, confidence_score, confidence_label, confidence_reason)
        VALUES
            ('sku-001', 'cv-001', 'pk_tcg:swsh3-136-en-unknown-raw', 'single_card',
             'Furret (en, unknown)', 0.8, 'HIGH', 'test');

        INSERT INTO v2_card_detail_api_cache (language_code, card_id, name)
        VALUES ('en', 'swsh3-136', 'Furret');
    """)

    # Apply v11 migrations
    apply_v11_migrations(conn)

    # Insert two sources
    conn.executescript("""
        INSERT INTO v11_price_sources
            (source_id, source_code, source_name, source_url, base_currency, is_enabled)
        VALUES
            ('src-tcgdex', 'tcgdex', 'TCGdex Market API', 'https://api.tcgdex.net', 'USD', 1),
            ('src-justtcg', 'justtcg', 'JustTCG Pricing API', 'https://api.justtcg.com', 'USD', 1);
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def comparison_app(comparison_api_db):
    """Create a minimal FastAPI app with v11 routes for testing."""
    from fastapi import FastAPI
    from pricing_sources.router import v11_pricing_router

    app = FastAPI()
    app.state.db = comparison_api_db
    app.state.settings = None

    app.include_router(v11_pricing_router)
    return app


@pytest.fixture
def comparison_client(comparison_app):
    return TestClient(comparison_app)


def _insert_price(conn, *, source_id, currency, listing_type, finish,
                  condition, amount, canonical_printing_id="cp-001",
                  fetched_at="2026-06-26T00:00:00Z"):
    """Insert one observation so the comparison endpoint can read it."""
    conn.execute(
        """INSERT INTO v11_price_observations
           (source_id, source_record_id, observed_at, currency, amount,
            condition, finish, listing_type, observation_type,
            canonical_printing_id, match_confidence, match_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'market_price', ?, 'HIGH', 'test')""",
        (source_id, f"test-{source_id}-{finish}", fetched_at, currency,
         amount, condition, finish, listing_type, canonical_printing_id),
    )
    conn.commit()


class TestComparisonEndpoint:
    def test_endpoint_returns_200_for_known_target(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=10.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["target_type"] == "canonical_printing"
        assert data["target_id"] == "cp-001"

    def test_one_source_returns_insufficient_evidence(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=10.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["summary"]["source_count"] == 1
        assert data["summary"]["highest_disagreement"] == "INSUFFICIENT_EVIDENCE"
        assert "one source" in data["summary"]["confidence_note"].lower()

    def test_two_agreeing_sources_return_agree(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        _insert_price(conn, source_id="src-justtcg", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=105.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["summary"]["source_count"] == 2
        # Find the comparable comparison
        comparable = [c for c in data["comparisons"] if c["is_comparable"]]
        assert len(comparable) >= 1
        assert comparable[0]["agreement_band"] == "AGREE"

    def test_two_minor_disagreeing_sources(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        _insert_price(conn, source_id="src-justtcg", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=130.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        comparable = [c for c in data["comparisons"] if c["is_comparable"]]
        assert len(comparable) >= 1
        assert comparable[0]["agreement_band"] == "MINOR_DISAGREEMENT"

    def test_two_major_disagreeing_sources(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        _insert_price(conn, source_id="src-justtcg", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=180.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        comparable = [c for c in data["comparisons"] if c["is_comparable"]]
        assert len(comparable) >= 1
        assert comparable[0]["agreement_band"] == "MAJOR_DISAGREEMENT"

    def test_currency_mismatch_not_compared_as_equal(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        _insert_price(conn, source_id="src-justtcg", currency="EUR",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        # Same numeric value but different currencies should NOT be AGREE
        comparable = [c for c in data["comparisons"] if c["is_comparable"]]
        # Currency mismatch produces MIXED_SEMANTICS, not comparable
        assert len(comparable) == 0

    def test_listing_type_mismatch_not_compared(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        _insert_price(conn, source_id="src-justtcg", currency="USD",
                      listing_type="sold", finish="normal",
                      condition="unknown", amount=100.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        comparable = [c for c in data["comparisons"] if c["is_comparable"]]
        assert len(comparable) == 0

    def test_unknown_target_returns_empty_not_error(self, comparison_client):
        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-nonexistent")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["comparisons"] == []
        assert data["summary"]["source_count"] == 0

    def test_response_shape_has_required_fields(self, comparison_client, comparison_api_db):
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=100.0)
        _insert_price(conn, source_id="src-justtcg", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=110.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/comparison/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]

        # Check summary fields
        summary = data["summary"]
        assert "source_count" in summary
        assert "comparison_count" in summary
        assert "highest_disagreement" in summary
        assert "confidence_note" in summary

        # Check comparison row fields
        if data["comparisons"]:
            row = data["comparisons"][0]
            for field in [
                "source_a_id", "source_b_id", "currency", "listing_type",
                "finish", "condition", "source_a_median", "source_b_median",
                "absolute_difference", "percentage_difference",
                "agreement_band", "confidence_impact", "comparison_reason",
                "is_comparable",
            ]:
                assert field in row, f"Missing field: {field}"

    def test_existing_v11_aggregate_endpoint_still_works(self, comparison_client, comparison_api_db):
        """Ensure the existing aggregate endpoint is not broken."""
        conn = sqlite3.connect(comparison_api_db)
        _insert_price(conn, source_id="src-tcgdex", currency="USD",
                      listing_type="market_price", finish="normal",
                      condition="unknown", amount=10.0)
        conn.close()

        response = comparison_client.get("/api/v1/prices/aggregate/canonical_printing/cp-001")
        assert response.status_code == 200
        # Aggregate endpoint reads from v11_price_aggregates which is empty
        # (we only inserted observations). This is fine — the endpoint works.
        data = response.json()["data"]
        assert isinstance(data, list)
