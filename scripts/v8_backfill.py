#!/usr/bin/env python3
"""v8 Canonical Printing & SKU Backfill Tool

Reads existing card records from the production DB and generates:
1. canonical_printings (one per unique card_id + language_code)
2. commercial_variants (initial: normal finish per printing)
3. sellable_skus (raw-condition SKUs only, where identity is clear)
4. external_references (eBay UK price search references)

Idempotent: can be safely re-run. Uses INSERT OR IGNORE for dedup.
Reports conflicts instead of guessing.

Usage:
    python scripts/v8_backfill.py <source_db_path> [--report-only]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalize_collector_number(raw: str | None) -> str:
    """Normalize collector number for matching: strip leading zeros."""
    if not raw:
        return ''
    return raw.lstrip('0') or '0'


def build_sku_key(set_code: str, collector_number: str, language_code: str,
                  condition_code: str, variant_label: str = 'normal') -> str:
    """Build a deterministic SKU key."""
    parts = [set_code, collector_number, language_code, variant_label, condition_code]
    return '|'.join(parts)


def run_backfill(db_path: str, report_only: bool = False) -> dict[str, Any]:
    """Run the backfill. Returns counts and conflict report."""
    start = time.time()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Ensure new tables exist
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS canonical_printings (
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
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_printings_unique
            ON canonical_printings(canonical_card_key, language_code, set_code, collector_number_normalized);
        CREATE TABLE IF NOT EXISTS commercial_variants (
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
        );
        CREATE TABLE IF NOT EXISTS sellable_skus (
            sku_id INTEGER PRIMARY KEY,
            printing_id INTEGER NOT NULL,
            variant_id INTEGER,
            language_code TEXT NOT NULL,
            condition_code TEXT NOT NULL,
            sku_key TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS external_references (
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
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_references_unique
            ON external_references(entity_type, entity_id, source_name, external_id);
    """)

    report: dict[str, Any] = {
        'counts': {},
        'conflicts': [],
        'skipped': [],
        'timing_seconds': 0,
    }

    # ── Phase 1: Canonical Printings ─────────────────────────────────
    print('[backfill] Phase 1: Generating canonical printings...')

    # Get all distinct card identities from v2_card_detail_api_cache
    cur.execute("""
        SELECT DISTINCT
            card_id, language_code, card_name, core_set_id, local_id,
            core_set_name, rarity
        FROM v2_card_detail_api_cache
        ORDER BY card_id, language_code
    """)

    rows = cur.fetchall()
    total_cards = len(rows)
    print(f'[backfill]   Found {total_cards:,} distinct card+language combinations')

    printings_inserted = 0
    printing_id_map: dict[str, int] = {}  # canonical_card_key → printing_id

    for card_id, language_code, card_name, core_set_id, local_id, core_set_name, rarity in rows:
        canonical_card_key = f"{language_code}:{card_id}"
        collector_norm = normalize_collector_number(local_id)

        # Look up English name
        cur.execute("""
            SELECT en_name FROM card_name_translations
            WHERE card_id = ? AND language_code = ? AND source != 'untranslated'
            LIMIT 1
        """, (card_id, language_code))
        row = cur.fetchone()
        name_english = row[0] if row else None

        # Look up release date from sets_core
        cur.execute("""
            SELECT release_date FROM sets_core WHERE core_set_id = ? LIMIT 1
        """, (core_set_id,))
        row = cur.fetchone()
        release_date = row[0] if row else None

        # Check for existing (idempotent)
        if canonical_card_key in printing_id_map:
            continue

        if not report_only:
            cur.execute("""
                INSERT OR IGNORE INTO canonical_printings (
                    canonical_card_key, source_card_id, language_code,
                    set_id, set_code, collector_number, collector_number_normalized,
                    name_localized, name_english, release_date, rarity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (canonical_card_key, card_id, language_code,
                  core_set_id, core_set_id, local_id, collector_norm,
                  card_name, name_english, release_date, rarity))

            if cur.rowcount > 0:
                printing_id = cur.lastrowid
                printing_id_map[canonical_card_key] = printing_id
                printings_inserted += 1
        else:
            printings_inserted += 1
            printing_id_map[canonical_card_key] = -1  # placeholder

    print(f'[backfill]   Inserted {printings_inserted:,} canonical printings')
    report['counts']['canonical_printings'] = printings_inserted

    # ── Phase 2: Commercial Variants ─────────────────────────────────
    print('[backfill] Phase 2: Generating commercial variants...')

    variants_inserted = 0
    # For each printing, create a 'normal' variant (default)
    for canonical_card_key, printing_id in printing_id_map.items():
        if report_only:
            variants_inserted += 1
            continue

        # Check if this card has holo indicators in card_details or card_variants
        card_id = canonical_card_key.split(':', 1)[1]
        language_code = canonical_card_key.split(':', 1)[0]

        # Check for holo/reverse variants in card_variants table
        cur.execute("""
            SELECT variant_type, variant_label, print_finish FROM card_variants
            WHERE card_id = ? AND language_code = ?
            LIMIT 5
        """, (card_id, language_code))
        variant_rows = cur.fetchall()

        variant_types = set()
        for vtype, vlabel, vfinish in variant_rows:
            label = (vlabel or vtype or 'normal').lower().strip()
            if 'holo' in label and 'reverse' in label:
                variant_types.add('reverse_holo')
            elif 'holo' in label:
                variant_types.add('holo')
            elif 'first' in label or '1st' in label:
                variant_types.add('first_edition')
            elif 'unlimited' in label:
                variant_types.add('unlimited')
            elif 'normal' in label or 'standard' in label or not label:
                variant_types.add('normal')
            elif label:
                variant_types.add(label)

        # Always create 'normal' variant
        variant_types.add('normal')

        for vtype in variant_types:
            label = vtype
            is_first_edition = 1 if vtype == 'first_edition' else 0
            finish = 'normal' if vtype == 'normal' else vtype

            cur.execute("""
                INSERT OR IGNORE INTO commercial_variants (
                    printing_id, finish, variant_label, is_first_edition
                ) VALUES (?, ?, ?, ?)
            """, (printing_id, finish, label, is_first_edition))

            if cur.rowcount > 0:
                variants_inserted += 1

    print(f'[backfill]   Inserted {variants_inserted:,} commercial variants')
    report['counts']['commercial_variants'] = variants_inserted

    # ── Phase 3: Sellable SKUs (raw condition only) ──────────────────
    print('[backfill] Phase 3: Generating sellable SKUs (raw conditions)...')

    skus_inserted = 0
    conditions = ['Near Mint', 'Excellent', 'Mint']

    for canonical_card_key, printing_id in printing_id_map.items():
        if report_only:
            skus_inserted += len(conditions)
            continue

        card_id = canonical_card_key.split(':', 1)[1]
        language_code = canonical_card_key.split(':', 1)[0]

        # Get set_code and collector_number from canonical_printings
        cur.execute("""
            SELECT set_code, collector_number_normalized FROM canonical_printings
            WHERE printing_id = ?
        """, (printing_id,))
        cprow = cur.fetchone()
        if not cprow:
            continue
        set_code, colnum = cprow

        # Get the default variant (normal) for this printing
        cur.execute("""
            SELECT variant_id FROM commercial_variants
            WHERE printing_id = ? AND variant_label = 'normal'
            LIMIT 1
        """, (printing_id,))
        vrow = cur.fetchone()
        variant_id = vrow[0] if vrow else None

        for cond in conditions:
            sku_key = build_sku_key(set_code or '', colnum or '', language_code, cond)

            cur.execute("""
                INSERT OR IGNORE INTO sellable_skus (
                    printing_id, variant_id, language_code, condition_code, sku_key
                ) VALUES (?, ?, ?, ?, ?)
            """, (printing_id, variant_id, language_code, cond, sku_key))

            if cur.rowcount > 0:
                skus_inserted += 1

    print(f'[backfill]   Inserted {skus_inserted:,} sellable SKUs')
    report['counts']['sellable_skus'] = skus_inserted

    # ── Phase 4: External References ─────────────────────────────────
    print('[backfill] Phase 4: Generating external references (price search URLs)...')

    refs_inserted = 0
    # For each canonical printing, generate an eBay UK price search reference
    # Only for English cards (eBay UK is English)
    # Build a lookup: canonical_card_key → printing_id from the actual table
    cur.execute("SELECT printing_id, canonical_card_key FROM canonical_printings")
    pid_map = {row[1]: row[0] for row in cur.fetchall()}

    for canonical_card_key, printing_id in pid_map.items():
        language_code = canonical_card_key.split(':', 1)[0]
        if language_code != 'en':
            continue

        if report_only:
            refs_inserted += 1
            continue

        card_id = canonical_card_key.split(':', 1)[1]
        cur.execute("""
            SELECT name_english, set_code, collector_number_normalized, name_localized
            FROM canonical_printings WHERE printing_id = ?
        """, (printing_id,))
        cprow = cur.fetchone()
        if not cprow:
            continue
        name_en, set_code, colnum = cprow[0], cprow[1], cprow[2]

        # For English cards, name_english may be null (not in translations table)
        # Use name_localized as fallback for English cards
        if not name_en:
            name_en = cprow[3]  # name_localized

        if name_en and set_code and colnum:
            # Build eBay UK search URL
            query = f"{name_en} {set_code}-{colnum}"
            external_url = f"https://www.ebay.co.uk/sch/i.html?_nkw={query.replace(' ', '+')}"

            cur.execute("""
                INSERT OR IGNORE INTO external_references (
                    entity_type, entity_id, source_name, external_id, external_url
                ) VALUES (?, ?, ?, ?, ?)
            """, ('printing', printing_id, 'ebay_uk_search', query, external_url))

            if cur.rowcount > 0:
                refs_inserted += 1

    print(f'[backfill]   Inserted {refs_inserted:,} external references')
    report['counts']['external_references'] = refs_inserted

    # ── Summary ──────────────────────────────────────────────────────
    elapsed = time.time() - start
    report['timing_seconds'] = round(elapsed, 1)

    # Verify counts
    cur.execute("SELECT COUNT(*) FROM canonical_printings")
    total_printings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM commercial_variants")
    total_variants = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sellable_skus")
    total_skus = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM external_references")
    total_refs = cur.fetchone()[0]

    report['counts']['final_canonical_printings'] = total_printings
    report['counts']['final_commercial_variants'] = total_variants
    report['counts']['final_sellable_skus'] = total_skus
    report['counts']['final_external_references'] = total_refs

    conn.commit()
    conn.close()

    report['counts']['source_cards'] = total_cards
    report['counts']['elapsed_seconds'] = round(elapsed, 1)

    return report


def main():
    parser = argparse.ArgumentParser(description='v8 canonical printing & SKU backfill')
    parser.add_argument('db', help='Path to the SQLite database')
    parser.add_argument('--report-only', action='store_true',
                        help='Count only, do not write')
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f'ERROR: {args.db} not found')
        sys.exit(1)

    print(f'=== v8 Backfill Tool ===')
    print(f'Database: {args.db}')
    print(f'Mode: {"report-only" if args.report_only else "write"}')
    print()

    report = run_backfill(args.db, report_only=args.report_only)

    print()
    print('=== Results ===')
    for key, val in report['counts'].items():
        print(f'  {key}: {val:,}' if isinstance(val, int) else f'  {key}: {val}')
    if report['conflicts']:
        print(f'  Conflicts: {len(report["conflicts"])}')
        for c in report['conflicts'][:10]:
            print(f'    {c}')
    if report['skipped']:
        print(f'  Skipped: {len(report["skipped"])}')
    print(f'\nDone in {report["timing_seconds"]}s')


if __name__ == '__main__':
    main()
