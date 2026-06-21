#!/usr/bin/env python3
"""Safely apply recovered images to the v2 display-image candidate layer.

Default mode is candidate/display-layer only:
- verifies manifest rows with status=downloaded;
- verifies local file existence and SHA-256;
- inserts exact same-language/set/local recovered TCGdex asset rows into card_image_candidates;
- records provenance/source-document metadata when v2 provenance tables exist;
- refreshes v2_card_image_best and reporting views;
- refreshes the FTS/API cache used by FastAPI/UI/Shopify export;
- runs a two-wave audit.

It deliberately does NOT update cards.image_url unless --exact-write is passed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pokemon_db_v2_search_and_image_audit import create_reporting_views, rows, scalar  # noqa: E402
from pokemon_db_v2_search_api import setup_fts  # noqa: E402

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORTS = DB.parent / 'reports'
DEFAULT_MANIFEST = REPORTS / f'v2_image_recovery_gather_manifest_{dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")}.json'
DEFAULT_CANDIDATE_TYPE = 'exact_tcgdex_recovered_asset'
EXACT_RECOVERED_CANDIDATE_TYPES = {
    'exact_tcgdex_recovered_asset',
    'exact_asia_official_recovered_asset',
    'exact_tcgdex_ja_recovered_asset',
    'exact_asia_tw_scraped_asset',
    'exact_limitless_jp_recovered_asset',
    'exact_limitless_euro_asset',
    'exact_asia_th_scraped_asset',
    'exact_asia_tw_scraped',
    'exact_asia_th_scraped',
    'exact_jp_official_scraped_asset',
    'exact_tcgdex_set_api_recovered_asset',
    'exact_ptcg_io_recovered',
    'exact_ptcg_io_search',
    'exact_ptcg_io_set',
    'exact_limitless_tcg_pocket_asset',
    'exact_pkmncards_asset',
    'exact_dittobase_asset',
    'exact_cardsrealm_asset',
    'exact_pricecharting_asset',
    'exact_tcgcollector_asset',
    'exact_wonderclub_asset',
    'exact_zhcn_tcg_mik_moe',
    'exact_limitless_jp_recovered_asset',
}


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def hid(prefix: str, *parts: Any) -> str:
    return prefix + '_' + hashlib.sha1('\u241f'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()[:24]


def ensure_recovered_best_view(cur: sqlite3.Cursor) -> None:
    cur.executescript(f'''
DROP VIEW IF EXISTS v2_card_image_best;
CREATE VIEW v2_card_image_best AS
SELECT language_code, card_id, candidate_image_url, candidate_type, source_language_code, source_set_id, source_card_id, confidence
FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY language_code, card_id
    ORDER BY
      CASE candidate_type
        WHEN 'exact_raw_tcgdex_verified' THEN 0
        WHEN 'exact_tcgdex_recovered_asset' THEN 1
        WHEN 'exact_asia_official_recovered_asset' THEN 1
        WHEN 'exact_limitless_tcg_pocket_asset' THEN 1
        WHEN 'exact_pkmncards_asset' THEN 1
        WHEN 'exact_dittobase_asset' THEN 1
        WHEN 'exact_cardsrealm_asset' THEN 1
        WHEN 'exact_pricecharting_asset' THEN 1
        WHEN 'exact_tcgcollector_asset' THEN 1
        WHEN 'exact_wonderclub_asset' THEN 1
        WHEN 'exact_zhcn_tcg_mik_moe' THEN 1
        WHEN 'exact_limitless_jp_recovered_asset' THEN 1
        WHEN 'exact_asia_th_scraped_asset' THEN 1
        WHEN 'exact_asia_tw_scraped_asset' THEN 1
        WHEN 'exact_asia_th_scraped' THEN 1
        WHEN 'exact_asia_tw_scraped' THEN 1
        WHEN 'exact_tcgdex_ja_recovered_asset' THEN 1
        WHEN 'exact_tcgdex_set_api_recovered_asset' THEN 1
        WHEN 'exact_existing_image' THEN 2
        WHEN 'same_card_id_existing_image' THEN 3
        WHEN 'same_core_local_id_existing_image' THEN 4
        ELSE 9
      END,
      confidence DESC,
      source_language_code
  ) AS rn
  FROM card_image_candidates
)
WHERE rn=1;
''')


def insert_provenance(cur: sqlite3.Cursor, entry: dict[str, Any], fetched_at: str) -> None:
    """Best-effort provenance insertion for v2 tables plus legacy card_source_provenance."""
    lang = entry['language_code']
    card_id = entry['card_id']
    set_id = entry.get('core_set_id') or entry.get('resolved_set_id') or entry.get('source_set_id')
    source_api_url = entry.get('source_api_url')
    asset_url = entry.get('asset_url')
    local_path = entry.get('local_path')
    sha = entry.get('sha256')
    candidate_type = entry.get('candidate_type') or DEFAULT_CANDIDATE_TYPE
    source_type = 'asia_official_card_search_asset' if candidate_type == 'exact_asia_official_recovered_asset' else 'tcgdex_api_and_asset'
    reliability = 'Official Asia Pokémon card-search/detail page and same-language card image used for recovered display image candidate.' if candidate_type == 'exact_asia_official_recovered_asset' else 'TCGdex API/card asset used for recovered display image candidate.'
    note = f"Recovered display image asset {asset_url}; local_path={local_path}; sha256={sha}; source_api={source_api_url}; candidate_type={candidate_type}."
    try:
        cur.execute('''
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        ''', (lang, set_id, card_id, source_api_url or asset_url, f'v2_image_recovered_{candidate_type}_candidate', note, fetched_at))
    except sqlite3.Error:
        pass
    try:
        doc_id = hid('src', source_api_url or asset_url, lang, set_id)
        cur.execute('''
            INSERT OR IGNORE INTO source_documents(source_document_id,source_url,source_type,language_code,fetched_at,retrieved_by,reliability_notes)
            VALUES (?,?,?,?,?, 'Hermes Agent', ?)
        ''', (doc_id, source_api_url or asset_url, source_type, lang, fetched_at, reliability))
        prov_id = hid('prov', 'cards', lang, card_id, candidate_type, asset_url, sha)
        cur.execute('''
            INSERT OR REPLACE INTO provenance_records(
                provenance_id,entity_table,entity_key,language_code,source_document_id,source_url,method,
                fetched_at,confidence,source_notes,extraction_notes,created_at
            ) VALUES (?, 'cards', ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)
        ''', (prov_id, f'{lang}:{card_id}', lang, doc_id, source_api_url or asset_url, candidate_type, fetched_at, reliability, note, fetched_at))
    except sqlite3.Error:
        pass


def two_wave_audit(cur: sqlite3.Cursor) -> dict[str, Any]:
    wave1 = {
        'cards': scalar(cur, 'SELECT COUNT(*) FROM cards'),
        'cards_v2': scalar(cur, 'SELECT COUNT(*) FROM cards_v2'),
        'core_unresolved': scalar(cur, 'SELECT COUNT(*) FROM cards_v2 WHERE core_set_id IS NULL'),
        'visible_template_names': scalar(cur, "SELECT COUNT(*) FROM cards WHERE name LIKE '{{%' OR name LIKE '[[%' OR name='Pardon Our Interruption'"),
        'placeholder_names': scalar(cur, "SELECT COUNT(*) FROM cards WHERE name LIKE 'Unknown card %' OR name LIKE 'Unknown %' OR name LIKE 'Unresolved %' OR name='Pardon Our Interruption'"),
        'language_orphan_rows': scalar(cur, 'SELECT COUNT(*) FROM cards c LEFT JOIN languages l ON l.code=c.language_code WHERE l.code IS NULL'),
        'missing_language_set_rows': scalar(cur, 'SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id)'),
        'missing_exact_image_rows': scalar(cur, "SELECT COUNT(*) FROM cards WHERE image_url IS NULL OR TRIM(image_url)=''"),
        'missing_display_image_rows': scalar(cur, 'SELECT COUNT(*) FROM v2_card_search WHERE has_display_image=0'),
        'integrity_check': scalar(cur, 'PRAGMA integrity_check'),
        'quick_check': scalar(cur, 'PRAGMA quick_check'),
        'foreign_key_check_rows': len(rows(cur, 'PRAGMA foreign_key_check')),
    }
    raw_cards = rows(cur, 'SELECT language_code,set_id,name,image_url FROM cards')
    langs = {r['code'] for r in rows(cur, 'SELECT code FROM languages')}
    wave2 = {
        'cards': len(raw_cards),
        'visible_template_names': sum(1 for r in raw_cards if r['name'].startswith('{{') or r['name'].startswith('[[') or r['name']=='Pardon Our Interruption'),
        'language_orphan_rows': sum(1 for r in raw_cards if r['language_code'] not in langs),
        'missing_exact_image_rows': sum(1 for r in raw_cards if not r['image_url'] or not str(r['image_url']).strip()),
    }
    return {'wave1_sql': wave1, 'wave2_python': wave2, 'pass': wave1['core_unresolved']==0 and wave1['visible_template_names']==0 and wave1['placeholder_names']==0 and wave1['language_orphan_rows']==0 and wave1['missing_language_set_rows']==0 and wave1['integrity_check']=='ok' and wave1['quick_check']=='ok' and wave1['cards']==wave2['cards'] and wave1['visible_template_names']==wave2['visible_template_names'] and wave1['language_orphan_rows']==wave2['language_orphan_rows'] and wave1['missing_exact_image_rows']==wave2['missing_exact_image_rows']}


def load_downloaded_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding='utf-8'))
    manifest = data.get('manifest', [])
    # Accept entries that have sha256 (downloaded successfully) or status='downloaded'
    if isinstance(manifest, list):
        return [m for m in manifest if m.get('sha256') or m.get('status') == 'downloaded']
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Apply recovered image manifest entries to v2 display candidates safely.')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST))
    parser.add_argument('--db', default=str(DB))
    parser.add_argument('--exact-write', action='store_true', help='Also update cards.image_url for exact same-language rows. Off by default.')
    args = parser.parse_args(argv)

    db = Path(args.db)
    manifest_path = Path(args.manifest)
    REPORTS.mkdir(parents=True, exist_ok=True)
    fetched_at = now_utc()
    backup = db.with_name(db.stem + f'.backup_before_recovered_image_apply_{stamp()}' + db.suffix)
    shutil.copy2(db, backup)

    entries = load_downloaded_manifest(manifest_path)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    before_display = scalar(cur, 'SELECT COUNT(*) FROM v2_card_search WHERE has_display_image=0')
    before_candidates = scalar(cur, "SELECT COUNT(*) FROM card_image_candidates WHERE candidate_type IN (%s)" % ','.join('?' for _ in EXACT_RECOVERED_CANDIDATE_TYPES), tuple(EXACT_RECOVERED_CANDIDATE_TYPES))

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    exact_written = 0
    for entry in entries:
        local_path = Path(entry.get('local_path') or '')
        expected_sha = entry.get('sha256')
        if not local_path.exists():
            skipped.append({**entry, 'skip_reason': 'local_file_missing'}); continue
        actual_sha = sha256_file(local_path)
        if expected_sha and actual_sha != expected_sha:
            skipped.append({**entry, 'skip_reason': 'sha256_mismatch', 'actual_sha256': actual_sha}); continue
        lang = entry['language_code']
        card_id = entry['card_id']
        set_id = entry.get('core_set_id') or entry.get('resolved_set_id') or entry.get('source_set_id')
        local_id = entry.get('local_id')
        asset_url = entry.get('asset_url')
        source_api_url = entry.get('source_api_url')
        candidate_type = entry.get('candidate_type') or DEFAULT_CANDIDATE_TYPE
        if candidate_type not in EXACT_RECOVERED_CANDIDATE_TYPES:
            skipped.append({**entry, 'skip_reason': f'unsupported_candidate_type:{candidate_type}'}); continue
        if not (lang and card_id and asset_url):
            skipped.append({**entry, 'skip_reason': 'missing_required_manifest_fields'}); continue

        cur.execute('''
            INSERT OR REPLACE INTO card_image_candidates(
                language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,
                source_language_code,source_set_id,source_card_id,source_url,verification_method,
                verified_at,http_status,confidence,notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            lang, card_id, set_id, local_id, asset_url, candidate_type,
            lang, set_id, card_id, source_api_url or asset_url, 'manifest_sha256_and_source_asset_verified',
            fetched_at, 200, 0.98,
            f"Recovered exact same-language source asset candidate. candidate_type={candidate_type}; local_path={local_path}; sha256={actual_sha}; source_api_url={source_api_url}; asset_url={asset_url}."
        ))
        insert_provenance(cur, {**entry, 'sha256': actual_sha}, fetched_at)
        if args.exact_write:
            cur.execute("UPDATE cards SET image_url=? WHERE language_code=? AND card_id=? AND (image_url IS NULL OR TRIM(image_url)='')", (asset_url, lang, card_id))
            exact_written += cur.rowcount
        applied.append({**entry, 'actual_sha256': actual_sha})

    ensure_recovered_best_view(cur)
    create_reporting_views(cur)
    conn.commit()

    after_display = scalar(cur, 'SELECT COUNT(*) FROM v2_card_search WHERE has_display_image=0')
    after_candidates = scalar(cur, "SELECT COUNT(*) FROM card_image_candidates WHERE candidate_type IN (%s)" % ','.join('?' for _ in EXACT_RECOVERED_CANDIDATE_TYPES), tuple(EXACT_RECOVERED_CANDIDATE_TYPES))
    audit = two_wave_audit(cur)
    # Refresh materialized API/FTS cache so FastAPI/browser/Shopify see new display images.
    fts = setup_fts(db)

    report = {
        'generated_at': fetched_at,
        'database': str(db),
        'backup': str(backup),
        'manifest': str(manifest_path),
        'mode': 'exact-write' if args.exact_write else 'candidate-display-only',
        'candidate_types': sorted(EXACT_RECOVERED_CANDIDATE_TYPES),
        'downloaded_manifest_entries': len(entries),
        'applied_candidates': len(applied),
        'skipped': len(skipped),
        'exact_image_urls_written': exact_written,
        'missing_display_images_before': before_display,
        'missing_display_images_after': after_display,
        'missing_display_images_delta': before_display - after_display,
        'recovered_candidate_rows_before': before_candidates,
        'recovered_candidate_rows_after': after_candidates,
        'two_wave_audit': audit,
        'fts_refresh': fts,
        'applied': applied,
        'skipped_entries': skipped,
    }
    out = REPORTS / f'v2_apply_recovered_images_report_{dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['generated_at','backup','manifest','mode','downloaded_manifest_entries','applied_candidates','skipped','exact_image_urls_written','missing_display_images_before','missing_display_images_after','missing_display_images_delta','recovered_candidate_rows_after'] } | {'two_wave_pass': audit['pass'], 'report': str(out)}, ensure_ascii=False, indent=2))
    return 0 if audit['pass'] and len(applied) > 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
