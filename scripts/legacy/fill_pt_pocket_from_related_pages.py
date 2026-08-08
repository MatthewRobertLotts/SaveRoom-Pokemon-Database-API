#!/usr/bin/env python3
"""Complete remaining Portuguese Pocket rows from related-card pages on pokemonpocketbr.com.

Some secret/shiny rows do not have their own URL in the sitemap, but are listed
as related prints on another card page for the same Pokémon. If that related page
contains the target card id, use its parsed Nome field as the sourced card name.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import re
import sqlite3
import time
import unicodedata
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36 SaveRoom/1.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
}
SITEMAPS = ['https://pokemonpocketbr.com/carta-sitemap.xml','https://pokemonpocketbr.com/carta-sitemap2.xml']


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'ignore')


def slugify(name: str) -> str:
    s = name.replace(': Null',' null').replace('♀','f').replace('♂','m')
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower()
    s = re.sub(r'[^a-z0-9]+','-',s).strip('-')
    return s


def strip_tags(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s).replace(':ex:', 'ex')
    return re.sub(r'\s+', ' ', s).strip()


def parse_name(raw: str) -> str | None:
    m = re.search(r'>\s*Nome:\s*</span>\s*<span[^>]*>(.*?)</span>', raw, re.S | re.I)
    if m:
        return strip_tags(m.group(1))
    return None


def discover_by_slug() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sm in SITEMAPS:
        xml = fetch(sm)
        urls = re.findall(r'<loc>\s*(?:<!\[CDATA\[)?(https://pokemonpocketbr\.com/carta/[^\]\s<]+)', xml)
        for url in urls:
            m = re.search(r'/carta/[a-z0-9]+-[0-9]{3}-(.*?)/$', url, re.I)
            if not m:
                continue
            out.setdefault(m.group(1), []).append(url)
    return out


def unresolved(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
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


def inspect_target(row: dict, urls: list[str]) -> dict:
    needle = row['card_id']
    # Also site often displays uppercase/lowercase same id.
    for url in urls[:20]:
        try:
            raw = fetch(url)
        except Exception:
            continue
        if needle in raw or needle.upper() in raw or needle.lower() in raw:
            name = parse_name(raw)
            if name:
                return {**row, 'status': 'ok', 'url': url, 'name': name}
    return {**row, 'status': 'no_related_page', 'candidate_count': len(urls)}


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in unresolved(conn)]
    by_slug = discover_by_slug()
    print('remaining pt pocket', len(rows), 'slug groups', len(by_slug))
    targets = []
    no_slug = []
    for r in rows:
        sl = slugify(r['old_name'])
        urls = by_slug.get(sl) or []
        if not urls:
            no_slug.append({**r, 'slug': sl})
        else:
            targets.append((r, urls))
    print('targets', len(targets), 'no_slug', len(no_slug))
    results = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(inspect_target, r, urls) for r, urls in targets]
        for fut in cf.as_completed(futs):
            results.append(fut.result())
    updated = 0
    examples = []
    status_counts = {}
    for res in results:
        status_counts[res['status']] = status_counts.get(res['status'],0)+1
        if res['status'] != 'ok':
            continue
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?', (res['name'], 'pt', res['card_id']))
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            'pt', res['set_id'], res['card_id'], res['url'], 'pokemonpocketbr_related_card_page',
            f'Portuguese Pocket row sourced from pokemonpocketbr.com related-card page containing target card id; old fallback={res["old_name"]!r}.',
            FETCHED_AT,
        ))
        updated += 1
        if len(examples) < 40:
            examples.append({'card_id': res['card_id'], 'old': res['old_name'], 'new': res['name'], 'url': res['url']})
    conn.commit()
    remaining = len(unresolved(conn))
    remaining_total = conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p WHERE p.language_code='pt' AND p.method='cross_language_template'
          AND NOT EXISTS (SELECT 1 FROM card_source_provenance r WHERE r.language_code=p.language_code AND r.card_id=p.card_id AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket'))
    """).fetchone()[0]
    report={'fetched_at':FETCHED_AT,'input_rows':len(rows),'targets':len(targets),'no_slug_count':len(no_slug),'status_counts':status_counts,'updated':updated,'remaining_pt_pocket':remaining,'remaining_pt_total':remaining_total,'examples':examples,'no_slug_examples':no_slug[:50],'failed_examples':[r for r in results if r.get('status')!='ok'][:50]}
    out=REPORT_DIR/'pokemonpocketbr_pt_related_page_completion.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:12000])
    print('Report:',out)
    conn.close()

if __name__=='__main__':
    main()
