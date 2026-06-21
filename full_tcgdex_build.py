#!/usr/bin/env python3
"""Build the SaveRoom Pokémon TCG set knowledge base from TCGdex set endpoints.

This importer intentionally works at set/checklist level first. It fetches every
available TCGdex set for each configured language, stores source snapshots,
populates SQLite tables, and generates human-readable Markdown/CSV reports.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex')
RAW_DIR = BASE_DIR / 'raw' / 'sets'
REPORT_DIR = BASE_DIR / 'reports'
GENERATED_DIR = BASE_DIR / 'generated_set_notes'
DB_PATH = BASE_DIR / 'pokemon_tcg_set_knowledge_base.sqlite'
API_BASE = 'https://api.tcgdex.net/v2'
# Active TCGdex language endpoints discovered from the live API.
# Do not rely only on marketing/docs copy: Korean, Simplified Chinese, Dutch,
# Polish, Russian, Portuguese-Portugal, and pt-br may exist even when status
# pages describe them as partial/coming soon.
LANGUAGES = [
    ('en', 'English'),
    ('fr', 'French'),
    ('es', 'Spanish'),
    ('it', 'Italian'),
    ('pt', 'Portuguese / TCGdex pt'),
    ('de', 'German'),
    ('ja', 'Japanese'),
    ('zh-tw', 'Chinese Traditional'),
    ('zh-cn', 'Chinese Simplified'),
    ('ko', 'Korean'),
    ('id', 'Indonesian'),
    ('th', 'Thai'),
    ('nl', 'Dutch'),
    ('pl', 'Polish'),
    ('ru', 'Russian'),
    ('pt-pt', 'Portuguese (Portugal)'),
    ('pt-br', 'Portuguese (Brazil / pt-br endpoint)'),
]


def slugify(value: str) -> str:
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', value.strip())
    value = re.sub(r'_+', '_', value).strip('_')
    return value[:120] or 'unnamed'


def fetch_json(url: str, *, attempts: int = 4, sleep: float = 0.8) -> Any:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'SaveRoom-KB-Builder/1.0'})
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == attempts:
                raise
            time.sleep(sleep * attempt)
    raise RuntimeError(f'Unreachable fetch failure for {url}: {last}')


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        '''
        PRAGMA journal_mode=WAL;
        DROP TABLE IF EXISTS import_errors;
        DROP TABLE IF EXISTS cards;
        DROP TABLE IF EXISTS sets;
        DROP TABLE IF EXISTS languages;
        DROP TABLE IF EXISTS meta;

        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE languages (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            set_count INTEGER NOT NULL DEFAULT 0,
            card_count INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE sets (
            language_code TEXT NOT NULL,
            set_id TEXT NOT NULL,
            name TEXT NOT NULL,
            series_name TEXT,
            release_date TEXT,
            logo_url TEXT,
            symbol_url TEXT,
            abbreviation TEXT,
            tcg_online TEXT,
            official_count INTEGER,
            total_count INTEGER,
            normal_count INTEGER,
            holo_count INTEGER,
            reverse_count INTEGER,
            first_ed_count INTEGER,
            raw_json_path TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (language_code, set_id),
            FOREIGN KEY (language_code) REFERENCES languages(code)
        );

        CREATE TABLE cards (
            language_code TEXT NOT NULL,
            set_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            local_id TEXT,
            local_id_sort INTEGER,
            name TEXT NOT NULL,
            image_url TEXT,
            PRIMARY KEY (language_code, card_id),
            FOREIGN KEY (language_code, set_id) REFERENCES sets(language_code, set_id)
        );

        CREATE TABLE import_errors (
            language_code TEXT,
            set_id TEXT,
            url TEXT NOT NULL,
            error TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );

        CREATE INDEX idx_sets_lang_series ON sets(language_code, series_name, release_date, set_id);
        CREATE INDEX idx_cards_set ON cards(language_code, set_id, local_id_sort, local_id);
        CREATE INDEX idx_cards_name ON cards(name);
        '''
    )
    conn.commit()


def local_sort(local_id: Any) -> int | None:
    if local_id is None:
        return None
    m = re.search(r'\d+', str(local_id))
    return int(m.group(0)) if m else None


def card_count_value(card_count: dict[str, Any], key: str) -> int | None:
    value = card_count.get(key)
    return int(value) if isinstance(value, int) else None


def write_set_note(lang_code: str, lang_name: str, set_data: dict[str, Any]) -> Path:
    set_id = set_data.get('id', 'unknown')
    name = set_data.get('name') or set_id
    series = (set_data.get('serie') or {}).get('name') if isinstance(set_data.get('serie'), dict) else None
    card_count = set_data.get('cardCount') or {}
    cards = set_data.get('cards') or []
    rel = set_data.get('releaseDate') or 'unknown'
    note_dir = GENERATED_DIR / lang_code
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / f"{slugify(set_id)}__{slugify(name)}.md"
    lines = [
        f"# {name}",
        "",
        f"Language: {lang_name} (`{lang_code}`)",
        f"TCGdex set id: `{set_id}`",
        f"Series: {series or 'unknown'}",
        f"Release date: {rel}",
        "",
        "## Counts",
        "",
        f"- Official cards: {card_count.get('official', 'unknown')}",
        f"- Total cards: {card_count.get('total', 'unknown')}",
        f"- Normal print count: {card_count.get('normal', 'unknown')}",
        f"- Holo print count: {card_count.get('holo', 'unknown')}",
        f"- Reverse print count: {card_count.get('reverse', 'unknown')}",
        f"- First Edition print count: {card_count.get('firstEd', 'unknown')}",
        "",
        "## Ordered Checklist",
        "",
        "| # | Card | TCGdex card id | Image |",
        "|---:|---|---|---|",
    ]
    for card in sorted(cards, key=lambda c: (local_sort(c.get('localId')) is None, local_sort(c.get('localId')) or 10**9, str(c.get('localId') or ''), c.get('id') or '')):
        local = card.get('localId') or ''
        cname = (card.get('name') or '').replace('|', '\\|')
        cid = card.get('id') or ''
        image = card.get('image') or ''
        lines.append(f"| {local} | {cname} | `{cid}` | {image} |")
    lines.extend([
        "",
        "## Source",
        "",
        f"- Source: TCGdex REST API `/v2/{lang_code}/sets/{set_id}`",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ])
    note_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return note_path


def main() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    conn.execute('INSERT INTO meta(key, value) VALUES (?, ?)', ('built_at_utc', fetched_at))
    conn.execute('INSERT INTO meta(key, value) VALUES (?, ?)', ('source', 'TCGdex REST API'))

    errors: list[tuple[str, str | None, str, str]] = []
    language_totals: dict[str, dict[str, int]] = {}

    for lang_code, lang_name in LANGUAGES:
        print(f'Fetching set list: {lang_code} ({lang_name})')
        list_url = f'{API_BASE}/{lang_code}/sets'
        try:
            set_list = fetch_json(list_url)
        except Exception as exc:
            err = repr(exc)
            errors.append((lang_code, None, list_url, err))
            conn.execute('INSERT INTO import_errors VALUES (?, ?, ?, ?, ?)', (lang_code, None, list_url, err, fetched_at))
            continue

        raw_lang_dir = RAW_DIR / lang_code
        raw_lang_dir.mkdir(parents=True, exist_ok=True)
        (raw_lang_dir / '_set_list.json').write_text(json.dumps(set_list, ensure_ascii=False, indent=2), encoding='utf-8')
        conn.execute('INSERT INTO languages(code, name, set_count, card_count, fetched_at) VALUES (?, ?, 0, 0, ?)', (lang_code, lang_name, fetched_at))
        card_total = 0
        set_total = 0
        for idx, item in enumerate(set_list, 1):
            set_id = item.get('id')
            if not set_id:
                continue
            quoted_set_id = urllib.parse.quote(str(set_id), safe='')
            url = f'{API_BASE}/{lang_code}/sets/{quoted_set_id}'
            try:
                set_data = fetch_json(url)
            except Exception as exc:
                err = repr(exc)
                print(f'  ERROR {lang_code}/{set_id}: {err}')
                errors.append((lang_code, set_id, url, err))
                conn.execute('INSERT INTO import_errors VALUES (?, ?, ?, ?, ?)', (lang_code, set_id, url, err, fetched_at))
                continue

            raw_path = raw_lang_dir / f'{slugify(set_id)}.json'
            raw_path.write_text(json.dumps(set_data, ensure_ascii=False, indent=2), encoding='utf-8')
            write_set_note(lang_code, lang_name, set_data)

            card_count = set_data.get('cardCount') or {}
            series = set_data.get('serie') or {}
            conn.execute(
                '''INSERT OR REPLACE INTO sets(
                    language_code, set_id, name, series_name, release_date, logo_url, symbol_url,
                    abbreviation, tcg_online, official_count, total_count, normal_count, holo_count,
                    reverse_count, first_ed_count, raw_json_path, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    lang_code,
                    set_data.get('id') or set_id,
                    set_data.get('name') or item.get('name') or set_id,
                    series.get('name') if isinstance(series, dict) else None,
                    set_data.get('releaseDate'),
                    set_data.get('logo'),
                    set_data.get('symbol'),
                    json.dumps(set_data.get('abbreviation'), ensure_ascii=False) if isinstance(set_data.get('abbreviation'), (dict, list)) else set_data.get('abbreviation'),
                    json.dumps(set_data.get('tcgOnline'), ensure_ascii=False) if isinstance(set_data.get('tcgOnline'), (dict, list)) else set_data.get('tcgOnline'),
                    card_count_value(card_count, 'official'),
                    card_count_value(card_count, 'total'),
                    card_count_value(card_count, 'normal'),
                    card_count_value(card_count, 'holo'),
                    card_count_value(card_count, 'reverse'),
                    card_count_value(card_count, 'firstEd'),
                    str(raw_path),
                    fetched_at,
                ),
            )
            cards = set_data.get('cards') or []
            for card in cards:
                cid = card.get('id')
                if not cid:
                    continue
                conn.execute(
                    '''INSERT OR REPLACE INTO cards(language_code, set_id, card_id, local_id, local_id_sort, name, image_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (lang_code, set_data.get('id') or set_id, cid, card.get('localId'), local_sort(card.get('localId')), card.get('name') or cid, card.get('image')),
                )
            card_total += len(cards)
            set_total += 1
            if idx % 25 == 0:
                conn.commit()
                print(f'  {lang_code}: {idx}/{len(set_list)} sets fetched')
        conn.execute('UPDATE languages SET set_count=?, card_count=? WHERE code=?', (set_total, card_total, lang_code))
        language_totals[lang_code] = {'sets': set_total, 'cards': card_total}
        conn.commit()

    # Reports
    rows = conn.execute(
        '''SELECT language_code, set_id, name, series_name, release_date, official_count, total_count,
                  (SELECT COUNT(*) FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id) AS imported_cards
           FROM sets s ORDER BY language_code, release_date, series_name, set_id'''
    ).fetchall()
    with (REPORT_DIR / 'set_coverage_matrix.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['language_code', 'set_id', 'name', 'series_name', 'release_date', 'official_count', 'total_count', 'imported_cards'])
        writer.writerows(rows)

    shared = conn.execute(
        '''SELECT set_id, COUNT(*) AS languages, GROUP_CONCAT(language_code, ',') AS language_codes,
                  MAX(CASE WHEN language_code='en' THEN name END) AS english_name,
                  MIN(release_date) AS earliest_release
           FROM sets GROUP BY set_id ORDER BY earliest_release, set_id'''
    ).fetchall()
    with (REPORT_DIR / 'cross_language_set_index.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['set_id', 'language_count', 'language_codes', 'english_name', 'earliest_release'])
        writer.writerows(shared)

    summary_langs = conn.execute('SELECT code, name, set_count, card_count FROM languages ORDER BY code').fetchall()
    total_sets = conn.execute('SELECT COUNT(*) FROM sets').fetchone()[0]
    total_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    unique_set_ids = conn.execute('SELECT COUNT(DISTINCT set_id) FROM sets').fetchone()[0]
    series_count = conn.execute('SELECT COUNT(DISTINCT series_name) FROM sets WHERE series_name IS NOT NULL').fetchone()[0]
    problem_count = conn.execute('SELECT COUNT(*) FROM import_errors').fetchone()[0]
    count_mismatches = conn.execute(
        '''SELECT COUNT(*) FROM sets s
           WHERE official_count IS NOT NULL AND official_count != (SELECT COUNT(*) FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id)'''
    ).fetchone()[0]
    top_series = conn.execute(
        '''SELECT COALESCE(series_name, 'unknown') AS series_name, COUNT(*) AS set_rows
           FROM sets GROUP BY COALESCE(series_name, 'unknown') ORDER BY set_rows DESC, series_name LIMIT 20'''
    ).fetchall()

    md = [
        '# Pokemon TCG Set Knowledge Base — Full TCGdex Build',
        '',
        f'Built at: {fetched_at}',
        '',
        '## Scope',
        '',
        'This build imports every set exposed by the TCGdex `/sets` and `/sets/{id}` endpoints for the configured active TCGdex languages. It is a set/checklist-level knowledge base: every set has a source snapshot, SQLite row, ordered card checklist, and generated Markdown set note.',
        '',
        '## Artifacts',
        '',
        f'- SQLite database: `{DB_PATH}`',
        f'- Raw source snapshots: `{RAW_DIR}`',
        f'- Generated per-set notes: `{GENERATED_DIR}`',
        f'- Set coverage matrix: `{REPORT_DIR / "set_coverage_matrix.csv"}`',
        f'- Cross-language set index: `{REPORT_DIR / "cross_language_set_index.csv"}`',
        '',
        '## Totals',
        '',
        f'- Language-specific set rows: {total_sets}',
        f'- Unique set IDs across languages: {unique_set_ids}',
        f'- Ordered card checklist rows: {total_cards}',
        f'- Distinct series names: {series_count}',
        f'- Import errors: {problem_count}',
        f'- Official-count vs checklist mismatches: {count_mismatches}',
        '',
        '## Language Coverage',
        '',
        '| Language | Code | Sets | Checklist cards |',
        '|---|---:|---:|---:|',
    ]
    for code, name, scount, ccount in summary_langs:
        md.append(f'| {name} | `{code}` | {scount} | {ccount} |')
    md.extend(['', '## Largest Series by Set Rows', '', '| Series | Set rows |', '|---|---:|'])
    for series_name, set_rows in top_series:
        md.append(f'| {series_name} | {set_rows} |')
    md.extend([
        '',
        '## Quality Notes',
        '',
        '- This build deliberately does not claim to include non-TCG products, Topps, Merlin, Panini, prize/trophy outliers, market prices, or variant-level truths unless TCGdex exposes them at set level.',
        '- The next pass should add card-detail enrichment for rarity/types/artist/illustrator, then add non-TCG and promo/outlier source families from the source registry.',
        '- TCGdex language coverage is uneven by design; missing languages do not imply a set never existed in that language.',
    ])
    if errors:
        md.extend(['', '## Import Errors', '', '| Language | Set | URL | Error |', '|---|---|---|---|'])
        for lang, sid, url, err in errors[:100]:
            md.append(f'| {lang} | {sid or ""} | {url} | `{err[:180]}` |')
    (REPORT_DIR / 'full_build_summary.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

    # Small machine-readable summary
    summary = {
        'built_at_utc': fetched_at,
        'database': str(DB_PATH),
        'raw_snapshots': str(RAW_DIR),
        'generated_set_notes': str(GENERATED_DIR),
        'language_specific_sets': total_sets,
        'unique_set_ids': unique_set_ids,
        'cards': total_cards,
        'series': series_count,
        'import_errors': problem_count,
        'official_count_mismatches': count_mismatches,
        'languages': [
            {'code': code, 'name': name, 'sets': scount, 'cards': ccount}
            for code, name, scount, ccount in summary_langs
        ],
    }
    (REPORT_DIR / 'full_build_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
