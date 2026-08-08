#!/usr/bin/env python3
"""Use TCGdex set endpoints to replace unresolved cross-language fallback rows.

Some Pocket set endpoints include localized card summaries even when card-detail
endpoints 404 for many localIds. This imports those summaries with provenance.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
USER_AGENT = 'SaveRoom-SetEndpointCompletion/1.0'


def api_lang(db_lang: str, series_name: str | None) -> str:
    if db_lang == 'pt' and series_name and 'Pocket' in series_name:
        return 'pt-br'
    return db_lang


def local_sort(local_id: str | None) -> int | None:
    if not local_id:
        return None
    digits = ''.join(ch for ch in str(local_id) if ch.isdigit())
    return int(digits) if digits else None


def fetch_set(lang: str, set_id: str) -> tuple[str, dict | None, str | None]:
    url = f'https://api.tcgdex.net/v2/{lang}/sets/{set_id}'
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return url, json.load(r), None
    except Exception as e:
        return url, None, f'{type(e).__name__}: {e}'


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    groups = conn.execute("""
        SELECT p.language_code, p.set_id, s.series_name, s.name, COUNT(*) AS unresolved
        FROM card_source_provenance p
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        GROUP BY p.language_code, p.set_id
        ORDER BY unresolved DESC
    """).fetchall()

    print(f'Unresolved groups: {len(groups)}')
    updated = 0
    groups_with_cards = 0
    group_reports = []

    for idx, g in enumerate(groups, 1):
        db_lang, set_id, series_name = g['language_code'], g['set_id'], g['series_name']
        alang = api_lang(db_lang, series_name)
        url, data, err = fetch_set(alang, set_id)
        cards = (data or {}).get('cards') or []
        if cards:
            groups_with_cards += 1
        changed_this = 0
        for c in cards:
            card_id = c.get('id') or (f'{set_id}-{c.get("localId")}' if c.get('localId') else None)
            local_id = c.get('localId')
            name = c.get('name')
            image = c.get('image')
            if not card_id or not name:
                continue
            exists_unresolved = conn.execute("""
                SELECT 1 FROM card_source_provenance p
                WHERE p.language_code=? AND p.card_id=? AND p.method='cross_language_template'
                  AND NOT EXISTS (
                    SELECT 1 FROM card_source_provenance r
                    WHERE r.language_code=p.language_code
                      AND r.card_id=p.card_id
                      AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
                  )
            """, (db_lang, card_id)).fetchone()
            if not exists_unresolved:
                continue
            conn.execute("""
                UPDATE cards
                SET name=?, image_url=COALESCE(?, image_url), local_id=COALESCE(?, local_id), local_id_sort=COALESCE(?, local_id_sort)
                WHERE language_code=? AND card_id=?
            """, (name, image, local_id, local_sort(local_id), db_lang, card_id))
            conn.execute("""
                INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                VALUES (?,?,?,?,?,?,?)
            """, (
                db_lang, set_id, card_id, url, 'tcgdex_set_endpoint',
                f'Localized card summary fetched from TCGdex set endpoint using API language {alang}.',
                FETCHED_AT,
            ))
            changed_this += 1
            updated += 1
        if changed_this or cards or err:
            group_reports.append({
                'language_code': db_lang, 'api_lang': alang, 'set_id': set_id, 'set_name': g['name'],
                'series_name': series_name, 'unresolved_before': g['unresolved'],
                'endpoint_card_count': len(cards), 'updated': changed_this, 'url': url, 'error': err,
            })
        if idx % 20 == 0:
            conn.commit()
            print(f'  {idx}/{len(groups)} groups checked; groups_with_cards={groups_with_cards}; updated={updated}')

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
        'groups_checked': len(groups),
        'groups_with_endpoint_cards': groups_with_cards,
        'rows_updated': updated,
        'remaining_total': sum(r[1] for r in remaining_by_lang),
        'remaining_by_language': [list(r) for r in remaining_by_lang],
        'groups': group_reports,
    }
    out = REPORT_DIR / 'tcgdex_set_endpoint_fallback_completion.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n=== Done ===')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:10000])
    print('Report:', out)
    conn.close()


if __name__ == '__main__':
    main()
