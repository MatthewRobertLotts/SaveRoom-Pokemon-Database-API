#!/usr/bin/env python3
"""Import card-level data from TCGdex GitHub repository into the SaveRoom Pokémon set KB.

Fetches card .ts files from the tcgdex/cards-database repo, parses card metadata
(name, localId, illustrator, category, hp, types, attacks, weaknesses, resistances,
variants, rarity, description, stage, retreat), and inserts into a card_details table.
Also fills in missing Korean/other language card rows in the main cards table.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
RAW_CARD_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/raw/tcgdex_repo_cards')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
GITHUB_TREE = 'https://api.github.com/repos/tcgdex/cards-database/git/trees/master?recursive=1'
RAW_BASE = 'https://raw.githubusercontent.com/tcgdex/cards-database/master/'

FETCHED_AT = '2026-06-11T12:00:00+00:00'


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'SaveRoom-TCGdex-CardImport/1.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode('utf-8')


def extract_field(ts: str, field: str) -> str | None:
    """Extract a simple string field from the card .ts file."""
    m = re.search(rf'\b{re.escape(field)}\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_name_field(ts: str) -> dict[str, str]:
    """Extract the name: { ... } block."""
    m = re.search(r'\bname\s*:\s*\{(?P<body>.*?)\n\s*\}', ts, re.S)
    if not m:
        return {}
    body = m.group('body')
    return {k: v for k, v in re.findall(r'[\'"]?([a-z]{2}(?:-[a-z]{2})?)[\'"]?\s*:\s*[\'"]([^\'"]*)[\'"]', body)}


def extract_local_id(ts: str) -> str | None:
    m = re.search(r'\blocalId\s*:\s*[\'"]([^\'"]+)[\'"]', ts)
    return m.group(1) if m else None


def extract_card_number(ts: str) -> str | None:
    m = re.search(r'\bcardNumber\s*:\s*[\'"]([^\'"]+)[\'"]', ts)
    return m.group(1) if m else None


def extract_illustrator(ts: str) -> str | None:
    m = re.search(r'\billustrator\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_category(ts: str) -> str | None:
    m = re.search(r'\bcategory\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_hp(ts: str) -> int | None:
    m = re.search(r'\bhp\s*:\s*(\d+)', ts)
    return int(m.group(1)) if m else None


def extract_types(ts: str) -> str | None:
    m = re.search(r'\btypes\s*:\s*\[(.*?)\]', ts, re.S)
    if m:
        types = re.findall(r'[\'"]([^\'"]*)[\'"]', m.group(1))
        return ','.join(types) if types else None
    return None


def extract_rarity(ts: str) -> str | None:
    m = re.search(r'\brarity\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_stage(ts: str) -> str | None:
    m = re.search(r'\bstage\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_retreat(ts: str) -> int | None:
    m = re.search(r'\bretreat\s*:\s*(\d+)', ts)
    return int(m.group(1)) if m else None


def extract_attacks(ts: str) -> str | None:
    """Extract attacks as JSON string."""
    m = re.search(r'\battacks\s*:\s*\[(.*?)\]', ts, re.S)
    if m:
        return m.group(1).strip()[:2000]  # truncate for storage
    return None


def extract_weaknesses(ts: str) -> str | None:
    m = re.search(r'\bweaknesses\s*:\s*\[(.*?)\]', ts, re.S)
    if m:
        return m.group(1).strip()[:500]
    return None


def extract_resistances(ts: str) -> str | None:
    m = re.search(r'\bresistances\s*:\s*\[(.*?)\]', ts, re.S)
    if m:
        return m.group(1).strip()[:500]
    return None


def extract_variants(ts: str) -> str | None:
    m = re.search(r'\bvariants\s*:\s*\{(.*?)\}', ts, re.S)
    if m:
        return m.group(1).strip()[:500]
    return None


def extract_legal(ts: str) -> str | None:
    m = re.search(r'\blegal\s*:\s*\{(.*?)\}', ts, re.S)
    if m:
        return m.group(1).strip()[:500]
    return None


def extract_regulation_mark(ts: str) -> str | None:
    m = re.search(r'\bregulationMark\s*:\s*[\'"]([^\'"]*)[\'"]', ts)
    return m.group(1) if m else None


def extract_description(ts: str) -> dict[str, str]:
    m = re.search(r'\bdescription\s*:\s*\{(?P<body>.*?)\n\s*\}', ts, re.S)
    if not m:
        return {}
    body = m.group('body')
    return {k: v for k, v in re.findall(r'[\'"]?([a-z]{2}(?:-[a-z]{2})?)[\'"]?\s*:\s*[\'"]([^\'"]*)[\'"]', body)}


def local_sort(local_id: Any) -> int | None:
    if local_id is None:
        return None
    m = re.search(r'\d+', str(local_id))
    return int(m.group(0)) if m else None


def main() -> None:
    RAW_CARD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    # Create card_details table
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

    # Get GitHub tree
    print("Fetching GitHub tree...")
    tree = json.loads(fetch_text(GITHUB_TREE))

    # Find card-level files (depth 3)
    card_files = [
        item['path'] for item in tree['tree']
        if item.get('type') == 'blob'
        and item.get('path', '').endswith('.ts')
        and (item['path'].startswith('data/') or item['path'].startswith('data-asia/'))
        and item['path'].count('/') == 3
    ]
    print(f"Card-level files found: {len(card_files)}")

    # Group by set_id
    by_set: dict[str, list[str]] = defaultdict(list)
    for path in card_files:
        parts = path.split('/')
        set_id = parts[2]
        by_set[set_id].append(path)

    # Get DB set IDs
    db_sets = {row[0] for row in conn.execute('SELECT DISTINCT set_id FROM sets').fetchall()}
    covered_sets = sorted(set(by_set.keys()) & db_sets)
    total_files = sum(len(by_set[s]) for s in covered_sets)
    print(f"DB sets with card files: {len(covered_sets)}, total files: {total_files}")

    # Import cards
    new_details = 0
    new_cards = 0
    errors = 0
    lang_counts: dict[str, int] = defaultdict(int)

    for set_idx, set_id in enumerate(covered_sets, 1):
        paths = by_set[set_id]
        for path in paths:
            parts = path.split('/')
            filename = parts[3]  # e.g. "001.ts"
            local_id = filename.replace('.ts', '')

            # Determine language from path
            # data/ = international, data-asia/ = Asian
            # The card file itself contains name blocks with language keys
            raw_url = RAW_BASE + urllib.parse.quote(path, safe='/')

            try:
                ts = fetch_text(raw_url)
            except Exception:
                errors += 1
                continue

            # Save raw file
            card_dir = RAW_CARD_DIR / set_id
            card_dir.mkdir(parents=True, exist_ok=True)
            (card_dir / filename).write_text(ts, encoding='utf-8')

            # Extract card data
            names = extract_name_field(ts)
            illustrator = extract_illustrator(ts)
            category = extract_category(ts)
            hp = extract_hp(ts)
            types = extract_types(ts)
            rarity = extract_rarity(ts)
            stage = extract_stage(ts)
            retreat = extract_retreat(ts)
            regulation = extract_regulation_mark(ts)
            attacks = extract_attacks(ts)
            weaknesses = extract_weaknesses(ts)
            resistances = extract_resistances(ts)
            variants = extract_variants(ts)
            legal = extract_legal(ts)
            descriptions = extract_description(ts)

            # Insert card details for each language
            for lang, name in names.items():
                card_id = f"{set_id}-{local_id}"
                lang_counts[lang] += 1

                conn.execute('''
                    INSERT OR REPLACE INTO card_details(
                        card_id, language_code, set_id, local_id, local_id_sort, name,
                        illustrator, category, hp, types, rarity, stage, retreat,
                        regulation_mark, attacks, weaknesses, resistances, variants,
                        legal, description, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    card_id, lang, set_id, local_id, local_sort(local_id), name,
                    illustrator, category, hp, types, rarity, stage, retreat,
                    regulation, attacks, weaknesses, resistances, variants,
                    legal, json.dumps(descriptions, ensure_ascii=False) if descriptions else None,
                    FETCHED_AT,
                ))
                new_details += 1

                # Also insert into main cards table if not already there
                existing = conn.execute(
                    'SELECT COUNT(*) FROM cards WHERE card_id=? AND language_code=?',
                    (card_id, lang)
                ).fetchone()[0]
                if existing == 0:
                    conn.execute('''
                        INSERT INTO cards(language_code, set_id, card_id, local_id, local_id_sort, name, image_url)
                        VALUES (?, ?, ?, ?, ?, ?, NULL)
                    ''', (lang, set_id, card_id, local_id, local_sort(local_id), name))
                    new_cards += 1

        if set_idx % 20 == 0:
            conn.commit()
            print(f"  Progress: {set_idx}/{len(covered_sets)} sets, {new_details} details, {new_cards} new cards")

    conn.commit()

    # Summary
    total_details = conn.execute('SELECT COUNT(*) FROM card_details').fetchone()[0]
    total_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    ko_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='ko'").fetchone()[0]
    zh_cn_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='zh-cn'").fetchone()[0]
    nl_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='nl'").fetchone()[0]
    pl_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='pl'").fetchone()[0]
    ru_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE language_code='ru'").fetchone()[0]

    print(f"\n=== Import Complete ===")
    print(f"New card details: {new_details}")
    print(f"New cards in main table: {new_cards}")
    print(f"Errors: {errors}")
    print(f"\nTotal card details: {total_details}")
    print(f"Total cards: {total_cards}")
    print(f"Korean cards: {ko_cards}")
    print(f"Simplified Chinese cards: {zh_cn_cards}")
    print(f"Dutch cards: {nl_cards}")
    print(f"Polish cards: {pl_cards}")
    print(f"Russian cards: {ru_cards}")

    print(f"\nTop languages in card_details:")
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {lang}: {count}")

    # Write summary report
    summary = {
        'built_at': FETCHED_AT,
        'card_files_processed': total_files,
        'sets_covered': len(covered_sets),
        'new_card_details': new_details,
        'new_cards': new_cards,
        'errors': errors,
        'total_card_details': total_details,
        'total_cards': total_cards,
        'korean_cards': ko_cards,
        'simplified_chinese_cards': zh_cn_cards,
        'dutch_cards': nl_cards,
        'polish_cards': pl_cards,
        'russian_cards': ru_cards,
        'language_counts': dict(sorted(lang_counts.items(), key=lambda x: -x[1])),
    }
    (REPORT_DIR / 'card_import_from_repo_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    conn.close()


if __name__ == '__main__':
    main()
