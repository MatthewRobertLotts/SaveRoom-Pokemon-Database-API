#!/usr/bin/env python3
"""Rebuild the FTS index to include name_english column for cross-language search."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pokemon_db_v2_search_api import setup_fts, FTS_TABLE

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")

print(f"Rebuilding FTS index: {FTS_TABLE}")
print(f"Database: {DB_PATH}")

try:
    setup_fts(DB_PATH)
    print("FTS index rebuilt successfully.")

    # Verify
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {FTS_TABLE}")
    count = cur.fetchone()[0]
    print(f"FTS rows: {count:,}")

    # Check name_english column has data
    cur.execute(f"SELECT COUNT(*) FROM {FTS_TABLE} WHERE name_english != ''")
    en_count = cur.fetchone()[0]
    print(f"Rows with name_english: {en_count:,}")

    # Sample cross-language matches
    cur.execute(f"SELECT card_name, name_english, language_code FROM {FTS_TABLE} WHERE name_english LIKE '%Charizard%' LIMIT 5")
    rows = cur.fetchall()
    if rows:
        print("\nSample cross-language matches for 'Charizard':")
        for name, en_name, lang in rows:
            print(f"  {lang}: {name} → {en_name}")
    conn.close()
except Exception as e:
    print(f"ERROR: {e}")
    raise
