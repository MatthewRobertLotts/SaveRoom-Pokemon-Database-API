"""Tests for v11 price matching and confidence logic.

Uses a seeded temporary database with v10 identity data.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from pricing_sources.matcher import (
    determine_match_confidence,
    find_canonical_printing,
    find_commercial_variant,
    find_sellable_sku,
    match_observation_to_identity,
)
from pricing_sources.base import MatchConfidence


@pytest.fixture
def v10_db(tmp_path):
    """Create a minimal v10 database for matching tests."""
    conn = sqlite3.connect(str(tmp_path / "test_v10.sqlite"))
    conn.execute("PRAGMA journal_keys=ON")

    # Create v10 tables
    conn.executescript("""
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
            stamp TEXT,
            edition TEXT,
            is_reverse_holo INTEGER NOT NULL DEFAULT 0,
            is_holo INTEGER,
            is_promo INTEGER NOT NULL DEFAULT 0,
            market_region TEXT,
            status TEXT NOT NULL DEFAULT 'active',
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
            condition_policy TEXT NOT NULL DEFAULT 'raw_conditioned',
            display_title TEXT NOT NULL,
            pricing_key TEXT,
            inventory_enabled INTEGER NOT NULL DEFAULT 1,
            listing_enabled INTEGER NOT NULL DEFAULT 1,
            scanner_enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
    """)

    # Insert test data: Charizard ex (swsh3-136 area)
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
             '125', '000125', 'Charizard', 'Charizard', 'en', 'test', 0.85, 'HIGH', 'test'),
            ('cp-003', 'pk_tcg:sv03-125-ja', 'sv03', 'sv03', 'sv03',
             '125', '000125', 'Charizard', 'リザードン', 'ja', 'test', 0.85, 'HIGH', 'test');

        INSERT INTO v10_commercial_variants
            (commercial_variant_id, canonical_printing_id, variant_key, language_code,
             finish, variant_type, confidence_score, confidence_label, confidence_reason)
        VALUES
            ('cv-001', 'cp-001', 'swsh3-136-en-unknown', 'en', 'unknown', 'standard',
             0.8, 'HIGH', 'test'),
            ('cv-002', 'cp-002', 'sv03-125-en-unknown', 'en', 'unknown', 'standard',
             0.8, 'HIGH', 'test'),
            ('cv-003', 'cp-002', 'sv03-125-en-holo', 'en', 'holo', 'standard',
             0.8, 'HIGH', 'test'),
            ('cv-004', 'cp-003', 'sv03-125-ja-unknown', 'ja', 'unknown', 'standard',
             0.8, 'HIGH', 'test');

        INSERT INTO v10_sellable_skus
            (sellable_sku_id, commercial_variant_id, sku_key, item_class,
             display_title, confidence_score, confidence_label, confidence_reason)
        VALUES
            ('sku-001', 'cv-001', 'pk_tcg:swsh3-136-en-unknown-raw', 'single_card',
             'Furret (en, unknown)', 0.8, 'HIGH', 'test'),
            ('sku-002', 'cv-002', 'pk_tcg:sv03-125-en-unknown-raw', 'single_card',
             'Charizard (en, unknown)', 0.8, 'HIGH', 'test'),
            ('sku-003', 'cv-003', 'pk_tcg:sv03-125-en-holo-raw', 'single_card',
             'Charizard (en, holo)', 0.8, 'HIGH', 'test');
    """)

    conn.commit()
    yield conn
    conn.close()


class TestFindCanonicalPrinting:
    def test_exact_set_and_number(self, v10_db):
        results = find_canonical_printing(v10_db, "swsh3", "136")
        assert len(results) == 1
        assert results[0][0] == "cp-001"
        assert results[0][1] == MatchConfidence.HIGH

    def test_set_and_number_no_match(self, v10_db):
        results = find_canonical_printing(v10_db, "swsh3", "999")
        assert results == []

    def test_set_and_name(self, v10_db):
        results = find_canonical_printing(v10_db, "sv03", None, card_name="Charizard")
        assert len(results) >= 1
        assert results[0][1] == MatchConfidence.MEDIUM

    def test_name_only(self, v10_db):
        results = find_canonical_printing(v10_db, None, None, card_name="Furret")
        assert len(results) >= 1
        assert results[0][1] == MatchConfidence.LOW

    def test_no_match(self, v10_db):
        results = find_canonical_printing(v10_db, None, None, card_name="NonexistentCard")
        assert results == []

    def test_empty_query(self, v10_db):
        results = find_canonical_printing(v10_db, None, None)
        assert results == []


class TestFindCommercialVariant:
    def test_with_language_and_finish(self, v10_db):
        results = find_commercial_variant(v10_db, "cp-002", "en", "holo")
        assert len(results) == 1
        assert results[0][0] == "cv-003"
        assert results[0][1] == MatchConfidence.HIGH

    def test_with_language_unknown_finish(self, v10_db):
        results = find_commercial_variant(v10_db, "cp-002", "en", "unknown")
        assert len(results) >= 1
        # Should match cv-002 (en, unknown)
        ids = [r[0] for r in results]
        assert "cv-002" in ids

    def test_with_language_no_finish(self, v10_db):
        results = find_commercial_variant(v10_db, "cp-002", "en", None)
        assert len(results) >= 1

    def test_no_language(self, v10_db):
        results = find_commercial_variant(v10_db, "cp-002", None, None)
        assert len(results) >= 1
        # All variants for cp-002
        ids = [r[0] for r in results]
        assert "cv-002" in ids
        assert "cv-003" in ids

    def test_no_variants(self, v10_db):
        # cp-003 only has one variant (ja, unknown)
        results = find_commercial_variant(v10_db, "cp-003", "en", "holo")
        assert len(results) == 0  # No en/holo variant for cp-003


class TestFindSellableSKU:
    def test_find_sku_for_variant(self, v10_db):
        results = find_sellable_sku(v10_db, "cv-001")
        assert len(results) == 1
        assert results[0][0] == "sku-001"

    def test_no_sku_for_variant(self, v10_db):
        results = find_sellable_sku(v10_db, "cv-999")
        assert results == []


class TestMatchObservationToIdentity:
    def test_full_match(self, v10_db):
        result = match_observation_to_identity(
            v10_db, "swsh3", "136", card_name="Furret", language="en"
        )
        assert len(result["canonical_printings"]) == 1
        assert result["canonical_printings"][0]["id"] == "cp-001"
        assert len(result["commercial_variants"]) >= 1
        assert len(result["sellable_skus"]) >= 1

    def test_name_only_match(self, v10_db):
        result = match_observation_to_identity(
            v10_db, None, None, card_name="Charizard"
        )
        assert len(result["canonical_printings"]) >= 1
        # Should match both en and ja Charizard
        ids = [cp["id"] for cp in result["canonical_printings"]]
        assert "cp-002" in ids

    def test_no_match(self, v10_db):
        result = match_observation_to_identity(
            v10_db, None, None, card_name="Nonexistent"
        )
        assert result["canonical_printings"] == []
        assert result["commercial_variants"] == []
        assert result["sellable_skus"] == []


class TestDetermineMatchConfidence:
    def test_high_all_match(self):
        conf, reason = determine_match_confidence(True, True, True, True, True)
        assert conf == MatchConfidence.HIGH
        assert "exact" in reason

    def test_medium_set_number_only(self):
        conf, reason = determine_match_confidence(True, True, True, False, False)
        assert conf == MatchConfidence.MEDIUM
        assert "set+number" in reason

    def test_medium_set_name(self):
        conf, reason = determine_match_confidence(True, False, True, False, False)
        assert conf == MatchConfidence.MEDIUM
        assert "set+name" in reason

    def test_low_name_only(self):
        conf, reason = determine_match_confidence(False, False, True, False, False)
        assert conf == MatchConfidence.LOW
        assert "name-only" in reason

    def test_unusable_no_match(self):
        conf, reason = determine_match_confidence(False, False, False, False, False)
        assert conf == MatchConfidence.UNUSABLE
        assert "no reliable" in reason
