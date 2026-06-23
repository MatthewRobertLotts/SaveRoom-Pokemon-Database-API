#!/usr/bin/env python3
"""
Translate remaining un-EN card names to English.

Uses multiple strategies in order:
1. Existing dictionary lookup (already done in previous passes)
2. Batch translation using the `translators` library (Google Translate)
3. Mark any failures for manual review

Usage:
    python scripts/translate_remaining.py [--dry-run] [--lang zh-tw]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")

# Translators library uses different language codes
TRANSLATOR_LANG_MAP = {
    "zh-tw": "zh-TW",
    "zh-cn": "zh-CN",
    "ja": "ja",
    "ko": "ko",
    "th": "th",
    "id": "id",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "it": "it",
    "pt": "pt",
    "ru": "ru",
    "pl": "pl",
    "nl": "nl",
}


def translate_batch(names: list[str], lang: str, delay: float = 0.5) -> dict[str, str]:
    """Translate a batch of names using Google Translate."""
    try:
        import translators as ts
    except ImportError:
        print("ERROR: translators library not installed. Run: pip install translators")
        return {}

    results = {}
    translator_lang = TRANSLATOR_LANG_MAP.get(lang, lang)

    for name in names:
        for attempt in range(3):
            try:
                translated = ts.translate_text(
                    name,
                    translator="google",
                    from_language=translator_lang,
                    to_language="en",
                )
                if translated and isinstance(translated, str) and translated.strip():
                    results[name] = translated.strip()
                else:
                    print(f"  Warning: Empty translation for {name!r}")
                break  # Success, exit retry loop
            except Exception as e:
                print(f"  Warning: Failed to translate {name!r} (attempt {attempt+1}/3): {e}")
                time.sleep(2 * (attempt + 1))  # Exponential backoff
        time.sleep(delay)

    return results


def main():
    parser = argparse.ArgumentParser(description="Translate remaining card names to English")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be translated without writing")
    parser.add_argument("--lang", help="Only translate specific language code")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for translation")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls (seconds)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get remaining untranslated names
    if args.lang:
        cur.execute('''
            SELECT DISTINCT local_name, language_code, COUNT(*) as n
            FROM card_name_translations
            WHERE source = 'untranslated' AND language_code = ?
            GROUP BY local_name, language_code
            ORDER BY n DESC
        ''', (args.lang,))
    else:
        cur.execute('''
            SELECT DISTINCT local_name, language_code, COUNT(*) as n
            FROM card_name_translations
            WHERE source = 'untranslated'
            GROUP BY local_name, language_code
            ORDER BY n DESC
        ''')

    rows = cur.fetchall()
    total_unique = len(rows)
    total_cards = sum(r[2] for r in rows)

    print(f"Remaining to translate: {total_unique} unique names ({total_cards} total cards)")

    if total_unique == 0:
        print("✅ All cards already have English names!")
        conn.close()
        return

    # Group by language
    by_lang: dict[str, list[tuple[str, int]]] = {}
    for local_name, lang, n in rows:
        if lang not in by_lang:
            by_lang[lang] = []
        by_lang[lang].append((local_name, n))

    print("\nBy language:")
    for lang, names in sorted(by_lang.items()):
        print(f"  {lang}: {len(names)} unique names")

    if args.dry_run:
        print("\n[DRY RUN] Would translate:")
        for lang, names in sorted(by_lang.items()):
            print(f"\n  {lang}:")
            for name, n in names[:10]:
                print(f"    {n:>4}x  {name!r}")
            if len(names) > 10:
                print(f"    ... and {len(names) - 10} more")
        conn.close()
        return

    # Translate by language
    total_translated = 0
    total_failed = 0

    for lang, names in sorted(by_lang.items()):
        print(f"\n=== Translating {lang} ({len(names)} names) ===")

        names_only = [n[0] for n in names]
        translations = translate_batch(names_only, lang, delay=args.delay)

        updates = []
        for local_name, count in names:
            if local_name in translations:
                en_name = translations[local_name]
                # Clean up: remove "Pokémon card" suffix that Google often adds
                en_name = en_name.replace(" Pokémon card", "").replace(" pokemon card", "").strip()
                updates.append((en_name, "google_translate", local_name, lang))
                total_translated += 1
            else:
                total_failed += 1

        if updates:
            # Update by (local_name, language_code) since card_name_translations
            # has unique constraint on (card_id, language_code) but we need to update
            # all rows with the same name+lang
            cur.executemany('''
                UPDATE card_name_translations 
                SET en_name = ?, source = ?
                WHERE local_name = ? AND language_code = ? AND source = 'untranslated'
            ''', updates)
            conn.commit()
            print(f"  Updated {len(updates)} names")

    # Final report
    print(f"\n=== Translation complete ===")
    print(f"  Translated: {total_translated}")
    print(f"  Failed: {total_failed}")

    # Coverage
    cur.execute('''
        SELECT language_code, 
               COUNT(*) as total,
               SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) as translated,
               ROUND(100.0 * SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
        FROM card_name_translations
        GROUP BY language_code
        ORDER BY COUNT(*) DESC
    ''')
    print("\n=== Coverage by language ===")
    for lang, total, trans, pct in cur.fetchall():
        print(f"  {lang:10s}: {trans:>6,} / {total:>6,} ({pct}%)")

    # Remaining
    cur.execute("SELECT COUNT(*) FROM card_name_translations WHERE source = 'untranslated'")
    remaining = cur.fetchone()[0]
    if remaining > 0:
        print(f"\n⚠️  {remaining} names still untranslated")
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
    else:
        print(f"\n✅ All non-English cards now have English names!")

    conn.close()


if __name__ == "__main__":
    main()
