#!/usr/bin/env python3
"""Replace official_count placeholders using official Asia Pokémon Card site.

Targets language codes served by https://asia.pokemon-card.com/<region>/card-search/:
- id (Indonesian)
- th (Thai)
- zh-tw (Traditional Chinese)

For each set with official_count_placeholder rows, fetches list pages using
?expansionCodes=<set_id>&pageNo=N, follows detail links, extracts title/name and
collector number, then updates cards and provenance.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
CACHE_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/raw/official_asia_card_search')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
FETCHED_AT = '2026-06-11T16:15:00+00:00'
USER_AGENT = 'Mozilla/5.0 SaveRoomPokemonKB/1.0'
LANG_BASE = {
    'id': 'https://asia.pokemon-card.com/id',
    'th': 'https://asia.pokemon-card.com/th',
    'zh-tw': 'https://asia.pokemon-card.com/tw',
}


def fetch(url: str, cache_path: Path, timeout: int = 45) -> str | None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and cache_path.stat().st_size > 500:
        return cache_path.read_text(encoding='utf-8', errors='replace')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None
    cache_path.write_text(text, encoding='utf-8')
    time.sleep(0.08)
    return text


def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', html_lib.unescape(re.sub(r'<[^>]+>', '', s))).strip()


def list_url(lang: str, set_id: str, page: int) -> str:
    base = LANG_BASE[lang]
    qs = urllib.parse.urlencode({'expansionCodes': set_id, 'pageNo': page})
    return f'{base}/card-search/list/?{qs}'


def detail_url(lang: str, detail_id: str) -> str:
    base = LANG_BASE[lang]
    return f'{base}/card-search/detail/{detail_id}/'


def parse_list_page(lang: str, html: str) -> tuple[int | None, int | None, list[str]]:
    total = None
    pages = None
    m = re.search(r'<p class="resultCount">\s*(\d+)\s*</p>', html)
    if m:
        total = int(m.group(1))
    m = re.search(r'Total\s*(\d+)\s*(?:halaman|หน้า|頁)', html, re.I)
    if m:
        pages = int(m.group(1))
    # Region path differs (/id/, /th/, /tw/)
    path_code = {'id': 'id', 'th': 'th', 'zh-tw': 'tw'}[lang]
    ids = sorted(set(re.findall(rf'/{path_code}/card-search/detail/(\d+)/', html)))
    return total, pages, ids


def parse_detail(lang: str, html: str) -> dict | None:
    title = None
    m = re.search(r'<title>\s*(.*?)\s*\|', html, re.S)
    if m:
        title = clean(m.group(1))
    if not title:
        m = re.search(r'<li class="current">\s*(.*?)\s*</li>', html, re.S)
        if m:
            title = clean(m.group(1))
    num = None
    m = re.search(r'<span class="collectorNumber">\s*([^<]+?)\s*</span>', html, re.S)
    if m:
        num = clean(m.group(1))
    set_code = None
    path_code = {'id': 'id', 'th': 'th', 'zh-tw': 'tw'}[lang]
    m = re.search(rf'/{path_code}/card-search/list/\?expansionCodes=([^"&]+)', html)
    if m:
        set_code = urllib.parse.unquote(m.group(1))
    rarity = None
    # Rarity appears as alpha span near expansion. Use alpha only when short.
    m = re.search(r'<span class="alpha">\s*([^<]{1,8})\s*</span>', html, re.S)
    if m:
        rarity = clean(m.group(1))
    if not (title and num):
        return None
    local = num.split('/')[0].strip()
    return {'name': title, 'collector_number': num, 'local_id': local, 'set_code': set_code, 'rarity': rarity}


def update_card(conn: sqlite3.Connection, lang: str, set_id: str, data: dict, source_url: str) -> bool:
    local_id = data['local_id']
    card_id = f'{set_id}-{local_id}'
    row = conn.execute('SELECT name FROM cards WHERE language_code=? AND card_id=?', (lang, card_id)).fetchone()
    if not row:
        # Some placeholders use two digits for counts <100; detail may use 001. Try integer matching.
        sort = int(re.search(r'\d+', local_id).group(0)) if re.search(r'\d+', local_id) else None
        row = conn.execute('SELECT card_id FROM cards WHERE language_code=? AND set_id=? AND local_id_sort=?', (lang, set_id, sort)).fetchone()
        if row:
            card_id = row[0]
        else:
            return False
    old_name = row[0] if len(row) > 0 else None
    conn.execute('UPDATE cards SET name=?, local_id=?, local_id_sort=? WHERE language_code=? AND card_id=?', (
        data['name'], local_id, int(re.search(r'\d+', local_id).group(0)) if re.search(r'\d+', local_id) else None, lang, card_id
    ))
    conn.execute('''
        INSERT OR REPLACE INTO card_source_provenance(language_code,set_id,card_id,source_url,method,note,fetched_at)
        VALUES (?,?,?,?,?,?,?)
    ''', (lang, set_id, card_id, source_url, 'official_asia_card_search', f'Replaced placeholder/cross-language name {old_name!r} with official Asia card-search detail data; collector_number={data["collector_number"]}', FETCHED_AT))
    conn.execute('''
        INSERT OR REPLACE INTO card_details(card_id,language_code,set_id,local_id,local_id_sort,name,rarity,fetched_at)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (card_id, lang, set_id, local_id, int(re.search(r'\d+', local_id).group(0)) if re.search(r'\d+', local_id) else None, data['name'], data.get('rarity'), FETCHED_AT))
    return True


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    targets = conn.execute('''
        SELECT p.language_code, p.set_id, COUNT(*) cnt, s.name, s.official_count
        FROM card_source_provenance p
        JOIN sets s ON s.language_code=p.language_code AND s.set_id=p.set_id
        WHERE p.method IN ('official_count_placeholder','cross_language_template')
          AND p.language_code IN ('id','th','zh-tw')
          AND NOT EXISTS (
              SELECT 1 FROM card_source_provenance done
              WHERE done.language_code=p.language_code
                AND done.set_id=p.set_id
                AND done.method IN ('bulbapedia_v2_setlist','bulbapedia_setlist','official_asia_card_search')
          )
        GROUP BY p.language_code,p.set_id
        ORDER BY cnt DESC
    ''').fetchall()
    print(f'target sets: {len(targets)}')
    report = []
    total_updated = 0
    for idx, (lang, set_id, cnt, set_name, official_count) in enumerate(targets, 1):
        first_url = list_url(lang, set_id, 1)
        html = fetch(first_url, CACHE_DIR / lang / set_id / 'list_1.html')
        if not html:
            report.append({'lang': lang, 'set_id': set_id, 'status': 'list_fetch_failed'})
            continue
        total, pages, ids = parse_list_page(lang, html)
        if not pages:
            pages = max(1, (total or 0 + 19) // 20) if total else 1
        all_ids = set(ids)
        for p in range(2, pages + 1):
            h = fetch(list_url(lang, set_id, p), CACHE_DIR / lang / set_id / f'list_{p}.html')
            if h:
                _, _, more = parse_list_page(lang, h)
                all_ids.update(more)
        if not all_ids:
            report.append({'lang': lang, 'set_id': set_id, 'status': 'no_detail_links', 'total': total, 'pages': pages})
            continue
        updated = 0
        parsed = 0
        for did in sorted(all_ids, key=int):
            du = detail_url(lang, did)
            dh = fetch(du, CACHE_DIR / lang / set_id / f'detail_{did}.html')
            if not dh:
                continue
            data = parse_detail(lang, dh)
            if not data:
                continue
            parsed += 1
            if update_card(conn, lang, set_id, data, du):
                updated += 1
        conn.commit()
        total_updated += updated
        status = 'ok' if updated else 'parsed_no_updates'
        print(f'{idx}/{len(targets)} {lang} {set_id}: details={len(all_ids)} parsed={parsed} updated={updated}')
        report.append({'lang': lang, 'set_id': set_id, 'set_name': set_name, 'placeholder_rows': cnt, 'official_count': official_count, 'site_total': total, 'pages': pages, 'detail_links': len(all_ids), 'parsed': parsed, 'updated': updated, 'status': status})
    (REPORT_DIR / 'official_asia_placeholder_replacement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('total_updated', total_updated)
    conn.close()

if __name__ == '__main__':
    main()
