#!/usr/bin/env python3
"""Propagate Portuguese Pocket names from source-backed base cards to variant rows.

Secret/alternate Pocket rows often have the exact same printed card name as a
base card in the same set. After importing source-backed main-set rows from
pokemonpocketbr.com, use the recorded old fallback name in provenance notes to
map fallback English/reference names to the source-backed Portuguese name.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
SOURCE_METHODS = ('pokemonpocketbr_card_page','tcgdex_pocket_rest')


def old_from_note(note: str | None) -> str | None:
    if not note:
        return None
    m = re.search(r"old fallback='([^']*)'", note)
    if m:
        return m.group(1)
    m = re.search(r"old='([^']*)'", note)
    if m:
        return m.group(1)
    return None


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    mapping: dict[tuple[str, str], dict[str, str]] = {}
    source_rows = conn.execute(f"""
        SELECT p.set_id, p.card_id, c.name AS pt_name, p.source_url, p.method, p.note
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.language_code='pt' AND s.series_name LIKE '%Pocket%'
          AND p.method IN ({','.join('?' for _ in SOURCE_METHODS)})
    """, SOURCE_METHODS).fetchall()
    for r in source_rows:
        old = old_from_note(r['note'])
        if old:
            key = (r['set_id'], old)
            # Keep first; if multiple variants map to same official name anyway.
            mapping.setdefault(key, {'pt_name': r['pt_name'], 'source_url': r['source_url'], 'source_card_id': r['card_id'], 'source_method': r['method']})
    print('mapping entries', len(mapping))

    unresolved = conn.execute("""
        SELECT p.language_code, p.set_id, p.card_id, c.name AS old_name
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.language_code='pt' AND s.series_name LIKE '%Pocket%'
          AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        ORDER BY p.set_id, c.local_id_sort
    """).fetchall()
    updated = 0
    no_map = []
    examples = []
    for r in unresolved:
        hit = mapping.get((r['set_id'], r['old_name']))
        if not hit:
            no_map.append(dict(r))
            continue
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?', (hit['pt_name'], 'pt', r['card_id']))
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            'pt', r['set_id'], r['card_id'], hit['source_url'], 'pokemonpocketbr_variant_name_propagation',
            f'Portuguese Pocket variant row name propagated from source-backed card {hit["source_card_id"]} ({hit["source_method"]}) because both rows share fallback/reference name {r["old_name"]!r}; official card-name text is identical across variants.',
            FETCHED_AT,
        ))
        updated += 1
        if len(examples) < 40:
            examples.append({'card_id': r['card_id'], 'old': r['old_name'], 'new': hit['pt_name'], 'source_card_id': hit['source_card_id'], 'source_url': hit['source_url']})
    conn.commit()
    remaining_pt_pocket = conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.language_code='pt' AND s.series_name LIKE '%Pocket%' AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
    """).fetchone()[0]
    remaining_pt_total = conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p
        WHERE p.language_code='pt' AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
    """).fetchone()[0]
    report = {'fetched_at': FETCHED_AT, 'source_rows': len(source_rows), 'mapping_entries': len(mapping), 'unresolved_input': len(unresolved), 'updated': updated, 'remaining_pt_pocket': remaining_pt_pocket, 'remaining_pt_total': remaining_pt_total, 'examples': examples, 'no_map_examples': no_map[:80]}
    out = REPORT_DIR / 'pt_pocket_variant_name_propagation.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:12000])
    print('Report:', out)
    conn.close()

if __name__ == '__main__':
    main()
