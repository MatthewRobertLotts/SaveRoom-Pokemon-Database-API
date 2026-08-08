#!/usr/bin/env python3
"""Replace unresolved cross-language fallback card names with TCGdex card endpoints.

This targets rows that still only have `cross_language_template` provenance.
For each unresolved row, it probes the card-level TCGdex endpoint because some
Pocket sets have empty set-level `cards` arrays while individual card endpoints
already work. Successful hits update `cards`, add/update a basic `card_details`
row, and add source provenance so audits no longer count the row as unresolved.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
REPORT_DIR.mkdir(parents=True, exist_ok=True)
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
USER_AGENT = 'SaveRoom-RealDataCompletion/1.0'


def api_lang(db_lang: str, series_name: str | None) -> str:
    # TCGdex Pocket Brazilian Portuguese is pt-br; this DB has both pt and pt-br rows.
    if db_lang == 'pt' and series_name and 'Pocket' in series_name:
        return 'pt-br'
    return db_lang


def local_sort(local_id: str | None) -> int | None:
    if not local_id:
        return None
    digits = ''.join(ch for ch in str(local_id) if ch.isdigit())
    return int(digits) if digits else None


def fetch_card(task: dict[str, Any]) -> dict[str, Any]:
    lang = task['api_lang']
    card_id = task['card_id']
    url = f'https://api.tcgdex.net/v2/{lang}/cards/{card_id}'
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        name = data.get('name')
        if not name:
            return {**task, 'status': 'no_name', 'url': url}
        return {**task, 'status': 'ok', 'url': url, 'data': data}
    except urllib.error.HTTPError as e:
        return {**task, 'status': f'http_{e.code}', 'url': url}
    except Exception as e:
        return {**task, 'status': f'error_{type(e).__name__}', 'url': url, 'error': str(e)[:200]}


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT p.language_code, p.set_id, p.card_id, c.local_id, c.local_id_sort,
               c.name AS old_name, s.name AS set_name, s.series_name
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        ORDER BY p.language_code, p.set_id, p.card_id
    """).fetchall()

    tasks = []
    for row in rows:
        d = dict(row)
        d['api_lang'] = api_lang(d['language_code'], d.get('series_name'))
        tasks.append(d)

    print(f'Unresolved fallback rows to probe: {len(tasks)}')
    print('API language counts:')
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t['api_lang']] = counts.get(t['api_lang'], 0) + 1
    for lang, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  {lang}: {count}')

    ok = 0
    changed = 0
    status_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(fetch_card, task) for task in tasks]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            res = fut.result()
            status = res['status']
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == 'ok':
                data = res['data']
                name = data.get('name')
                image = data.get('image')
                local_id = data.get('localId') or res.get('local_id')
                lsort = local_sort(local_id) or res.get('local_id_sort')
                db_lang = res['language_code']
                card_id = res['card_id']
                set_id = res['set_id']

                conn.execute("""
                    UPDATE cards
                    SET name=?, image_url=COALESCE(?, image_url), local_id=COALESCE(?, local_id), local_id_sort=COALESCE(?, local_id_sort)
                    WHERE language_code=? AND card_id=?
                """, (name, image, local_id, lsort, db_lang, card_id))

                conn.execute("""
                    INSERT OR REPLACE INTO card_details(
                        card_id, language_code, set_id, local_id, local_id_sort, name,
                        illustrator, category, hp, types, rarity, stage, retreat,
                        regulation_mark, attacks, weaknesses, resistances, variants,
                        legal, description, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    card_id, db_lang, set_id, local_id, lsort, name,
                    data.get('illustrator'), data.get('category'), data.get('hp'),
                    ','.join(data.get('types') or []) if isinstance(data.get('types'), list) else data.get('types'),
                    data.get('rarity'), data.get('stage'), data.get('retreat'), data.get('regulationMark'),
                    json.dumps(data.get('attacks'), ensure_ascii=False) if data.get('attacks') is not None else None,
                    json.dumps(data.get('weaknesses'), ensure_ascii=False) if data.get('weaknesses') is not None else None,
                    json.dumps(data.get('resistances'), ensure_ascii=False) if data.get('resistances') is not None else None,
                    json.dumps(data.get('variants'), ensure_ascii=False) if data.get('variants') is not None else None,
                    json.dumps(data.get('legal'), ensure_ascii=False) if data.get('legal') is not None else None,
                    json.dumps(data.get('description'), ensure_ascii=False) if data.get('description') is not None else None,
                    FETCHED_AT,
                ))

                method = 'tcgdex_card_endpoint'
                note = 'Localized card data fetched from TCGdex card endpoint during real-data completion pass.'
                if res['api_lang'] != db_lang:
                    note += f' API language mapped from DB language {db_lang} to {res["api_lang"]}.'
                conn.execute("""
                    INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                    VALUES (?,?,?,?,?,?,?)
                """, (db_lang, set_id, card_id, res['url'], method, note, FETCHED_AT))
                ok += 1
                if name != res.get('old_name'):
                    changed += 1
                    if len(examples) < 30:
                        examples.append({
                            'language_code': db_lang,
                            'set_id': set_id,
                            'card_id': card_id,
                            'old_name': res.get('old_name'),
                            'new_name': name,
                            'url': res['url'],
                        })
            if i % 250 == 0:
                conn.commit()
                print(f'  {i}/{len(tasks)} probed; ok={ok}; changed={changed}; statuses={status_counts}')

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
    remaining_total = sum(r[1] for r in remaining_by_lang)

    report = {
        'fetched_at': FETCHED_AT,
        'tasks': len(tasks),
        'successful_endpoint_hits': ok,
        'changed_names': changed,
        'status_counts': status_counts,
        'examples': examples,
        'remaining_total': remaining_total,
        'remaining_by_language': [list(r) for r in remaining_by_lang],
    }
    out = REPORT_DIR / 'tcgdex_card_endpoint_fallback_completion.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n=== Done ===')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:8000])
    print(f'Report: {out}')
    conn.close()


if __name__ == '__main__':
    main()
