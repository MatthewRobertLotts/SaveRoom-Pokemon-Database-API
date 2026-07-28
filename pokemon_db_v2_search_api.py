#!/usr/bin/env python3
"""FTS-backed v2 Pokémon card search API/export helper.

This script builds an SQLite FTS5 index from v2_card_search and exposes a small
CLI/API layer for product search, card detail export, and SaveRoom sample JSONs.

The script is deliberately read-mostly: it creates/rebuilds only search support
objects and JSON reports. It does not mutate raw card facts such as cards.name or
cards.image_url.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from pokemon_db_v3_config import DEFAULT_DB, DEFAULT_REPORTS_DIR

DB = DEFAULT_DB
REPORTS = DEFAULT_REPORTS_DIR
FTS_TABLE = 'v2_card_search_fts'
CACHE_TABLE = 'v2_card_detail_api_cache'

SEARCH_COLUMNS = [
    'language_code', 'language_name', 'card_id', 'raw_set_id', 'resolved_set_id',
    'core_set_id', 'core_set_name', 'local_id', 'card_name', 'resolved_set_name',
    'resolved_series_name', 'category', 'hp', 'types', 'rarity', 'stage',
    'illustrator', 'regulation_mark', 'exact_image_url', 'display_image_url',
    'local_display_image_url', 'local_display_image_cache_profile',
    'local_display_image_bytes', 'display_image_source_type', 'display_image_source_language_code',
    'has_exact_image', 'has_display_image'
]

DETAIL_COLUMNS = [
    'language_code', 'language_name', 'card_id', 'raw_set_id', 'resolved_set_id',
    'core_set_id', 'core_set_name', 'local_id', 'local_id_sort', 'card_name',
    'resolved_set_name', 'resolved_series_name', 'resolved_release_date',
    'category', 'hp', 'types', 'rarity', 'stage', 'illustrator',
    'regulation_mark', 'variants', 'legal', 'exact_image_url', 'display_image_url',
    'local_display_image_url', 'local_display_image_cache_profile',
    'local_display_image_bytes', 'display_image_source_type', 'display_image_source_language_code',
    'has_exact_image', 'has_display_image', 'attacks', 'weaknesses', 'resistances',
    'retreat', 'description', 'provenance_record_count', 'legacy_provenance_count'
]

EXAMPLE_QUERIES = [
    {
        'name': 'search_charizard',
        'description': 'Common English/product search for Charizard.',
        'query': 'charizard',
        'limit': 25,
    },
    {
        'name': 'search_pikachu_japanese',
        'description': 'Language-aware query using the English language name Japanese.',
        'query': 'pikachu japanese',
        'limit': 25,
    },
    {
        'name': 'search_by_core_set_svp',
        'description': 'Set/core-set search example for Scarlet & Violet Promos.',
        'query': '',
        'core_set_id': 'svp',
        'limit': 25,
    },
]


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp_date() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')


def connect(db: Path = DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def rows(cur: sqlite3.Cursor, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, tuple(params)).fetchall()]


def scalar(cur: sqlite3.Cursor, sql: str, params: Iterable[Any] = ()) -> Any:
    return cur.execute(sql, tuple(params)).fetchone()[0]


def json_ready(value: Any) -> Any:
    """Best-effort decode for JSON-ish text fields without changing plain text."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text[0] in '[{' and text[-1:] in ']}':
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def normalize_row(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """Return a stable product/API shape from v2 views."""
    out = {
        'language_code': row.get('language_code'),
        'language_name': row.get('language_name'),
        'card_id': row.get('card_id'),
        'name': row.get('card_name'),
        'collector_number': row.get('local_id'),
        'set': {
            'raw_set_id': row.get('raw_set_id'),
            'resolved_set_id': row.get('resolved_set_id'),
            'resolved_set_name': row.get('resolved_set_name'),
            'core_set_id': row.get('core_set_id'),
            'core_set_name': row.get('core_set_name'),
            'series': row.get('resolved_series_name'),
            'release_date': row.get('resolved_release_date'),
        },
        'card': {
            'category': row.get('category'),
            'hp': row.get('hp'),
            'types': json_ready(row.get('types')),
            'rarity': row.get('rarity'),
            'stage': row.get('stage'),
            'illustrator': row.get('illustrator'),
            'regulation_mark': row.get('regulation_mark'),
            'variants': json_ready(row.get('variants')),
            'legal': json_ready(row.get('legal')),
        },
        'images': {
            'exact_image_url': row.get('exact_image_url'),
            'display_image_url': row.get('display_image_url'),
            'local_display_image_url': row.get('local_display_image_url'),
            'local_display_image_cache_profile': row.get('local_display_image_cache_profile'),
            'local_display_image_bytes': row.get('local_display_image_bytes'),
            'display_image_source_type': row.get('display_image_source_type'),
            'display_image_source_language_code': row.get('display_image_source_language_code'),
            'has_exact_image': bool(row.get('has_exact_image')),
            'has_display_image': bool(row.get('has_display_image')),
        },
    }
    if 'rank' in row:
        out['search'] = {'rank': row.get('rank')}
    if detail:
        out['rules_text'] = {
            'attacks': json_ready(row.get('attacks')),
            'weaknesses': json_ready(row.get('weaknesses')),
            'resistances': json_ready(row.get('resistances')),
            'retreat': row.get('retreat'),
            'description': row.get('description'),
        }
        out['provenance'] = {
            'v2_count': row.get('provenance_record_count'),
            'legacy_count': row.get('legacy_provenance_count'),
        }
    return out


def ensure_base_views(cur: sqlite3.Cursor) -> None:
    missing = [name for name in ('v2_card_search', 'v2_card_detail')
               if scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (name,)) == 0]
    if missing:
        raise RuntimeError(f"Missing required v2 view(s): {', '.join(missing)}. Run pokemon_db_v2_search_and_image_audit.py first.")


def create_fts(cur: sqlite3.Cursor) -> None:
    ensure_base_views(cur)
    cur.executescript(f'''
DROP VIEW IF EXISTS v2_card_search_fts_api;
DROP TABLE IF EXISTS {CACHE_TABLE};
DROP TABLE IF EXISTS {FTS_TABLE};
''')
    if scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='card_image_local_cache'"):
        cur.executescript(f'''
CREATE TABLE {CACHE_TABLE} AS
SELECT d.*,
       lc.local_image_url AS local_display_image_url,
       lc.cache_profile AS local_display_image_cache_profile,
       lc.bytes_cached AS local_display_image_bytes
FROM v2_card_detail d
LEFT JOIN card_image_local_cache lc
  ON lc.language_code=d.language_code
 AND lc.card_id=d.card_id
 AND lc.cache_profile=(
   SELECT cache_profile
   FROM card_image_local_cache lc2
   WHERE lc2.language_code=d.language_code AND lc2.card_id=d.card_id
   ORDER BY max_width DESC, quality DESC, cache_profile
   LIMIT 1
 );
''')
    else:
        cur.executescript(f'''
CREATE TABLE {CACHE_TABLE} AS
SELECT d.*,
       NULL AS local_display_image_url,
       NULL AS local_display_image_cache_profile,
       NULL AS local_display_image_bytes
FROM v2_card_detail d;
''')
    cur.executescript(f'''
CREATE INDEX idx_v2_card_detail_api_cache_pk ON {CACHE_TABLE}(language_code, card_id);
CREATE INDEX idx_v2_card_detail_api_cache_core_set ON {CACHE_TABLE}(core_set_id);
CREATE INDEX idx_v2_card_detail_api_cache_resolved_set ON {CACHE_TABLE}(resolved_set_id);
CREATE INDEX idx_v2_card_detail_api_cache_raw_set ON {CACHE_TABLE}(raw_set_id);
CREATE INDEX idx_v2_card_detail_api_cache_display ON {CACHE_TABLE}(has_display_image);
CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5(
  doc_key UNINDEXED,
  language_code UNINDEXED,
  card_id UNINDEXED,
  raw_set_id,
  resolved_set_id,
  core_set_id,
  local_id,
  card_name,
  name_english,
  language_name,
  resolved_set_name,
  core_set_name,
  resolved_series_name,
  category,
  types,
  rarity,
  stage,
  illustrator,
  regulation_mark,
  search_blob,
  tokenize = 'unicode61 remove_diacritics 2'
);
''')
    cur.execute(f'''
INSERT INTO {FTS_TABLE}(
  doc_key, language_code, card_id, raw_set_id, resolved_set_id, core_set_id,
  local_id, card_name, name_english, language_name, resolved_set_name, core_set_name,
  resolved_series_name, category, types, rarity, stage, illustrator,
  regulation_mark, search_blob
)
SELECT
  language_code || ':' || card_id,
  language_code,
  card_id,
  COALESCE(raw_set_id,''),
  COALESCE(resolved_set_id,''),
  COALESCE(core_set_id,''),
  COALESCE(local_id,''),
  COALESCE(card_name,''),
  COALESCE((SELECT en_name FROM card_name_translations t WHERE t.card_id=s.card_id AND t.language_code=s.language_code AND t.source!='untranslated' LIMIT 1), ''),
  COALESCE(language_name,''),
  COALESCE(resolved_set_name,''),
  COALESCE(core_set_name,''),
  COALESCE(resolved_series_name,''),
  COALESCE(category,''),
  COALESCE(types,''),
  COALESCE(rarity,''),
  COALESCE(stage,''),
  COALESCE(illustrator,''),
  COALESCE(regulation_mark,''),
  lower(
    COALESCE(card_name,'') || ' ' ||
    COALESCE((SELECT en_name FROM card_name_translations t WHERE t.card_id=s.card_id AND t.language_code=s.language_code AND t.source!='untranslated' LIMIT 1), '') || ' ' ||
    COALESCE(language_name,'') || ' ' ||
    COALESCE(language_code,'') || ' ' || COALESCE(card_id,'') || ' ' ||
    COALESCE(raw_set_id,'') || ' ' || COALESCE(resolved_set_id,'') || ' ' ||
    COALESCE(core_set_id,'') || ' ' || COALESCE(local_id,'') || ' ' ||
    COALESCE(resolved_set_name,'') || ' ' || COALESCE(core_set_name,'') || ' ' ||
    COALESCE(resolved_series_name,'') || ' ' || COALESCE(category,'') || ' ' ||
    COALESCE(types,'') || ' ' || COALESCE(rarity,'') || ' ' ||
    COALESCE(stage,'') || ' ' || COALESCE(illustrator,'') || ' ' ||
    COALESCE(regulation_mark,'')
  )
FROM v2_card_search s;
''')
    cur.executescript(f'''
CREATE VIEW v2_card_search_fts_api AS
SELECT
  f.rowid AS fts_rowid,
  f.doc_key,
  f.language_code,
  f.card_id,
  f.card_name,
  f.name_english,
  f.local_id,
  f.raw_set_id,
  f.resolved_set_id,
  f.core_set_id,
  f.resolved_set_name,
  f.core_set_name,
  f.language_name
FROM {FTS_TABLE} f;
''')


def escape_fts_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def build_match_query(query: str) -> str:
    """Build FTS5 match query that searches both local name and English name.

    For each token, searches across card_name AND name_english columns.
    This allows cross-language search: typing "Charizard" finds Japanese
    リザードン cards because their name_english is "Charizard".
    """
    tokens = re.findall(r"[\w\-]+|[^\s]", query.strip(), flags=re.UNICODE)
    tokens = [t for t in tokens if t.strip()]
    if not tokens:
        return ''
    # Each token must match in at least one column (card_name OR name_english)
    # Use FTS5 column filter syntax: {card_name name_english} : token
    return ' AND '.join(
        '{card_name name_english} : ' + escape_fts_token(t) for t in tokens
    )


def build_match_query(query: str) -> str:
    """Build FTS5 match query that searches both local name and English name.

    For each token, searches across card_name AND name_english columns.
    This allows cross-language search: typing "Charizard" finds Japanese
    リザードン cards because their name_english is "Charizard".

    Also handles multi-token queries with AND logic.
    """
    # Extract alphanumeric tokens (including Unicode letters and hyphens)
    tokens = re.findall(r"[\w\-]+", query.strip(), flags=re.UNICODE)
    tokens = [t for t in tokens if t.strip()]
    if not tokens:
        return ''
    # Each token must match in at least one column (card_name OR name_english)
    # Use FTS5 column filter syntax: {card_name name_english} : token
    return ' AND '.join(
        '{card_name name_english} : ' + escape_fts_token(t) for t in tokens
    )


def build_match_query_with_synonyms(query: str, conn: sqlite3.Connection) -> str:
    """Build FTS5 match query with synonym expansion.

    Searches across card_name, name_english, set names, and other text fields.
    For each token, looks up synonyms and creates OR alternatives.
    """
    if not query.strip():
        return ''

    tokens = re.findall(r"[\w\-]+", query.strip(), flags=re.UNICODE)
    tokens = [t for t in tokens if t.strip()]
    if not tokens:
        return ''

    cur = conn.cursor()
    parts = []

    for token in tokens:
        token_lower = token.lower()
        # Look up synonyms
        cur.execute(
            'SELECT canonical, entity_type FROM search_synonyms WHERE synonym=?',
            (token_lower,)
        )
        results = cur.fetchall()

        if results:
            # Group synonyms by entity type to target the right columns
            by_type: dict[str, list[str]] = {}
            for canon, etype in results:
                by_type.setdefault(etype, []).append(canon)

            type_parts = []
            for etype, canonicals in by_type.items():
                all_forms = [token] + canonicals
                seen = set()
                unique_forms = []
                for form in all_forms:
                    fl = form.lower()
                    if fl not in seen:
                        seen.add(fl)
                        unique_forms.append(form)
                or_group = '(' + ' OR '.join(escape_fts_token(f) for f in unique_forms) + ')'

                if etype == 'set':
                    # Set names are in resolved_set_name, core_set_name, resolved_series_name
                    cols = '{resolved_set_name core_set_name resolved_series_name raw_set_id resolved_set_id core_set_id search_blob}'
                elif etype == 'pokemon':
                    cols = '{card_name name_english local_id search_blob}'
                else:
                    # ebay_term and others: search all text columns
                    cols = '{card_name name_english resolved_set_name core_set_name local_id raw_set_id resolved_set_id core_set_id search_blob}'
                type_parts.append(f'{cols} : {or_group}')

            if len(type_parts) == 1:
                parts.append(type_parts[0])
            else:
                parts.append('(' + ' OR '.join(type_parts) + ')')
        else:
            # No synonyms: search all text columns
            cols = '{card_name name_english resolved_set_name core_set_name local_id raw_set_id resolved_set_id core_set_id search_blob}'
            parts.append(f'{cols} : {escape_fts_token(token)}')

    return ' AND '.join(parts)


def expand_synonyms(query: str, conn: sqlite3.Connection) -> str:
    """Deprecated: use build_match_query_with_synonyms instead.

    Kept for backward compatibility. Returns a simple OR-expanded string.
    """
    return build_match_query_with_synonyms(query, conn)


def fuzzy_search_names(query: str, conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    """Fuzzy search using trigram similarity.

    For a given query, find cards whose names have high trigram overlap.
    This catches misspellings like "charzard" → "Charizard".

    Returns list of {card_id, language_code, name, name_english, score}.
    """
    if not query.strip() or len(query.strip()) < 3:
        return []

    cur = conn.cursor()
    query_lower = query.lower()

    # Generate trigrams for the query
    query_trigrams = []
    for i in range(len(query_lower) - 2):
        tri = query_lower[i:i+3]
        if tri.isalnum():
            query_trigrams.append(tri)

    if not query_trigrams:
        return []

    # Find cards with matching trigrams
    placeholders = ','.join('?' * len(query_trigrams))
    cur.execute(f'''
        SELECT
            t.card_id,
            t.language_code,
            COUNT(DISTINCT t.trigram) as match_count,
            s.card_name,
            COALESCE(te.en_name, '') as name_english
        FROM search_trigrams t
        JOIN v2_card_search s ON s.card_id=t.card_id AND s.language_code=t.language_code
        LEFT JOIN card_name_translations te
            ON te.card_id=t.card_id AND te.language_code=t.language_code
            AND te.source != 'untranslated'
        WHERE t.trigram IN ({placeholders})
        GROUP BY t.card_id, t.language_code
        HAVING match_count >= 2
        ORDER BY match_count DESC
        LIMIT ?
    ''', query_trigrams + [limit])

    results = []
    for row in cur.fetchall():
        card_id, lang, match_count, name, en_name = row
        # Calculate similarity score (Jaccard-like)
        name_trigrams = max(len(name.lower()) - 2, 1) if name else 1
        en_trigrams = max(len(en_name.lower()) - 2, 1) if en_name else 1
        max_trigrams = max(name_trigrams, en_trigrams)
        score = match_count / max_trigrams if max_trigrams > 0 else 0
        results.append({
            'card_id': card_id,
            'language_code': lang,
            'name': name,
            'name_english': en_name,
            'score': round(score, 3),
        })

    return results


def autocomplete_suggestions(query: str, conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, str]]:
    """Provide autocomplete suggestions based on partial input.

    Searches across:
    1. Pokémon names (local and English) via FTS prefix matching
    2. Synonyms/nicknames
    3. Set names

    Returns list of {type, name, card_key}.
    """
    if not query.strip() or len(query.strip()) < 2:
        return []

    cur = conn.cursor()
    query_lower = query.strip().lower()
    suggestions = []

    # 1. FTS prefix search on card_name and name_english
    try:
        cur.execute(f'''
            SELECT DISTINCT
                f.card_name,
                f.name_english,
                f.language_code,
                f.card_id
            FROM {FTS_TABLE} f
            WHERE f.card_name MATCH ? OR f.name_english MATCH ?
            ORDER BY bm25({FTS_TABLE})
            LIMIT ?
        ''', (f'{query_lower}*', f'{query_lower}*', limit))
        for row in cur.fetchall():
            name, en_name, lang, card_id = row
            display = en_name or name
            if display:
                suggestions.append({
                    'type': 'card',
                    'name': display,
                    'card_key': f'{lang}:{card_id}',
                    'language': lang,
                })
    except Exception:
        pass

    # 2. Synonym lookup
    cur.execute('''
        SELECT synonym, canonical, entity_type
        FROM search_synonyms
        WHERE synonym LIKE ?
        LIMIT ?
    ''', (f'{query_lower}%', 5))
    for row in cur.fetchall():
        syn, canon, etype = row
        suggestions.append({
            'type': etype,
            'name': f'{syn} → {canon}',
            'synonym': syn,
            'canonical': canon,
        })

    # Deduplicate by name
    seen = set()
    unique = []
    for s in suggestions:
        key = s.get('name', '')
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique[:limit]


def search_cards(
    conn: sqlite3.Connection,
    query: str = '',
    *,
    language_code: str | None = None,
    set_id: str | None = None,
    core_set_id: str | None = None,
    has_display_image: bool | None = None,
    limit: int = 25,
) -> tuple[list[dict[str, Any]], float]:
    cur = conn.cursor()
    ensure_base_views(cur)
    if scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (FTS_TABLE,)) == 0:
        raise RuntimeError('FTS index is missing. Run: setup-fts')
    if scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (CACHE_TABLE,)) == 0:
        raise RuntimeError('API cache is missing. Run: setup-fts')

    where = []
    params: list[Any] = []
    # ponytail: legacy /search powers the browser UI; keep it aligned with v1 search.
    match = build_match_query_with_synonyms(query, conn)
    rank_expr = '0.0 AS rank'
    with_sql = ''
    join = ''
    source_table = CACHE_TABLE
    if match:
        candidate_limit = max(limit * 100, 5000)
        with_sql = f'''WITH hits AS (
  SELECT language_code, card_id, bm25({FTS_TABLE}) AS rank
  FROM {FTS_TABLE}
  WHERE {FTS_TABLE} MATCH ?
  ORDER BY rank
  LIMIT ?
)'''
        params.extend([match, candidate_limit])
        join = 'JOIN hits h ON h.language_code=s.language_code AND h.card_id=s.card_id'
        rank_expr = 'h.rank AS rank'
    if language_code:
        where.append('s.language_code = ?')
        params.append(language_code)
    if set_id:
        where.append('(s.resolved_set_id = ? OR s.raw_set_id = ?)')
        params.extend([set_id, set_id])
    if core_set_id:
        where.append('s.core_set_id = ?')
        params.append(core_set_id)
    if has_display_image is not None:
        where.append('s.has_display_image = ?')
        params.append(1 if has_display_image else 0)
    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    sql = f'''
{with_sql}
SELECT {', '.join('s.' + c for c in SEARCH_COLUMNS)}, {rank_expr}
FROM {source_table} s
{join}
{where_sql}
ORDER BY
  CASE WHEN s.has_display_image=1 THEN 0 ELSE 1 END,
  rank ASC,
  CASE WHEN s.language_code='en' THEN 0 WHEN s.language_code='ja' THEN 1 ELSE 2 END,
  s.language_code,
  s.resolved_set_id,
  s.local_id_sort,
  s.card_id
LIMIT ?
'''
    params.append(limit)
    start = time.perf_counter()
    out = [normalize_row(dict(r)) for r in cur.execute(sql, params).fetchall()]
    return out, (time.perf_counter() - start) * 1000


def get_card_detail(conn: sqlite3.Connection, language_code: str, card_id: str) -> tuple[dict[str, Any] | None, float]:
    cur = conn.cursor()
    sql = f"SELECT {', '.join(DETAIL_COLUMNS)} FROM {CACHE_TABLE} WHERE language_code=? AND card_id=? LIMIT 1"
    start = time.perf_counter()
    row = cur.execute(sql, (language_code, card_id)).fetchone()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return (normalize_row(dict(row), detail=True) if row else None), elapsed_ms


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def reports_dir_for_db(db: Path, reports_dir: Path | None = None) -> Path:
    return reports_dir or (db.parent / 'reports')


def setup_fts(db: Path = DB, *, reports_dir: Path | None = None) -> dict[str, Any]:
    reports_dir_for_db(db, reports_dir).mkdir(parents=True, exist_ok=True)
    conn = connect(db)
    cur = conn.cursor()
    start = time.perf_counter()
    create_fts(cur)
    conn.commit()
    elapsed_ms = (time.perf_counter() - start) * 1000
    count = scalar(cur, f'SELECT COUNT(*) FROM {FTS_TABLE}')
    cache_count = scalar(cur, f'SELECT COUNT(*) FROM {CACHE_TABLE}')
    v2_count = scalar(cur, 'SELECT COUNT(*) FROM v2_card_search')
    return {
        'database': str(db),
        'fts_table': FTS_TABLE,
        'api_cache_table': CACHE_TABLE,
        'fts_rows': count,
        'api_cache_rows': cache_count,
        'v2_card_search_rows': v2_count,
        'row_count_matches': count == v2_count == cache_count,
        'elapsed_ms': round(elapsed_ms, 3),
    }


def run_examples(db: Path = DB, *, reports_dir: Path | None = None) -> dict[str, Any]:
    reports_dir = reports_dir_for_db(db, reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(db)
    setup = setup_fts(db, reports_dir=reports_dir)
    sample_paths: dict[str, str] = {}
    examples: list[dict[str, Any]] = []
    total_start = time.perf_counter()

    for spec in EXAMPLE_QUERIES:
        results, elapsed_ms = search_cards(
            conn,
            spec.get('query', ''),
            core_set_id=spec.get('core_set_id'),
            set_id=spec.get('set_id'),
            language_code=spec.get('language_code'),
            limit=spec.get('limit', 25),
        )
        payload = {
            'generated_at': now_utc(),
            'description': spec['description'],
            'query': spec.get('query', ''),
            'filters': {k: spec[k] for k in ('language_code', 'set_id', 'core_set_id') if k in spec},
            'elapsed_ms': round(elapsed_ms, 3),
            'count': len(results),
            'results': results,
        }
        path = reports_dir / f"v2_fts_{spec['name']}_{stamp_date()}.json"
        write_json(path, payload)
        sample_paths[spec['name']] = str(path)
        examples.append({k: payload[k] for k in ('description', 'query', 'filters', 'elapsed_ms', 'count')})

    # Detail sample: prefer an iconic English Charizard if present; otherwise first Charizard result.
    charizard_results, _ = search_cards(conn, 'charizard', language_code='en', limit=1)
    if charizard_results:
        detail_lang = charizard_results[0]['language_code']
        detail_card_id = charizard_results[0]['card_id']
    else:
        detail_lang, detail_card_id = 'en', 'base1-4'
    detail, detail_ms = get_card_detail(conn, detail_lang, detail_card_id)
    detail_payload = {
        'generated_at': now_utc(),
        'language_code': detail_lang,
        'card_id': detail_card_id,
        'elapsed_ms': round(detail_ms, 3),
        'detail': detail,
    }
    detail_path = reports_dir / f'v2_fts_card_detail_{detail_lang}_{detail_card_id}_{stamp_date()}.json'
    write_json(detail_path, detail_payload)
    sample_paths['card_detail'] = str(detail_path)

    cur = conn.cursor()
    verification = {
        'generated_at': now_utc(),
        'database': str(db),
        'setup': setup,
        'examples': examples,
        'detail_export': {
            'language_code': detail_lang,
            'card_id': detail_card_id,
            'found': detail is not None,
            'elapsed_ms': round(detail_ms, 3),
        },
        'counts': {
            'v2_card_search': scalar(cur, 'SELECT COUNT(*) FROM v2_card_search'),
            'v2_card_detail': scalar(cur, 'SELECT COUNT(*) FROM v2_card_detail'),
            'api_cache_rows': scalar(cur, f'SELECT COUNT(*) FROM {CACHE_TABLE}'),
            'fts_rows': scalar(cur, f'SELECT COUNT(*) FROM {FTS_TABLE}'),
            'fts_api_view_exists': scalar(cur, "SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='v2_card_search_fts_api'"),
        },
        'sample_paths': sample_paths,
        'total_elapsed_ms': round((time.perf_counter() - total_start) * 1000, 3),
        'cli_examples': [
            "python3 pokemon_db_v2_search_api.py setup-fts",
            "python3 pokemon_db_v2_search_api.py search 'charizard' --limit 10",
            "python3 pokemon_db_v2_search_api.py search 'pikachu japanese' --limit 10",
            "python3 pokemon_db_v2_search_api.py search --core-set-id svp --limit 10",
            f"python3 pokemon_db_v2_search_api.py detail {detail_lang} {detail_card_id}",
            "python3 pokemon_db_v2_search_api.py examples",
        ],
    }
    verification['pass'] = (
        verification['counts']['v2_card_search'] == verification['counts']['fts_rows'] == verification['counts']['api_cache_rows']
        and verification['counts']['v2_card_detail'] == verification['counts']['v2_card_search']
        and all(e['count'] > 0 for e in examples)
        and verification['detail_export']['found']
    )
    report_path = reports_dir / f'v2_fts_search_api_verification_{stamp_date()}.json'
    write_json(report_path, verification)
    verification['verification_report'] = str(report_path)
    # Write again with self-reference included.
    write_json(report_path, verification)
    return verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='FTS-backed API/export layer over v2_card_search and v2_card_detail.')
    parser.add_argument('--db', default=str(DB), help='SQLite database path.')
    parser.add_argument('--reports-dir', default=None, help='Report output directory. Defaults to <db directory>/reports.')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('setup-fts', help='Create/rebuild the SQLite FTS5 search table from v2_card_search.')

    search = sub.add_parser('search', help='Search cards through the FTS-backed v2 layer.')
    search.add_argument('query', nargs='?', default='', help='Search text, e.g. charizard or "pikachu japanese".')
    search.add_argument('--language-code')
    search.add_argument('--set-id', help='Filter by raw or resolved set id.')
    search.add_argument('--core-set-id', help='Filter by normalized core set id.')
    search.add_argument('--has-display-image', action='store_true', help='Only return rows with a display image.')
    search.add_argument('--limit', type=int, default=25)
    search.add_argument('--out', help='Optional JSON output path.')

    detail = sub.add_parser('detail', help='Export one card detail from v2_card_detail.')
    detail.add_argument('language_code')
    detail.add_argument('card_id')
    detail.add_argument('--out', help='Optional JSON output path.')

    sub.add_parser('examples', help='Run SaveRoom example searches and write JSON samples plus verification report.')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = Path(args.db)
    reports_dir = Path(args.reports_dir) if args.reports_dir else None
    if args.command == 'setup-fts':
        result = setup_fts(db, reports_dir=reports_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    conn = connect(db)
    if args.command == 'search':
        results, elapsed_ms = search_cards(
            conn,
            args.query,
            language_code=args.language_code,
            set_id=args.set_id,
            core_set_id=args.core_set_id,
            has_display_image=True if args.has_display_image else None,
            limit=args.limit,
        )
        payload = {
            'generated_at': now_utc(),
            'query': args.query,
            'filters': {
                'language_code': args.language_code,
                'set_id': args.set_id,
                'core_set_id': args.core_set_id,
                'has_display_image': True if args.has_display_image else None,
            },
            'elapsed_ms': round(elapsed_ms, 3),
            'count': len(results),
            'results': results,
        }
        if args.out:
            write_json(Path(args.out), payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == 'detail':
        detail, elapsed_ms = get_card_detail(conn, args.language_code, args.card_id)
        payload = {
            'generated_at': now_utc(),
            'language_code': args.language_code,
            'card_id': args.card_id,
            'elapsed_ms': round(elapsed_ms, 3),
            'detail': detail,
        }
        if args.out:
            write_json(Path(args.out), payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if detail else 2

    if args.command == 'examples':
        result = run_examples(db, reports_dir=reports_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('pass') else 1

    return 2


if __name__ == '__main__':
    raise SystemExit(main())
