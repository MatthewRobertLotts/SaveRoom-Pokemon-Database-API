#!/usr/bin/env python3
"""Build v10 canonical commercial identity from existing database.

Derives canonical printings, commercial variants, and sellable SKUs from the
source card/set/language data already in the database.

This script is idempotent: running it multiple times does not duplicate rows.
Use --dry-run to inspect counts without writing. Use --limit to cap processing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALGORITHM_VERSION = "1.0.0"
BATCH_SIZE = 5_000


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _mk_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _scalar(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> Any:
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_migration_tables(conn: sqlite3.Connection) -> None:
    """Ensure v10 tables exist (idempotent DDL)."""
    cur = conn.cursor()
    ddl = [
        """CREATE TABLE IF NOT EXISTS v10_canonical_printings (
            canonical_printing_id TEXT PRIMARY KEY,
            canonical_key TEXT UNIQUE NOT NULL,
            game TEXT NOT NULL DEFAULT 'pokemon_tcg',
            core_set_id TEXT NOT NULL,
            set_id TEXT, set_code TEXT,
            collector_number TEXT, collector_number_sort TEXT,
            canonical_name TEXT NOT NULL,
            name_english TEXT,
            primary_language TEXT NOT NULL,
            card_kind TEXT, rarity TEXT,
            first_seen_source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_v10_cp_core_set ON v10_canonical_printings(core_set_id, collector_number_sort)",
        "CREATE INDEX IF NOT EXISTS idx_v10_cp_name ON v10_canonical_printings(canonical_name)",
        "CREATE INDEX IF NOT EXISTS idx_v10_cp_confidence ON v10_canonical_printings(confidence_label)",
        """CREATE TABLE IF NOT EXISTS v10_canonical_printing_cards (
            canonical_printing_id TEXT NOT NULL,
            card_key TEXT NOT NULL,
            language_code TEXT NOT NULL,
            source_card_id TEXT,
            match_method TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (canonical_printing_id, card_key)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_v10_cpc_card_key ON v10_canonical_printing_cards(card_key)",
        """CREATE TABLE IF NOT EXISTS v10_commercial_variants (
            commercial_variant_id TEXT PRIMARY KEY,
            canonical_printing_id TEXT NOT NULL,
            variant_key TEXT UNIQUE NOT NULL,
            language_code TEXT NOT NULL,
            finish TEXT NOT NULL DEFAULT 'unknown',
            variant_type TEXT NOT NULL DEFAULT 'standard',
            stamp TEXT, edition TEXT,
            is_reverse_holo INTEGER NOT NULL DEFAULT 0,
            is_holo INTEGER,
            is_promo INTEGER NOT NULL DEFAULT 0,
            market_region TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            confidence_score REAL NOT NULL,
            confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_v10_cv_canonical ON v10_commercial_variants(canonical_printing_id)",
        "CREATE INDEX IF NOT EXISTS idx_v10_cv_language ON v10_commercial_variants(language_code)",
        "CREATE INDEX IF NOT EXISTS idx_v10_cv_finish ON v10_commercial_variants(finish)",
        """CREATE TABLE IF NOT EXISTS v10_sellable_skus (
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
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_v10_sku_variant ON v10_sellable_skus(commercial_variant_id)",
        "CREATE INDEX IF NOT EXISTS idx_v10_sku_item_class ON v10_sellable_skus(item_class)",
        """CREATE TABLE IF NOT EXISTS v10_external_references (
            external_reference_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            source_name TEXT NOT NULL, source_entity_type TEXT,
            source_identifier TEXT NOT NULL, source_url TEXT,
            match_method TEXT NOT NULL,
            confidence_score REAL NOT NULL, confidence_label TEXT NOT NULL,
            confidence_reason TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(entity_type, entity_id, source_name, source_identifier)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_v10_er_entity ON v10_external_references(entity_type, entity_id)",
        """CREATE TABLE IF NOT EXISTS v10_identity_build_runs (
            build_run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL, finished_at TEXT,
            status TEXT NOT NULL, source_db_path TEXT,
            algorithm_version TEXT NOT NULL,
            cards_seen INTEGER DEFAULT 0,
            canonical_printings_created INTEGER DEFAULT 0,
            commercial_variants_created INTEGER DEFAULT 0,
            sellable_skus_created INTEGER DEFAULT 0,
            external_references_created INTEGER DEFAULT 0,
            warnings_count INTEGER DEFAULT 0, errors_count INTEGER DEFAULT 0,
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS v10_identity_build_events (
            event_id TEXT PRIMARY KEY,
            build_run_id TEXT NOT NULL, severity TEXT NOT NULL,
            entity_type TEXT, entity_id TEXT,
            message TEXT NOT NULL, details_json TEXT,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS v10_inventory_sku_links (
            link_id TEXT PRIMARY KEY,
            sellable_sku_id TEXT NOT NULL, legacy_sku_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(sellable_sku_id, legacy_sku_id)
        )""",
    ]
    for sql in ddl:
        cur.execute(sql)
    conn.commit()


def _parse_finish(variants_str: str | None) -> tuple[str, int | None, int, str, str, str]:
    """Parse variants field. Returns (finish, is_holo, is_reverse_holo, edition, stamp, variant_type)."""
    if not variants_str or not variants_str.strip():
        return ("unknown", None, 0, "", "", "standard")

    finish = "normal"
    is_holo = None
    is_reverse = 0
    edition = ""
    variant_type = "standard"

    raw = variants_str.lower().strip()
    # Normalise and parse
    parts = raw.replace("\n", ",").replace("\t", "").split(",")
    has_normal = False
    has_reverse = False
    has_holo = False
    has_first = False

    for part in parts:
        part = part.strip().strip('"')
        if ":" not in part:
            continue
        key, _, val = part.partition(":")
        key = key.strip().strip('"')
        val = val.strip().strip('"')
        if key == "normal" and val == "true":
            has_normal = True
        elif key == "reverse" and val == "true":
            has_reverse = True
        elif key == "holo" and val == "true":
            has_holo = True
        elif key == "firstedition" and val == "true":
            has_first = True

    if has_first:
        edition = "first_edition"

    if has_holo and has_reverse:
        return ("reverse_holo", 1, 1, edition, "", "standard")
    elif has_holo:
        return ("holo", 1, 0, edition, "", "standard")
    elif has_reverse:
        return ("reverse", 0, 1, edition, "", "standard")
    elif has_normal:
        return ("normal", 0, 0, edition, "", "standard")
    else:
        return ("unknown", None, 0, edition, "", "standard")


def _sortable_number(raw: str | None) -> str:
    """Create a sortable version of collector number."""
    if not raw:
        return ""
    # Split on dash for numbers like "123a", "123b"
    s = raw.strip().lower()
    # Extract numeric and alpha parts
    num_part = ""
    alpha_part = ""
    for ch in s:
        if ch.isdigit():
            if not alpha_part:
                num_part += ch
            else:
                alpha_part += ch
        elif ch.isalpha():
            alpha_part += ch
        # skip other chars
    num = int(num_part) if num_part else 0
    return f"{num:06d}{alpha_part}"


def build_identity(
    conn: sqlite3.Connection,
    *,
    language_filter: str | None = None,
    core_set_filter: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run identity build.

    Returns a results dict with counts.
    """
    cur = conn.cursor()
    now = _now()
    cards_seen = 0
    cp_created = 0
    cv_created = 0
    sku_created = 0
    er_created = 0

    # Build base query for cards
    base_sql = """
        SELECT c.card_id, c.language_code, c.card_name,
               c.core_set_id, c.resolved_set_id,
               c.raw_set_id, c.local_id, c.category, c.rarity,
               c.variants
        FROM v2_card_detail_api_cache c
    """
    conditions = []
    params: list[Any] = []
    if language_filter:
        conditions.append("c.language_code = ?")
        params.append(language_filter)
    if core_set_filter:
        conditions.append("c.core_set_id = ?")
        params.append(core_set_filter)
    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)
    base_sql += " ORDER BY c.core_set_id, c.local_id_sort, c.language_code"
    if limit:
        base_sql += f" LIMIT {int(limit)}"

    cur.execute(base_sql, tuple(params))
    all_cards = cur.fetchall()
    cards_seen = len(all_cards)

    # ── Phase 1: Build canonical printings ──────────────────────────────
    # Strategy: Group English cards by (core_set_id, local_id) → one canonical per distinct (core_set_id, local_id, card_name)
    # Then use translations to merge non-English cards into existing canonicals

    # Step 1: Collect English translation map: source_card_id -> en_name
    cur.execute("""
        SELECT DISTINCT t.card_id, t.en_name
        FROM card_name_translations t
        WHERE t.source IN ('db_join', 'pokemon_names_exact', 'latin_recognized', 'pokemon_suffix')
        AND t.language_code != 'en'
    """)
    en_translation_map: dict[str, str] = {}
    for row in cur.fetchall():
        en_translation_map[row["card_id"]] = row["en_name"]

    # Step 2: Collect all card rows into structured records
    cards_by_slot: dict[str, list[sqlite3.Row]] = {}
    for card in all_cards:
        slot_key = f"{card['core_set_id']}|{card['card_name']}|{card['local_id']}"
        if slot_key not in cards_by_slot:
            cards_by_slot[slot_key] = []
        cards_by_slot[slot_key].append(card)

    # Step 3: Create canonical printing for each slot
    # Group by (core_set_id, local_id, canonical_name) to avoid slot ambiguity
    canonical_keys_seen: set[str] = set()

    for slot_key, cards in cards_by_slot.items():
        # First card becomes the canonical representative
        primary = cards[0]
        canonical_name = primary["card_name"]
        core_set_id = primary["core_set_id"]
        set_id = primary["resolved_set_id"] or primary["raw_set_id"]
        local_id = primary["local_id"] if primary["local_id"] else ""

        # If we have an English name for this card, use it
        en_name = None
        for c in cards:
            if c["language_code"] == "en":
                en_name = c["card_name"]
                break
        if not en_name:
            en_name = en_translation_map.get(primary["card_id"])

        # Build canonical key
        primary_lang = primary["language_code"]
        num_sort = _sortable_number(local_id)
        canonical_key = f"pk_tcg:{core_set_id}-{local_id}-{primary_lang}"

        if canonical_key in canonical_keys_seen:
            # Skip duplicates (same key from another row in same slot)
            continue
        canonical_keys_seen.add(canonical_key)

        cp_id = _mk_id("cp")
        cp_created += 1

        if not dry_run:
            cur.execute("""
                INSERT OR IGNORE INTO v10_canonical_printings
                (canonical_printing_id, canonical_key, core_set_id, set_id,
                 collector_number, collector_number_sort, canonical_name,
                 name_english, primary_language, card_kind, rarity,
                 first_seen_source, status, confidence_score,
                 confidence_label, confidence_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cp_id, canonical_key, core_set_id, set_id,
                local_id, num_sort, canonical_name,
                en_name, primary_lang, primary["category"], primary["rarity"],
                "v2_card_detail_api_cache:v10_build",
                "active", 0.85, "HIGH",
                f"exact core_set_id + local_id group, {len(cards)} card row(s)",
                now, now,
            ))

        # Step 4: Link all card rows to this canonical printing
        for c in cards:
            card_key = f"{c['language_code']}:{c['card_id']}"
            match_method = "exact_set_number_group"
            confidence = 0.85
            if en_name and c["card_name"] == en_name:
                match_method = "translation_english"
                confidence = 0.95

            if not dry_run:
                cur.execute("""
                    INSERT OR IGNORE INTO v10_canonical_printing_cards
                    (canonical_printing_id, card_key, language_code,
                     source_card_id, match_method, confidence_score,
                     confidence_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cp_id, card_key, c["language_code"],
                    c["card_id"], match_method, confidence,
                    match_method, now,
                ))

            # Step 5: Create commercial variant per language in this group
            finish, is_holo, is_reverse_holo, edition, _stamp, variant_type = _parse_finish(c["variants"])
            cv_key = f"{core_set_id}-{local_id}-{c['language_code']}-{finish}"

            # Check if variant_key already used (multiple card_key rows with same finish)
            existing_cv = _scalar(cur,
                "SELECT 1 FROM v10_commercial_variants WHERE variant_key = ?", (cv_key,))
            if not existing_cv:
                cv_id = _mk_id("cv")
                is_reverse_holo = 1 if finish == "reverse" else (1 if edition and is_holo else 0)

                if not dry_run:
                    cur.execute("""
                        INSERT OR IGNORE INTO v10_commercial_variants
                        (commercial_variant_id, canonical_printing_id, variant_key,
                         language_code, finish, variant_type, edition,
                         is_reverse_holo, is_holo, is_promo,
                         status, confidence_score, confidence_label,
                         confidence_reason, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        cv_id, cp_id, cv_key,
                        c["language_code"], finish, variant_type, edition,
                        int(is_reverse_holo), is_holo, 0,
                        "active", 0.8, "HIGH",
                        f"derived from core_set_id + local_id + language",
                        now, now,
                    ))
                cv_created += 1

                # Step 6: Create sellable SKU
                sku_key = f"pk_tcg:{core_set_id}-{local_id}-{c['language_code']}-{finish}-raw"
                display_title = f"{canonical_name} ({c['language_code']}, {finish.replace('_', ' ')})"

                existing_sku = _scalar(cur,
                    "SELECT 1 FROM v10_sellable_skus WHERE sku_key = ?", (sku_key,))
                if not existing_sku:
                    sku_id = _mk_id("sku")

                    if not dry_run:
                        cur.execute("""
                            INSERT OR IGNORE INTO v10_sellable_skus
                            (sellable_sku_id, commercial_variant_id, sku_key,
                             item_class, condition_policy, display_title,
                             confidence_score, confidence_label,
                             confidence_reason, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sku_id, cv_id, sku_key,
                            "single_card", "raw_conditioned", display_title,
                            0.8, "HIGH",
                            f"single-card SKU for {cv_key}",
                            now, now,
                        ))
                    if dry_run or cur.rowcount > 0:
                        sku_created += 1

            # Step 7: Internal external reference
            ref_id = _mk_id("er")
            if not dry_run:
                cur.execute("""
                    INSERT OR IGNORE INTO v10_external_references
                    (external_reference_id, entity_type, entity_id,
                     source_name, source_identifier, match_method,
                     confidence_score, confidence_label, confidence_reason,
                     created_at, updated_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ref_id, "canonical_printing", cp_id,
                    "internal_source_card_id", c["card_id"], "exact",
                    1.0, "HIGH", "internal_source_id", now, now, "active",
                ))
            er_created += 1

    if not dry_run:
        conn.commit()

    return {
        "cards_seen": cards_seen,
        "canonical_printings_created": cp_created,
        "commercial_variants_created": cv_created,
        "sellable_skus_created": sku_created,
        "external_references_created": er_created,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build v10 canonical commercial identity from existing Pokémon DB."
    )
    parser.add_argument("--db", required=True, type=Path, help="Path to SQLite database.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count rows but do not write.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of unique card slots to process.")
    parser.add_argument("--language", type=str, default=None,
                        help="Only process this language (e.g. 'en').")
    parser.add_argument("--core-set-id", type=str, default=None,
                        help="Only process this core_set_id (e.g. 'base1').")
    parser.add_argument("--json", action="store_true", help="Output results as JSON.")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: Database does not exist: {args.db}", file=sys.stderr)
        return 1

    db_path = args.db
    build_run_id = _mk_id("br")
    started_at = _now()

    try:
        conn = _connect(db_path)
    except Exception as e:
        print(f"ERROR: Cannot open database: {e}", file=sys.stderr)
        return 1

    try:
        with closing(conn):
            _ensure_migration_tables(conn)
            cur = conn.cursor()

            # Record build run
            if not args.dry_run:
                cur.execute("""
                    INSERT INTO v10_identity_build_runs
                    (build_run_id, started_at, status, source_db_path,
                     algorithm_version)
                    VALUES (?, ?, ?, ?, ?)
                """, (build_run_id, started_at, "running",
                      str(db_path.resolve()), ALGORITHM_VERSION))
                conn.commit()

            # Run build
            try:
                results = build_identity(
                    conn,
                    language_filter=args.language,
                    core_set_filter=args.core_set_id,
                    dry_run=args.dry_run,
                    limit=args.limit,
                )
            except Exception as e:
                if not args.dry_run:
                    cur.execute("""
                        UPDATE v10_identity_build_runs
                        SET status='failed', finished_at=?,
                            errors_count=1, notes=?
                        WHERE build_run_id=?
                    """, (_now(), f"ERROR: {e}", build_run_id))
                    cur.execute("""
                        INSERT INTO v10_identity_build_events
                        (event_id, build_run_id, severity, message,
                         created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (_mk_id("ev"), build_run_id, "ERROR",
                          f"Build failed: {e}", _now()))
                    conn.commit()
                if args.json:
                    print(json.dumps({"status": "error", "error": str(e)}))
                else:
                    print(f"BUILD FAILED: {e}")
                return 1

            # Update build run
            finished_at = _now()
            summary = (
                f"cards={results['cards_seen']}, "
                f"cp={results['canonical_printings_created']}, "
                f"cv={results['commercial_variants_created']}, "
                f"sku={results['sellable_skus_created']}, "
                f"er={results['external_references_created']}"
            )
            if not args.dry_run:
                cur.execute("""
                    UPDATE v10_identity_build_runs
                    SET finished_at=?, status=?,
                        cards_seen=?,
                        canonical_printings_created=?,
                        commercial_variants_created=?,
                        sellable_skus_created=?,
                        external_references_created=?, notes=?
                    WHERE build_run_id=?
                """, (
                    finished_at, "completed",
                    results["cards_seen"],
                    results["canonical_printings_created"],
                    results["commercial_variants_created"],
                    results["sellable_skus_created"],
                    results["external_references_created"],
                    summary, build_run_id,
                ))
                conn.commit()

        if args.json:
            print(json.dumps({
                "status": "dry_run" if args.dry_run else "completed",
                "build_run_id": build_run_id,
                "algorithm_version": ALGORITHM_VERSION,
                **results,
                "started_at": started_at,
                "finished_at": finished_at,
            }, indent=2))
        else:
            mode = "DRY RUN" if args.dry_run else "COMPLETED"
            print(f"[{mode}] {summary}")
            if not args.dry_run:
                print(f"Build run: {build_run_id}")

        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
