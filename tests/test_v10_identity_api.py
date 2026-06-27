"""Tests for v10 identity API endpoints."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import os
os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)

from pokemon_db_v3_config import PokemonDBSettings
from pokemon_db_v2_fastapi import create_app

# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with a fresh DB containing the production schema."""
    db_path = tmp_path / 'test_api.db'
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=60000')
    # Minimal schema to satisfy app startup checks
    conn.executescript("""
        CREATE TABLE v2_card_search_fts (card_key TEXT PRIMARY KEY);
        CREATE TABLE v2_card_detail_api_cache (
            language_code TEXT, language_name TEXT, card_id TEXT,
            raw_set_id TEXT, resolved_set_id TEXT, core_set_id TEXT,
            core_set_name TEXT, local_id TEXT, local_id_sort INT,
            card_name TEXT, category TEXT, rarity TEXT, variants TEXT
        );
        CREATE TABLE cards (language_code TEXT, set_id TEXT, card_id TEXT,
            local_id TEXT, local_id_sort INT, name TEXT, image_url TEXT);
        CREATE TABLE sets (language_code TEXT, set_id TEXT, name TEXT);
        CREATE TABLE schema_migrations (id INTEGER PRIMARY KEY,
            version TEXT UNIQUE, applied_at TEXT, description TEXT);
    """)
    # v10 migrations
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS v10_canonical_printings (
            canonical_printing_id TEXT PRIMARY KEY,
            canonical_key TEXT UNIQUE NOT NULL,
            game TEXT NOT NULL DEFAULT 'pokemon_tcg',
            core_set_id TEXT NOT NULL, set_id TEXT, set_code TEXT,
            collector_number TEXT, collector_number_sort TEXT,
            canonical_name TEXT NOT NULL, name_english TEXT,
            primary_language TEXT NOT NULL, card_kind TEXT, rarity TEXT,
            first_seen_source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            confidence_score REAL NOT NULL, confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v10_canonical_printing_cards (
            canonical_printing_id TEXT NOT NULL, card_key TEXT NOT NULL,
            language_code TEXT NOT NULL, source_card_id TEXT,
            match_method TEXT NOT NULL, confidence_score REAL NOT NULL,
            confidence_reason TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (canonical_printing_id, card_key)
        );
        CREATE TABLE IF NOT EXISTS v10_commercial_variants (
            commercial_variant_id TEXT PRIMARY KEY,
            canonical_printing_id TEXT NOT NULL, variant_key TEXT UNIQUE NOT NULL,
            language_code TEXT NOT NULL, finish TEXT NOT NULL DEFAULT 'unknown',
            variant_type TEXT NOT NULL DEFAULT 'standard', stamp TEXT, edition TEXT,
            is_reverse_holo INTEGER NOT NULL DEFAULT 0, is_holo INTEGER,
            is_promo INTEGER NOT NULL DEFAULT 0, market_region TEXT,
            status TEXT NOT NULL DEFAULT 'active', confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL, confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v10_sellable_skus (
            sellable_sku_id TEXT PRIMARY KEY, commercial_variant_id TEXT NOT NULL,
            sku_key TEXT UNIQUE NOT NULL, item_class TEXT NOT NULL DEFAULT 'single_card',
            condition_policy TEXT NOT NULL DEFAULT 'raw_conditioned',
            display_title TEXT NOT NULL, pricing_key TEXT,
            inventory_enabled INTEGER NOT NULL DEFAULT 1,
            listing_enabled INTEGER NOT NULL DEFAULT 1,
            scanner_enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active', confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL, confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v10_external_references (
            external_reference_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            source_name TEXT NOT NULL, source_entity_type TEXT,
            source_identifier TEXT NOT NULL, source_url TEXT,
            match_method TEXT NOT NULL, confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL, confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(entity_type, entity_id, source_name, source_identifier)
        );
        CREATE TABLE IF NOT EXISTS v10_identity_build_runs (
            build_run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
            finished_at TEXT, status TEXT NOT NULL, source_db_path TEXT,
            algorithm_version TEXT NOT NULL DEFAULT '1.0.0',
            cards_seen INTEGER DEFAULT 0,
            canonical_printings_created INTEGER DEFAULT 0,
            commercial_variants_created INTEGER DEFAULT 0,
            sellable_skus_created INTEGER DEFAULT 0,
            external_references_created INTEGER DEFAULT 0,
            warnings_count INTEGER DEFAULT 0, errors_count INTEGER DEFAULT 0, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS v10_identity_build_events (
            event_id TEXT PRIMARY KEY, build_run_id TEXT NOT NULL,
            severity TEXT NOT NULL, entity_type TEXT, entity_id TEXT,
            message TEXT NOT NULL, details_json TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v10_inventory_sku_links (
            link_id TEXT PRIMARY KEY, sellable_sku_id TEXT NOT NULL,
            legacy_sku_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(sellable_sku_id, legacy_sku_id)
        );
    """)
    conn.commit()
    conn.close()

    settings = PokemonDBSettings(db=db_path, skip_search_setup=True, require_api_key=False)
    test_app = create_app(settings)
    with TestClient(test_app) as c:
        yield c


# ── Tests ──────────────────────────────────────────────────────────────

class TestIdentityHealth:
    def test_health_returns_zero_counts(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/health')
        assert response.status_code == 200
        data = response.json()
        assert data['canonical_printings'] == 0
        assert data['commercial_variants'] == 0
        assert data['last_build_run'] is None

    def test_health_structure(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/health')
        data = response.json()
        expected_keys = {
            'canonical_printings', 'card_links', 'commercial_variants',
            'sellable_skus', 'external_references', 'build_runs',
            'high_confidence', 'medium_confidence', 'low_confidence',
        }
        assert expected_keys.issubset(set(data.keys()))

    def test_health_has_data(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/health')
        assert 'canonical_printings' in response.json()


class TestIdentityCanonicalPrintings:
    def test_empty_list(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/canonical-printings')
        assert response.status_code == 200
        data = response.json()
        assert 'data' in data
        assert data['data'] == []

    def test_list_meta_present(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/canonical-printings')
        assert 'meta' in response.json()
        assert response.json()['meta']['limit'] == 50

    def test_filter_by_core_set_id(self, client: TestClient) -> None:
        response = client.get(f'/api/v1/identity/canonical-printings?core_set_id=base1')
        assert response.status_code == 200
        assert response.json()['data'] == []


class TestIdentitySellableSKUs:
    def test_empty_skus_list(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/sellable-skus')
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_sku_list_meta(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/sellable-skus')
        data = response.json()
        assert 'meta' in data
        assert data['meta']['limit'] == 50

    def test_filter_by_item_class(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/sellable-skus?item_class=single_card')
        assert response.status_code == 200


class TestMissingEntity:
    def test_canonical_printing_not_found(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/canonical-printings/nonexistent-id-xyz')
        assert response.status_code in (404, 422)
        data = response.json()
        assert 'detail' in data or 'error' in data

    def test_sku_not_found(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/sellable-skus/nonexistent-id-xyz')
        assert response.status_code in (404, 422)
        data = response.json()
        assert 'detail' in data or 'error' in data


class TestIdentityCardLookup:
    def test_unmapped_card_returns_warning(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/cards/en:nonexistent-card-xyz')
        assert response.status_code == 200
        data = response.json()
        assert data['data']['mapped'] is False
        assert len(data['data']['warnings']) > 0

    def test_card_key_path_encoded(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/cards/en%3Atest%2Fcard-1')
        assert response.status_code == 200
        data = response.json()
        assert data['data']['card_key'] == 'en:test/card-1'


class TestIdentityExternalReferences:
    def test_empty_references(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/external-references')
        assert response.status_code == 200
        data = response.json()
        assert data['data'] == []

    def test_filter_by_entity_type(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/external-references?entity_type=canonical_printing')
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_references_meta(self, client: TestClient) -> None:
        response = client.get('/api/v1/identity/external-references')
        assert 'meta' in response.json()
        assert response.json()['meta']['count'] == 0
