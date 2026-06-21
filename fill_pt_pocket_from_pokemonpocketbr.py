#!/usr/bin/env python3
"""Complete Portuguese/Brazilian Portuguese Pocket fallback rows from pokemonpocketbr.com.

The site exposes a WordPress carta sitemap and per-card pages with Portuguese UI/card
metadata. We use the sitemap as source discovery, then parse each target page's
"Nome:" field and add explicit provenance.
"""
from __future__ import annotations

import concurrent.futures as cf
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
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36 SaveRoom/1.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
}
SITEMAPS = [
    'https://pokemonpocketbr.com/carta-sitemap.xml',
    'https://pokemonpocketbr.com/carta-sitemap2.xml',
]


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def discover_urls() -> dict[str, str]:
    out: dict[str, str] = {}
    for sm in SITEMAPS:
        xml = fetch(sm)
        urls = re.findall(r'<loc>\s*(?:<!\[CDATA\[)?(https://pokemonpocketbr\.com/carta/[^\]\s<]+)', xml)
        for url in urls:
            m = re.search(r'/carta/([a-z0-9]+)-([0-9]{3})-[^/]+/', url, re.I)
            if not m:
                continue
            set_id = m.group(1)
            num = m.group(2)
            card_id = f'{set_id.upper() if set_id.isupper() else set_id}-{num}'
            # Normalize only the prefix capitalization, preserving a/b suffixes.
            card_id = f'{set_id[0].upper() + set_id[1:]}-{num}'
            out[card_id] = url
    return out


def strip_tags(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = s.replace(':ex:', 'ex')
    return re.sub(r'\s+', ' ', s).strip()


def parse_page(url: str) -> dict:
    try:
        raw = fetch(url)
        m = re.search(r'>\s*Nome:\s*</span>\s*<span[^>]*>(.*?)</span>', raw, re.S | re.I)
        if not m:
            # fallback title: "B2-002 Ledian - Pokémon TCG Pocket"
            title = re.search(r'<title>(.*?)</title>', raw, re.S | re.I)
            if title:
                t = strip_tags(title.group(1))
                mt = re.match(r'[A-Za-z0-9]+-\d{3}\s+(.+?)\s+-\s+Pok', t)
                if mt:
                    return {'url': url, 'status': 'ok', 'name': mt.group(1).strip()}
            return {'url': url, 'status': 'no_name'}
        name = strip_tags(m.group(1))
        # Remove any energy/rarity tail that got included after the name; img tags are stripped, but alt text is not in body.
        return {'url': url, 'status': 'ok', 'name': name}
    except Exception as e:
        return {'url': url, 'status': f'error_{type(e).__name__}', 'error': str(e)[:200]}


def unresolved_pt_pocket(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT p.language_code, p.set_id, p.card_id, c.local_id, c.name AS old_name, s.series_name
        FROM card_source_provenance p
        JOIN cards c ON c.language_code=p.language_code AND c.card_id=p.card_id
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.language_code='pt'
          AND s.series_name LIKE '%Pocket%'
          AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code
              AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
        ORDER BY p.set_id, c.local_id_sort
    """).fetchall()


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = unresolved_pt_pocket(conn)
    print('unresolved pt pocket rows', len(rows))
    url_map = discover_urls()
    print('discovered card urls', len(url_map))
    targets = []
    missing_url = []
    for r in rows:
        url = url_map.get(r['card_id'])
        if not url:
            missing_url.append(dict(r))
        else:
            targets.append((r, url))
    print('targets with url', len(targets), 'missing_url', len(missing_url))

    page_results = {}
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(parse_page, url): (r, url) for r, url in targets}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            r, url = futs[fut]
            page_results[r['card_id']] = fut.result()
            if i % 100 == 0:
                print(' fetched', i, '/', len(targets))

    updated = 0
    examples = []
    statuses = {}
    for r, url in targets:
        res = page_results.get(r['card_id']) or {'status': 'missing_result'}
        statuses[res['status']] = statuses.get(res['status'], 0) + 1
        if res.get('status') != 'ok' or not res.get('name'):
            continue
        name = res['name']
        conn.execute('UPDATE cards SET name=? WHERE language_code=? AND card_id=?', (name, 'pt', r['card_id']))
        conn.execute("""
            INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            'pt', r['set_id'], r['card_id'], url, 'pokemonpocketbr_card_page',
            f'Portuguese/Brazilian Portuguese Pokémon TCG Pocket card name parsed from pokemonpocketbr.com card page; old fallback={r["old_name"]!r}.',
            FETCHED_AT,
        ))
        updated += 1
        if len(examples) < 30:
            examples.append({'card_id': r['card_id'], 'old': r['old_name'], 'new': name, 'url': url})
    conn.commit()

    remaining_pt = conn.execute("""
        SELECT COUNT(*) FROM card_source_provenance p
        WHERE p.language_code='pt' AND p.method='cross_language_template'
          AND NOT EXISTS (
            SELECT 1 FROM card_source_provenance r
            WHERE r.language_code=p.language_code AND r.card_id=p.card_id
              AND r.method NOT IN ('cross_language_template','official_count_placeholder','unresolved_promo_bucket')
          )
    """).fetchone()[0]
    remaining_pt_pocket = len(unresolved_pt_pocket(conn))
    report = {
        'fetched_at': FETCHED_AT,
        'input_pt_pocket_rows': len(rows),
        'discovered_urls': len(url_map),
        'targets_with_url': len(targets),
        'missing_url_count': len(missing_url),
        'page_statuses': statuses,
        'updated': updated,
        'examples': examples,
        'missing_url_examples': missing_url[:50],
        'remaining_pt_total': remaining_pt,
        'remaining_pt_pocket': remaining_pt_pocket,
    }
    out = REPORT_DIR / 'pokemonpocketbr_pt_pocket_completion.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:12000])
    print('Report:', out)
    conn.close()

if __name__ == '__main__':
    main()
