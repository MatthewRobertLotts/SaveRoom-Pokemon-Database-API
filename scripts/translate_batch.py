#!/usr/bin/env python3
"""
Translate remaining card names using Google Translate.
Processes in small batches with error handling and rate limit awareness.
"""
from __future__ import annotations

import sqlite3
import time
import sys
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")

LANG_MAP = {
    "zh-tw": "zh-TW",
    "zh-cn": "zh-CN",
    "ja": "ja",
    "ko": "ko",
    "th": "th",
}

def translate_names(names: list[str], lang: str) -> tuple[dict[str, str], list[str]]:
    """Translate a list of names, returning ({original: translated}, [failed_names])."""
    import translators as ts
    results: dict[str, str] = {}
    failed: list[str] = []
    tl = LANG_MAP.get(lang, lang)

    for i, name in enumerate(names):
        translated = False
        for attempt in range(3):
            try:
                result = ts.translate_text(
                    name,
                    translator="google",
                    from_language=tl,
                    to_language="en",
                )
                if result and isinstance(result, str) and result.strip():
                    results[name] = result.strip()
                    translated = True
                break  # Success (or empty) — exit retry loop
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    print(f"  [{lang}] SKIP after 3 failures: {name!r}: {e}", flush=True)
                    failed.append(name)

        if (i + 1) % 25 == 0:
            print(f"  [{lang}] {i+1}/{len(names)} done, {len(results)} ok, {len(failed)} skipped", flush=True)
        time.sleep(0.25)

    return results, failed


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get remaining untranslated names grouped by language
    cur.execute('''
        SELECT DISTINCT local_name, language_code, COUNT(*) as n
        FROM card_name_translations
        WHERE source = 'untranslated'
        GROUP BY local_name, language_code
        ORDER BY language_code, n DESC
    ''')
    rows = cur.fetchall()

    # Group by language
    by_lang: dict[str, list[tuple[str, int]]] = {}
    for name, lang, n in rows:
        by_lang.setdefault(lang, []).append((name, n))

    total_translated = 0
    total_failed = 0
    all_skipped: list[tuple[str, str]] = []

    for lang in sorted(by_lang.keys()):
        names_list = by_lang[lang]
        print(f"\n=== {lang}: {len(names_list)} names ===", flush=True)

        # Process in batches of 50
        batch_size = 50
        for batch_start in range(0, len(names_list), batch_size):
            batch = names_list[batch_start:batch_start + batch_size]
            names_only = [n[0] for n in batch]

            translations, failed = translate_names(names_only, lang)
            all_skipped.extend((name, lang) for name in failed)

            updates = []
            for name, count in batch:
                if name in translations:
                    en = translations[name]
                    en = en.replace(" Pokémon card", "").replace(" pokemon card", "").strip()
                    updates.append((en, "google_translate", name, lang))
                    total_translated += 1
                else:
                    total_failed += 1

            if updates:
                cur.executemany('''
                    UPDATE card_name_translations
                    SET en_name = ?, source = ?
                    WHERE local_name = ? AND language_code = ? AND source = 'untranslated'
                ''', updates)
                conn.commit()
                print(f"  Committed {len(updates)} updates ({len(failed)} skipped)", flush=True)

    # Log skipped names
    skipped_path = Path("/media/matt/Storage/Brain/Pokemon Card Database/references/skipped_translations.csv")
    if all_skipped:
        with open(skipped_path, "w", encoding="utf-8") as f:
            f.write("local_name,language_code\n")
            for name, lang in all_skipped:
                f.write(f"{name},{lang}\n")
        print(f"\nLogged {len(all_skipped)} skipped names to {skipped_path}")

    print(f"\n=== Done ===")
    print(f"Translated: {total_translated}")
    print(f"Failed: {total_failed}")

    # Final coverage
    cur.execute('''
        SELECT language_code, COUNT(*) as total,
               SUM(CASE WHEN source != 'untranslated' THEN 1 ELSE 0 END) as translated
        FROM card_name_translations GROUP BY language_code ORDER BY COUNT(*) DESC
    ''')
    print("\nCoverage:")
    for lang, total, trans in cur.fetchall():
        pct = 100.0 * trans / total if total else 0
        print(f"  {lang}: {trans:,} / {total:,} ({pct:.1f}%)")

    cur.execute("SELECT COUNT(*) FROM card_name_translations WHERE source = 'untranslated'")
    print(f"\nRemaining untranslated: {cur.fetchone()[0]:,}")
    conn.close()


if __name__ == "__main__":
    main()
