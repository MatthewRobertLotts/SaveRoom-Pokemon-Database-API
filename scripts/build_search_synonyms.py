#!/usr/bin/env python3
"""
Build the search synonyms/nicknames data layer.

Creates a `search_synonyms` table that maps:
- Pokémon name nicknames/abbreviations → canonical English name
- Set name abbreviations → canonical set name
- Common eBay search term aliases
- Misspelling corrections

Also builds a trigram index for fuzzy matching.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")

# Pokémon name nicknames and abbreviations commonly used in eBay titles
# Format: (synonym, canonical_english_name, source)
POKEMON_SYNONYMS = [
    # Charizard variants
    ("zard", "Charizard", "nickname"),
    ("charzard", "Charizard", "misspelling"),
    ("charzrd", "Charizard", "misspelling"),
    ("char", "Charizard", "abbreviation"),
    # Pikachu variants
    ("pika", "Pikachu", "nickname"),
    ("pikapika", "Pikachu", "nickname"),
    ("pikachu", "Pikachu", "canonical"),
    # Venusaur variants
    ("venu", "Venusaur", "abbreviation"),
    ("venasaur", "Venusaur", "misspelling"),
    ("venusaur", "Venusaur", "canonical"),
    # Blastoise variants
    ("blastoise", "Blastoise", "canonical"),
    ("blastoyse", "Blastoise", "misspelling"),
    # Mewtwo variants
    ("mewtwo", "Mewtwo", "canonical"),
    ("mew2", "Mewtwo", "abbreviation"),
    ("mew 2", "Mewtwo", "abbreviation"),
    # Mew variants
    ("mew", "Mew", "canonical"),
    # Eevee variants
    ("eevee", "Eevee", "canonical"),
    ("eev", "Eevee", "abbreviation"),
    # Umbreon variants
    ("umbreon", "Umbreon", "canonical"),
    ("umbre", "Umbreon", "abbreviation"),
    # Espeon variants
    ("espeon", "Espeon", "canonical"),
    ("espe", "Espeon", "abbreviation"),
    # Gengar variants
    ("gengar", "Gengar", "canonical"),
    ("geng", "Gengar", "abbreviation"),
    # Dragonite variants
    ("dragonite", "Dragonite", "canonical"),
    ("dragonite", "Dragonite", "canonical"),
    ("drgnite", "Dragonite", "misspelling"),
    # Rayquaza variants
    ("rayquaza", "Rayquaza", "canonical"),
    ("ray", "Rayquaza", "abbreviation"),
    # Lugia variants
    ("lugia", "Lugia", "canonical"),
    # Groudon variants
    ("groudon", "Groudon", "canonical"),
    ("groud", "Groudon", "abbreviation"),
    # Kyogre variants
    ("kyogre", "Kyogre", "canonical"),
    # Arceus variants
    ("arceus", "Arceus", "canonical"),
    ("arc", "Arceus", "abbreviation"),
    # Darkrai variants
    ("darkrai", "Darkrai", "canonical"),
    ("dark", "Darkrai", "abbreviation"),
    # Lucario variants
    ("lucario", "Lucario", "canonical"),
    ("luca", "Lucario", "abbreviation"),
    # Gardevoir variants
    ("gardevoir", "Gardevoir", "canonical"),
    ("gardy", "Gardevoir", "nickname"),
    # Garchomp variants
    ("garchomp", "Garchomp", "canonical"),
    ("garchom", "Garchomp", "misspelling"),
    # Metagross variants
    ("metagross", "Metagross", "canonical"),
    ("meta", "Metagross", "abbreviation"),
    # Blaziken variants
    ("blaziken", "Blaziken", "canonical"),
    ("blazi", "Blaziken", "abbreviation"),
    # Ho-Oh variants
    ("hooh", "Ho-Oh", "canonical"),
    ("ho oh", "Ho-Oh", "variant"),
    ("ho-oh", "Ho-Oh", "canonical"),
    # Celebi variants
    ("celebi", "Celebi", "canonical"),
    # Sylveon variants
    ("sylveon", "Sylveon", "canonical"),
    ("sylve", "Sylveon", "abbreviation"),
    # Greninja variants
    ("greninja", "Greninja", "canonical"),
    ("gren", "Greninja", "nickname"),
    # Decidueye variants
    ("decidueye", "Decidueye", "canonical"),
    # Incineroar variants
    ("incineroar", "Incineroar", "canonical"),
    ("incin", "Incineroar", "abbreviation"),
    # Mimikyu variants
    ("mimikyu", "Mimikyu", "canonical"),
    ("mimi", "Mimikyu", "abbreviation"),
    # Snorlax variants
    ("snorlax", "Snorlax", "canonical"),
    ("snor", "Snorlax", "abbreviation"),
    # Lapras variants
    ("lapras", "Lapras", "canonical"),
    # Zapdos variants
    ("zapdos", "Zapdos", "canonical"),
    ("zap", "Zapdos", "abbreviation"),
    # Moltres variants
    ("moltres", "Moltres", "canonical"),
    ("molty", "Moltres", "nickname"),
    # Articuno variants
    ("articuno", "Articuno", "canonical"),
    ("artic", "Articuno", "abbreviation"),
    # Ditto variants
    ("ditto", "Ditto", "canonical"),
    ("dito", "Ditto", "misspelling"),
    # Gyarados variants
    ("gyarados", "Gyarados", "canonical"),
    ("gyara", "Gyarados", "abbreviation"),
    # Alakazam variants
    ("alakazam", "Alakazam", "canonical"),
    ("alaka", "Alakazam", "abbreviation"),
    # Machamp variants
    ("machamp", "Machamp", "canonical"),
    ("macha", "Machamp", "abbreviation"),
    # Golem variants
    ("golem", "Golem", "canonical"),
    # Onix variants
    ("onix", "Onix", "canonical"),
    # Scyther variants
    ("scyther", "Scyther", "canonical"),
    ("scyth", "Scyther", "misspelling"),
    # Pidgeot variants
    ("pidgeot", "Pidgeot", "canonical"),
    # Raichu variants
    ("raichu", "Raichu", "canonical"),
    # Vaporeon variants
    ("vaporeon", "Vaporeon", "canonical"),
    ("vapor", "Vaporeon", "abbreviation"),
    # Jolteon variants
    ("jolteon", "Jolteon", "canonical"),
    ("jolt", "Jolteon", "abbreviation"),
    # Flareon variants
    ("flareon", "Flareon", "canonical"),
    ("flare", "Flareon", "abbreviation"),
    # Leafeon variants
    ("leafeon", "Leafeon", "canonical"),
    ("leaf", "Leafeon", "abbreviation"),
    # Glaceon variants
    ("glaceon", "Glaceon", "canonical"),
    ("glace", "Glaceon", "abbreviation"),
    # Zacian variants
    ("zacian", "Zacian", "canonical"),
    # Zamazenta variants
    ("zamazenta", "Zamazenta", "canonical"),
    # Eternatus variants
    ("eternatus", "Eternatus", "canonical"),
    ("eterna", "Eternatus", "abbreviation"),
]

# Set name abbreviations commonly used by eBay sellers
# Format: (abbreviation, canonical_set_name, source)
SET_SYNONYMS = [
    # Scarlet & Violet era
    ("sv1", "Scarlet & Violet", "abbreviation"),
    ("sv2", "Paldea Evolved", "abbreviation"),
    ("sv3", "Obsidian Flames", "abbreviation"),
    ("sv3.5", "151", "abbreviation"),
    ("sv4", "Paradox Rift", "abbreviation"),
    ("sv5", "Temporal Forces", "abbreviation"),
    ("sv6", "Twilight Masquerade", "abbreviation"),
    ("sv7", "Stellar Crown", "abbreviation"),
    ("sv8", "Surging Sparks", "abbreviation"),
    ("sv9", "Journey Together", "abbreviation"),
    ("sv10", "Destined Rivals", "abbreviation"),
    ("sv11", "Prismatic Evolutions", "abbreviation"),
    ("sv12", "Shrouded Fable", "abbreviation"),
    # Sun & Moon era
    ("sm1", "Sun & Moon", "abbreviation"),
    ("sm2", "Guardians Rising", "abbreviation"),
    ("sm3", "Burning Shadows", "abbreviation"),
    ("sm4", "Crimson Invasion", "abbreviation"),
    ("sm5", "Ultra Prism", "abbreviation"),
    ("sm6", "Forbidden Light", "abbreviation"),
    ("sm7", "Celestial Storm", "abbreviation"),
    ("sm8", "Lost Thunder", "abbreviation"),
    ("sm9", "Team Up", "abbreviation"),
    ("sm10", "Unbroken Bonds", "abbreviation"),
    ("sm11", "Unified Minds", "abbreviation"),
    ("sm12", "Cosmic Eclipse", "abbreviation"),
    # Sword & Shield era
    ("swsh1", "Sword & Shield", "abbreviation"),
    ("swsh2", "Rebel Clash", "abbreviation"),
    ("swsh3", "Darkness Ablaze", "abbreviation"),
    ("swsh4", "Vivid Voltage", "abbreviation"),
    ("swsh5", "Battle Styles", "abbreviation"),
    ("swsh6", "Chilling Reign", "abbreviation"),
    ("swsh7", "Evolving Skies", "abbreviation"),
    ("swsh8", "Fusion Strike", "abbreviation"),
    ("swsh9", "Brilliant Stars", "abbreviation"),
    ("swsh10", "Astral Radiance", "abbreviation"),
    ("swsh11", "Lost Origin", "abbreviation"),
    ("swsh12", "Paldea Evolved", "abbreviation"),
    # XY era
    ("xy1", "XY", "abbreviation"),
    ("xy2", "Flashfire", "abbreviation"),
    ("xy3", "Furious Fists", "abbreviation"),
    ("xy4", "Phantom Forces", "abbreviation"),
    ("xy5", "Primal Clash", "abbreviation"),
    ("xy6", "Roaring Skies", "abbreviation"),
    ("xy7", "Ancient Origins", "abbreviation"),
    ("xy8", "Breakpoint", "abbreviation"),
    ("xy9", "Fates Collide", "abbreviation"),
    ("xy10", "Steam Siege", "abbreviation"),
    ("xy11", "Evolutions", "abbreviation"),
    # Common set nicknames
    ("151", "151", "canonical"),
    ("obsidian", "Obsidian Flames", "nickname"),
    ("paradox", "Paradox Rift", "nickname"),
    ("temporal", "Temporal Forces", "nickname"),
    ("twilight", "Twilight Masquerade", "nickname"),
    ("stellar", "Stellar Crown", "nickname"),
    ("surging", "Surging Sparks", "nickname"),
    ("journey", "Journey Together", "nickname"),
    ("destined", "Destined Rivals", "nickname"),
    ("prismatic", "Prismatic Evolutions", "nickname"),
    ("shrouded", "Shrouded Fable", "nickname"),
    ("evolving", "Evolving Skies", "nickname"),
    ("brilliant", "Brilliant Stars", "nickname"),
    ("astral", "Astral Radiance", "nickname"),
    ("lost origin", "Lost Origin", "nickname"),
    ("fusion", "Fusion Strike", "nickname"),
    ("chilling", "Chilling Reign", "nickname"),
    ("battle styles", "Battle Styles", "nickname"),
    ("vivid", "Vivid Voltage", "nickname"),
    ("darkness", "Darkness Ablaze", "nickname"),
    ("rebel", "Rebel Clash", "nickname"),
    ("team up", "Team Up", "nickname"),
    ("unbroken", "Unbroken Bonds", "nickname"),
    ("unified", "Unified Minds", "nickname"),
    ("cosmic", "Cosmic Eclipse", "nickname"),
    ("lost thunder", "Lost Thunder", "nickname"),
    ("celestial", "Celestial Storm", "nickname"),
    ("forbidden", "Forbidden Light", "nickname"),
    ("ultra prism", "Ultra Prism", "nickname"),
    ("crimson", "Crimson Invasion", "nickname"),
    ("burning", "Burning Shadows", "nickname"),
    ("guardians", "Guardians Rising", "nickname"),
]

# Common eBay search term aliases
# Format: (synonym, canonical_term, source)
EBAY_SYNONYMS = [
    # Card type abbreviations
    ("ex", "ex", "canonical"),
    ("gx", "GX", "canonical"),
    ("v", "V", "canonical"),
    ("vmax", "VMAX", "canonical"),
    ("vstar", "VSTAR", "canonical"),
    ("ex", "EX", "canonical"),
    # Rarity terms
    ("holo", "Holo", "canonical"),
    ("holographic", "Holo", "synonym"),
    ("holofoil", "Holo", "synonym"),
    ("foil", "Holo", "synonym"),
    ("non-holo", "Non-holo", "canonical"),
    ("non holo", "Non-holo", "canonical"),
    ("reverse holo", "Reverse Holo", "canonical"),
    ("rh", "Reverse Holo", "abbreviation"),
    ("rholo", "Reverse Holo", "abbreviation"),
    ("full art", "Full Art", "canonical"),
    ("fa", "Full Art", "abbreviation"),
    ("alt art", "Alternate Art", "canonical"),
    ("aa", "Alternate Art", "abbreviation"),
    ("secret rare", "Secret Rare", "canonical"),
    ("sr", "Secret Rare", "abbreviation"),
    ("ur", "Ultra Rare", "abbreviation"),
    ("ultra rare", "Ultra Rare", "canonical"),
    ("ir", "Illustration Rare", "abbreviation"),
    ("illustration rare", "Illustration Rare", "canonical"),
    ("sir", "Special Illustration Rare", "abbreviation"),
    ("special illustration rare", "Special Illustration Rare", "canonical"),
    # Card condition
    ("mint", "Mint", "canonical"),
    ("nm", "Near Mint", "abbreviation"),
    ("near mint", "Near Mint", "canonical"),
    ("lp", "Lightly Played", "abbreviation"),
    ("lightly played", "Lightly Played", "canonical"),
    ("mp", "Moderately Played", "abbreviation"),
    ("moderately played", "Moderately Played", "canonical"),
    ("hp", "Heavily Played", "abbreviation"),
    ("heavily played", "Heavily Played", "canonical"),
    ("damaged", "Damaged", "canonical"),
    # Product type
    ("tcg", "TCG", "canonical"),
    ("pokemon tcg", "Pokemon TCG", "canonical"),
    ("pokémon", "Pokemon", "synonym"),
    ("pokmon", "Pokemon", "misspelling"),
    ("pokeman", "Pokemon", "misspelling"),
    ("pokamom", "Pokemon", "misspelling"),
]


def build_synonyms_table(conn: sqlite3.Connection) -> int:
    """Create and populate the search_synonyms table. Returns count of entries."""
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS search_synonyms')
    cur.execute('''
        CREATE TABLE search_synonyms (
            id INTEGER PRIMARY KEY,
            synonym TEXT NOT NULL,
            canonical TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            source TEXT NOT NULL,
            UNIQUE(synonym, entity_type)
        )
    ''')
    cur.execute('CREATE INDEX idx_synonyms_synonym ON search_synonyms(synonym)')
    cur.execute('CREATE INDEX idx_synonyms_canonical ON search_synonyms(canonical)')
    cur.execute('CREATE INDEX idx_synonyms_type ON search_synonyms(entity_type)')

    entries = []
    for syn, canon, src in POKEMON_SYNONYMS:
        entries.append((syn.lower().strip(), canon, "pokemon", src))
    for syn, canon, src in SET_SYNONYMS:
        entries.append((syn.lower().strip(), canon, "set", src))
    for syn, canon, src in EBAY_SYNONYMS:
        entries.append((syn.lower().strip(), canon, "ebay_term", src))

    # Deduplicate
    seen = set()
    unique = []
    for syn, canon, etype, src in entries:
        key = (syn, etype)
        if key not in seen:
            seen.add(key)
            unique.append((syn, canon, etype, src))

    cur.executemany(
        'INSERT OR IGNORE INTO search_synonyms(synonym, canonical, entity_type, source) VALUES (?, ?, ?, ?)',
        unique
    )
    conn.commit()
    return len(unique)


def build_trigram_index(conn: sqlite3.Connection) -> int:
    """Build a trigram table for fuzzy matching of Pokémon names."""
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

    # Get all card names and English names
    cur.execute('''
        SELECT DISTINCT
            s.card_id,
            s.language_code,
            s.card_name,
            COALESCE(t.en_name, '') as en_name
        FROM v2_card_search s
        LEFT JOIN card_name_translations t
            ON t.card_id = s.card_id
            AND t.language_code = s.language_code
            AND t.source != 'untranslated'
        WHERE s.card_name != ''
    ''')

    entries = []
    for row in cur.fetchall():
        card_id, lang, name, en_name = row
        for field, text in [('card_name', name), ('name_english', en_name)]:
            if text:
                text_lower = text.lower()
                # Generate trigrams
                for i in range(len(text_lower) - 2):
                    tri = text_lower[i:i+3]
                    if tri.strip():
                        entries.append((tri, card_id, lang, field))

    # Batch insert
    cur.executemany(
        'INSERT OR IGNORE INTO search_trigrams(trigram, card_id, language_code, field) VALUES (?, ?, ?, ?)',
        entries
    )
    conn.commit()
    return len(entries)


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Building synonyms table...")
    syn_count = build_synonyms_table(conn)
    print(f"  {syn_count:,} synonym entries")

    print("Building trigram index...")
    tri_count = build_trigram_index(conn)
    print(f"  {tri_count:,} trigram entries")

    # Verify
    cur = conn.cursor()
    cur.execute("SELECT entity_type, COUNT(*) FROM search_synonyms GROUP BY entity_type")
    print("\nSynonym breakdown:")
    for etype, count in cur.fetchall():
        print(f"  {etype:15s}: {count:,}")

    cur.execute("SELECT COUNT(DISTINCT card_id) FROM search_trigrams")
    print(f"\nCards with trigrams: {cur.fetchone()[0]:,}")

    # Sample lookups
    print("\nSample synonym lookups:")
    for test in ["zard", "pika", "gren", "obsidian", "holo", "nm"]:
        cur.execute("SELECT canonical, entity_type FROM search_synonyms WHERE synonym=? LIMIT 3", (test,))
        rows = cur.fetchall()
        if rows:
            print(f"  '{test}' → {', '.join(f'{c} ({t})' for c,t in rows)}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
