#!/usr/bin/env python3
"""Import French Pokémon TCG Pocket card names from Eternia cartodex pages.

Eternia exposes full French Pocket set tables for B1/B1a/B2 etc. This parser
extracts the number/name pairs from those pages and uses them to replace
remaining cross-language fallback rows with explicit source provenance.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
USER_AGENT = 'SaveRoom-EterniaPocketFR/1.0'

SOURCES = {
    'B1': 'https://eternia.fr/fr/site/article/5692-pokemon-pocket-extension-mega-ascension/',
    'B1a': 'https://eternia.fr/fr/site/article/6014-pokemon-pocket-extension-embrasement-ecarlate/',
    'B2': 'https://eternia.fr/fr/site/article/6015-pokemon-pocket-extension-parade-onirique/',
    'A4a': 'https://eternia.fr/fr/site/article/5629-pokemon-pocket-extension-source-secrete/',
    'B2a': 'https://eternia.fr/fr/site/article/6050-pokemon-pocket-extension-merveilles-de-paldea/',
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode('utf-8', 'ignore')


def strip_tags(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def parse_cards(raw: str) -> dict[str, str]:
    # Split by table row. The card-name cell has the French name in a <b> tag,
    # followed by the English name in <i>. Avoid the first <b> which is the number.
    out: dict[str, str] = {}
    for tr in re.findall(r'<tr\b.*?</tr>', raw, flags=re.S | re.I):
        num_m = re.search(r'<b>\s*(\d{1,3})\s*/\s*\d+\s*</b>', tr, flags=re.I)
        if not num_m:
            continue
        num = f'{int(num_m.group(1)):03d}'
        # Prefer the <td> after the illustration cell that contains <b>Name</b> + <i>English</i>.
        candidates = re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S | re.I)
        name = None
        for td in candidates:
            if '<i>' in td.lower():
                bnames = re.findall(r'<b>(.*?)</b>', td, flags=re.S | re.I)
                # In the correct cell the first bold value is the French card name.
                if bnames:
                    candidate = strip_tags(bnames[0])
                    # Skip number-like cells.
                    if candidate and not re.match(r'^\d+\s*/', candidate):
                        name = candidate
                        break
        if name:
            out[num] = name
    return out


def unresolved_count(conn: sqlite3.Connection, set_id: str) -> int:
    return conn.execute("""
        SELECT COUNT(*)
        FROM card_source_provenance p
        WHERE p.language_code='fr' AND p.set_id=? AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
    """, (set_id,)).fetchone()[0]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    updated_total = 0
    reports = []
    for set_id, url in SOURCES.items():
        before = unresolved_count(conn, set_id)
        raw = fetch(url)
        cards = parse_cards(raw)
        updated = 0
        examples = []
        for local_id, name in cards.items():
            card_id = f'{set_id}-{local_id}'
            unresolved = conn.execute("""
                SELECT c.name FROM cards c
                JOIN card_source_provenance p ON p.language_code=c.language_code AND p.card_id=c.card_id
                WHERE c.language_code='fr' AND c.card_id=? AND p.method='cross_language_template'
                  AND NOT EXISTS (
                    SELECT 1 FROM card_source_provenance r
                    WHERE r.language_code=p.language_code
                      AND r.card_id=p.card_id
                      AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
                  )
            """, (card_id,)).fetchone()
            if not unresolved:
                continue
            old = unresolved[0]
            conn.execute("UPDATE cards SET name=? WHERE language_code='fr' AND card_id=?", (name, card_id))
            conn.execute("""
                INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
                VALUES (?,?,?,?,?,?,?)
            """, (
                'fr', set_id, card_id, url, 'eternia_pocket_fr_cartodex',
                f'French Pokémon TCG Pocket card name parsed from Eternia cartodex page; old fallback={old!r}.',
                FETCHED_AT,
            ))
            updated += 1
            updated_total += 1
            if len(examples) < 10:
                examples.append({'card_id': card_id, 'old': old, 'new': name})
        conn.commit()
        after = unresolved_count(conn, set_id)
        reports.append({'set_id': set_id, 'url': url, 'parsed_cards': len(cards), 'unresolved_before': before, 'updated': updated, 'unresolved_after': after, 'examples': examples})
        print(set_id, 'parsed', len(cards), 'before', before, 'updated', updated, 'after', after)
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
    report = {'fetched_at': FETCHED_AT, 'updated_total': updated_total, 'sets': reports, 'remaining_total': sum(r[1] for r in remaining_by_lang), 'remaining_by_language': [list(r) for r in remaining_by_lang]}
    out = REPORT_DIR / 'eternia_pocket_fr_completion.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:10000])
    print('Report:', out)
    conn.close()


if __name__ == '__main__':
    main()
