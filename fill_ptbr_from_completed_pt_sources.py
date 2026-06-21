#!/usr/bin/env python3
"""Complete pt-br fallback rows from completed Portuguese/Brazilian sources.

The DB's `pt` Pocket rows were completed from Brazilian Portuguese sources
(pokemonpocketbr.com, GetMyDex, TCGdex pt-br). The unresolved `pt-br` rows are
for the same Pocket set/card ids (B1a, B2, A4a), so copy the source-backed names
and source URLs from the completed `pt` rows into `pt-br` with explicit provenance.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
VALID_PT_METHODS = {
    'pokemonpocketbr_card_page',
    'pokemonpocketbr_variant_name_propagation',
    'pokemonpocketbr_related_card_page',
    'pokemonpocketbr_species_name_reference',
    'getmydex_pt_card_page',
    'tcgdex_pocket_rest',
}


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT p.language_code, p.set_id, p.card_id, c.name AS old_name
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.language_code='pt-br'
          AND s.series_name LIKE '%Pocket%'
          AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        ORDER BY p.set_id, c.local_id_sort, p.card_id
    """).fetchall()
    print('pt-br unresolved pocket rows', len(rows))
    updated = 0
    misses = []
    examples = []
    method_counts: dict[str, int] = {}
    for r in rows:
        source = conn.execute(f"""
            SELECT c.name, p.source_url, p.method, p.note, p.fetched_at
            FROM cards c
            JOIN card_source_provenance p ON p.language_code=c.language_code AND p.card_id=c.card_id
            WHERE c.language_code='pt' AND c.card_id=?
              AND p.method IN ({','.join('?' for _ in VALID_PT_METHODS)})
            ORDER BY CASE p.method
                WHEN 'pokemonpocketbr_card_page' THEN 1
                WHEN 'pokemonpocketbr_related_card_page' THEN 2
                WHEN 'pokemonpocketbr_species_name_reference' THEN 3
                WHEN 'getmydex_pt_card_page' THEN 4
                WHEN 'tcgdex_pocket_rest' THEN 5
                WHEN 'pokemonpocketbr_variant_name_propagation' THEN 6
                ELSE 9 END
            LIMIT 1
        """, (r['card_id'], *VALID_PT_METHODS)).fetchone()
        if not source:
            misses.append(dict(r))
            continue
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?', (source['name'], 'pt-br', r['card_id']))
        method = 'ptbr_from_brazilian_portuguese_source'
        note = (
            f'pt-br row completed from source-backed pt row for the same Pocket card id; '
            f'underlying source method={source["method"]}; old fallback={r["old_name"]!r}. '
            'The pt row was sourced from Brazilian Portuguese Pocket/TCG references.'
        )
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """, ('pt-br', r['set_id'], r['card_id'], source['source_url'], method, note, FETCHED_AT))
        updated += 1
        method_counts[source['method']] = method_counts.get(source['method'], 0) + 1
        if len(examples) < 40:
            examples.append({'card_id': r['card_id'], 'old': r['old_name'], 'new': source['name'], 'source_method': source['method'], 'source_url': source['source_url']})
    conn.commit()
    remaining = conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p
        WHERE p.language_code='pt-br' AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
    """).fetchone()[0]
    by_set = list(conn.execute("""
        SELECT p.set_id, COUNT(*) FROM card_source_provenance p
        WHERE p.language_code='pt-br' AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        GROUP BY p.set_id ORDER BY COUNT(*) DESC
    """).fetchall())
    report = {
        'fetched_at': FETCHED_AT,
        'input_rows': len(rows),
        'updated': updated,
        'miss_count': len(misses),
        'remaining_ptbr': remaining,
        'remaining_by_set': [list(x) for x in by_set],
        'source_method_counts': method_counts,
        'examples': examples,
        'misses': misses[:100],
    }
    out = REPORT_DIR / 'ptbr_from_completed_pt_sources.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:12000])
    print('Report:', out)
    conn.close()

if __name__ == '__main__':
    main()
