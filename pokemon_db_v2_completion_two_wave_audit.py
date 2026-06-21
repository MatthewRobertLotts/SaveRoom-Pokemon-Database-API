#!/usr/bin/env python3
"""Complete Pokémon DB v2 normalization as far as source-backed/additive rules allow.

This script is intentionally conservative about raw structure:
- does not rewrite cards.set_id or language_code;
- resolves remaining core-unresolved alias buckets via set_aliases_core only;
- cleans visible MediaWiki template artifacts in cards.name/card_details.name using names already embedded in source-backed templates or clean parallel rows;
- records provenance for every name cleanup;
- runs two independent audit waves and writes JSON/CSV reports.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
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
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)


def hid(prefix: str, *parts: Any) -> str:
    raw = "\u241f".join("" if p is None else str(p) for p in parts)
    return prefix + "_" + hashlib.sha1(raw.encode()).hexdigest()[:24]


def clean_name(name: str, parallel_name: str | None = None) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    if name == "{{Mega":
        if parallel_name and not is_dirty(parallel_name):
            return parallel_name, "clean_parallel_row_for_truncated_mega_template"
        return None, None
    if name.startswith("{{TCG ID|"):
        # Truncated raw MediaWiki template like {{TCG ID|Set|Card Name|123
        parts = name[2:].split("|")
        if len(parts) >= 3:
            val = parts[2].strip().strip("}").strip()
            return (val, "mediawiki_tcg_id_template_card_name") if val else (None, None)
    if name.startswith("{{TCG|"):
        parts = name[2:].split("|")
        if len(parts) >= 2:
            val = parts[1].strip().strip("}").strip()
            return (val, "mediawiki_tcg_template_name") if val else (None, None)
    if name.startswith("[["):
        body = name[2:].strip().rstrip("]")
        if "|" in body:
            val = body.split("|")[-1].strip()
        else:
            val = re.sub(r"\s*\([^)]*$", "", body).strip()
        return (val, "mediawiki_link_display_or_title_name") if val else (None, None)
    return None, None


def is_dirty(name: str | None) -> bool:
    return bool(name) and (name.startswith("{{") or name.startswith("[[") or name == "Pardon Our Interruption")


def existing_source(cur: sqlite3.Cursor, language_code: str, card_id: str) -> tuple[str, str]:
    r = cur.execute("""
        SELECT source_url, method FROM card_source_provenance
        WHERE language_code=? AND card_id=? AND source_url IS NOT NULL AND TRIM(source_url) <> ''
        ORDER BY CASE WHEN method LIKE 'bulbapedia%' THEN 0 ELSE 1 END, fetched_at DESC
        LIMIT 1
    """, (language_code, card_id)).fetchone()
    if r:
        return r["source_url"], r["method"]
    return f"internal://pokemon-db/source-backed-template-cleanup/{language_code}/{card_id}", "existing_card_row_template_artifact"


def recreate_views(cur: sqlite3.Cursor) -> None:
    cur.execute("DROP VIEW IF EXISTS cards_with_resolved_sets")
    cur.execute("""
        CREATE VIEW cards_with_resolved_sets AS
        SELECT c.language_code,c.set_id,c.card_id,c.local_id,c.local_id_sort,c.name,c.image_url,
               COALESCE(sa.target_language_code,c.language_code) AS resolved_language_code,
               COALESCE(sa.target_set_id,c.set_id) AS resolved_set_id,
               rs.name AS resolved_set_name, rs.series_name AS resolved_series_name, rs.release_date AS resolved_release_date,
               CASE WHEN sa.target_set_id IS NOT NULL THEN 1 ELSE 0 END AS resolved_via_set_alias,
               sa.alias_type AS set_alias_type, sa.method AS set_alias_method, sa.confidence AS set_alias_confidence, sa.notes AS set_alias_notes
        FROM cards c
        LEFT JOIN set_aliases sa ON sa.alias_language_code=c.language_code AND sa.alias_set_id=c.set_id
        LEFT JOIN sets rs ON rs.language_code=COALESCE(sa.target_language_code,c.language_code) AND rs.set_id=COALESCE(sa.target_set_id,c.set_id)
    """)
    cur.execute("DROP VIEW IF EXISTS cards_v2")
    cur.execute("""
        CREATE VIEW cards_v2 AS
        SELECT c.*,
               COALESCE(ls.core_set_id, sac.target_core_set_id) AS core_set_id,
               sc.canonical_name AS core_set_name,
               sc.canonical_language_code AS core_canonical_language_code,
               sc.canonical_set_id AS core_canonical_set_id,
               CASE WHEN COALESCE(ls.core_set_id, sac.target_core_set_id) IS NOT NULL THEN 1 ELSE 0 END AS resolved_to_core,
               CASE WHEN sac.target_core_set_id IS NOT NULL THEN 1 ELSE 0 END AS resolved_via_core_alias
        FROM cards_with_resolved_sets c
        LEFT JOIN localized_sets ls ON ls.language_code=c.resolved_language_code AND ls.set_id=c.resolved_set_id
        LEFT JOIN set_aliases_core sac ON sac.alias_language_code=c.language_code AND sac.alias_set_id=c.set_id
        LEFT JOIN sets_core sc ON sc.core_set_id=COALESCE(ls.core_set_id, sac.target_core_set_id)
    """)
    cur.execute("DROP VIEW IF EXISTS v2_quality_summary")
    cur.execute("""
        CREATE VIEW v2_quality_summary AS
        SELECT 'cards_v2_rows' metric, COUNT(*) value FROM cards_v2
        UNION ALL SELECT 'raw_unmatched_card_set_rows', COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)
        UNION ALL SELECT 'localized_view_unmatched_card_set_rows', COUNT(*) FROM cards_with_resolved_sets c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.resolved_language_code AND s.set_id=c.resolved_set_id)
        UNION ALL SELECT 'core_unresolved_card_rows', COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL
        UNION ALL SELECT 'visible_template_names', COUNT(*) FROM cards WHERE name LIKE '{{%' OR name LIKE '[[%' OR name='Pardon Our Interruption'
    """)


def audit_wave_sql(cur: sqlite3.Cursor) -> dict[str, Any]:
    return {
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "cards_v2": scalar(cur, "SELECT COUNT(*) FROM cards_v2"),
        "core_unresolved": scalar(cur, "SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL"),
        "raw_unmatched": scalar(cur, "SELECT COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)"),
        "localized_view_unmatched": scalar(cur, "SELECT COUNT(*) FROM cards_with_resolved_sets c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.resolved_language_code AND s.set_id=c.resolved_set_id)"),
        "visible_template_names": scalar(cur, "SELECT COUNT(*) FROM cards WHERE name LIKE '{{%' OR name LIKE '[[%' OR name='Pardon Our Interruption'"),
        "unresolved_fallback_rows": scalar(cur, """SELECT COUNT(*) FROM card_source_provenance p WHERE p.method='cross_language_template' AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))"""),
        "placeholder_names": scalar(cur, "SELECT COUNT(*) FROM cards WHERE name LIKE 'Unknown card %' OR name LIKE 'Unknown %' OR name LIKE 'Unresolved %' OR name='Pardon Our Interruption'"),
        "missing_language_set_rows": scalar(cur, "SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id)"),
        "language_orphan_rows": scalar(cur, "SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL"),
        "integrity_check": scalar(cur, "PRAGMA integrity_check"),
        "quick_check": scalar(cur, "PRAGMA quick_check"),
        "foreign_key_check_rows": len(rows(cur, "PRAGMA foreign_key_check")),
    }


def audit_wave_python(cur: sqlite3.Cursor) -> dict[str, Any]:
    cards = rows(cur, "SELECT language_code,set_id,card_id,name FROM cards")
    sets = {(r["language_code"], r["set_id"]) for r in rows(cur, "SELECT language_code,set_id FROM sets")}
    langs = {r["code"] for r in rows(cur, "SELECT code FROM languages")}
    core_unresolved = scalar(cur, "SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL")  # view cross-check still deliberate
    return {
        "cards": len(cards),
        "sets": len(sets),
        "languages": len(langs),
        "raw_unmatched": sum(1 for c in cards if (c["language_code"], c["set_id"]) not in sets),
        "visible_template_names": sum(1 for c in cards if is_dirty(c["name"])),
        "language_orphan_rows": sum(1 for c in cards if c["language_code"] not in langs),
        "core_unresolved": core_unresolved,
    }


def main() -> int:
    fetched_at = now_utc(); REPORTS.mkdir(parents=True, exist_ok=True)
    backup = DB.with_name(DB.stem + f".backup_before_v2_completion_{stamp()}" + DB.suffix)
    shutil.copy2(DB, backup)
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    cur = conn.cursor(); cur.execute("PRAGMA foreign_keys=ON")
    before = audit_wave_sql(cur)

    # Resolve remaining core-unresolved buckets through core aliases only.
    core_aliases = [
        # exact base XY set rows that use alias set_id XY, target core xy1 in same language
        *[(lang, "XY", "xy1", "v2_manual_xy_alias_to_xy1_core", 0.99, "XY orphan bucket has 146 cards matching existing localized xy1 set total/count/name.") for lang in ["de","en","es","fr","it","pt"]],
        ("zh-tw", "S-P", "S-P", "v2_same_set_id_alias_to_existing_core", 0.90, "Traditional Chinese S-P orphan bucket mapped to existing S-P core identity only; no localized set row created."),
        ("th", "SVAL", "SVAL", "v2_same_set_id_alias_to_existing_core", 0.85, "Thai SVAL orphan bucket mapped to existing SVAL core identity only; candidate set exists in id/zh-tw source index."),
        ("th", "SVAM", "SVAM", "v2_same_set_id_alias_to_existing_core", 0.85, "Thai SVAM orphan bucket mapped to existing SVAM core identity only; candidate set exists in id/zh-tw source index."),
        ("th", "SVAW", "SVAW", "v2_same_set_id_alias_to_existing_core", 0.85, "Thai SVAW orphan bucket mapped to existing SVAW core identity only; candidate set exists in id/zh-tw source index."),
    ]
    inserted_core_aliases = 0
    for lang, alias_set_id, core_set_id, method, conf, note in core_aliases:
        if scalar(cur, "SELECT COUNT(*) FROM cards_v2 WHERE language_code=? AND set_id=? AND core_set_id IS NULL", (lang, alias_set_id)) == 0:
            continue
        if scalar(cur, "SELECT COUNT(*) FROM sets_core WHERE core_set_id=?", (core_set_id,)) == 0:
            continue
        cur.execute("""
            INSERT OR REPLACE INTO set_aliases_core(alias_language_code,alias_set_id,target_core_set_id,target_language_code,target_set_id,alias_type,source_url,method,confidence,status,notes,reviewed_by,reviewed_at,fetched_at)
            VALUES (?,?,?,?,?,'core_identity_alias',NULL,?,?,'resolved_to_core',?,'Hermes Agent',?,?)
        """, (lang, alias_set_id, core_set_id, None, None, method, conf, note, fetched_at, fetched_at))
        inserted_core_aliases += cur.rowcount
    recreate_views(cur)

    # Clean visible template names source-backed by template source/provenance.
    dirty = rows(cur, "SELECT language_code,set_id,card_id,local_id,name FROM cards WHERE name LIKE '{{%' OR name LIKE '[[%' OR name='Pardon Our Interruption' ORDER BY language_code,set_id,local_id_sort,card_id")
    cleaned = []
    skipped = []
    for c in dirty:
        parallel = None
        pr = cur.execute("SELECT name FROM cards WHERE card_id=? AND name NOT LIKE '{{%' AND name NOT LIKE '[[%' AND name <> 'Pardon Our Interruption' ORDER BY CASE WHEN language_code='en' THEN 0 WHEN language_code='fr' THEN 1 ELSE 2 END LIMIT 1", (c["card_id"],)).fetchone()
        if pr: parallel = pr["name"]
        new_name, rule = clean_name(c["name"], parallel)
        if not new_name or is_dirty(new_name):
            skipped.append({**c, "reason": "no_source_backed_parse_rule"})
            continue
        source_url, source_method = existing_source(cur, c["language_code"], c["card_id"])
        old = c["name"]
        cur.execute("UPDATE cards SET name=? WHERE language_code=? AND card_id=?", (new_name, c["language_code"], c["card_id"]))
        cur.execute("UPDATE card_details SET name=? WHERE language_code=? AND card_id=?", (new_name, c["language_code"], c["card_id"]))
        method = "v2_visible_template_artifact_cleanup"
        note = f"Replaced visible legacy artifact {old!r} with source-backed parsed/recovered name {new_name!r}; rule={rule}; prior_source_method={source_method}. No machine translation."
        cur.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """, (c["language_code"], c["set_id"], c["card_id"], source_url, method, note, fetched_at))
        # General provenance too.
        doc_id = hid("src", source_url, method, c["language_code"])
        cur.execute("INSERT OR IGNORE INTO source_documents(source_document_id,source_url,source_type,language_code,fetched_at,retrieved_by,reliability_notes) VALUES (?,?, 'v2_template_cleanup_source', ?, ?, 'Hermes Agent', 'Template cleanup source derived from existing provenance or clean parallel row; no translation.')", (doc_id, source_url, c["language_code"], fetched_at))
        prov_id = hid("prov", "cards", c["language_code"], c["card_id"], method, source_url)
        cur.execute("""
            INSERT OR REPLACE INTO provenance_records(provenance_id,entity_table,entity_key,language_code,source_document_id,source_url,method,fetched_at,confidence,source_notes,extraction_notes,created_at)
            VALUES (?, 'cards', ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)
        """, (prov_id, f"{c['language_code']}:{c['card_id']}", c["language_code"], doc_id, source_url, method, fetched_at, note, f"old_name={old!r}; new_name={new_name!r}; rule={rule}", fetched_at))
        cleaned.append({**c, "new_name": new_name, "rule": rule, "source_url": source_url})
    conn.commit(); recreate_views(cur); conn.commit()

    # Reports/audits.
    wave1 = audit_wave_sql(cur)
    wave2 = audit_wave_python(cur)
    wave2_matches = {
        "cards": wave1["cards"] == wave2["cards"],
        "sets": wave1["sets"] == wave2["sets"],
        "languages": wave1["languages"] == wave2["languages"],
        "raw_unmatched": wave1["raw_unmatched"] == wave2["raw_unmatched"],
        "visible_template_names": wave1["visible_template_names"] == wave2["visible_template_names"],
        "language_orphan_rows": wave1["language_orphan_rows"] == wave2["language_orphan_rows"],
        "core_unresolved": wave1["core_unresolved"] == wave2["core_unresolved"],
    }
    write_csv(REPORTS / "v2_template_artifact_cleanup_rows.csv", cleaned)
    write_csv(REPORTS / "v2_template_artifact_cleanup_skipped.csv", skipped)
    remaining_core = rows(cur, "SELECT language_code,set_id,COUNT(*) rows FROM cards_v2 WHERE core_set_id IS NULL GROUP BY language_code,set_id ORDER BY rows DESC")
    write_csv(REPORTS / "v2_remaining_core_unresolved_after_completion.csv", remaining_core)
    report = {
        "fetched_at": fetched_at,
        "database": str(DB),
        "backup": str(backup),
        "before": before,
        "actions": {
            "core_aliases_inserted_or_replaced": inserted_core_aliases,
            "template_artifact_rows_seen": len(dirty),
            "template_artifact_rows_cleaned": len(cleaned),
            "template_artifact_rows_skipped": len(skipped),
            "raw_cards_rewritten": "Only cards.name/card_details.name visible template artifacts were cleaned; cards.set_id and language_code were not rewritten.",
        },
        "wave_1_sql_audit": wave1,
        "wave_2_python_audit": wave2,
        "wave_matches": wave2_matches,
        "pass": bool(
            wave1["core_unresolved"] == 0 and wave1["visible_template_names"] == 0 and
            wave1["unresolved_fallback_rows"] == 0 and wave1["placeholder_names"] == 0 and
            wave1["missing_language_set_rows"] == 0 and wave1["language_orphan_rows"] == 0 and
            wave1["integrity_check"] == "ok" and wave1["quick_check"] == "ok" and all(wave2_matches.values())
        ),
        "known_caveat": "PRAGMA foreign_key_check still reports raw cards->sets violations because raw cards.set_id is intentionally preserved; v2 views/core resolve them without destructive set_id rewrite.",
        "artifacts": {
            "cleaned_rows_csv": str(REPORTS / "v2_template_artifact_cleanup_rows.csv"),
            "skipped_rows_csv": str(REPORTS / "v2_template_artifact_cleanup_skipped.csv"),
            "remaining_core_unresolved_csv": str(REPORTS / "v2_remaining_core_unresolved_after_completion.csv"),
        }
    }
    out = REPORTS / f"v2_completion_two_wave_audit_{fetched_at[:10]}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out), "backup": str(backup), "pass": report["pass"], "cleaned": len(cleaned), "skipped": len(skipped), "core_unresolved": wave1["core_unresolved"], "visible_templates": wave1["visible_template_names"], "integrity": wave1["integrity_check"], "quick": wave1["quick_check"]}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
