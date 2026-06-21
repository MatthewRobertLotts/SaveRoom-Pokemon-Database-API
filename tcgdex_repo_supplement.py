#!/usr/bin/env python3
"""Supplement the SaveRoom Pokémon set KB with TCGdex GitHub source set files.

The REST API can omit set IDs that exist in the upstream cards-database source.
This script fetches the GitHub tree, parses set metadata from direct set .ts files,
creates source-audit tables, and inserts missing set/language rows into the main
SQLite set table with zero checklist cards so gaps are visible.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex')
RAW_REPO_DIR = BASE_DIR / 'raw' / 'tcgdex_repo_sets'
REPORT_DIR = BASE_DIR / 'reports'
DB_PATH = BASE_DIR / 'pokemon_tcg_set_knowledge_base.sqlite'
GITHUB_TREE = 'https://api.github.com/repos/tcgdex/cards-database/git/trees/master?recursive=1'
RAW_BASE = 'https://raw.githubusercontent.com/tcgdex/cards-database/master/'


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'SaveRoom-TCGdex-Repo-Supplement/1.0'})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read().decode('utf-8')


def parse_names(ts: str) -> dict[str, str]:
    # Capture the first `name: { ... }` block. Good enough for these source files.
    m = re.search(r'\bname\s*:\s*\{(?P<body>.*?)\n\s*\}', ts, re.S)
    if not m:
        m2 = re.search(r'\bname\s*:\s*[\'\"]([^\'\"]+)[\'\"]', ts)
        return {'unknown': m2.group(1)} if m2 else {}
    body = m.group('body')
    names: dict[str, str] = {}
    for key, value in re.findall(r'[\'\"]?([a-z]{2}(?:-[a-z]{2})?)[\'\"]?\s*:\s*[\'\"]([^\'\"]*)[\'\"]', body):
        names[key] = value
    return names


def parse_int_field(ts: str, field: str) -> int | None:
    m = re.search(rf'\b{re.escape(field)}\s*:\s*(\d+)', ts)
    return int(m.group(1)) if m else None


def main() -> None:
    RAW_REPO_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec='seconds')

    tree = json.loads(fetch_text(GITHUB_TREE))
    set_paths = [
        item['path'] for item in tree['tree']
        if item.get('type') == 'blob'
        and item.get('path', '').endswith('.ts')
        and (item['path'].startswith('data/') or item['path'].startswith('data-asia/'))
        and item['path'].count('/') == 2
    ]

    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS tcgdex_repo_sets (
            set_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            product_family TEXT NOT NULL,
            series_slug TEXT NOT NULL,
            release_date TEXT,
            official_count INTEGER,
            total_count INTEGER,
            fetched_at TEXT NOT NULL,
            raw_text_path TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tcgdex_repo_set_names (
            set_id TEXT NOT NULL,
            language_code TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (set_id, language_code)
        );
    ''')

    api_ids = {row[0] for row in conn.execute('SELECT DISTINCT set_id FROM sets')}
    parsed_rows: list[dict[str, Any]] = []
    missing_ids: set[str] = set()

    for path in sorted(set_paths):
        url = RAW_BASE + urllib.parse.quote(path, safe='/')
        ts = fetch_text(url)
        set_id_match = re.search(r'\bid\s*:\s*[\'\"]([^\'\"]+)[\'\"]', ts)
        if not set_id_match:
            continue
        set_id = set_id_match.group(1)
        product_family = path.split('/')[0]
        series_slug = path.split('/')[1]
        names = parse_names(ts)
        release_match = re.search(r'\breleaseDate\s*:\s*[\'\"]([^\'\"]+)[\'\"]', ts)
        release_date = release_match.group(1) if release_match else None
        official = parse_int_field(ts, 'official')
        total = parse_int_field(ts, 'total')
        raw_path = RAW_REPO_DIR / f'{set_id}.ts'
        raw_path.write_text(ts, encoding='utf-8')

        conn.execute(
            '''INSERT OR REPLACE INTO tcgdex_repo_sets
               (set_id, source_path, product_family, series_slug, release_date, official_count, total_count, fetched_at, raw_text_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (set_id, path, product_family, series_slug, release_date, official, total, fetched_at, str(raw_path)),
        )
        for lang, name in names.items():
            conn.execute(
                'INSERT OR REPLACE INTO tcgdex_repo_set_names(set_id, language_code, name) VALUES (?, ?, ?)',
                (set_id, lang, name),
            )
            # Insert only missing REST/API set IDs into the main set table. These rows intentionally have no cards.
            if set_id not in api_ids:
                conn.execute(
                    '''INSERT OR IGNORE INTO sets(
                        language_code, set_id, name, series_name, release_date, logo_url, symbol_url,
                        abbreviation, tcg_online, official_count, total_count, normal_count, holo_count,
                        reverse_count, first_ed_count, raw_json_path, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, NULL, NULL, NULL, NULL, ?, ?)''',
                    (lang, set_id, name, series_slug, release_date, official, total, str(raw_path), fetched_at),
                )
        if set_id not in api_ids:
            missing_ids.add(set_id)
        parsed_rows.append({
            'set_id': set_id,
            'source_path': path,
            'product_family': product_family,
            'series_slug': series_slug,
            'release_date': release_date,
            'official_count': official,
            'total_count': total,
            'languages': ','.join(sorted(names)),
            'in_rest_api': set_id in api_ids,
        })

    conn.commit()
    api_after = {row[0] for row in conn.execute('SELECT DISTINCT set_id FROM sets')}
    total_set_rows = conn.execute('SELECT COUNT(*) FROM sets').fetchone()[0]
    total_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    total_langs = conn.execute('SELECT COUNT(DISTINCT language_code) FROM sets').fetchone()[0]
    repo_ids = {row['set_id'] for row in parsed_rows}

    with (REPORT_DIR / 'tcgdex_repo_set_audit.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(parsed_rows[0].keys()))
        writer.writeheader()
        writer.writerows(sorted(parsed_rows, key=lambda r: (r['in_rest_api'], r['set_id'])))

    md = [
        '# TCGdex Repository Supplement Audit',
        '',
        f'Built at: {fetched_at}',
        '',
        '## Why This Exists',
        '',
        'The REST API is not the whole TCGdex source of truth. A repository audit found set IDs in `tcgdex/cards-database` that were not returned by the REST set endpoints. These are now recorded as source-backed set rows with zero checklist cards so the gap is visible instead of silently missing.',
        '',
        '## Counts',
        '',
        f'- Parsed repository set IDs: {len(repo_ids)}',
        f'- REST/API unique set IDs before supplement: {len(api_ids)}',
        f'- Repository set IDs missing from REST/API: {len(missing_ids)}',
        f'- Unique set IDs after supplement: {len(api_after)}',
        f'- Language-specific set rows after supplement: {total_set_rows}',
        f'- Checklist card rows after supplement: {total_cards}',
        f'- Distinct language codes in set table after supplement: {total_langs}',
        '',
        '## Missing REST/API Set IDs Added From Repository',
        '',
    ]
    for sid in sorted(missing_ids):
        names = conn.execute('SELECT language_code, name FROM tcgdex_repo_set_names WHERE set_id=? ORDER BY language_code', (sid,)).fetchall()
        name_text = '; '.join(f'`{lang}` {name}' for lang, name in names) or 'no parsed name'
        md.append(f'- `{sid}` — {name_text}')
    md.extend([
        '',
        '## Artifact Paths',
        '',
        f'- SQLite database: `{DB_PATH}`',
        f'- Raw repository set files: `{RAW_REPO_DIR}`',
        f'- CSV audit: `{REPORT_DIR / "tcgdex_repo_set_audit.csv"}`',
        '',
        '## Interpretation',
        '',
        '- Repository-only sets are source-backed set metadata, not completed card checklists.',
        '- They should be treated as high-priority gaps for card-list enrichment.',
        '- This audit confirms the database should reconcile API output against upstream/source repositories, not just scrape public endpoints.',
    ])
    (REPORT_DIR / 'tcgdex_repo_supplement_audit.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

    summary = {
        'built_at_utc': fetched_at,
        'repo_set_ids': len(repo_ids),
        'rest_api_set_ids_before_supplement': len(api_ids),
        'repo_set_ids_missing_from_rest_api': len(missing_ids),
        'unique_set_ids_after_supplement': len(api_after),
        'language_specific_set_rows_after_supplement': total_set_rows,
        'checklist_card_rows_after_supplement': total_cards,
        'distinct_language_codes_after_supplement': total_langs,
        'missing_rest_api_set_ids': sorted(missing_ids),
    }
    (REPORT_DIR / 'tcgdex_repo_supplement_audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
