#!/usr/bin/env python3
"""Make the separate v2 decision for es-mx language metadata.

Decision: keep es-mx as a distinct locale/import bucket and add language metadata.
No card rows, set IDs, names, or aliases are rewritten here.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

DB = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
REPORTS = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports")


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def rows(cur: sqlite3.Cursor, sql: str, params=()):
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def scalar(cur: sqlite3.Cursor, sql: str, params=()):
    return cur.execute(sql, params).fetchone()[0]


def main() -> int:
    fetched_at = now_utc()
    REPORTS.mkdir(parents=True, exist_ok=True)
    backup = DB.with_name(DB.stem + f".backup_before_es_mx_metadata_{stamp()}" + DB.suffix)
    shutil.copy2(DB, backup)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    before = {
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "es_mx_language_rows": scalar(cur, "SELECT COUNT(*) FROM languages WHERE code='es-mx'"),
        "card_language_codes_not_in_languages_total": scalar(cur, "SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL"),
        "es_mx_cards": scalar(cur, "SELECT COUNT(*) FROM cards WHERE language_code='es-mx'"),
        "es_mx_set_groups": scalar(cur, "SELECT COUNT(DISTINCT set_id) FROM cards WHERE language_code='es-mx'"),
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
    }
    esmx_sets = rows(cur, """
        SELECT set_id, COUNT(*) AS rows, COUNT(DISTINCT local_id) AS distinct_local_ids,
               SUM(CASE WHEN name LIKE '{{%' OR name LIKE '[[%' OR name='Pardon Our Interruption' THEN 1 ELSE 0 END) AS visible_template_rows,
               SUM(CASE WHEN image_url IS NULL OR image_url='' THEN 1 ELSE 0 END) AS missing_image_rows,
               MIN(name) AS sample_name_min, MAX(name) AS sample_name_max
        FROM cards WHERE language_code='es-mx'
        GROUP BY set_id ORDER BY rows DESC, set_id
    """)
    esmx_provenance = rows(cur, """
        SELECT p.method, COUNT(*) AS rows
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        WHERE c.language_code='es-mx'
        GROUP BY p.method ORDER BY rows DESC
    """)

    decision = "add_es_mx_language_metadata_keep_distinct_do_not_merge"
    rationale = [
        "The database contains a real es-mx card bucket: 1,699 card rows across 13 set_id groups.",
        "Adding a languages row is additive metadata and does not invent localized card data.",
        "Merging es-mx into es would rewrite locale semantics and requires source-backed equivalence review, so it is explicitly not done.",
        "Set normalization for es-mx remains separate; most es-mx set_ids are still alias/unmatched-set candidates.",
    ]

    if before["es_mx_language_rows"] == 0 and before["es_mx_cards"] > 0:
        cur.execute("""
            INSERT INTO languages(code, name, set_count, card_count, fetched_at)
            VALUES ('es-mx', 'Spanish (Mexico)', ?, ?, ?)
        """, (before["es_mx_set_groups"], before["es_mx_cards"], fetched_at))
        applied = True
    else:
        applied = False
    conn.commit()

    after = {
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "es_mx_language_rows": scalar(cur, "SELECT COUNT(*) FROM languages WHERE code='es-mx'"),
        "card_language_codes_not_in_languages_total": scalar(cur, "SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL"),
        "es_mx_cards": scalar(cur, "SELECT COUNT(*) FROM cards WHERE language_code='es-mx'"),
        "es_mx_set_groups": scalar(cur, "SELECT COUNT(DISTINCT set_id) FROM cards WHERE language_code='es-mx'"),
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "integrity_check": scalar(cur, "PRAGMA integrity_check"),
        "quick_check": scalar(cur, "PRAGMA quick_check"),
        "foreign_key_check_rows": len(rows(cur, "PRAGMA foreign_key_check")),
    }

    report = {
        "fetched_at": fetched_at,
        "database": str(DB),
        "backup": str(backup),
        "decision": decision,
        "rationale": rationale,
        "applied_language_metadata": applied,
        "before": before,
        "after": after,
        "es_mx_set_audit": esmx_sets,
        "es_mx_provenance_methods": esmx_provenance,
        "not_done": [
            "Did not merge es-mx into es.",
            "Did not rewrite any cards.language_code, cards.set_id, card names, or image URLs.",
            "Did not promote es-mx set aliases; those remain in set_aliases_proposed/needs_review unless separately reviewed.",
        ],
    }
    out = REPORTS / f"v2_es_mx_language_decision_{fetched_at[:10]}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "backup": str(backup),
        "decision": decision,
        "applied": applied,
        "languages_before": before["languages"],
        "languages_after": after["languages"],
        "language_orphan_rows_before": before["card_language_codes_not_in_languages_total"],
        "language_orphan_rows_after": after["card_language_codes_not_in_languages_total"],
        "cards_unchanged": before["cards"] == after["cards"],
        "sets_unchanged": before["sets"] == after["sets"],
        "integrity_check": after["integrity_check"],
        "quick_check": after["quick_check"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
