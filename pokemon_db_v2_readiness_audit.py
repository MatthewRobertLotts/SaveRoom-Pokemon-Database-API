#!/usr/bin/env python3
"""Pokémon Card Database v2 readiness audit and safe proposal-table builder.

This script is intentionally non-destructive for card/set data. With --apply-proposal-table
it creates/replaces only a generated proposal table, `set_aliases_proposed`, which records
candidate mappings for card rows whose (language_code,set_id) currently has no parent in `sets`.
It does not rewrite `cards.set_id`.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_DB = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
DEFAULT_REPORTS = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports")

VISIBLE_TEMPLATE_SQL = """
SELECT COUNT(*) FROM cards
WHERE name LIKE '{{%' OR name LIKE '[[%' OR name = 'Pardon Our Interruption'
"""

UNRESOLVED_FALLBACK_SQL = """
SELECT COUNT(*)
FROM card_source_provenance p
WHERE p.method = 'cross_language_template'
  AND NOT EXISTS (
    SELECT 1 FROM card_source_provenance r
    WHERE r.language_code = p.language_code
      AND r.card_id = p.card_id
      AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
  )
"""

PLACEHOLDER_SQL = """
SELECT COUNT(*) FROM cards
WHERE name LIKE 'Unknown card %'
   OR name LIKE 'Unknown %'
   OR name LIKE 'Unresolved %'
   OR name = 'Pardon Our Interruption'
"""

MISSING_LANGUAGE_SET_ROWS_SQL = """
SELECT COUNT(*)
FROM sets s
WHERE NOT EXISTS (
  SELECT 1 FROM cards c
  WHERE c.language_code = s.language_code AND c.set_id = s.set_id
)
"""

UNMATCHED_CARD_SET_SQL = """
SELECT c.language_code, c.set_id, COUNT(*) AS rows,
       MIN(c.local_id_sort) AS min_local_id_sort, MAX(c.local_id_sort) AS max_local_id_sort,
       COUNT(DISTINCT c.local_id) AS distinct_local_ids,
       SUM(CASE WHEN c.name LIKE '{{%' OR c.name LIKE '[[%' OR c.name = 'Pardon Our Interruption' THEN 1 ELSE 0 END) AS visible_template_rows,
       SUM(CASE WHEN c.image_url IS NULL OR c.image_url = '' THEN 1 ELSE 0 END) AS missing_image_rows
FROM cards c
WHERE NOT EXISTS (
  SELECT 1 FROM sets s
  WHERE s.language_code = c.language_code AND s.set_id = c.set_id
)
GROUP BY c.language_code, c.set_id
ORDER BY rows DESC, c.language_code, c.set_id
"""


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = s.replace("pokémon", "pokemon")
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def rows_to_dicts(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def scalar(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return cur.execute(sql, params).fetchone()[0]


def build_set_indexes(cur: sqlite3.Cursor) -> dict[str, Any]:
    sets = rows_to_dicts(cur, "SELECT language_code,set_id,name,series_name,abbreviation,tcg_online,official_count,total_count FROM sets")
    by_lang_setid = {(r["language_code"], r["set_id"]): r for r in sets}
    exact_by_lang: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    norm_by_lang: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    global_exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    global_norm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in sets:
        candidates = [r.get("set_id"), r.get("name"), r.get("abbreviation"), r.get("tcg_online")]
        for val in candidates:
            if not val:
                continue
            exact_by_lang[r["language_code"]][val].append(r)
            global_exact[val].append(r)
            n = norm(val)
            if n:
                norm_by_lang[r["language_code"]][n].append(r)
                global_norm[n].append(r)
    return {
        "sets": sets,
        "by_lang_setid": by_lang_setid,
        "exact_by_lang": exact_by_lang,
        "norm_by_lang": norm_by_lang,
        "global_exact": global_exact,
        "global_norm": global_norm,
    }


def choose_candidate(unmatched: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
    lang = unmatched["language_code"]
    alias = unmatched["set_id"]
    rules: list[tuple[str, float, list[dict[str, Any]]]] = []
    if alias in indexes["exact_by_lang"].get(lang, {}):
        rules.append(("same_language_exact_set_field", 0.99, indexes["exact_by_lang"][lang][alias]))
    n = norm(alias)
    if n and n in indexes["norm_by_lang"].get(lang, {}):
        rules.append(("same_language_normalized_set_field", 0.94, indexes["norm_by_lang"][lang][n]))
    if alias in indexes["global_exact"]:
        rules.append(("cross_language_exact_set_field", 0.82, indexes["global_exact"][alias]))
    if n and n in indexes["global_norm"]:
        rules.append(("cross_language_normalized_set_field", 0.76, indexes["global_norm"][n]))

    # Prefer same-language, then unique target, then English as a reference only.
    for rule, confidence, cands in rules:
        same_lang = [c for c in cands if c["language_code"] == lang]
        pool = same_lang or cands
        if len(pool) == 1:
            c = pool[0]
            same_language_choice = bool(same_lang)
            return {
                "target_language_code": c["language_code"],
                "target_set_id": c["set_id"],
                "target_name": c["name"],
                "match_rule": rule,
                "confidence": confidence if same_language_choice else min(confidence, 0.72),
                "status": "proposed" if same_language_choice else "needs_review",
                "evidence": {
                    "candidate_count": len(cands),
                    "chosen_from_same_language": same_language_choice,
                    "official_count": c.get("official_count"),
                    "total_count": c.get("total_count"),
                    "note": None if same_language_choice else "Cross-language target identifies the likely canonical set id, but localized parent-row strategy must be approved before any rewrite.",
                },
            }
        english = [c for c in pool if c["language_code"] == "en"]
        if len(english) == 1:
            c = english[0]
            return {
                "target_language_code": c["language_code"],
                "target_set_id": c["set_id"],
                "target_name": c["name"],
                "match_rule": rule + "_english_reference_only",
                "confidence": min(confidence, 0.70),
                "status": "needs_review",
                "evidence": {"candidate_count": len(cands), "note": "English target is reference only; needs localized parent-row decision before rewrite."},
            }
        if pool:
            sample = [{"language_code": c["language_code"], "set_id": c["set_id"], "name": c["name"]} for c in pool[:10]]
            return {
                "target_language_code": None,
                "target_set_id": None,
                "target_name": None,
                "match_rule": rule,
                "confidence": 0.40,
                "status": "ambiguous",
                "evidence": {"candidate_count": len(cands), "sample_candidates": sample},
            }
    return {
        "target_language_code": None,
        "target_set_id": None,
        "target_name": None,
        "match_rule": "no_candidate_found",
        "confidence": 0.0,
        "status": "unmatched",
        "evidence": {},
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            f.write("")
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    ap.add_argument("--apply-proposal-table", action="store_true", help="Create/replace set_aliases_proposed in the DB. Does not change cards/sets.")
    args = ap.parse_args()

    fetched_at = now_utc()
    args.reports.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    schema = rows_to_dicts(cur, "SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','index','view','trigger') ORDER BY type,name")
    tables = {r["name"]: rows_to_dicts(cur, f"PRAGMA table_info({r['name']})") for r in schema if r["type"] == "table" and not r["name"].startswith("sqlite_")}

    totals = {
        "languages": scalar(cur, "SELECT COUNT(*) FROM languages"),
        "sets": scalar(cur, "SELECT COUNT(*) FROM sets"),
        "cards": scalar(cur, "SELECT COUNT(*) FROM cards"),
        "provenance_rows": scalar(cur, "SELECT COUNT(*) FROM card_source_provenance"),
    }
    gates = {
        "unresolved_fallback_rows": scalar(cur, UNRESOLVED_FALLBACK_SQL),
        "unknown_or_unresolved_placeholder_names": scalar(cur, PLACEHOLDER_SQL),
        "missing_language_set_rows": scalar(cur, MISSING_LANGUAGE_SET_ROWS_SQL),
        "visible_template_names": scalar(cur, VISIBLE_TEMPLATE_SQL),
        "cards_without_matching_set_total": scalar(cur, "SELECT COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM sets s WHERE s.language_code=c.language_code AND s.set_id=c.set_id)"),
        "card_language_codes_not_in_languages_total": scalar(cur, "SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL"),
        "cards_without_provenance_total": scalar(cur, "SELECT COUNT(*) FROM cards c WHERE NOT EXISTS (SELECT 1 FROM card_source_provenance p WHERE p.language_code=c.language_code AND p.card_id=c.card_id)"),
        "duplicate_language_set_local_id_groups_total": scalar(cur, "SELECT COUNT(*) FROM (SELECT language_code,set_id,local_id FROM cards WHERE local_id IS NOT NULL AND local_id <> '' GROUP BY language_code,set_id,local_id HAVING COUNT(*) > 1)"),
        "missing_image_urls_total": scalar(cur, "SELECT COUNT(*) FROM cards WHERE image_url IS NULL OR image_url=''"),
    }

    unmatched_groups = rows_to_dicts(cur, UNMATCHED_CARD_SET_SQL)
    indexes = build_set_indexes(cur)
    proposals: list[dict[str, Any]] = []
    for u in unmatched_groups:
        p = choose_candidate(u, indexes)
        proposals.append({
            "alias_language_code": u["language_code"],
            "alias_set_id": u["set_id"],
            "card_rows": u["rows"],
            "distinct_local_ids": u["distinct_local_ids"],
            "min_local_id_sort": u["min_local_id_sort"],
            "max_local_id_sort": u["max_local_id_sort"],
            "visible_template_rows": u["visible_template_rows"],
            "missing_image_rows": u["missing_image_rows"],
            **p,
            "evidence_json": json.dumps(p["evidence"], ensure_ascii=False, sort_keys=True),
            "created_at": fetched_at,
        })

    proposal_counts = Counter(p["status"] for p in proposals)
    proposed_rows_by_status = defaultdict(int)
    for p in proposals:
        proposed_rows_by_status[p["status"]] += int(p["card_rows"] or 0)

    esmx_summary = rows_to_dicts(cur, """
        SELECT c.set_id, COUNT(*) AS rows,
               COUNT(DISTINCT c.local_id) AS distinct_local_ids,
               SUM(CASE WHEN c.name LIKE '{{%' OR c.name LIKE '[[%' OR c.name = 'Pardon Our Interruption' THEN 1 ELSE 0 END) AS visible_template_rows,
               SUM(CASE WHEN c.image_url IS NULL OR c.image_url = '' THEN 1 ELSE 0 END) AS missing_image_rows,
               MIN(c.name) AS sample_name_min,
               MAX(c.name) AS sample_name_max
        FROM cards c
        WHERE c.language_code = 'es-mx'
        GROUP BY c.set_id
        ORDER BY rows DESC, c.set_id
    """)
    esmx_sample = rows_to_dicts(cur, """
        SELECT c.language_code,c.set_id,c.card_id,c.local_id,c.name,c.image_url
        FROM cards c
        WHERE c.language_code='es-mx'
        ORDER BY c.set_id,c.local_id_sort,c.card_id
        LIMIT 50
    """)
    languages = rows_to_dicts(cur, "SELECT * FROM languages ORDER BY code")

    unmatched_csv = args.reports / "v2_card_set_unmatched_groups.csv"
    proposals_csv = args.reports / "v2_set_aliases_proposed.csv"
    esmx_csv = args.reports / "v2_es_mx_audit.csv"
    write_csv(unmatched_csv, unmatched_groups)
    write_csv(proposals_csv, proposals)
    write_csv(esmx_csv, esmx_summary)

    table_applied = False
    table_before_count = None
    table_after_count = None
    if args.apply_proposal_table:
        table_before_count = scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='set_aliases_proposed'")
        cur.execute("DROP TABLE IF EXISTS set_aliases_proposed")
        cur.execute("""
            CREATE TABLE set_aliases_proposed (
                alias_language_code TEXT NOT NULL,
                alias_set_id TEXT NOT NULL,
                target_language_code TEXT,
                target_set_id TEXT,
                target_name TEXT,
                match_rule TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                card_rows INTEGER NOT NULL,
                distinct_local_ids INTEGER,
                min_local_id_sort INTEGER,
                max_local_id_sort INTEGER,
                visible_template_rows INTEGER NOT NULL DEFAULT 0,
                missing_image_rows INTEGER NOT NULL DEFAULT 0,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (alias_language_code, alias_set_id),
                FOREIGN KEY (target_language_code, target_set_id) REFERENCES sets(language_code, set_id)
            )
        """)
        cur.executemany("""
            INSERT INTO set_aliases_proposed (
                alias_language_code, alias_set_id, target_language_code, target_set_id, target_name,
                match_rule, confidence, status, card_rows, distinct_local_ids, min_local_id_sort,
                max_local_id_sort, visible_template_rows, missing_image_rows, evidence_json, created_at
            ) VALUES (:alias_language_code, :alias_set_id, :target_language_code, :target_set_id, :target_name,
                :match_rule, :confidence, :status, :card_rows, :distinct_local_ids, :min_local_id_sort,
                :max_local_id_sort, :visible_template_rows, :missing_image_rows, :evidence_json, :created_at)
        """, proposals)
        cur.execute("CREATE INDEX idx_set_aliases_proposed_target ON set_aliases_proposed(target_language_code, target_set_id)")
        cur.execute("CREATE INDEX idx_set_aliases_proposed_status ON set_aliases_proposed(status, confidence)")
        conn.commit()
        table_applied = True
        table_after_count = scalar(cur, "SELECT COUNT(*) FROM set_aliases_proposed")

    integrity = scalar(cur, "PRAGMA integrity_check")
    quick = scalar(cur, "PRAGMA quick_check")
    fk = rows_to_dicts(cur, "PRAGMA foreign_key_check")

    report = {
        "fetched_at": fetched_at,
        "database": str(args.db),
        "schema_summary": {"objects": len(schema), "tables": {k: [c["name"] for c in v] for k, v in tables.items()}},
        "totals": totals,
        "quality_gates": gates,
        "languages": languages,
        "set_alias_readiness": {
            "unmatched_groups": len(unmatched_groups),
            "unmatched_card_rows": gates["cards_without_matching_set_total"],
            "proposal_status_counts": dict(proposal_counts),
            "proposal_card_rows_by_status": dict(proposed_rows_by_status),
            "csv": str(proposals_csv),
            "unmatched_groups_csv": str(unmatched_csv),
            "interpretation": "Proposals are candidate aliases only; do not rewrite cards.set_id until each status=proposed mapping is manually/source reviewed and ambiguous/unmatched rows are resolved.",
        },
        "es_mx_audit": {
            "card_rows": sum(r["rows"] for r in esmx_summary),
            "set_groups": len(esmx_summary),
            "summary_csv": str(esmx_csv),
            "sample_rows": esmx_sample,
            "recommendation": "Keep es-mx as a separate language/locale candidate for now. Add language metadata only after accepting it as a supported locale; do not merge into es without card-by-card/source review because rows are currently a distinct import bucket.",
        },
        "applied_changes": {
            "set_aliases_proposed_table_created_or_replaced": table_applied,
            "table_existed_before": bool(table_before_count) if table_before_count is not None else None,
            "set_aliases_proposed_rows": table_after_count,
        },
        "verification": {
            "integrity_check": integrity,
            "quick_check": quick,
            "foreign_key_check_rows": len(fk),
            "foreign_key_check_sample": fk[:20],
            "cards_total_after": scalar(cur, "SELECT COUNT(*) FROM cards"),
            "sets_total_after": scalar(cur, "SELECT COUNT(*) FROM sets"),
            "languages_total_after": scalar(cur, "SELECT COUNT(*) FROM languages"),
            "provenance_total_after": scalar(cur, "SELECT COUNT(*) FROM card_source_provenance"),
        },
        "artifacts": {
            "unmatched_groups_csv": str(unmatched_csv),
            "set_aliases_proposed_csv": str(proposals_csv),
            "es_mx_audit_csv": str(esmx_csv),
        },
    }
    out = args.reports / f"v2_migration_readiness_{fetched_at[:10]}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out), "set_aliases_proposed_rows": table_after_count, "integrity_check": integrity, "quick_check": quick, "foreign_key_check_rows": len(fk)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
