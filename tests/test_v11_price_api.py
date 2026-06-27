"""Tests for v11 pricing evidence API endpoints.

Uses a seeded temporary database with v10 identity and v11 schema.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pricing_sources.migrations import apply_v11_migrations


@pytest.fixture
def v11_api_db(tmp_path):
    """Create a test database with v10 + v11 schema and sample data."""
    db_path = str(tmp_path / "test_v11_api.sqlite")
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
             '136', '000136', 'Furret', 'Furret', 'en', 'test', 0.85, 'HIGH', 'test'),
            ('cp-002', 'pk_tcg:sv03-125-en', 'sv03', 'sv03', 'sv03',
             '125', '000125', 'Charizard', 'Charizard', 'en', 'test', 0.85, 'HIGH', 'test');

        INSERT INTO v10_commercial_variants
            (commercial_variant_id, canonical_printing_id, variant_key, language_code,
             finish, variant_type, confidence_score, confidence_label, confidence_reason)
        VALUES
            ('cv-001', 'cp-001', 'swsh3-136-en-unknown', 'en', 'unknown', 'standard',
             0.8, 'HIGH', 'test'),
            ('cv-002', 'cp-002', 'sv03-125-en-unknown', 'en', 'unknown', 'standard',
             0.8, 'HIGH', 'test');

        INSERT INTO v10_sellable_skus
            (sellable_sku_id, commercial_variant_id, sku_key, item_class,
             display_title, confidence_score, confidence_label, confidence_reason)
        VALUES
            ('sku-001', 'cv-001', 'pk_tcg:swsh3-136-en-unknown-raw', 'single_card',
             'Furret (en, unknown)', 0.8, 'HIGH', 'test'),
            ('sku-002', 'cv-002', 'pk_tcg:sv03-125-en-unknown-raw', 'single_card',
             'Charizard (en, unknown)', 0.8, 'HIGH', 'test');

        INSERT INTO v2_card_detail_api_cache (language_code, card_id, name)
        VALUES ('en', 'swsh3-136', 'Furret'), ('en', 'sv03-125', 'Charizard');
    """)

    # Apply v11 migrations
    apply_v11_migrations(conn)

    # Insert a TCGdex source
    conn.execute(
        """INSERT INTO v11_price_sources
           (source_id, source_code, source_name, source_url, base_currency, is_enabled)
           VALUES ('src-tcgdex', 'tcgdex', 'TCGdex Market API', 'https://api.tcgdex.net', 'USD', 1)"""
    )

    # Insert sample observations
    conn.executescript("""
        INSERT INTO v11_price_observations
            (source_id, source_record_id, observed_at, currency, amount,
             finish, marketplace, listing_type, observation_type,
             canonical_printing_id, match_confidence, match_reason)
        VALUES
            ('src-tcgdex', 'swsh3-136:tcgplayer:normal', '2026-06-26T21:04:42Z',
             'USD', 0.11, 'normal', 'tcgplayer', 'market_price', 'market_price',
             'cp-001', 'HIGH', 'exact set+number'),
            ('src-tcgdex', 'swsh3-136:tcgplayer:reverse-holofoil', '2026-06-26T21:04:42Z',
             'USD', 0.37, 'reverse_holo', 'tcgplayer', 'market_price', 'market_price',
             'cp-001', 'HIGH', 'exact set+number'),
            ('src-tcgdex', 'swsh3-136:cardmarket:normal', '2026-06-26T21:03:30Z',
             'EUR', 0.12, 'normal', 'cardmarket', 'market_price', 'market_price',
             'cp-001', 'HIGH', 'exact set+number');

        INSERT INTO v11_price_observation_matches
            (observation_id, target_type, target_id, match_confidence, match_reason, match_method)
        VALUES
            (1, 'canonical_printing', 'cp-001', 'HIGH', 'exact set+number', 'set_code+collector_number'),
            (2, 'canonical_printing', 'cp-001', 'HIGH', 'exact set+number', 'set_code+collector_number'),
            (3, 'canonical_printing', 'cp-001', 'HIGH', 'exact set+number', 'set_code+collector_number');
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def v11_app(v11_api_db):
    """Create a minimal FastAPI app with v11 routes for testing."""
    from fastapi import FastAPI
    from pricing_sources.router import v11_pricing_router

    app = FastAPI()
    app.state.db = v11_api_db
    app.state.settings = None

    app.include_router(v11_pricing_router)
    return app


@pytest.fixture
def client(v11_app):
    return TestClient(v11_app)


class TestV11SourcesEndpoint:
    def test_list_sources(self, client):
        response = client.get("/api/v1/prices/sources")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1
        assert data[0]["source_code"] == "tcgdex"

    def test_get_source_health(self, client):
        response = client.get("/api/v1/prices/sources/tcgdex/health")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["source_code"] == "tcgdex"
        assert "status" in data

    def test_get_source_health_not_found(self, client):
        response = client.get("/api/v1/prices/sources/nonexistent/health")
        assert response.status_code == 404


class TestV11ObservationsEndpoint:
    def test_list_observations(self, client):
        response = client.get("/api/v1/prices/observations")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1
        assert "pagination" in response.json()

    def test_list_observations_with_filter(self, client):
        response = client.get("/api/v1/prices/observations?source_code=tcgdex")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1

    def test_list_observations_with_currency_filter(self, client):
        response = client.get("/api/v1/prices/observations?currency=USD")
        assert response.status_code == 200
        data = response.json()["data"]
        for obs in data:
            assert obs["currency"] == "USD"

    def test_list_observations_pagination(self, client):
        response = client.get("/api/v1/prices/observations?limit=2&offset=0")
        assert response.status_code == 200
        pagination = response.json()["pagination"]
        assert pagination["limit"] == 2

    def test_get_observation(self, client):
        response = client.get("/api/v1/prices/observations/1")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["observation_id"] == 1
        assert "matches" in data

    def test_get_observation_not_found(self, client):
        response = client.get("/api/v1/prices/observations/99999")
        assert response.status_code == 404


class TestV11AggregateEndpoint:
    def test_get_aggregate(self, client):
        response = client.get("/api/v1/prices/aggregate/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        # May be empty if no aggregates computed yet
        assert isinstance(data, list)

    def test_get_aggregate_with_currency(self, client):
        response = client.get("/api/v1/prices/aggregate/canonical_printing/cp-001?currency=USD")
        assert response.status_code == 200


class TestV11RefreshEndpoint:
    def test_refresh_returns_status(self, client):
        # This will try to fetch from TCGdex, which may fail in test env
        # We just check it returns a valid response structure
        response = client.post("/api/v1/prices/refresh/canonical_printing/cp-001")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "run_id" in data
        assert "status" in data
