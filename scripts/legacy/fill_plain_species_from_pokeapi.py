#!/usr/bin/env python3
"""Replace unresolved fallback rows that are plain Pokémon species names.

This is a conservative pass: only rows whose fallback name is a direct Pokémon
species name, optionally with a simple " ex" suffix, are updated. The localized
species name comes from PokeAPI's species endpoint; trainer/item cards, regional
forms, Mega forms, masks, and other ambiguous names are left unresolved.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
USER_AGENT = 'SaveRoom-PokeAPISpeciesLocalization/1.0'
LANG_MAP = {'de': 'de', 'es': 'es', 'it': 'it', 'ja': 'ja-Hrkt', 'ko': 'ko'}

SPECIAL_SLUGS = {
    'Mr. Mime': 'mr-mime', 'Mr. Rime': 'mr-rime', "Farfetch'd": 'farfetchd', "Sirfetch'd": 'sirfetchd',
    'Mime Jr.': 'mime-jr', 'Type: Null': 'type-null', 'Ho-Oh': 'ho-oh', 'Porygon-Z': 'porygon-z',
    'Jangmo-o': 'jangmo-o', 'Hakamo-o': 'hakamo-o', 'Kommo-o': 'kommo-o', 'Nidoran♀': 'nidoran-f', 'Nidoran♂': 'nidoran-m',
    'Flabébé': 'flabebe', 'Wo-Chien': 'wo-chien', 'Chien-Pao': 'chien-pao', 'Ting-Lu': 'ting-lu', 'Chi-Yu': 'chi-yu',
}


def slugify(name: str) -> str:
    if name in SPECIAL_SLUGS:
        return SPECIAL_SLUGS[name]
    n = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    n = n.lower().replace('.', '').replace("'", '').replace(':', '')
    n = re.sub(r'[^a-z0-9]+', '-', n).strip('-')
    return n


def parse_plain_species(card_name: str) -> tuple[str, bool] | None:
    # Deliberately skip ambiguous compound/card-title patterns.
    if any(token in card_name for token in ['Mega ', 'Alolan ', 'Galarian ', 'Paldean ', 'Hisuian ', ' Mask ', 'Fossil', 'Potion', 'Energy', 'Search', 'Ball', 'Cape', 'Poncho', 'Candy', 'Hammer', 'Ticket', 'Lithograph']):
        return None
    has_ex = False
    base = card_name
    if base.endswith(' ex'):
        has_ex = True
        base = base[:-3]
    # Skip trainer names and likely non-species phrases.
    if len(base.split()) > 2 and base not in SPECIAL_SLUGS:
        return None
    return base, has_ex


def fetch_species(base: str) -> dict[str, str] | None:
    slug = slugify(base)
    url = f'https://pokeapi.co/api/v2/pokemon-species/{slug}/'
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None
    names = {}
    for item in data.get('names') or []:
        code = (item.get('language') or {}).get('name')
        if code:
            names[code] = item.get('name')
    return names


def format_name(localized: str, lang: str, has_ex: bool) -> str:
    if not has_ex:
        return localized
    if lang in {'de', 'it'}:
        return f'{localized}-ex'
    return f'{localized} ex'


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT p.language_code, p.set_id, p.card_id, c.name AS old_name
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        WHERE p.method='cross_language_template'
          AND p.language_code IN ('de','es','it','ja','ko')
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
    """).fetchall()

    candidates: dict[str, tuple[str, bool]] = {}
    row_candidates = []
    for r in rows:
        parsed = parse_plain_species(r['old_name'])
        if not parsed:
            continue
        base, has_ex = parsed
        candidates[base] = parsed
        row_candidates.append((r, base, has_ex))
    print('rows', len(rows), 'row_candidates', len(row_candidates), 'unique species candidates', len(candidates))

    species_data: dict[str, dict[str, str] | None] = {}
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_species, base): base for base in candidates}
        for fut in cf.as_completed(futs):
            base = futs[fut]
            species_data[base] = fut.result()

    updated = 0
    skipped_no_species = 0
    skipped_no_lang = 0
    examples = []
    for r, base, has_ex in row_candidates:
        names = species_data.get(base)
        if not names:
            skipped_no_species += 1
            continue
        lang = r['language_code']
        poke_lang = LANG_MAP[lang]
        localized = names.get(poke_lang)
        if not localized:
            skipped_no_lang += 1
            continue
        new_name = format_name(localized, lang, has_ex)
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?', (new_name, lang, r['card_id']))
        source_url = f'https://pokeapi.co/api/v2/pokemon-species/{slugify(base)}/'
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            lang, r['set_id'], r['card_id'], source_url, 'pokeapi_species_localized_name',
            f'Conservative species-name localization from PokeAPI for plain Pokémon card fallback {r["old_name"]!r}; suffix/prefix limited to simple ex only.',
            FETCHED_AT,
        ))
        updated += 1
        if len(examples) < 40:
            examples.append({'language_code': lang, 'card_id': r['card_id'], 'old': r['old_name'], 'new': new_name, 'source': source_url})
    conn.commit()

    remaining_by_lang = list(conn.execute("""
        SELECT p.language_code, COUNT(*)
        FROM card_source_provenance p
        WHERE p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        GROUP BY p.language_code ORDER BY COUNT(*) DESC
    """).fetchall())
    report = {
        'fetched_at': FETCHED_AT,
        'input_rows': len(rows),
        'candidate_rows': len(row_candidates),
        'unique_species_candidates': len(candidates),
        'updated': updated,
        'skipped_no_species': skipped_no_species,
        'skipped_no_language_name': skipped_no_lang,
        'examples': examples,
        'remaining_total': sum(r[1] for r in remaining_by_lang),
        'remaining_by_language': [list(r) for r in remaining_by_lang],
    }
    out = REPORT_DIR / 'pokeapi_species_fallback_completion.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:10000])
    print('Report:', out)
    conn.close()

if __name__ == '__main__':
    main()
