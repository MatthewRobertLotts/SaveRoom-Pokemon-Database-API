#!/usr/bin/env python3
"""
Smart translation using substring matching against known Pokémon names.

For remaining untranslated names, try to find a known Pokémon name
as a substring and translate based on that.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
REF_DIR = Path("/media/matt/Storage/Brain/Pokemon Card Database/references")

# Load all Pokémon name mappings
with open(REF_DIR / "pokemon_names_en.json", encoding="utf-8") as f:
    en_names = json.load(f)

# Build reverse mappings for all languages
POKEAPI_MAPS = {}
for lang_file, lang_code in [
    ("pokemon_names_ja.json", "ja"),
    ("pokemon_names_ko.json", "ko"),
    ("pokemon_names_zh_hant.json", "zh-tw"),
    ("pokemon_names_zh_hans.json", "zh-cn"),
    ("pokemon_names_th.json", "th"),
]:
    with open(REF_DIR / lang_file, encoding="utf-8") as f:
        local_names = json.load(f)
    POKEAPI_MAPS[lang_code] = {}
    for i, local_name in enumerate(local_names):
        if i < len(en_names):
            POKEAPI_MAPS[lang_code][local_name] = en_names[i]

# Also load the existing dictionary for non-Pokémon terms
DICT_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/references/pokemon_name_dictionary.json")
with open(DICT_PATH, encoding="utf-8") as f:
    existing_dict = json.load(f)


def smart_translate(local_name: str, lang: str) -> tuple[str | None, str | None]:
    """Try multiple strategies to translate a card name."""

    # Strategy 1: Check existing dictionary
    if lang in existing_dict and local_name in existing_dict[lang]:
        return existing_dict[lang][local_name], "dictionary"

    # Strategy 2: Direct Pokémon name match
    if lang in POKEAPI_MAPS and local_name in POKEAPI_MAPS[lang]:
        return POKEAPI_MAPS[lang][local_name], "pokemon_direct"

    # Strategy 3: Strip suffixes and match
    base = local_name
    all_suffixes = [
        " ex", " EX", " V", " VMAX", " VSTAR", " GX", " LV.X", " BREAK",
        " FB", " ◇", "Ｚ", " FA", " TAG", " 연합",
        "（デルタ種）", " (Delta Species)",
        " VMAX\n[다이맥스]", " V\n[퓨전]",
    ]
    for suffix in all_suffixes:
        if base.endswith(suffix):
            base = base[:-len(suffix)].strip()
            break

    if lang in POKEAPI_MAPS and base in POKEAPI_MAPS[lang]:
        return POKEAPI_MAPS[lang][base], "pokemon_suffix"

    # Strategy 4: Substring match — find the longest matching Pokémon name
    if lang in POKEAPI_MAPS:
        best_match = None
        best_len = 0
        for local_pokemon, en_pokemon in POKEAPI_MAPS[lang].items():
            if local_pokemon in local_name and len(local_pokemon) > best_len:
                best_match = en_pokemon
                best_len = len(local_pokemon)
        if best_match:
            return best_match, "pokemon_substring"

    # Strategy 5: For Latin-script names, check if it contains an English Pokémon name
    if re.match(r"^[A-Za-z0-9\s\-'.()]+$", local_name):
        for en_name in sorted(en_names, key=len, reverse=True):
            if en_name.lower() in local_name.lower():
                return local_name, "latin_contains_pokemon"

    # Strategy 6: Chinese compound patterns
    if lang in ("zh-tw", "zh-cn"):
        # "<X的>Y" → Y
        m = re.match(r"^<.+?的>(.+)$", local_name)
        if m:
            inner = m.group(1).strip()
            if lang in POKEAPI_MAPS and inner in POKEAPI_MAPS[lang]:
                return POKEAPI_MAPS[lang][inner], "zh_compound"
        # "X&Y" Tag Team → try to translate each part
        if "&" in local_name:
            parts = local_name.split("&")
            translated_parts = []
            all_translated = True
            for part in parts:
                part = part.strip()
                if lang in POKEAPI_MAPS and part in POKEAPI_MAPS[lang]:
                    translated_parts.append(POKEAPI_MAPS[lang][part])
                else:
                    all_translated = False
                    break
            if all_translated and translated_parts:
                return " & ".join(translated_parts), "zh_tag_team"

    # Strategy 7: Japanese compound "XのY"
    if lang == "ja":
        m = re.match(r"^.+?の(.+)$", local_name)
        if m:
            inner = m.group(1).strip()
            if inner in POKEAPI_MAPS.get(lang, {}):
                return POKEAPI_MAPS[lang][inner], "ja_compound"

    return None, None


def apply_smart_translation():
    """Apply smart translation to all remaining untranslated names."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('''
        SELECT id, card_id, language_code, local_name
        FROM card_name_translations
        WHERE source = 'untranslated'
    ''')

    updates = []
    translated = 0
    still_untranslated = 0

    for row_id, card_id, lang, local_name in cur.fetchall():
        en_name, source = smart_translate(local_name, lang)
        if en_name:
            updates.append((en_name, source, row_id))
            translated += 1
        else:
            still_untranslated += 1

    cur.executemany('UPDATE card_name_translations SET en_name = ?, source = ? WHERE id = ?', updates)
    conn.commit()

    print(f"Smart translation results:")
    print(f"  Translated: {translated}")
    print(f"  Still untranslated: {still_untranslated}")

    # Coverage
    print("\n=== Coverage by language ===")
    cur.execute('''
        SELECT language_code, 
               COUNT(*) as total,
               SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) as translated,
               ROUND(100.0 * SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
        FROM card_name_translations
        GROUP BY language_code
        ORDER BY COUNT(*) DESC
    ''')
    for lang, total, trans, pct in cur.fetchall():
        print(f"  {lang:10s}: {trans:>6,} / {total:>6,} ({pct}%)")

    # Source breakdown
    print("\n=== Source breakdown ===")
    cur.execute('SELECT source, COUNT(*) FROM card_name_translations GROUP BY source ORDER BY COUNT(*) DESC')
    for source, count in cur.fetchall():
        print(f"  {source:30s}: {count:>6,}")

    # Remaining
    if still_untranslated > 0:
        print(f"\n=== Remaining untranslated ({still_untranslated}) ===")
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
    return still_untranslated


if __name__ == "__main__":
    remaining = apply_smart_translation()
    if remaining == 0:
        print(f"\n✅ All non-English cards now have English names!")
    else:
        print(f"\n⚠️  {remaining} names still untranslated")
