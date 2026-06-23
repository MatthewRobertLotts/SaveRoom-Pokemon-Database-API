#!/usr/bin/env python3
"""
Third-pass translation: use comprehensive Pokémon name lists from sindresorhus/pokemon.

Downloads ja/ko/zh-hans/zh-hant/th Pokémon names and builds reverse mappings
to translate remaining untranslated card names.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")
REF_DIR = Path("/media/matt/Storage/Brain/Pokemon Card Database/references")

# Language code mapping
LANG_FILES = {
    "ja": "pokemon_names_ja.json",
    "ko": "pokemon_names_ko.json",
    "zh-cn": "pokemon_names_zh_hans.json",
    "zh-tw": "pokemon_names_zh_hant.json",
    "th": "pokemon_names_th.json",
}


def load_pokemon_names() -> dict[str, dict[str, str]]:
    """Load Pokémon names and build reverse mappings: {lang: {local: en}}."""
    reverse: dict[str, dict[str, str]] = {}

    with open(REF_DIR / "pokemon_names_en.json", encoding="utf-8") as f:
        en_names = json.load(f)

    for lang, filename in LANG_FILES.items():
        with open(REF_DIR / filename, encoding="utf-8") as f:
            local_names = json.load(f)
        reverse[lang] = {}
        for i, local_name in enumerate(local_names):
            if i < len(en_names):
                reverse[lang][local_name] = en_names[i]

    return reverse


def apply_third_pass():
    """Apply Pokémon name translations from comprehensive lists."""
    pokemon_reverse = load_pokemon_names()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get remaining untranslated
    cur.execute('''
        SELECT id, card_id, language_code, local_name
        FROM card_name_translations
        WHERE source = 'untranslated'
    ''')

    updates = []
    translated = 0
    still_untranslated = 0

    for row_id, card_id, lang, local_name in cur.fetchall():
        en_name = None
        source = None

        # Try exact Pokémon name match
        if lang in pokemon_reverse and local_name in pokemon_reverse[lang]:
            en_name = pokemon_reverse[lang][local_name]
            source = "pokemon_names_exact"
        else:
            # Try stripping common suffixes and matching
            base = local_name
            # Japanese suffixes
            if lang == "ja":
                for suffix in [" ex", " EX", " V", " VMAX", " VSTAR", " GX", " LV.X",
                               "（デルタ種）", " FB", " ◇", "Ｚ"]:
                    if base.endswith(suffix):
                        base = base[:-len(suffix)].strip()
                        break
            # Korean suffixes
            elif lang == "ko":
                for suffix in [" ex", " EX", " V", " VMAX", " VSTAR", " GX",
                               " ex", " Ｚ"]:
                    if base.endswith(suffix):
                        base = base[:-len(suffix)].strip()
                        break
            # Chinese suffixes
            elif lang in ("zh-tw", "zh-cn"):
                for suffix in ["GX", "EX", " V", " VMAX", "◇"]:
                    if base.endswith(suffix):
                        base = base[:-len(suffix)].strip()
                        break

            if lang in pokemon_reverse and base in pokemon_reverse[lang]:
                en_name = pokemon_reverse[lang][base]
                source = "pokemon_names_suffix_strip"

        if en_name:
            updates.append((en_name, source, row_id))
            translated += 1
        else:
            still_untranslated += 1

    cur.executemany('UPDATE card_name_translations SET en_name = ?, source = ? WHERE id = ?', updates)
    conn.commit()

    print(f"Third pass results:")
    print(f"  Translated: {translated}")
    print(f"  Still untranslated: {still_untranslated}")

    # Coverage report
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

    # Remaining untranslated
    print("\n=== Remaining untranslated (sample) ===")
    cur.execute('''
        SELECT language_code, local_name, COUNT(*) as n
        FROM card_name_translations
        WHERE source = 'untranslated'
        GROUP BY language_code, local_name
        ORDER BY n DESC
        LIMIT 30
    ''')
    for lang, name, n in cur.fetchall():
        print(f"  {lang:5s} {n:>4}x  {name!r}")

    conn.close()
    return still_untranslated


if __name__ == "__main__":
    remaining = apply_third_pass()
    if remaining > 0:
        print(f"\n⚠️  {remaining} names still need translation")
    else:
        print(f"\n✅ All cards now have English names!")
