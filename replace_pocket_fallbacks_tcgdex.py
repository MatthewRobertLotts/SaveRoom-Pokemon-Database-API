#!/usr/bin/env python3
"""Replace Pokémon TCG Pocket cross-language fallback names using TCGdex Pocket REST.

TCGdex documents Pocket as the `tcgp` series under normal set/card endpoints:
https://api.tcgdex.net/v2/{lang}/sets/{set_id}

The local DB uses `pt` for some Brazilian Portuguese Pocket sets; Pocket itself is
localized as pt-br, so pt and pt-br both source from TCGdex pt-br.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from pathlib import Path

DB = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
CACHE = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/raw/tcgdex_pocket')
REPORT = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports/tcgdex_pocket_replacement.json')
FETCHED_AT = '2026-06-11T18:10:00+00:00'
LANG_TO_API = {'fr':'fr', 'de':'de', 'es':'es', 'it':'it', 'pt':'pt-br', 'pt-br':'pt-br'}
UA = 'SaveRoomPokemonKB/1.0'


def fetch_set(api_lang: str, set_id: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = CACHE / f'{api_lang}_{set_id}.json'
    if cp.exists() and cp.stat().st_size > 20:
        return json.loads(cp.read_text(encoding='utf-8'))
    url = f'https://api.tcgdex.net/v2/{api_lang}/sets/{set_id}'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    data = json.loads(urllib.request.urlopen(req, timeout=45).read().decode('utf-8'))
    cp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    time.sleep(0.12)
    return data


def main() -> None:
    conn = sqlite3.connect(DB)
    targets = conn.execute("""
        select p.language_code, p.set_id, s.name, count(*) cnt
        from card_source_provenance p
        join sets s on s.language_code=p.language_code and s.set_id=p.set_id
        where p.method='cross_language_template'
          and p.language_code in ('fr','de','es','it','pt','pt-br')
          and s.series_name like '%Pocket%'
          and not exists (
              select 1 from card_source_provenance r
              where r.language_code=p.language_code and r.card_id=p.card_id
                and r.method not in ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        group by p.language_code, p.set_id
        order by cnt desc
    """).fetchall()
    print('targets', len(targets))
    report = []
    total_updated = 0
    for lang, set_id, set_name, cnt in targets:
        api_lang = LANG_TO_API[lang]
        try:
            data = fetch_set(api_lang, set_id)
        except Exception as exc:
            report.append({'language_code': lang, 'set_id': set_id, 'status': 'fetch_error', 'error': repr(exc), 'target_count': cnt})
            print(lang, set_id, 'FETCH_ERROR', repr(exc))
            continue
        cards = data.get('cards') or []
        if not cards:
            report.append({'language_code': lang, 'set_id': set_id, 'status': 'empty_from_tcgdex', 'api_lang': api_lang, 'tcgdex_set_name': data.get('name'), 'target_count': cnt})
            print(lang, set_id, 'EMPTY', data.get('name'), 'target', cnt)
            continue
        by_local = {str(c.get('localId') or '').lstrip('0') or str(c.get('localId') or ''): c for c in cards if c.get('localId') and c.get('name')}
        updated = 0
        rows = conn.execute("""
            select card_id, local_id, local_id_sort, name
            from cards
            where language_code=? and set_id=?
            order by local_id_sort
        """, (lang, set_id)).fetchall()
        for card_id, local_id, local_sort, old_name in rows:
            key = str(local_id or '').lstrip('0') or str(local_sort or '')
            c = by_local.get(key)
            if not c:
                c = by_local.get(str(local_sort or ''))
            if not c:
                continue
            new_name = c.get('name')
            new_local = c.get('localId') or local_id
            image = c.get('image')
            if not new_name:
                continue
            conn.execute('update cards set name=?, local_id=?, image_url=coalesce(?, image_url) where language_code=? and card_id=?', (new_name, new_local, image, lang, card_id))
            conn.execute("""insert or replace into card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                            values(?,?,?,?,?,?,?)""", (
                lang, set_id, card_id,
                f'https://api.tcgdex.net/v2/{api_lang}/sets/{set_id}',
                'tcgdex_pocket_rest',
                f'Real localized Pokémon TCG Pocket card name from TCGdex {api_lang}; set={data.get("name")}; old={old_name!r}',
                FETCHED_AT,
            ))
            conn.execute("""insert or replace into card_details(card_id,language_code,set_id,local_id,local_id_sort,name,rarity,fetched_at)
                            values(?,?,?,?,?,?,?,?)""", (
                card_id, lang, set_id, new_local, local_sort, new_name, c.get('rarity'), FETCHED_AT
            ))
            updated += 1
        conn.commit()
        total_updated += updated
        report.append({'language_code': lang, 'set_id': set_id, 'status': 'ok', 'api_lang': api_lang, 'tcgdex_set_name': data.get('name'), 'tcgdex_cards': len(cards), 'target_count': cnt, 'updated': updated})
        print(lang, set_id, data.get('name'), 'cards', len(cards), 'updated', updated)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({'total_updated': total_updated, 'runs': report}, ensure_ascii=False, indent=2), encoding='utf-8')
    conn.close()
    print('total_updated', total_updated)


if __name__ == '__main__':
    main()
