#!/usr/bin/env python3
"""Import card-level data from local TCGdex GitHub clone into the SaveRoom Pokémon set KB.

Parses all card .ts files from the cloned repo, extracts card metadata, and inserts
into card_details table and fills missing rows in the main cards table.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_DIR = Path('/media/matt/Storage/Brain/PokemonCardDB/repo')
DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')

FETCHED_AT = '2026-06-11T12:00:00+00:00'


def extract_names(ts: str) -> dict[str, str]:
    m = re.search(r'\bname\s*:\s*\{(?P<body>.*?)\n\s*\}', ts, re.S)
    if not m:
        m2 = re.search(r'\bname\s*:\s*[\'"]([^\'"]+)[\'"]', ts)
        return {'unknown': m2.group(1)} if m2 else {}
    body = m.group('body')
    return {k: v for k, v in re.findall(r'[\'"]?([a-z]{2}(?:-[a-z]{2})?)[\'"]?\s*:\s*[\'"]([^\'"]*)[\'"]', body)}


def extract_local_id(ts: str) -> str | None:
    m = re.search(r'\blocalId\s*:\s*[\'"]([^\'"]+)[\'"]', ts)
    return m.group(1) if m else None


def extract_simple_str(ts: str, field: str) -> str | None:
    m = re.search(rf'\b{re.escape(field)}\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_simple_int(ts: str, field: str) -> int | None:
    m = re.search(rf'\b{re.escape(field)}\s*:\s*(\d+)', ts)
    return int(m.group(1)) if m else None


def extract_array(ts: str, field: str) -> str | None:
    m = re.search(rf'\b{re.escape(field)}\s*:\s*\[(.*?)\]', ts, re.S)
    if m:
        items = re.findall(r'[\'"]([^\'"]*)[\'"]', m.group(1))
        return ','.join(items) if items else None
    return None


def extract_object(ts: str, field: str) -> str | None:
    pattern = r'\b' + re.escape(field) + r'\s*:\s*\{(.*?)\}'
    m = re.search(pattern, ts, re.S)
    return m.group(1).strip()[:1000] if m else None


def extract_attacks(ts: str) -> str | None:
    pattern = r'\battacks\s*:\s*\[(.*?)(?:\]\s*\n\s*weaknesses|\]\s*\n\s*resistances|\]\s*\n\s*retreat|\]\s*\n\s*\})'
    m = re.search(pattern, ts, re.S)
    if not m:
        m = re.search(r'\battacks\s*:\s*\[(.*?)\]', ts, re.S)
    return m.group(1).strip()[:2000] if m else None


def local_sort_val(local_id: Any) -> int | None:
    if local_id is None:
        return None
    m = re.search(r'\d+', str(local_id))
    return int(m.group(0)) if m else None


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # Create tables
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS card_details (
            card_id TEXT NOT NULL,
            language_code TEXT NOT NULL,
            set_id TEXT NOT NULL,
            local_id TEXT,
            local_id_sort INTEGER,
            name TEXT,
            illustrator TEXT,
            category TEXT,
            hp INTEGER,
            types TEXT,
            rarity TEXT,
            stage TEXT,
            retreat INTEGER,
            regulation_mark TEXT,
            attacks TEXT,
            weaknesses TEXT,
            resistances TEXT,
            variants TEXT,
            legal TEXT,
            description TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (card_id, language_code)
        );
        CREATE INDEX IF NOT EXISTS idx_card_details_set ON card_details(set_id, language_code);
        CREATE INDEX IF NOT EXISTS idx_card_details_name ON card_details(name);
    ''')

    # Get DB set IDs
    db_sets = {row[0] for row in conn.execute('SELECT DISTINCT set_id FROM sets').fetchall()}
    print(f"DB set IDs: {len(db_sets)}")

    # Find all card-level .ts files (depth 3: data/{series}/{set}/{card}.ts)
    card_files = []
    for data_dir in [REPO_DIR / 'data', REPO_DIR / 'data-asia']:
        if not data_dir.exists():
            continue
        for series_dir in data_dir.iterdir():
            if not series_dir.is_dir():
                continue
            for set_dir in series_dir.iterdir():
                if not set_dir.is_dir():
                    continue
                set_id = set_dir.name
                if set_id not in db_sets:
                    continue
                for card_file in set_dir.glob('*.ts'):
                    card_files.append((set_id, card_file))

    print(f"Card files to process: {len(card_files)}")

    # Process cards
    new_details = 0
    new_cards = 0
    errors = 0
    lang_counts: dict[str, int] = defaultdict(int)
    set_counts: dict[str, int] = defaultdict(int)

    for idx, (set_id, card_file) in enumerate(card_files, 1):
        try:
            ts = card_file.read_text(encoding='utf-8')
        except Exception:
            errors += 1
            continue

        local_id = extract_local_id(ts) or card_file.stem
        names = extract_names(ts)

        if not names:
            continue

        illustrator = extract_simple_str(ts, 'illustrator')
        category = extract_simple_str(ts, 'category')
        hp = extract_simple_int(ts, 'hp')
        types = extract_array(ts, 'types')
        rarity = extract_simple_str(ts, 'rarity')
        stage = extract_simple_str(ts, 'stage')
        retreat = extract_simple_int(ts, 'retreat')
        regulation = extract_simple_str(ts, 'regulationMark')
        attacks = extract_attacks(ts)
        weaknesses = extract_object(ts, 'weaknesses')
        resistances = extract_object(ts, 'resistances')
        variants = extract_object(ts, 'variants')
        legal = extract_object(ts, 'legal')

        # Extract descriptions
        desc_m = re.search(r'\bdescription\s*:\s*\{(?P<body>.*?)\n\s*\}', ts, re.S)
        description = None
        if desc_m:
            desc_body = desc_m.group('body')
            desc_dict = {k: v for k, v in re.findall(r'[\'"]?([a-z]{2}(?:-[a-z]{2})?)[\'"]?\s*:\s*[\'"]([^\'"]*)[\'"]', desc_body)}
            if desc_dict:
                description = json.dumps(desc_dict, ensure_ascii=False)

        card_id = f"{set_id}-{local_id}"

        for lang, name in names.items():
            lang_counts[lang] += 1
            set_counts[lang] = set_counts.get(lang, 0) + 1

            conn.execute('''
                INSERT OR REPLACE INTO card_details(
                    card_id, language_code, set_id, local_id, local_id_sort, name,
                    illustrator, category, hp, types, rarity, stage, retreat,
                    regulation_mark, attacks, weaknesses, resistances, variants,
                    legal, description, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                card_id, lang, set_id, local_id, local_sort_val(local_id), name,
                illustrator, category, hp, types, rarity, stage, retreat,
                regulation, attacks, weaknesses, resistances, variants,
                legal, description, FETCHED_AT,
            ))
            new_details += 1

            # Insert into main cards table if not already there
            existing = conn.execute(
                'SELECT COUNT(*) FROM cards WHERE card_id=? AND language_code=?',
                (card_id, lang)
            ).fetchone()[0]
            if existing == 0:
                conn.execute('''
                    INSERT INTO cards(language_code, set_id, card_id, local_id, local_id_sort, name, image_url)
                    VALUES (?, ?, ?, ?, ?, ?, NULL)
                ''', (lang, set_id, card_id, local_id, local_sort_val(local_id), name))
                new_cards += 1

        if idx % 2000 == 0:
            conn.commit()
            print(f"  Progress: {idx}/{len(card_files)} files, {new_details} details, {new_cards} new cards")

    conn.commit()

    # Summary
    total_details = conn.execute('SELECT COUNT(*) FROM card_details').fetchone()[0]
    total_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    ko_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='ko'").fetchone()[0]
    zh_cn_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='zh-cn'").fetchone()[0]
    nl_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='nl'").fetchone()[0]
    pl_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='pl'").fetchone()[0]
    ru_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='ru'").fetchone()[0]
    unique_sets_with_cards = conn.execute('SELECT COUNT(DISTINCT set_id) FROM cards').fetchone()[0]
    sets_without_checklist = conn.execute('SELECT COUNT(DISTINCT set_id) FROM sets WHERE set_id NOT IN (SELECT DISTINCT set_id FROM cards)').fetchone()[0]

    print(f"\n=== Import Complete ===")
    print(f"Card files processed: {len(card_files)}")
    print(f"New card details: {new_details}")
    print(f"New cards in main table: {new_cards}")
    print(f"Errors: {errors}")
    print(f"\nTotal card details: {total_details}")
    print(f"Total cards: {total_cards}")
    print(f"Unique sets with cards: {unique_sets_with_cards}")
    print(f"Sets still without any checklist: {sets_without_checklist}")
    print(f"\nKorean cards: {ko_cards}")
    print(f"Simplified Chinese cards: {zh_cn_cards}")
    print(f"Dutch cards: {nl_cards}")
    print(f"Polish cards: {pl_cards}")
    print(f"Russian cards: {ru_cards}")

    print(f"\nTop 20 languages in card_details:")
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {lang}: {count}")

    # Write summary
    summary = {
        'built_at': FETCHED_AT,
        'card_files_processed': len(card_files),
        'new_card_details': new_details,
        'new_cards': new_cards,
        'errors': errors,
        'total_card_details': total_details,
        'total_cards': total_cards,
        'unique_sets_with_cards': unique_sets_with_cards,
        'sets_without_checklist': sets_without_checklist,
        'korean_cards': ko_cards,
        'simplified_chinese_cards': zh_cn_cards,
        'dutch_cards': nl_cards,
        'polish_cards': pl_cards,
        'russian_cards': ru_cards,
        'top_languages': dict(sorted(lang_counts.items(), key=lambda x: -x[1])[:30]),
    }
    (REPORT_DIR / 'card_import_from_repo_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    conn.close()


if __name__ == '__main__':
    main()
