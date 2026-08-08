#!/usr/bin/env python3
"""Create v2-backed search/reporting views and image URL recovery audit.

Safe rules:
- raw cards.set_id/language_code are not rewritten;
- cards.image_url is updated only for HTTP-verified exact same language+set raw-source image URLs;
- cross-language/core image matches are exposed as display candidates, not written to cards.image_url;
- reports are JSON/CSV under full_tcgdex/reports/;
- two-wave v2 audit runs after changes.
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
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
ROOT = DB.parent
REPORTS = ROOT / 'reports'
RAW_SETS = ROOT / 'raw' / 'sets'


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def scalar(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return cur.execute(sql, params).fetchone()[0]


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        if not data:
            f.write('')
            return
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader(); w.writerows(data)


def hid(prefix: str, *parts: Any) -> str:
    return prefix + '_' + hashlib.sha1('\u241f'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()[:24]


def verify_url(url: str, timeout: int = 12) -> tuple[bool, int | None, str | None]:
    try:
        req = Request(url, method='HEAD', headers={'User-Agent': 'HermesAgent/1.0'})
        with urlopen(req, timeout=timeout) as r:
            status = int(getattr(r, 'status', 0) or 0)
            ctype = r.headers.get('content-type')
            # TCGdex asset endpoints often respond text/html while still being valid asset handles.
            return (200 <= status < 400), status, ctype
    except HTTPError as e:
        return False, int(e.code), None
    except (URLError, TimeoutError, OSError):
        return False, None, None


def create_reporting_views(cur: sqlite3.Cursor) -> None:
    cur.executescript('''
DROP VIEW IF EXISTS v2_card_search;
CREATE VIEW v2_card_search AS
SELECT
  cv.language_code,
  l.name AS language_name,
  cv.card_id,
  cv.set_id AS raw_set_id,
  cv.resolved_set_id,
  cv.core_set_id,
  cv.core_set_name,
  cv.local_id,
  cv.local_id_sort,
  cv.name AS card_name,
  lower(cv.name || ' ' || COALESCE(cv.core_set_name,'') || ' ' || COALESCE(cv.resolved_set_name,'') || ' ' || cv.card_id || ' ' || COALESCE(cv.local_id,'')) AS search_text,
  cv.resolved_set_name,
  cv.resolved_series_name,
  cv.resolved_release_date,
  cd.category,
  cd.hp,
  cd.types,
  cd.rarity,
  cd.stage,
  cd.illustrator,
  cd.regulation_mark,
  cd.variants,
  cd.legal,
  cv.image_url AS exact_image_url,
  ib.candidate_image_url AS display_image_url,
  ib.candidate_type AS display_image_source_type,
  ib.source_language_code AS display_image_source_language_code,
  CASE WHEN cv.image_url IS NOT NULL AND TRIM(cv.image_url) <> '' THEN 1 ELSE 0 END AS has_exact_image,
  CASE WHEN ib.candidate_image_url IS NOT NULL THEN 1 ELSE 0 END AS has_display_image
FROM cards_v2 cv
LEFT JOIN languages l ON l.code=cv.language_code
LEFT JOIN card_details cd ON cd.language_code=cv.language_code AND cd.card_id=cv.card_id
LEFT JOIN v2_card_image_best ib ON ib.language_code=cv.language_code AND ib.card_id=cv.card_id;

DROP VIEW IF EXISTS v2_card_detail;
CREATE VIEW v2_card_detail AS
SELECT
  s.*,
  cd.attacks,
  cd.weaknesses,
  cd.resistances,
  cd.retreat,
  cd.description,
  (SELECT COUNT(*) FROM provenance_records pr WHERE pr.entity_table='cards' AND pr.entity_key=s.language_code || ':' || s.card_id) AS provenance_record_count,
  (SELECT COUNT(*) FROM card_source_provenance csp WHERE csp.language_code=s.language_code AND csp.card_id=s.card_id) AS legacy_provenance_count
FROM v2_card_search s
LEFT JOIN card_details cd ON cd.language_code=s.language_code AND cd.card_id=s.card_id;

DROP VIEW IF EXISTS v2_set_report;
CREATE VIEW v2_set_report AS
SELECT
  language_code,
  resolved_set_id,
  resolved_set_name,
  resolved_series_name,
  core_set_id,
  core_set_name,
  COUNT(*) AS card_rows,
  SUM(has_exact_image) AS rows_with_exact_images,
  COUNT(*) - SUM(has_exact_image) AS rows_missing_exact_images,
  SUM(has_display_image) AS rows_with_display_images,
  COUNT(*) - SUM(has_display_image) AS rows_missing_display_images,
  SUM(CASE WHEN provenance_record_count > 0 OR legacy_provenance_count > 0 THEN 1 ELSE 0 END) AS rows_with_any_provenance
FROM v2_card_detail
GROUP BY language_code,resolved_set_id,resolved_set_name,resolved_series_name,core_set_id,core_set_name;

DROP VIEW IF EXISTS v2_missing_image_audit;
CREATE VIEW v2_missing_image_audit AS
SELECT
  language_code,
  resolved_set_id,
  resolved_set_name,
  core_set_id,
  core_set_name,
  COUNT(*) AS missing_exact_image_rows,
  SUM(CASE WHEN display_image_url IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_display_fallback,
  SUM(CASE WHEN display_image_url IS NULL THEN 1 ELSE 0 END) AS rows_without_display_fallback,
  GROUP_CONCAT(DISTINCT display_image_source_type) AS fallback_source_types
FROM v2_card_search
WHERE has_exact_image=0
GROUP BY language_code,resolved_set_id,resolved_set_name,core_set_id,core_set_name;
''')


def ensure_image_tables(cur: sqlite3.Cursor) -> None:
    cur.executescript('''
CREATE TABLE IF NOT EXISTS card_image_candidates (
  language_code TEXT NOT NULL,
  card_id TEXT NOT NULL,
  set_id TEXT,
  local_id TEXT,
  candidate_image_url TEXT NOT NULL,
  candidate_type TEXT NOT NULL,
  source_language_code TEXT,
  source_set_id TEXT,
  source_card_id TEXT,
  source_url TEXT,
  verification_method TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  http_status INTEGER,
  confidence REAL NOT NULL DEFAULT 1.0,
  notes TEXT,
  PRIMARY KEY (language_code, card_id, candidate_type)
);
CREATE INDEX IF NOT EXISTS idx_card_image_candidates_card ON card_image_candidates(language_code, card_id);
CREATE INDEX IF NOT EXISTS idx_card_image_candidates_type ON card_image_candidates(candidate_type);

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


def raw_exact_candidates(cur: sqlite3.Cursor, fetched_at: str) -> list[dict[str, Any]]:
    missing = rows(cur, """
        SELECT language_code,set_id,card_id,local_id
        FROM cards
        WHERE image_url IS NULL OR TRIM(image_url)=''
        ORDER BY language_code,set_id,local_id_sort,card_id
    """)
    by_path: dict[Path, list[dict[str, Any]]] = {}
    for r in missing:
        p = RAW_SETS / r['language_code'] / f"{r['set_id']}.json"
        if p.exists():
            by_path.setdefault(p, []).append(r)
    candidates: list[dict[str, Any]] = []
    for path, wanted in by_path.items():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        index: dict[str, str] = {}
        for card in data.get('cards') or []:
            img = card.get('image')
            if not img:
                continue
            cid = card.get('id')
            local = card.get('localId') or card.get('local_id') or (cid.split('-')[-1] if cid else None)
            for key in {cid, local, str(local).lstrip('0') if local is not None else None, str(local).zfill(3) if local is not None else None}:
                if key:
                    index[str(key)] = img
        for r in wanted:
            lid = r.get('local_id') or ''
            img = index.get(r['card_id']) or index.get(lid) or index.get(lid.lstrip('0')) or index.get(lid.zfill(3))
            if img:
                candidates.append({**r, 'candidate_image_url': img, 'raw_json_path': str(path), 'verified_at': fetched_at})
    return candidates


def populate_display_candidates(cur: sqlite3.Cursor, fetched_at: str) -> dict[str, int]:
    # Existing exact image rows as candidates for themselves make v2_card_search display_image_url universal for exact rows too.
    cur.execute('''
INSERT OR REPLACE INTO card_image_candidates(language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,source_language_code,source_set_id,source_card_id,source_url,verification_method,verified_at,http_status,confidence,notes)
SELECT language_code,card_id,set_id,local_id,image_url,'exact_existing_image',language_code,set_id,card_id,image_url,'existing_db_value_not_reverified',?,NULL,1.0,'Existing image_url already present before this pass.'
FROM cards
WHERE image_url IS NOT NULL AND TRIM(image_url) <> ''
''', (fetched_at,))
    exact_existing = cur.rowcount

    # Same card_id fallback: useful for cross-language visual display, never written to exact image_url.
    cur.execute('''
CREATE TEMP TABLE IF NOT EXISTS tmp_missing_cards AS
SELECT language_code,set_id,card_id,local_id FROM cards WHERE image_url IS NULL OR TRIM(image_url)=''
''')
    cur.execute('CREATE INDEX IF NOT EXISTS tmp_missing_cards_card ON tmp_missing_cards(card_id)')
    cur.execute('''
CREATE TEMP TABLE tmp_same_card AS
SELECT * FROM (
  SELECT m.language_code,m.set_id,m.card_id,m.local_id,x.language_code AS src_lang,x.set_id AS src_set,x.card_id AS src_card,x.image_url,
         ROW_NUMBER() OVER (PARTITION BY m.language_code,m.card_id ORDER BY CASE WHEN x.language_code='en' THEN 0 WHEN x.language_code=m.language_code THEN 1 ELSE 2 END, x.language_code) rn
  FROM tmp_missing_cards m
  JOIN cards x ON x.card_id=m.card_id AND x.image_url IS NOT NULL AND TRIM(x.image_url) <> ''
)
WHERE rn=1
''')
    cur.execute('''
INSERT OR REPLACE INTO card_image_candidates(language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,source_language_code,source_set_id,source_card_id,source_url,verification_method,verified_at,http_status,confidence,notes)
SELECT language_code,card_id,set_id,local_id,image_url,'same_card_id_existing_image',src_lang,src_set,src_card,image_url,'existing_db_value_not_reverified',?,NULL,0.80,'Display fallback from an existing image_url on the same card_id; not written to cards.image_url.'
FROM tmp_same_card
''', (fetched_at,))
    same_card = cur.rowcount

    # Core/local fallback catches alias/core-equivalent rows where card_id differs.
    cur.execute('''
CREATE TEMP TABLE tmp_v2_images AS
SELECT language_code,set_id,card_id,local_id,core_set_id,image_url
FROM cards_v2
WHERE image_url IS NOT NULL AND TRIM(image_url) <> '' AND core_set_id IS NOT NULL
''')
    cur.execute('CREATE INDEX IF NOT EXISTS tmp_v2_images_core_local ON tmp_v2_images(core_set_id, local_id)')
    cur.execute('''
CREATE TEMP TABLE tmp_core_local AS
SELECT * FROM (
  SELECT m.language_code,m.set_id,m.card_id,m.local_id,v.language_code AS src_lang,v.set_id AS src_set,v.card_id AS src_card,v.image_url,
         ROW_NUMBER() OVER (PARTITION BY m.language_code,m.card_id ORDER BY CASE WHEN v.language_code='en' THEN 0 ELSE 1 END, v.language_code) rn
  FROM cards_v2 m
  JOIN tmp_v2_images v ON v.core_set_id=m.core_set_id AND v.local_id=m.local_id
  WHERE (m.image_url IS NULL OR TRIM(m.image_url)='') AND m.core_set_id IS NOT NULL
)
WHERE rn=1
''')
    cur.execute('''
INSERT OR IGNORE INTO card_image_candidates(language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,source_language_code,source_set_id,source_card_id,source_url,verification_method,verified_at,http_status,confidence,notes)
SELECT language_code,card_id,set_id,local_id,image_url,'same_core_local_id_existing_image',src_lang,src_set,src_card,image_url,'existing_db_value_not_reverified',?,NULL,0.65,'Display fallback from an existing image_url on the same core_set_id and local_id; not written to cards.image_url.'
FROM tmp_core_local
''', (fetched_at,))
    core_local = cur.rowcount
    return {'exact_existing_candidates': exact_existing, 'same_card_id_display_candidates': same_card, 'same_core_local_id_display_candidates': core_local}


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


def main() -> int:
    fetched_at = now_utc(); REPORTS.mkdir(parents=True, exist_ok=True)
    backup = DB.with_name(DB.stem + f'.backup_before_v2_search_image_{stamp()}' + DB.suffix)
    shutil.copy2(DB, backup)
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    cur = conn.cursor(); cur.execute('PRAGMA foreign_keys=ON')

    before_missing = scalar(cur, "SELECT COUNT(*) FROM cards WHERE image_url IS NULL OR TRIM(image_url)=''")
    ensure_image_tables(cur)
    # Rebuild deterministic fallback candidates on each run, while preserving
    # manifest-applied recovered exact source candidates. Those are created by
    # gather/apply scripts from verified local manifests and are not derivable
    # from raw cards.image_url, so deleting them would regress the display layer.
    cur.execute('DROP TABLE IF EXISTS tmp_recovered_image_candidates')
    cur.execute('''
CREATE TEMP TABLE tmp_recovered_image_candidates AS
SELECT * FROM card_image_candidates
WHERE candidate_type IN ('exact_tcgdex_recovered_asset','exact_asia_official_recovered_asset')
''')
    cur.execute('DELETE FROM card_image_candidates')
    conn.commit()

    # Exact raw-source candidates: write only if present and HTTP-verified.
    raw_candidates = raw_exact_candidates(cur, fetched_at)
    verified_raw: list[dict[str, Any]] = []
    for c in raw_candidates:
        ok, status, ctype = verify_url(c['candidate_image_url'])
        c['http_status'] = status; c['content_type'] = ctype; c['verified_http'] = ok
        if ok:
            verified_raw.append(c)
            cur.execute('''
                INSERT OR REPLACE INTO card_image_candidates(language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,source_language_code,source_set_id,source_card_id,source_url,verification_method,verified_at,http_status,confidence,notes)
                VALUES (?,?,?,?,?,'exact_raw_tcgdex_verified',?,?,?,?, 'http_head_and_raw_json_match', ?, ?, 1.0, ?)
            ''', (c['language_code'], c['card_id'], c['set_id'], c['local_id'], c['candidate_image_url'], c['language_code'], c['set_id'], c['card_id'], c['raw_json_path'], fetched_at, status, 'Exact same language/set/local_id image recovered from raw TCGdex set JSON and verified by HTTP HEAD.'))
            cur.execute('UPDATE cards SET image_url=? WHERE language_code=? AND card_id=? AND (image_url IS NULL OR TRIM(image_url)=\'\')', (c['candidate_image_url'], c['language_code'], c['card_id']))
            cur.execute('''INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at) VALUES (?,?,?,?,?,?,?)''', (c['language_code'], c['set_id'], c['card_id'], c['raw_json_path'], 'v2_image_url_raw_tcgdex_backfill', f"Backfilled exact image_url {c['candidate_image_url']} from raw TCGdex set JSON after HTTP verification.", fetched_at))
            doc_id = hid('src', c['raw_json_path'], c['language_code'], c['set_id'])
            cur.execute("INSERT OR IGNORE INTO source_documents(source_document_id,source_url,source_type,language_code,fetched_at,retrieved_by,reliability_notes) VALUES (?,?,'raw_tcgdex_set_json',?,?, 'Hermes Agent', 'Local raw TCGdex set JSON used for exact image_url recovery.')", (doc_id, c['raw_json_path'], c['language_code'], fetched_at))
            prov_id = hid('prov','cards',c['language_code'],c['card_id'],'v2_image_url_raw_tcgdex_backfill',c['candidate_image_url'])
            cur.execute('''INSERT OR REPLACE INTO provenance_records(provenance_id,entity_table,entity_key,language_code,source_document_id,source_url,method,fetched_at,confidence,source_notes,extraction_notes,created_at) VALUES (?, 'cards', ?, ?, ?, ?, 'v2_image_url_raw_tcgdex_backfill', ?, 1.0, ?, ?, ?)''', (prov_id, f"{c['language_code']}:{c['card_id']}", c['language_code'], doc_id, c['raw_json_path'], fetched_at, 'Exact image URL recovered from local raw TCGdex set JSON.', f"image_url={c['candidate_image_url']}; http_status={status}", fetched_at))
    display_counts = populate_display_candidates(cur, fetched_at)
    cur.execute('''
INSERT OR REPLACE INTO card_image_candidates(
  language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,
  source_language_code,source_set_id,source_card_id,source_url,verification_method,
  verified_at,http_status,confidence,notes
)
SELECT language_code,card_id,set_id,local_id,candidate_image_url,candidate_type,
       source_language_code,source_set_id,source_card_id,source_url,verification_method,
       verified_at,http_status,confidence,notes
FROM tmp_recovered_image_candidates
''')
    display_counts['recovered_exact_source_candidates_preserved'] = cur.rowcount
    create_reporting_views(cur)
    conn.commit()

    after_missing = scalar(cur, "SELECT COUNT(*) FROM cards WHERE image_url IS NULL OR TRIM(image_url)=''")
    missing_by_lang = rows(cur, "SELECT language_code, COUNT(*) AS missing_exact_image_rows FROM cards WHERE image_url IS NULL OR TRIM(image_url)='' GROUP BY language_code ORDER BY missing_exact_image_rows DESC")
    source_availability = rows(cur, '''
        SELECT language_code,
               COUNT(*) AS missing_exact_image_rows,
               SUM(CASE WHEN display_image_url IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_display_candidate,
               SUM(CASE WHEN display_image_url IS NULL THEN 1 ELSE 0 END) AS rows_without_display_candidate
        FROM v2_card_search
        WHERE has_exact_image=0
        GROUP BY language_code
        ORDER BY missing_exact_image_rows DESC
    ''')
    missing_by_set = rows(cur, 'SELECT * FROM v2_missing_image_audit ORDER BY rows_without_display_fallback DESC, missing_exact_image_rows DESC')
    missing_audit_json = REPORTS / f'v2_missing_image_audit_{fetched_at[:10]}.json'
    missing_audit_json.write_text(json.dumps({
        'fetched_at': fetched_at,
        'summary': {
            'missing_exact_image_rows': after_missing,
            'rows_with_display_candidate': sum(int(r['rows_with_display_candidate'] or 0) for r in source_availability),
            'rows_without_display_candidate': sum(int(r['rows_without_display_candidate'] or 0) for r in source_availability),
            'set_groups_with_missing_exact_images': len(missing_by_set),
        },
        'by_language': source_availability,
        'by_set': missing_by_set,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(REPORTS / 'v2_missing_image_audit_by_set.csv', missing_by_set)
    write_csv(REPORTS / 'v2_missing_image_audit_by_language.csv', source_availability)
    write_csv(REPORTS / 'v2_verified_raw_image_backfill_candidates.csv', verified_raw)

    # Sample detail export: pick useful known cards/sets plus rows with fallback image if available.
    sample = rows(cur, """
        SELECT * FROM v2_card_detail
        WHERE lower(card_name) IN ('pikachu','charizard','mewtwo')
           OR card_id IN ('base1-4','base1-58','sv3pt5-6','SVAM-001')
        ORDER BY CASE WHEN has_display_image=1 THEN 0 ELSE 1 END, language_code, card_id
        LIMIT 30
    """)
    if len(sample) < 10:
        sample += rows(cur, 'SELECT * FROM v2_card_detail ORDER BY has_display_image DESC, language_code, card_id LIMIT 20')
    sample_path = REPORTS / f'v2_sample_card_detail_export_{fetched_at[:10]}.json'
    sample_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding='utf-8')

    audit = two_wave_audit(cur)
    report = {
        'fetched_at': fetched_at,
        'database': str(DB),
        'backup': str(backup),
        'actions': {
            'views_created': ['v2_card_search','v2_card_detail','v2_set_report','v2_missing_image_audit'],
            'image_candidate_table': 'card_image_candidates',
            'best_image_view': 'v2_card_image_best',
            'missing_exact_images_before': before_missing,
            'raw_exact_candidates_found': len(raw_candidates),
            'raw_exact_candidates_http_verified': len(verified_raw),
            'exact_image_urls_backfilled': before_missing - after_missing,
            'missing_exact_images_after': after_missing,
            **display_counts,
        },
        'image_source_availability_by_language': source_availability,
        'image_source_availability_by_set': missing_by_set,
        'two_wave_audit_after_image_changes': audit,
        'caveat': 'cards.image_url is updated only for exact same-language raw-source verified URLs. Cross-language/core matches are display fallbacks in v2_card_search, not persisted exact card image URLs.',
        'artifacts': {
            'json_report': str(REPORTS / f'v2_search_image_audit_{fetched_at[:10]}.json'),
            'missing_image_audit_json': str(missing_audit_json),
            'missing_image_by_set_csv': str(REPORTS / 'v2_missing_image_audit_by_set.csv'),
            'missing_image_by_language_csv': str(REPORTS / 'v2_missing_image_audit_by_language.csv'),
            'verified_raw_backfill_csv': str(REPORTS / 'v2_verified_raw_image_backfill_candidates.csv'),
            'sample_card_detail_export_json': str(sample_path),
        }
    }
    out = REPORTS / f'v2_search_image_audit_{fetched_at[:10]}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(out), 'backup': str(backup), 'views_created': report['actions']['views_created'], 'missing_before': before_missing, 'missing_after': after_missing, 'exact_backfilled': before_missing-after_missing, 'display_candidates': display_counts, 'missing_display_after': audit['wave1_sql']['missing_display_image_rows'], 'two_wave_pass': audit['pass'], 'sample_export': str(sample_path)}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
