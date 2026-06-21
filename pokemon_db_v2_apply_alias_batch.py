#!/usr/bin/env python3
"""Apply the first reviewed Pokémon DB v2 set-alias batch safely.

This script is additive and non-destructive:
- creates reviewed set_aliases table if missing;
- reviews all same-language proposed aliases into a CSV/JSON report;
- promotes a small high-confidence batch into set_aliases;
- creates a read-only cards_with_resolved_sets view;
- verifies that resolved unmatched card/set count drops without changing cards.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
DEFAULT_REPORTS = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports")


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
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)


def create_set_aliases(cur: sqlite3.Cursor) -> None:
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


def create_resolved_view(cur: sqlite3.Cursor) -> None:
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
            CASE WHEN sa.target_language_code IS NOT NULL THEN sa.target_language_code ELSE c.language_code END AS resolved_language_code,
            CASE WHEN sa.target_set_id IS NOT NULL THEN sa.target_set_id ELSE c.set_id END AS resolved_set_id,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    ap.add_argument("--batch-size", type=int, default=25)
    args = ap.parse_args()

    fetched_at = now_utc()
    args.reports.mkdir(parents=True, exist_ok=True)

    backup = args.db.with_name(args.db.stem + f".backup_before_set_aliases_{stamp()}" + args.db.suffix)
    shutil.copy2(args.db, backup)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    before = {
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "set_aliases_exists": scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='set_aliases'"),
        "set_aliases_rows": scalar(cur, "SELECT COUNT(*) FROM set_aliases") if scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='set_aliases'") else 0,
        "raw_unmatched_card_rows": scalar(cur, """
            SELECT COUNT(*) FROM cards c
            WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)
        """),
    }

    review_sql = """
        SELECT
            p.alias_language_code,
            p.alias_set_id,
            p.target_language_code,
            p.target_set_id,
            p.target_name,
            p.match_rule,
            p.confidence,
            p.status,
            p.card_rows,
            p.distinct_local_ids,
            p.min_local_id_sort,
            p.max_local_id_sort,
            p.visible_template_rows,
            p.missing_image_rows,
            p.evidence_json,
            CASE WHEN s_target.language_code IS NOT NULL THEN 1 ELSE 0 END AS target_set_exists,
            CASE WHEN s_alias.language_code IS NOT NULL THEN 1 ELSE 0 END AS alias_set_already_exists,
            CASE WHEN p.alias_language_code = p.target_language_code THEN 1 ELSE 0 END AS same_language,
            CASE
                WHEN p.status = 'proposed'
                 AND p.match_rule = 'same_language_exact_set_field'
                 AND p.alias_language_code = p.target_language_code
                 AND s_target.language_code IS NOT NULL
                 AND s_alias.language_code IS NULL
                 AND p.visible_template_rows = 0
                 AND p.confidence >= 0.99
                THEN 'reviewed_safe_same_language_exact'
                ELSE 'not_promoted_in_this_batch'
            END AS review_decision
        FROM set_aliases_proposed p
        LEFT JOIN sets s_target
          ON s_target.language_code = p.target_language_code AND s_target.set_id = p.target_set_id
        LEFT JOIN sets s_alias
          ON s_alias.language_code = p.alias_language_code AND s_alias.set_id = p.alias_set_id
        WHERE p.status = 'proposed'
          AND p.match_rule = 'same_language_exact_set_field'
          AND p.alias_language_code = p.target_language_code
        ORDER BY p.card_rows DESC, p.alias_language_code, p.alias_set_id
    """
    reviewed = rows(cur, review_sql)
    eligible = [r for r in reviewed if r["review_decision"] == "reviewed_safe_same_language_exact"]
    batch = eligible[: args.batch_size]

    review_csv = args.reports / "v2_same_language_alias_review.csv"
    batch_csv = args.reports / "v2_set_aliases_promoted_batch.csv"
    write_csv(review_csv, reviewed)
    write_csv(batch_csv, batch)

    create_set_aliases(cur)
    for r in batch:
        cur.execute("""
            INSERT OR REPLACE INTO set_aliases (
                alias_language_code, alias_set_id, target_language_code, target_set_id,
                alias_type, source_url, method, confidence, notes, reviewed_by, reviewed_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["alias_language_code"],
            r["alias_set_id"],
            r["target_language_code"],
            r["target_set_id"],
            "import_alias",
            None,
            "v2_same_language_exact_alias_review",
            r["confidence"],
            f"Promoted from set_aliases_proposed after review: same-language exact set-field match; target set exists; alias is not already a set row; card_rows={r['card_rows']}; evidence={r['evidence_json']}",
            "Hermes Agent",
            fetched_at,
            fetched_at,
        ))
    create_resolved_view(cur)
    conn.commit()

    after = {
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "set_aliases_rows": scalar(cur, "SELECT COUNT(*) FROM set_aliases"),
        "set_aliases_batch_method_rows": scalar(cur, "SELECT COUNT(*) FROM set_aliases WHERE method='v2_same_language_exact_alias_review'"),
        "raw_unmatched_card_rows": scalar(cur, """
            SELECT COUNT(*) FROM cards c
            WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)
        """),
        "resolved_view_unmatched_card_rows": scalar(cur, """
            SELECT COUNT(*) FROM cards_with_resolved_sets c
            WHERE NOT EXISTS (
                SELECT 1 FROM sets s
                WHERE s.language_code=c.resolved_language_code AND s.set_id=c.resolved_set_id
            )
        """),
        "view_rows": scalar(cur, "SELECT COUNT(*) FROM cards_with_resolved_sets"),
        "view_alias_resolved_rows": scalar(cur, "SELECT COUNT(*) FROM cards_with_resolved_sets WHERE resolved_via_set_alias=1"),
        "unresolved_fallback_rows": scalar(cur, """
            SELECT COUNT(*) FROM card_source_provenance p
            WHERE p.method='cross_language_template'
              AND NOT EXISTS (
                SELECT 1 FROM card_source_provenance r
                WHERE r.language_code=p.language_code AND r.card_id=p.card_id
                  AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
              )
        """),
        "unknown_or_unresolved_placeholder_names": scalar(cur, """
            SELECT COUNT(*) FROM cards
            WHERE name LIKE 'Unknown card %' OR name LIKE 'Unknown %' OR name LIKE 'Unresolved %' OR name='Pardon Our Interruption'
        """),
        "missing_language_set_rows": scalar(cur, """
            SELECT COUNT(*) FROM sets s
            WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id)
        """),
        "integrity_check": scalar(cur, "PRAGMA integrity_check"),
        "quick_check": scalar(cur, "PRAGMA quick_check"),
        "foreign_key_check_rows": len(rows(cur, "PRAGMA foreign_key_check")),
    }

    promoted_rows = sum(int(r["card_rows"] or 0) for r in batch)
    report = {
        "fetched_at": fetched_at,
        "database": str(args.db),
        "backup": str(backup),
        "requested_steps": {
            "review_265_same_language_proposed_aliases": True,
            "apply_additive_set_aliases_table_only": True,
            "promote_small_reviewed_batch": True,
            "create_read_only_cards_with_resolved_sets_view": True,
            "prove_resolved_unmatched_count_drop_without_changing_cards": True,
            "es_mx_decision": "deferred_to_separate_report/decision; no es-mx mutation in this alias batch",
        },
        "review": {
            "same_language_proposed_aliases_reviewed": len(reviewed),
            "eligible_safe_same_language_exact": len(eligible),
            "review_csv": str(review_csv),
        },
        "promoted_batch": {
            "batch_size": len(batch),
            "promoted_card_rows_covered": promoted_rows,
            "batch_csv": str(batch_csv),
            "rows": batch,
        },
        "before": before,
        "after": after,
        "proof": {
            "cards_count_unchanged": before["cards"] == after["cards"],
            "sets_count_unchanged": before["sets"] == after["sets"],
            "languages_count_unchanged": before["languages"] == after["languages"],
            "raw_unmatched_unchanged": before["raw_unmatched_card_rows"] == after["raw_unmatched_card_rows"],
            "resolved_view_unmatched_drop": before["raw_unmatched_card_rows"] - after["resolved_view_unmatched_card_rows"],
            "expected_drop_from_promoted_batch": promoted_rows,
            "drop_matches_promoted_batch": (before["raw_unmatched_card_rows"] - after["resolved_view_unmatched_card_rows"]) == promoted_rows,
        },
        "artifacts": {
            "review_csv": str(review_csv),
            "batch_csv": str(batch_csv),
        },
    }
    out = args.reports / f"v2_set_aliases_batch_apply_{fetched_at[:10]}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "backup": str(backup),
        "reviewed_aliases": len(reviewed),
        "promoted_aliases": len(batch),
        "promoted_card_rows": promoted_rows,
        "raw_unmatched": after["raw_unmatched_card_rows"],
        "resolved_view_unmatched": after["resolved_view_unmatched_card_rows"],
        "drop": before["raw_unmatched_card_rows"] - after["resolved_view_unmatched_card_rows"],
        "cards_unchanged": before["cards"] == after["cards"],
        "integrity_check": after["integrity_check"],
        "quick_check": after["quick_check"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
