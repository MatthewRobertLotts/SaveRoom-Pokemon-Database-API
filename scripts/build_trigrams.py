#!/usr/bin/env python3
"""Build trigram index for fuzzy matching — optimized version."""
from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")

def build_trigrams():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS search_trigrams')
    cur.execute('''
        CREATE TABLE search_trigrams (
            trigram TEXT NOT NULL,
            card_id TEXT NOT NULL,
            language_code TEXT NOT NULL,
            field TEXT NOT NULL,
            PRIMARY KEY (trigram, card_id, language_code, field)
        ) WITHOUT ROWID
    ''')
    cur.execute('CREATE INDEX idx_trigrams_lookup ON search_trigrams(trigram)')

    # Only index distinct names (not every card row) — much faster
    cur.execute('''
        SELECT DISTINCT
            COALESCE(t.en_name, s.card_name) as name,
            s.card_id,
            s.language_code
        FROM v2_card_search s
        LEFT JOIN card_name_translations t
            ON t.card_id = s.card_id
            AND t.language_code = s.language_code
            AND t.source != 'untranslated'
        WHERE COALESCE(t.en_name, s.card_name) != ''
    ''')

    entries = []
    for row in cur.fetchall():
        name, card_id, lang = row
        text = name.lower()
        # Generate trigrams for names longer than 3 chars
        if len(text) >= 3:
            for i in range(len(text) - 2):
                tri = text[i:i+3]
                if tri.isalnum():
                    entries.append((tri, card_id, lang, 'name'))

    # Batch insert in chunks
    chunk_size = 50000
    for i in range(0, len(entries), chunk_size):
        chunk = entries[i:i+chunk_size]
        cur.executemany(
            'INSERT OR IGNORE INTO search_trigrams(trigram, card_id, language_code, field) VALUES (?, ?, ?, ?)',
            chunk
        )
        conn.commit()
        print(f'  Inserted {min(i+chunk_size, len(entries)):,} / {len(entries):,}')

    cur.execute('SELECT COUNT(*) FROM search_trigrams')
    total = cur.fetchone()[0]
    cur.execute('SELECT COUNT(DISTINCT card_id) FROM search_trigrams')
    cards = cur.fetchone()[0]
    print(f'\nTotal trigrams: {total:,}')
    print(f'Cards with trigrams: {cards:,}')

    conn.close()

if __name__ == "__main__":
    build_trigrams()
