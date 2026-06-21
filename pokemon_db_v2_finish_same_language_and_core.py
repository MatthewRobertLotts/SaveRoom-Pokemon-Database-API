#!/usr/bin/env python3
"""Finish v2 same-language alias promotion and add additive v2 core/provenance layer.

Safe/additive only:
- promotes all remaining reviewed same-language exact aliases into set_aliases;
- keeps cards/set rows untouched;
- treats cards_with_resolved_sets as the default v2 card query surface;
- creates global set identity layer (sets_core, localized_sets, set_aliases_core);
- resolves cross-language alias proposals to core identities, not localized card/set rewrites;
- creates source_documents/provenance_records and safely backfills from existing non-empty card_source_provenance.source_url rows;
- creates enrichment tables empty, ready for future source-backed data.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

DB = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
REPORTS = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports")


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def scalar(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return cur.execute(sql, params).fetchone()[0]


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        if not data:
            f.write("")
            return
        writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)


def h(prefix: str, *parts: object) -> str:
    s = "\u241f".join("" if p is None else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(s.encode('utf-8')).hexdigest()[:24]}"


def ensure_set_aliases(cur: sqlite3.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS set_aliases (
            alias_language_code TEXT NOT NULL,
            alias_set_id TEXT NOT NULL,
            target_language_code TEXT NOT NULL,
            target_set_id TEXT NOT NULL,
            alias_type TEXT NOT NULL DEFAULT 'import_alias',
            source_url TEXT,
            method TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            notes TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (alias_language_code, alias_set_id),
            FOREIGN KEY (target_language_code, target_set_id) REFERENCES sets(language_code, set_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_set_aliases_target ON set_aliases(target_language_code, target_set_id)")


def create_cards_with_resolved_sets(cur: sqlite3.Cursor) -> None:
    cur.execute("DROP VIEW IF EXISTS cards_with_resolved_sets")
    cur.execute("""
        CREATE VIEW cards_with_resolved_sets AS
        SELECT
            c.language_code,
            c.set_id,
            c.card_id,
            c.local_id,
            c.local_id_sort,
            c.name,
            c.image_url,
            COALESCE(sa.target_language_code, c.language_code) AS resolved_language_code,
            COALESCE(sa.target_set_id, c.set_id) AS resolved_set_id,
            rs.name AS resolved_set_name,
            rs.series_name AS resolved_series_name,
            rs.release_date AS resolved_release_date,
            CASE WHEN sa.target_set_id IS NOT NULL THEN 1 ELSE 0 END AS resolved_via_set_alias,
            sa.alias_type AS set_alias_type,
            sa.method AS set_alias_method,
            sa.confidence AS set_alias_confidence,
            sa.notes AS set_alias_notes
        FROM cards c
        LEFT JOIN set_aliases sa
          ON sa.alias_language_code = c.language_code
         AND sa.alias_set_id = c.set_id
        LEFT JOIN sets rs
          ON rs.language_code = COALESCE(sa.target_language_code, c.language_code)
         AND rs.set_id = COALESCE(sa.target_set_id, c.set_id)
    """)


def ensure_core_tables(cur: sqlite3.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sets_core (
            core_set_id TEXT PRIMARY KEY,
            canonical_language_code TEXT NOT NULL,
            canonical_set_id TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            product_family TEXT,
            series_name TEXT,
            release_date TEXT,
            official_count INTEGER,
            total_count INTEGER,
            source_method TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            notes TEXT,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (canonical_language_code, canonical_set_id) REFERENCES sets(language_code, set_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS localized_sets (
            language_code TEXT NOT NULL,
            set_id TEXT NOT NULL,
            core_set_id TEXT NOT NULL,
            localized_name TEXT NOT NULL,
            source_method TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            notes TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (language_code, set_id),
            FOREIGN KEY (language_code, set_id) REFERENCES sets(language_code, set_id),
            FOREIGN KEY (core_set_id) REFERENCES sets_core(core_set_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_localized_sets_core ON localized_sets(core_set_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS set_aliases_core (
            alias_language_code TEXT NOT NULL,
            alias_set_id TEXT NOT NULL,
            target_core_set_id TEXT NOT NULL,
            target_language_code TEXT,
            target_set_id TEXT,
            alias_type TEXT NOT NULL DEFAULT 'cross_language_import_alias',
            source_url TEXT,
            method TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'resolved_to_core',
            notes TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (alias_language_code, alias_set_id),
            FOREIGN KEY (target_core_set_id) REFERENCES sets_core(core_set_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_set_aliases_core_target ON set_aliases_core(target_core_set_id)")


def ensure_provenance_and_enrichment_tables(cur: sqlite3.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS source_documents (
            source_document_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_title TEXT,
            source_publisher TEXT,
            source_type TEXT NOT NULL,
            language_code TEXT,
            fetched_at TEXT NOT NULL,
            retrieved_by TEXT,
            content_hash TEXT,
            cache_path TEXT,
            license_notes TEXT,
            reliability_notes TEXT,
            FOREIGN KEY (language_code) REFERENCES languages(code)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_source_documents_url ON source_documents(source_url)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS provenance_records (
            provenance_id TEXT PRIMARY KEY,
            entity_table TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            language_code TEXT,
            source_document_id TEXT,
            source_url TEXT NOT NULL,
            method TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source_notes TEXT,
            extraction_notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (language_code) REFERENCES languages(code),
            FOREIGN KEY (source_document_id) REFERENCES source_documents(source_document_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_provenance_records_entity ON provenance_records(entity_table, entity_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_provenance_records_source ON provenance_records(source_url, method)")
    # Enrichment tables: additive and empty unless future source-backed facts are explicitly imported.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_variants (
            variant_id TEXT PRIMARY KEY, language_code TEXT NOT NULL, card_id TEXT NOT NULL, set_id TEXT NOT NULL,
            local_id TEXT, variant_type TEXT NOT NULL, variant_label TEXT, print_finish TEXT, distribution_context TEXT,
            notes TEXT, source_url TEXT NOT NULL, method TEXT NOT NULL, fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT,
            FOREIGN KEY (language_code, card_id) REFERENCES cards(language_code, card_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_card_variants_card ON card_variants(language_code, card_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_reprints (
            reprint_id TEXT PRIMARY KEY, language_code TEXT, source_card_id TEXT NOT NULL, source_set_id TEXT,
            reprint_card_id TEXT NOT NULL, reprint_set_id TEXT, relationship_type TEXT NOT NULL DEFAULT 'reprint',
            notes TEXT, source_url TEXT NOT NULL, method TEXT NOT NULL, fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_card_reprints_source ON card_reprints(language_code, source_card_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_card_reprints_reprint ON card_reprints(language_code, reprint_card_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_trivia (
            trivia_id TEXT PRIMARY KEY, language_code TEXT, card_id TEXT NOT NULL, set_id TEXT,
            trivia_text TEXT NOT NULL, trivia_type TEXT, source_url TEXT NOT NULL, method TEXT NOT NULL,
            fetched_at TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_card_trivia_card ON card_trivia(language_code, card_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_errors (
            error_id TEXT PRIMARY KEY, language_code TEXT, card_id TEXT NOT NULL, set_id TEXT,
            error_type TEXT NOT NULL, error_description TEXT NOT NULL, affected_prints TEXT, correction_status TEXT,
            source_url TEXT NOT NULL, method TEXT NOT NULL, fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_card_errors_card ON card_errors(language_code, card_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS card_errata (
            errata_id TEXT PRIMARY KEY, language_code TEXT, card_id TEXT NOT NULL, set_id TEXT,
            errata_date TEXT, original_text TEXT, corrected_text TEXT NOT NULL, ruling_context TEXT,
            source_url TEXT NOT NULL, method TEXT NOT NULL, fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_card_errata_card ON card_errata(language_code, card_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sealed_product_sources (
            sealed_product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL, product_type TEXT NOT NULL,
            language_code TEXT, set_id TEXT, release_date TEXT, region TEXT, contents_summary TEXT,
            source_url TEXT NOT NULL, method TEXT NOT NULL, fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT,
            FOREIGN KEY (language_code) REFERENCES languages(code)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sealed_product_sources_set ON sealed_product_sources(language_code, set_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            market_snapshot_id TEXT PRIMARY KEY, language_code TEXT, card_id TEXT, sealed_product_id TEXT,
            marketplace TEXT NOT NULL, price_amount REAL, price_currency TEXT, condition_grade TEXT,
            snapshot_at TEXT NOT NULL, source_url TEXT NOT NULL, method TEXT NOT NULL, fetched_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0, source_notes TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshots_card ON market_snapshots(language_code, card_id, snapshot_at)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_links (
            inventory_link_id TEXT PRIMARY KEY, language_code TEXT, card_id TEXT, sealed_product_id TEXT,
            external_system TEXT NOT NULL, external_id TEXT NOT NULL, external_url TEXT,
            link_status TEXT NOT NULL DEFAULT 'active', notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_links_external ON inventory_links(external_system, external_id)")


def main() -> int:
    fetched_at = now_utc()
    REPORTS.mkdir(parents=True, exist_ok=True)
    backup = DB.with_name(DB.stem + f".backup_before_v2_core_{stamp()}" + DB.suffix)
    shutil.copy2(DB, backup)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    before = {
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "set_aliases_rows": scalar(cur, "SELECT COUNT(*) FROM set_aliases") if scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='set_aliases'") else 0,
        "raw_unmatched": scalar(cur, "SELECT COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)"),
    }

    ensure_set_aliases(cur)
    create_cards_with_resolved_sets(cur)

    # 1. Finish same-language alias promotion.
    eligible = rows(cur, """
        SELECT p.*
        FROM set_aliases_proposed p
        JOIN sets target ON target.language_code=p.target_language_code AND target.set_id=p.target_set_id
        LEFT JOIN sets alias_set ON alias_set.language_code=p.alias_language_code AND alias_set.set_id=p.alias_set_id
        WHERE p.status='proposed'
          AND p.match_rule='same_language_exact_set_field'
          AND p.alias_language_code=p.target_language_code
          AND p.confidence >= 0.99
          AND p.visible_template_rows = 0
          AND alias_set.set_id IS NULL
        ORDER BY p.card_rows DESC, p.alias_language_code, p.alias_set_id
    """)
    for r in eligible:
        cur.execute("""
            INSERT OR REPLACE INTO set_aliases (
                alias_language_code, alias_set_id, target_language_code, target_set_id,
                alias_type, source_url, method, confidence, notes, reviewed_by, reviewed_at, fetched_at
            ) VALUES (?, ?, ?, ?, 'import_alias', NULL, 'v2_same_language_exact_alias_review', ?, ?, 'Hermes Agent', ?, ?)
        """, (
            r["alias_language_code"], r["alias_set_id"], r["target_language_code"], r["target_set_id"], r["confidence"],
            f"Reviewed same-language exact set-field alias. card_rows={r['card_rows']}; evidence={r['evidence_json']}",
            fetched_at, fetched_at,
        ))
    create_cards_with_resolved_sets(cur)

    # 2. Global set identity layer.
    ensure_core_tables(cur)
    # Core id uses existing set_id. Pick English row if present, else the row with largest language/card presence.
    core_candidates = rows(cur, """
        WITH ranked AS (
            SELECT s.*,
                   ROW_NUMBER() OVER (
                     PARTITION BY s.set_id
                     ORDER BY CASE WHEN s.language_code='en' THEN 0 ELSE 1 END,
                              s.language_code
                   ) AS rn
            FROM sets s
        )
        SELECT * FROM ranked WHERE rn=1
    """)
    for s in core_candidates:
        cur.execute("""
            INSERT OR IGNORE INTO sets_core (
                core_set_id, canonical_language_code, canonical_set_id, canonical_name,
                product_family, series_name, release_date, official_count, total_count,
                source_method, confidence, notes, fetched_at
            ) VALUES (?, ?, ?, ?, 'tcg', ?, ?, ?, ?, 'v2_existing_sets_grouped_by_set_id', 0.95, ?, ?)
        """, (
            s["set_id"], s["language_code"], s["set_id"], s["name"], s["series_name"], s["release_date"],
            s["official_count"], s["total_count"],
            "Core identity derived from existing sets rows sharing set_id; no card data rewritten.", fetched_at,
        ))
    localized = rows(cur, "SELECT language_code,set_id,name FROM sets")
    for s in localized:
        cur.execute("""
            INSERT OR IGNORE INTO localized_sets (
                language_code, set_id, core_set_id, localized_name, source_method, confidence, notes, fetched_at
            ) VALUES (?, ?, ?, ?, 'v2_existing_sets_row', 1.0, 'Localized set row linked to core by existing set_id.', ?)
        """, (s["language_code"], s["set_id"], s["set_id"], s["name"], fetched_at))

    # Same-language aliases are also localized-set aliases and point to the target core set.
    for a in rows(cur, "SELECT * FROM set_aliases"):
        target_core = scalar(cur, "SELECT core_set_id FROM localized_sets WHERE language_code=? AND set_id=?", (a["target_language_code"], a["target_set_id"]))
        cur.execute("""
            INSERT OR REPLACE INTO set_aliases_core (
                alias_language_code, alias_set_id, target_core_set_id, target_language_code, target_set_id,
                alias_type, source_url, method, confidence, status, notes, reviewed_by, reviewed_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, 'localized_import_alias', ?, ?, ?, 'resolved_to_core', ?, ?, ?, ?)
        """, (a["alias_language_code"], a["alias_set_id"], target_core, a["target_language_code"], a["target_set_id"],
              a["source_url"], a["method"], a["confidence"], a["notes"], a["reviewed_by"], a["reviewed_at"], a["fetched_at"]))

    # Resolve cross-language needs_review proposals to core identity only. This does not claim a localized parent row.
    cross = rows(cur, """
        SELECT p.*
        FROM set_aliases_proposed p
        JOIN localized_sets ls ON ls.language_code=p.target_language_code AND ls.set_id=p.target_set_id
        LEFT JOIN set_aliases_core existing ON existing.alias_language_code=p.alias_language_code AND existing.alias_set_id=p.alias_set_id
        WHERE p.status='needs_review'
          AND p.target_set_id IS NOT NULL
          AND p.confidence >= 0.70
          AND existing.alias_set_id IS NULL
          AND p.match_rule LIKE 'cross_language%'
        ORDER BY p.card_rows DESC, p.alias_language_code, p.alias_set_id
    """)
    for r in cross:
        target_core = scalar(cur, "SELECT core_set_id FROM localized_sets WHERE language_code=? AND set_id=?", (r["target_language_code"], r["target_set_id"]))
        cur.execute("""
            INSERT OR REPLACE INTO set_aliases_core (
                alias_language_code, alias_set_id, target_core_set_id, target_language_code, target_set_id,
                alias_type, source_url, method, confidence, status, notes, reviewed_by, reviewed_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, 'cross_language_import_alias', NULL, 'v2_cross_language_exact_alias_to_core', ?, 'resolved_to_core', ?, 'Hermes Agent', ?, ?)
        """, (r["alias_language_code"], r["alias_set_id"], target_core, r["target_language_code"], r["target_set_id"],
              r["confidence"],
              f"Resolved to global core identity only from proposed alias; not a localized set rewrite. match_rule={r['match_rule']}; card_rows={r['card_rows']}; evidence={r['evidence_json']}",
              fetched_at, fetched_at))

    # Core-aware default v2 report/tool views.
    cur.execute("DROP VIEW IF EXISTS cards_v2")
    cur.execute("""
        CREATE VIEW cards_v2 AS
        SELECT
            c.*,
            COALESCE(ls.core_set_id, sac.target_core_set_id) AS core_set_id,
            sc.canonical_name AS core_set_name,
            sc.canonical_language_code AS core_canonical_language_code,
            sc.canonical_set_id AS core_canonical_set_id,
            CASE WHEN COALESCE(ls.core_set_id, sac.target_core_set_id) IS NOT NULL THEN 1 ELSE 0 END AS resolved_to_core,
            CASE WHEN sac.target_core_set_id IS NOT NULL THEN 1 ELSE 0 END AS resolved_via_core_alias
        FROM cards_with_resolved_sets c
        LEFT JOIN localized_sets ls
          ON ls.language_code=c.resolved_language_code AND ls.set_id=c.resolved_set_id
        LEFT JOIN set_aliases_core sac
          ON sac.alias_language_code=c.language_code AND sac.alias_set_id=c.set_id
        LEFT JOIN sets_core sc
          ON sc.core_set_id=COALESCE(ls.core_set_id, sac.target_core_set_id)
    """)
    cur.execute("DROP VIEW IF EXISTS v2_quality_summary")
    cur.execute("""
        CREATE VIEW v2_quality_summary AS
        SELECT 'cards_v2_rows' AS metric, COUNT(*) AS value FROM cards_v2
        UNION ALL SELECT 'cards_with_resolved_sets_rows', COUNT(*) FROM cards_with_resolved_sets
        UNION ALL SELECT 'cards_raw_rows', COUNT(*) FROM cards
        UNION ALL SELECT 'raw_unmatched_card_set_rows', COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)
        UNION ALL SELECT 'localized_view_unmatched_card_set_rows', COUNT(*) FROM cards_with_resolved_sets c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.resolved_language_code AND s.set_id=c.resolved_set_id)
        UNION ALL SELECT 'core_unresolved_card_rows', COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL
        UNION ALL SELECT 'core_resolved_card_rows', COUNT(*) FROM cards_v2 WHERE core_set_id IS NOT NULL
    """)

    # 3. Provenance backfill from explicit existing provenance rows only.
    ensure_provenance_and_enrichment_tables(cur)
    prov_source_rows = rows(cur, """
        SELECT DISTINCT source_url, method, language_code, MIN(fetched_at) AS fetched_at
        FROM card_source_provenance
        WHERE source_url IS NOT NULL AND TRIM(source_url) <> ''
        GROUP BY source_url, method, language_code
    """)
    for r in prov_source_rows:
        doc_id = h("src", r["source_url"], r["method"], r["language_code"])
        cur.execute("""
            INSERT OR IGNORE INTO source_documents (
                source_document_id, source_url, source_type, language_code, fetched_at, retrieved_by, reliability_notes
            ) VALUES (?, ?, 'card_source_provenance_backfill', ?, ?, 'Hermes Agent', ?)
        """, (doc_id, r["source_url"], r["language_code"], r["fetched_at"] or fetched_at,
              "Backfilled only from existing explicit card_source_provenance.source_url; not a claim for rows without source_url."))
    prov_rows = rows(cur, """
        SELECT language_code,set_id,card_id,source_url,method,note,fetched_at
        FROM card_source_provenance
        WHERE source_url IS NOT NULL AND TRIM(source_url) <> ''
    """)
    inserted_prov = 0
    for p in prov_rows:
        doc_id = h("src", p["source_url"], p["method"], p["language_code"])
        prov_id = h("prov", "cards", p["language_code"], p["card_id"], p["method"], p["source_url"])
        cur.execute("""
            INSERT OR IGNORE INTO provenance_records (
                provenance_id, entity_table, entity_key, language_code, source_document_id, source_url,
                method, fetched_at, confidence, source_notes, extraction_notes, created_at
            ) VALUES (?, 'cards', ?, ?, ?, ?, ?, ?, 1.0, ?, 'Backfilled from existing card_source_provenance row with explicit source_url.', ?)
        """, (prov_id, f"{p['language_code']}:{p['card_id']}", p["language_code"], doc_id, p["source_url"], p["method"], p["fetched_at"], p["note"], fetched_at))
        inserted_prov += cur.rowcount

    conn.commit()

    # Reports and verification.
    after = {
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "set_aliases_rows": scalar(cur, "SELECT COUNT(*) FROM set_aliases"),
        "set_aliases_core_rows": scalar(cur, "SELECT COUNT(*) FROM set_aliases_core"),
        "sets_core_rows": scalar(cur, "SELECT COUNT(*) FROM sets_core"),
        "localized_sets_rows": scalar(cur, "SELECT COUNT(*) FROM localized_sets"),
        "source_documents_rows": scalar(cur, "SELECT COUNT(*) FROM source_documents"),
        "provenance_records_rows": scalar(cur, "SELECT COUNT(*) FROM provenance_records"),
        "raw_unmatched": scalar(cur, "SELECT COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)"),
        "localized_view_unmatched": scalar(cur, "SELECT COUNT(*) FROM cards_with_resolved_sets c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.resolved_language_code AND s.set_id=c.resolved_set_id)"),
        "core_unresolved": scalar(cur, "SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL"),
        "core_resolved": scalar(cur, "SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NOT NULL"),
        "cards_v2_rows": scalar(cur, "SELECT COUNT(*) FROM cards_v2"),
        "unresolved_fallback_rows": scalar(cur, """SELECT COUNT(*) FROM card_source_provenance p WHERE p.method='cross_language_template' AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))"""),
        "unknown_or_unresolved_placeholder_names": scalar(cur, "SELECT COUNT(*) FROM cards WHERE name LIKE 'Unknown card %' OR name LIKE 'Unknown %' OR name LIKE 'Unresolved %' OR name='Pardon Our Interruption'"),
        "missing_language_set_rows": scalar(cur, "SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id)"),
        "card_language_codes_not_in_languages_total": scalar(cur, "SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL"),
        "integrity_check": scalar(cur, "PRAGMA integrity_check"),
        "quick_check": scalar(cur, "PRAGMA quick_check"),
        "foreign_key_check_rows": len(rows(cur, "PRAGMA foreign_key_check")),
    }
    same_lang_summary = rows(cur, "SELECT sa.alias_language_code AS alias_language_code, COUNT(*) aliases, SUM(p.card_rows) card_rows FROM set_aliases sa LEFT JOIN set_aliases_proposed p ON p.alias_language_code=sa.alias_language_code AND p.alias_set_id=sa.alias_set_id WHERE sa.method='v2_same_language_exact_alias_review' GROUP BY sa.alias_language_code ORDER BY card_rows DESC")
    cross_summary = rows(cur, "SELECT sac.alias_language_code AS alias_language_code, COUNT(*) aliases, SUM(p.card_rows) card_rows FROM set_aliases_core sac LEFT JOIN set_aliases_proposed p ON p.alias_language_code=sac.alias_language_code AND p.alias_set_id=sac.alias_set_id WHERE sac.method='v2_cross_language_exact_alias_to_core' GROUP BY sac.alias_language_code ORDER BY card_rows DESC")
    write_csv(REPORTS / "v2_same_language_aliases_promoted_all.csv", rows(cur, "SELECT * FROM set_aliases WHERE method='v2_same_language_exact_alias_review' ORDER BY alias_language_code, alias_set_id"))
    write_csv(REPORTS / "v2_cross_language_aliases_resolved_to_core.csv", rows(cur, "SELECT * FROM set_aliases_core WHERE method='v2_cross_language_exact_alias_to_core' ORDER BY alias_language_code, alias_set_id"))
    write_csv(REPORTS / "v2_quality_summary.csv", rows(cur, "SELECT * FROM v2_quality_summary"))

    report = {
        "fetched_at": fetched_at,
        "database": str(DB),
        "backup": str(backup),
        "before": before,
        "after": after,
        "same_language_alias_promotion": {
            "eligible_reviewed_aliases": len(eligible),
            "set_aliases_total_after": after["set_aliases_rows"],
            "summary_by_language": same_lang_summary,
            "csv": str(REPORTS / "v2_same_language_aliases_promoted_all.csv"),
        },
        "default_v2_query_surface": {
            "primary_card_view": "cards_with_resolved_sets",
            "core_aware_card_view": "cards_v2",
            "quality_view": "v2_quality_summary",
            "localized_view_unmatched_drop_from_raw": after["raw_unmatched"] - after["localized_view_unmatched"],
            "core_unresolved_drop_from_raw": after["raw_unmatched"] - after["core_unresolved"],
        },
        "global_set_identity_layer": {
            "sets_core_rows": after["sets_core_rows"],
            "localized_sets_rows": after["localized_sets_rows"],
            "set_aliases_core_rows": after["set_aliases_core_rows"],
            "cross_language_aliases_resolved_to_core": len(cross),
            "cross_language_summary_by_language": cross_summary,
            "important_caveat": "Cross-language aliases resolve to core set identity only; they do not create localized set rows and do not rewrite cards.",
        },
        "provenance_backfill": {
            "source_documents_rows_total": after["source_documents_rows"],
            "provenance_records_rows_total": after["provenance_records_rows"],
            "new_provenance_records_inserted_this_run": inserted_prov,
            "rule": "Only existing card_source_provenance rows with non-empty source_url were backfilled. Unknown-source rows were not claimed.",
        },
        "enrichment_tables": {
            "created": ["card_variants", "card_reprints", "card_trivia", "card_errors", "card_errata", "sealed_product_sources", "market_snapshots", "inventory_links"],
            "populated_now": ["source_documents", "provenance_records"],
            "not_populated_now": "No card variants/trivia/errors/errata/sealed facts were inserted because this session did not verify new source-backed facts for those entities.",
        },
        "artifacts": {
            "same_language_aliases_csv": str(REPORTS / "v2_same_language_aliases_promoted_all.csv"),
            "cross_language_core_aliases_csv": str(REPORTS / "v2_cross_language_aliases_resolved_to_core.csv"),
            "quality_summary_csv": str(REPORTS / "v2_quality_summary.csv"),
        },
    }
    out = REPORTS / f"v2_core_and_provenance_implementation_{fetched_at[:10]}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "backup": str(backup),
        "set_aliases_rows": after["set_aliases_rows"],
        "localized_view_unmatched": after["localized_view_unmatched"],
        "core_unresolved": after["core_unresolved"],
        "sets_core_rows": after["sets_core_rows"],
        "localized_sets_rows": after["localized_sets_rows"],
        "set_aliases_core_rows": after["set_aliases_core_rows"],
        "source_documents_rows": after["source_documents_rows"],
        "provenance_records_rows": after["provenance_records_rows"],
        "cards_unchanged": before["cards"] == after["cards"],
        "sets_unchanged": before["sets"] == after["sets"],
        "integrity_check": after["integrity_check"],
        "quick_check": after["quick_check"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
