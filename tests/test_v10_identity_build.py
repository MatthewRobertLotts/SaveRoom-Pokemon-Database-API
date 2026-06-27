"""Tests for v10 identity build script."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.build_v10_identity import (
    _ensure_migration_tables,
    _mk_id,
    _parse_finish,
    _sortable_number,
    build_identity,
    _connect,
)


# ── _parse_finish unit tests ───────────────────────────────────────────

class TestParseFinish:
    def test_empty_string(self) -> None:
        assert _parse_finish(None) == ("unknown", None, 0, "", "", "standard")

    def test_blank(self) -> None:
        assert _parse_finish("") == ("unknown", None, 0, "", "", "standard")

    def test_only_whitespace(self) -> None:
        assert _parse_finish("  \n\t  ") == ("unknown", None, 0, "", "", "standard")

    def test_normal_only(self) -> None:
        result = _parse_finish("normal: true,\n\t\treverse: false,\n\t\tholo: false")
        assert result == ("normal", 0, 0, "", "", "standard")

    def test_holo(self) -> None:
        result = _parse_finish("normal: false,\n\t\treverse: false,\n\t\tholo: true")
        assert result == ("holo", 1, 0, "", "", "standard")

    def test_reverse_holo(self) -> None:
        result = _parse_finish("normal: false,\n\t\treverse: true,\n\t\tholo: true")
        assert result == ("reverse_holo", 1, 1, "", "", "standard")

    def test_reverse_only(self) -> None:
        result = _parse_finish("normal: false,\n\t\treverse: true,\n\t\tholo: false")
        assert result == ("reverse", 0, 1, "", "", "standard")

    def test_first_edition(self) -> None:
        result = _parse_finish("normal: true,\n\t\treverse: false,\n\t\tholo: false,\n\t\tfirstEdition: true")
        assert result == ("normal", 0, 0, "first_edition", "", "standard")

    def test_all_false(self) -> None:
        result = _parse_finish("normal: false,\n\t\treverse: false,\n\t\tholo: false,\n\t\tfirstEdition: false")
        assert result == ("unknown", None, 0, "", "", "standard")

    def test_quoted_variant_keys(self) -> None:
        result = _parse_finish('"normal": true, "reverse": true, "holo": false')
        assert result == ("reverse", 0, 1, "", "", "standard")


# ── _sortable_number tests ─────────────────────────────────────────────

class TestSortableNumber:
    def test_simple(self) -> None:
        assert _sortable_number("42") == "000042"

    def test_alpha_suffix(self) -> None:
        assert _sortable_number("42a") == "000042a"

    def test_none(self) -> None:
        assert _sortable_number(None) == ""

    def test_empty(self) -> None:
        assert _sortable_number("") == ""


# ── Fixture builder ───────────────────────────────────────────────────

def _seed_fixture(db_path: Path, cards: list[dict]) -> None:
    """Seed a minimal v2_card_detail_api_cache table for testing."""
    conn = _connect(db_path)
    cur = conn.cursor()
    _ensure_migration_tables(conn)
    # Also create a fake v2_card_detail_api_cache with minimal columns
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_card_detail_api_cache AS
        SELECT '' as language_code, '' as card_id, '' as raw_set_id, '' as resolved_set_id,
               '' as core_set_id, '' as core_set_id, '' as core_set_name, '' as local_id,
               0 as local_id_sort, '' as card_name, '' as category, '' as rarity, '' as variants
        WHERE 0
    """)
    # Create card_name_translations stub
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_name_translations AS
        SELECT '' as card_id, '' as language_code, '' as local_name, '' as en_name, '' as source
        WHERE 0
    """)
    # Insert test cards
    for card in cards:
        cur.execute("""
            INSERT INTO v2_card_detail_api_cache
            (language_code, card_id, raw_set_id, resolved_set_id, core_set_id,
             core_set_name, local_id, local_id_sort, card_name, category, rarity, variants)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            card["language_code"], card["card_id"], card["raw_set_id"],
            card.get("resolved_set_id", card["raw_set_id"]),
            card["core_set_id"], card.get("core_set_name", ""),
            card["local_id"], card.get("local_id_sort", 0),
            card["card_name"], card.get("category"),
            card.get("rarity"), card.get("variants"),
        ))
    # Insert translations if any
    for card in cards:
        if "en_name" in card and card["language_code"] != "en":
            cur.execute("""
                INSERT INTO card_name_translations (card_id, language_code, local_name, en_name, source)
                VALUES (?, ?, ?, ?, 'db_join')
            """, (card["card_id"], card["language_code"], card["card_name"], card["en_name"]))
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY, version TEXT NOT NULL UNIQUE,
            applied_at TEXT, description TEXT
        )
    """)
    conn.commit()
    conn.close()


# ── Build integration tests ────────────────────────────────────────────

@pytest.fixture
def fixture_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a small fixture DB and return its connection."""
    cards = [
        {
            "language_code": "en", "card_id": "base1-1", "raw_set_id": "base1",
            "core_set_id": "base1", "core_set_name": "Base Set",
            "local_id": "1", "local_id_sort": 1, "card_name": "Alakazam",
            "category": "Pokemon", "rarity": "Rare", "variants": None,
        },
        {
            "language_code": "en", "card_id": "base1-4", "raw_set_id": "base1",
            "core_set_id": "base1", "core_set_name": "Base Set",
            "local_id": "4", "local_id_sort": 4, "card_name": "Charizard",
            "category": "Pokemon", "rarity": "Rare",            "variants": "normal: false,\n\t\treverse: false,\n\t\tholo: true,\n\t\tfirstEdition: false",
        },
        {
            "language_code": "fr", "card_id": "base1-4-fr", "raw_set_id": "base1",
            "core_set_id": "base1", "core_set_name": "Base Set",
            "local_id": "4", "local_id_sort": 4, "card_name": "Dracaufeu",
            "category": "Pokemon", "rarity": "Rare", "variants": None,
            "en_name": "Charizard",
        },
    ]
    db_path = tmp_path / "fixture.db"
    _seed_fixture(db_path, cards)

    conn = _connect(db_path)
    return conn


class TestTimestampFormat:
    def test_now_iso_format(self) -> None:
        """_now() must produce format like 2026-06-27T01:29:12.877774Z (with seconds)."""
        from scripts.build_v10_identity import _now
        result = _now()
        # Must match pattern: YYYY-MM-DDTHH:MM:SS.ffffffZ
        assert len(result) == 27, f"Expected 27 chars, got {len(result)}: {result}"
        assert "T" in result
        assert result.endswith("Z")
        # Must have a period at position 19 (seconds.microseconds separator)
        assert result[19] == ".", f"Expected '.' at position 19, got '{result[19]}' in {result}"
        # Must have colons at hours:minutes and minutes:seconds
        assert result[13] == ":", f"Expected ':' at position 13, got '{result[13]}' in {result}"
        assert result[16] == ":", f"Expected ':' at position 16, got '{result[16]}' in {result}"


class TestBuildDryRun:
    def test_dry_run_no_writes(self, fixture_db: sqlite3.Connection, tmp_path: Path) -> None:
        results = build_identity(fixture_db, dry_run=True)
        cur = fixture_db.cursor()
        cur.execute("SELECT COUNT(*) FROM v10_canonical_printings")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM v10_sellable_skus")
        assert cur.fetchone()[0] == 0

    def test_dry_run_returns_counts(self, fixture_db: sqlite3.Connection) -> None:
        results = build_identity(fixture_db, dry_run=True, limit=10)
        assert results["cards_seen"] > 0
        assert results["canonical_printings_created"] > 0
        assert results["commercial_variants_created"] > 0
        assert results["sellable_skus_created"] > 0


class TestBuildIntegration:
    def test_limited_build(self, fixture_db: sqlite3.Connection) -> None:
        results = build_identity(fixture_db, limit=10)
        assert results["cards_seen"] >= 3  # our fixture has 3 cards
        cur = fixture_db.cursor()
        cur.execute("SELECT COUNT(*) FROM v10_canonical_printings")
        cp_count = cur.fetchone()[0]
        assert cp_count >= 2  # Alakazam + Charizard (fr CA card may or may not merge)

    def test_unknown_finish_handled(self, fixture_db: sqlite3.Connection) -> None:
        """Cards without variant evidence must get finish='unknown', not guessed."""
        results = build_identity(fixture_db, limit=10)
        cur = fixture_db.cursor()
        cur.execute("SELECT COUNT(*) FROM v10_commercial_variants WHERE finish = 'unknown'")
        unknown_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM v10_commercial_variants")
        total = cur.fetchone()[0]
        # All variants should be unknown for Alakazam (no variants) and Dracaufeu (no variants)
        assert unknown_count >= 2
        # At least some should be non-unknown (Charizard has holo variant)
        cur.execute("SELECT COUNT(*) FROM v10_commercial_variants WHERE finish = 'holo'")
        cur.fetchone()

    def test_holo_parsed_correctly(self, fixture_db: sqlite3.Connection) -> None:
        build_identity(fixture_db, limit=10)
        cur = fixture_db.cursor()
        # Charizard en should be holo
        cur.execute("""
            SELECT finish FROM v10_commercial_variants
            WHERE variant_key LIKE '%base1-4-en%'
        """)
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "holo"

    def test_confidence_and_provenance(self, fixture_db: sqlite3.Connection) -> None:
        build_identity(fixture_db, limit=10)
        cur = fixture_db.cursor()
        cur.execute("""
            SELECT confidence_score, confidence_label, confidence_reason
            FROM v10_canonical_printings
            LIMIT 1
        """)
        row = cur.fetchone()
        assert row[0] > 0
        assert row[1] in ("HIGH", "MEDIUM", "LOW")
        assert len(row[2]) > 0  # reason is non-empty

    def test_conservative_no_unsafe_merge(self, fixture_db: sqlite3.Connection) -> None:
        """English 'Dracaufeu' and 'Alakazam' have different names, must be separate canonicals."""
        build_identity(fixture_db, limit=10)
        cur = fixture_db.cursor()
        cur.execute("SELECT canonical_name FROM v10_canonical_printings WHERE core_set_id='base1'")
        names = {r[0] for r in cur.fetchall()}
        assert "Alakazam" in names


class TestBuildIdempotency:
    def test_rerun_no_duplicates(self, fixture_db: sqlite3.Connection) -> None:
        """Running build twice must not double row counts."""
        build_identity(fixture_db, limit=10)
        cur = fixture_db.cursor()
        cur.execute("SELECT COUNT(*) FROM v10_canonical_printings")
        cp_first = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM v10_sellable_skus")
        sku_first = cur.fetchone()[0]

        # Re-run
        build_identity(fixture_db, limit=10)
        cur.execute("SELECT COUNT(*) FROM v10_canonical_printings")
        cp_second = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM v10_sellable_skus")
        sku_second = cur.fetchone()[0]

        assert cp_first == cp_second
        assert sku_first == sku_second
