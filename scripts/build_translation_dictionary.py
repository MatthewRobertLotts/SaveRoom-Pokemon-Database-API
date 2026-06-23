#!/usr/bin/env python3
"""
Build and apply a translation layer for non-English card names.

Creates a `card_name_translations` table in the DB with:
  - card_id, language_code, en_name, source

Sources (in priority order):
  1. DB join: same card_id has an English row (covers European languages + some ja/ko)
  2. PokéAPI: Pokémon species names across languages (bulk fetch)
  3. Pattern matching: extract Pokémon name from compound card names

Then creates a materialized view `v2_card_detail_api_cache_i18n` that adds en_name to every row.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
DICT_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/references/pokemon_name_dictionary.json")

# PokéAPI language code → our language code
POKEAPI_TO_OUR_LANG = {
    "ja-Hrkt": "ja",
    "ko": "ko",
    "zh-Hant": "zh-tw",
    "zh-Hans": "zh-cn",
    "th": "th",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "it": "it",
    "pt": "pt",
    "ru": "ru",
    "pl": "pl",
    "nl": "nl",
    "id": "id",
}

# Suffixes that can be stripped to get the base Pokémon name
CARD_SUFFIXES = [
    " ex", " EX", " gx", " GX", " V", " VMAX", " VSTAR",
    " ex", " GX", " LV.X", " BREAK",
    "（デルタ種）", " (Delta Species)",
    " LV.", " FB", " ◇",
]

# Possessive patterns
POSSESSIVE_PATTERNS = [
    r"^(.+?)の(.+)$",           # Japanese: XのY → Y (keep the Pokémon part)
    r"^<(.+?)的>(.+)$",         # Chinese: <X的>Y → Y
    r"^(.+?)'s (.+)$",          # English-style possessives
]


def ensure_index():
    """Create index for efficient joins."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('CREATE INDEX IF NOT EXISTS idx_v2_card_detail_card_lang ON v2_card_detail_api_cache(card_id, language_code)')
    conn.commit()
    conn.close()


def extract_db_name_pairs() -> dict[str, dict[str, str]]:
    """Source 1: Get name pairs from DB where both en and non-en exist for same card_id."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        SELECT v.language_code, v.card_name, en.card_name
        FROM v2_card_detail_api_cache v
        INNER JOIN v2_card_detail_api_cache en
            ON en.card_id = v.card_id AND en.language_code = 'en'
        WHERE v.language_code != 'en'
    ''')

    pairs: dict[str, dict[str, str]] = {}
    for lang, local_name, en_name in cur.fetchall():
        local_name = local_name.strip()
        en_name = en_name.strip()
        if lang not in pairs:
            pairs[lang] = {}
        if local_name not in pairs[lang]:
            pairs[lang][local_name] = en_name

    conn.close()
    return pairs


def fetch_pokemon_names_bulk() -> dict[str, dict[str, str]]:
    """Source 2: Fetch ALL Pokémon names from PokéAPI efficiently."""
    print("  Fetching Pokémon species list...")
    url = "https://pokeapi.co/api/v2/pokemon-species?limit=10000"
    req = urllib.request.Request(url, headers={"User-Agent": "SaveRoom-Pokemon-DB/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    species_urls = [r["url"] for r in data.get("results", [])]
    total = len(species_urls)
    print(f"  Fetching names for {total} species...")

    # Build reverse mapping: {lang: {local_name: en_name}}
    reverse: dict[str, dict[str, str]] = {}

    for i, url in enumerate(species_urls):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SaveRoom-Pokemon-DB/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                sp = json.loads(resp.read())

            en_name = None
            locals_for_this_species: dict[str, str] = {}

            for ne in sp.get("names", []):
                lang = ne["language"]["name"]
                name = ne["name"]
                if lang == "en":
                    en_name = name
                elif lang in POKEAPI_TO_OUR_LANG:
                    our_lang = POKEAPI_TO_OUR_LANG[lang]
                    locals_for_this_species[our_lang] = name

            if en_name:
                for our_lang, local_name in locals_for_this_species.items():
                    if our_lang not in reverse:
                        reverse[our_lang] = {}
                    reverse[our_lang][local_name] = en_name

            if (i + 1) % 200 == 0:
                print(f"    {i + 1}/{total}...")
            time.sleep(0.02)

        except Exception as e:
            print(f"    Warning: {e}")
            continue

    return reverse


def strip_card_suffixes(name: str) -> str:
    """Strip card suffixes to get the base Pokémon name."""
    result = name
    for suffix in CARD_SUFFIXES:
        if result.endswith(suffix):
            result = result[:-len(suffix)].strip()
    return result


def extract_pokemon_from_compound(name: str, lang: str) -> str | None:
    """Try to extract the Pokémon name from a compound card name."""
    # Japanese: "XのY" → Y is usually the Pokémon
    if lang == "ja":
        m = re.match(r"^.+?の(.+)$", name)
        if m:
            return m.group(1).strip()

    # Chinese: "<X的>Y" → Y is the Pokémon
    if lang in ("zh-tw", "zh-cn"):
        m = re.match(r"^<.+?的>(.+)$", name)
        if m:
            return m.group(1).strip()

    return None


def build_translation_table():
    """Main: build the card_name_translations table."""
    ensure_index()

    # Gather all name mappings
    print("=== Building translation dictionary ===")

    # Source 1: DB pairs
    print("\nSource 1: DB name pairs...")
    db_pairs = extract_db_name_pairs()
    total_db = sum(len(v) for v in db_pairs.values())
    print(f"  {total_db} mappings from DB")

    # Source 2: PokéAPI
    print("\nSource 2: PokéAPI Pokémon names...")
    pokeapi_pairs = fetch_pokemon_names_bulk()
    total_pokeapi = sum(len(v) for v in pokeapi_pairs.values())
    print(f"  {total_pokeapi} mappings from PokéAPI")

    # Merge: DB pairs take priority
    merged: dict[str, dict[str, str]] = {}
    for lang, mappings in db_pairs.items():
        merged[lang] = dict(mappings)
    for lang, mappings in pokeapi_pairs.items():
        if lang not in merged:
            merged[lang] = {}
        for local, en in mappings.items():
            if local not in merged[lang]:
                merged[lang][local] = en

    total_merged = sum(len(v) for v in merged.values())
    print(f"\n  Merged total: {total_merged} mappings")

    # Save dictionary for reference
    DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DICT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"  Saved to {DICT_PATH}")

    # Create translation table in DB
    print("\n=== Creating translation table in DB ===")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS card_name_translations')
    cur.execute('''
        CREATE TABLE card_name_translations (
            id INTEGER PRIMARY KEY,
            card_id TEXT NOT NULL,
            language_code TEXT NOT NULL,
            local_name TEXT NOT NULL,
            en_name TEXT NOT NULL,
            source TEXT NOT NULL,
            UNIQUE(card_id, language_code)
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_translations_card_lang ON card_name_translations(card_id, language_code)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_translations_local ON card_name_translations(language_code, local_name)')

    # Phase 1: Direct translations from merged dictionary
    print("\nPhase 1: Direct dictionary lookup...")
    cur.execute('SELECT card_id, language_code, card_name FROM v2_card_detail_api_cache WHERE language_code != "en"')
    all_non_en = cur.fetchall()

    translated = 0
    untranslated = 0
    batch = []

    for card_id, lang, local_name in all_non_en:
        local_name = local_name.strip()
        en_name = None
        source = None

        # Try exact match in dictionary
        if lang in merged and local_name in merged[lang]:
            en_name = merged[lang][local_name]
            source = "db_join" if lang in db_pairs and local_name in db_pairs[lang] else "pokeapi"
        else:
            # Try stripping suffixes
            base_name = strip_card_suffixes(local_name)
            if lang in merged and base_name in merged[lang]:
                en_name = merged[lang][base_name]
                source = "suffix_strip"
            else:
                # Try extracting Pokémon from compound name
                pokemon_part = extract_pokemon_from_compound(local_name, lang)
                if pokemon_part and lang in merged and pokemon_part in merged[lang]:
                    en_name = merged[lang][pokemon_part]
                    source = "compound_extract"

        if en_name:
            batch.append((card_id, lang, local_name, en_name, source))
            translated += 1
        else:
            batch.append((card_id, lang, local_name, local_name, "untranslated"))
            untranslated += 1

        if len(batch) >= 10000:
            cur.executemany('INSERT OR REPLACE INTO card_name_translations (card_id, language_code, local_name, en_name, source) VALUES (?, ?, ?, ?, ?)', batch)
            batch = []

    if batch:
        cur.executemany('INSERT OR REPLACE INTO card_name_translations (card_id, language_code, local_name, en_name, source) VALUES (?, ?, ?, ?, ?)', batch)

    conn.commit()

    print(f"  Translated: {translated}")
    print(f"  Untranslated: {untranslated}")

    # Report by source
    print("\n=== Translation source breakdown ===")
    cur.execute('SELECT source, COUNT(*) FROM card_name_translations GROUP BY source ORDER BY COUNT(*) DESC')
    for source, count in cur.fetchall():
        print(f"  {source:25s}: {count:>6,}")

    # Report by language
    print("\n=== Translation coverage by language ===")
    cur.execute('''
        SELECT t.language_code, 
               COUNT(*) as total,
               SUM(CASE WHEN t.source != 'untranslated' THEN 1 ELSE 0 END) as translated,
               ROUND(100.0 * SUM(CASE WHEN t.source != 'untranslated' THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
        FROM card_name_translations t
        GROUP BY t.language_code
        ORDER BY COUNT(*) DESC
    ''')
    for lang, total, trans, pct in cur.fetchall():
        print(f"  {lang:10s}: {trans:>6,} / {total:>6,} ({pct}%)")

    # Sample untranslated
    print("\n=== Sample untranslated names ===")
    cur.execute('''
        SELECT language_code, local_name, COUNT(*) as n
        FROM card_name_translations
        WHERE source = 'untranslated'
        GROUP BY language_code, local_name
        ORDER BY n DESC
        LIMIT 20
    ''')
    for lang, name, n in cur.fetchall():
        print(f"  {lang:5s} {n:>4}x  {name!r}")

    conn.close()

    return translated, untranslated


if __name__ == "__main__":
    build_translation_table()
