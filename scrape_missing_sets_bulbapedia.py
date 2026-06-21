#!/usr/bin/env python3
"""Fill missing Pokémon TCG set checklists using existing rows + Bulbapedia scraping.

This script is intentionally resumable and source-aware:
1. For language-specific set rows that already have a checklist in another language,
   copy the local IDs/card IDs from the best reference language and mark provenance.
2. For set IDs with no checklist in any language, resolve Bulbapedia pages using the
   Japanese expansion list + MediaWiki search, parse {{Setlist/nmentry}} rows, and import.
3. If no page/list can be resolved, create explicit official-count placeholder rows
   named "Unknown card N" and mark provenance as official_count_placeholder.

No rows are silently invented as real card names. Every inserted row gets provenance.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite')
CACHE_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/raw/bulbapedia_missing_sets')
REPORT_DIR = Path('/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/reports')
USER_AGENT = 'SaveRoomPokemonKB/1.0 (local research; contact: saveroom)'
FETCHED_AT = '2026-06-11T15:30:00+00:00'

JAPANESE_LIST_TITLE = 'List_of_Japanese_Pokémon_Trading_Card_Game_expansions'
BULBA_WIKI = 'https://bulbapedia.bulbagarden.net/wiki/'
BULBA_RAW = 'https://bulbapedia.bulbagarden.net/w/index.php?title={title}&action=raw'
BULBA_API = 'https://bulbapedia.bulbagarden.net/w/api.php'

# Known title fixes for odd/special pages.
KNOWN_TITLE_BY_SET_ID = {
    'rc': 'Radiant Collection (TCG)',
    'wp': 'W Promotional cards (TCG)',
    'sp': 'Sample Set (TCG)',
    'jumbo': 'Jumbo cards (TCG)',
}


def urlopen_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def safe_filename(title: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', title)[:180]


def raw_page(title: str) -> str | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f'{safe_filename(title)}.wiki'
    if path.exists() and path.stat().st_size > 100:
        return path.read_text(encoding='utf-8', errors='replace')
    url = BULBA_RAW.format(title=urllib.parse.quote(title.replace(' ', '_'), safe=''))
    try:
        text = urlopen_text(url)
    except Exception:
        return None
    # MediaWiki raw for non-existing pages often returns empty-ish/noarticle text.
    if len(text) < 100 or 'There is currently no text in this page' in text:
        return None
    path.write_text(text, encoding='utf-8')
    time.sleep(0.15)
    return text


def search_titles(query: str, limit: int = 5) -> list[str]:
    params = {
        'action': 'query',
        'list': 'search',
        'srsearch': query,
        'format': 'json',
        'srlimit': str(limit),
    }
    url = BULBA_API + '?' + urllib.parse.urlencode(params)
    try:
        data = json.loads(urlopen_text(url))
    except Exception:
        return []
    titles = [h.get('title', '') for h in data.get('query', {}).get('search', [])]
    time.sleep(0.15)
    return [t for t in titles if t]


def strip_templates(text: str) -> str:
    text = re.sub(r'\{\{TCG\|([^}|]+)(?:\|[^}]*)?\}\}', r'\1', text)
    text = re.sub(r'\[\[([^]|]+)\|([^]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^]]+)\]\]', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\{\{[^{}]+\}\}', '', text)
    return text.strip()


def parse_japanese_expansion_list() -> dict[tuple[str, int], dict]:
    """Map (Japanese set name, count) -> English equivalent/page title info."""
    text = raw_page(JAPANESE_LIST_TITLE)
    if not text:
        return {}
    mapping: dict[tuple[str, int], dict] = {}
    # Split wikitext rows. Each row has cells beginning with |.
    rows = re.split(r'\n\|-', text)
    for row in rows:
        if 'Japanese name' in row or '{{TCG|' not in row:
            continue
        cells = [c.strip() for c in re.split(r'\n\|', row) if c.strip() and not c.strip().startswith('}')]
        if len(cells) < 5:
            continue
        # The name cell usually contains Japanese<br>{{TCG|Translated}}
        name_cell = None
        equiv_cell = None
        count_cell = None
        # Heuristic: find first cell with <br>{{TCG|...}}, then next non-file-ish cell is equivalent, then count.
        for i, cell in enumerate(cells):
            if '<br>' in cell and '{{TCG|' in cell:
                name_cell = cell
                if i + 1 < len(cells):
                    equiv_cell = cells[i + 1]
                if i + 2 < len(cells):
                    count_cell = cells[i + 2]
                break
        if not (name_cell and equiv_cell and count_cell):
            continue
        ja_name = strip_templates(name_cell.split('<br>')[0])
        trans_match = re.search(r'\{\{TCG\|([^}|]+)', name_cell)
        translated = trans_match.group(1).strip() if trans_match else None
        equivalent = strip_templates(equiv_cell)
        count_match = re.search(r'(\d+)', count_cell)
        if not (ja_name and equivalent and count_match):
            continue
        count = int(count_match.group(1))
        page_title = f'{equivalent} (TCG)'
        mapping[(ja_name, count)] = {
            'translated': translated,
            'equivalent': equivalent,
            'page_title': page_title,
        }
    return mapping


def split_template_args(arg_string: str) -> list[str]:
    args = []
    buf = []
    depth = 0
    i = 0
    while i < len(arg_string):
        ch = arg_string[i]
        if arg_string[i:i+2] == '{{':
            depth += 1
            buf.append('{{')
            i += 2
            continue
        if arg_string[i:i+2] == '}}' and depth:
            depth -= 1
            buf.append('}}')
            i += 2
            continue
        if ch == '|' and depth == 0:
            args.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    args.append(''.join(buf).strip())
    return args


def parse_setlist_entries(wikitext: str, official_count: int | None = None) -> list[dict]:
    entries = []
    for m in re.finditer(r'\{\{Setlist/nmentry\|(.*?)\}\}', wikitext, re.S):
        args = split_template_args(m.group(1))
        if len(args) < 2:
            continue
        num = strip_templates(args[0])
        den = None
        local = num
        if '/' in num:
            local, den_s = num.split('/', 1)
            den_m = re.search(r'\d+', den_s)
            den = int(den_m.group(0)) if den_m else None
        # If we have an official count, only use matching list sections.
        if official_count and den and den != official_count:
            continue
        card_tpl = args[1]
        # {{TCG ID|Set|Name|Number}}
        card_name = None
        id_m = re.search(r'\{\{TCG ID\|([^|{}]+)\|([^|{}]+)\|([^|{}]+)', card_tpl)
        if id_m:
            card_name = strip_templates(id_m.group(2))
        else:
            card_name = strip_templates(card_tpl)
        if not card_name:
            continue
        rarity = strip_templates(args[-1]) if len(args) >= 5 else None
        local = local.strip()
        entries.append({'local_id': local, 'name': card_name, 'rarity': rarity, 'denominator': den})
    # De-duplicate by local_id, keeping first occurrence.
    seen = set()
    deduped = []
    for e in entries:
        key = e['local_id']
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return deduped


def local_sort(local_id: str) -> int | None:
    m = re.search(r'\d+', str(local_id))
    return int(m.group(0)) if m else None


def ensure_provenance_table(conn: sqlite3.Connection) -> None:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS card_source_provenance (
            language_code TEXT NOT NULL,
            set_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            source_url TEXT,
            method TEXT NOT NULL,
            note TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (language_code, card_id, method)
        )
    ''')


def insert_card(conn: sqlite3.Connection, lang: str, set_id: str, local_id: str, name: str,
                source_url: str | None, method: str, note: str | None = None,
                rarity: str | None = None) -> bool:
    card_id = f'{set_id}-{local_id}'
    exists = conn.execute(
        'SELECT 1 FROM cards WHERE language_code=? AND card_id=?', (lang, card_id)
    ).fetchone()
    if exists:
        return False
    conn.execute('''
        INSERT INTO cards(language_code, set_id, card_id, local_id, local_id_sort, name, image_url)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
    ''', (lang, set_id, card_id, local_id, local_sort(local_id), name))
    conn.execute('''
        INSERT OR REPLACE INTO card_source_provenance(language_code, set_id, card_id, source_url, method, note, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (lang, set_id, card_id, source_url, method, note, FETCHED_AT))
    if rarity:
        conn.execute('''
            INSERT OR IGNORE INTO card_details(card_id, language_code, set_id, local_id, local_id_sort, name, rarity, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (card_id, lang, set_id, local_id, local_sort(local_id), name, rarity, FETCHED_AT))
    return True


def fill_from_reference(conn: sqlite3.Connection) -> int:
    inserted = 0
    missing = conn.execute('''
        SELECT s.language_code, s.set_id
        FROM sets s
        WHERE NOT EXISTS (
            SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id
        )
    ''').fetchall()
    preferred = ['en', 'ja', 'fr', 'de', 'es', 'it', 'pt', 'zh-tw', 'ko', 'zh-cn', 'th', 'id']
    for lang, set_id in missing:
        refs = conn.execute('''
            SELECT language_code, COUNT(*) as cnt FROM cards WHERE set_id=? GROUP BY language_code
        ''', (set_id,)).fetchall()
        if not refs:
            continue
        ref_langs = {r[0]: r[1] for r in refs}
        ref_lang = next((p for p in preferred if p in ref_langs), max(refs, key=lambda r: r[1])[0])
        rows = conn.execute('''
            SELECT local_id, name FROM cards WHERE language_code=? AND set_id=? ORDER BY local_id_sort, local_id
        ''', (ref_lang, set_id)).fetchall()
        for local_id, name in rows:
            inserted += insert_card(
                conn, lang, set_id, local_id, name,
                source_url=None,
                method='cross_language_template',
                note=f'Checklist copied from {ref_lang} rows for same set_id; names are fallback/reference names, not verified localized names.'
            )
    return inserted


def resolve_page_title(set_id: str, name: str, lang: str, official_count: int | None,
                       ja_mapping: dict[tuple[str, int], dict]) -> tuple[str | None, str]:
    if set_id in KNOWN_TITLE_BY_SET_ID:
        return KNOWN_TITLE_BY_SET_ID[set_id], 'known_title'
    if official_count and (name, official_count) in ja_mapping:
        return ja_mapping[(name, official_count)]['page_title'], 'japanese_expansion_list'
    # Search using translated/equivalent terms.
    queries = [f'{name} TCG', f'{name} Pokémon TCG', f'{set_id} TCG']
    for q in queries:
        for title in search_titles(q, limit=5):
            if title.endswith('(TCG)') or 'cards (TCG)' in title or 'Collection' in title:
                return title, f'search:{q}'
    return None, 'unresolved'


def scrape_unfillable(conn: sqlite3.Connection) -> dict:
    ja_mapping = parse_japanese_expansion_list()
    missing_sets = conn.execute('''
        SELECT s.set_id, MIN(s.name), MAX(s.official_count)
        FROM sets s
        WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.set_id=s.set_id)
        GROUP BY s.set_id
        ORDER BY s.set_id
    ''').fetchall()
    stats = Counter()
    page_cache: dict[str, list[dict]] = {}
    report_rows = []
    for set_id, sample_name, official_count in missing_sets:
        langs = conn.execute('''
            SELECT language_code, name, official_count FROM sets WHERE set_id=? ORDER BY language_code
        ''', (set_id,)).fetchall()
        # Prefer Japanese row for page resolution, else English, else first.
        chosen = next((r for r in langs if r[0] == 'ja'), None) or next((r for r in langs if r[0] == 'en'), None) or langs[0]
        lang, name, count = chosen
        count = count or official_count
        title, resolve_method = resolve_page_title(set_id, name, lang, count, ja_mapping)
        entries: list[dict] = []
        source_url = None
        if title:
            if title not in page_cache:
                text = raw_page(title)
                if text:
                    page_cache[title] = parse_setlist_entries(text, count)
                else:
                    page_cache[title] = []
            entries = page_cache[title]
            source_url = BULBA_WIKI + urllib.parse.quote(title.replace(' ', '_'), safe='()_')
        if entries:
            for lang2, local_name, local_count in langs:
                for e in entries:
                    inserted = insert_card(
                        conn, lang2, set_id, e['local_id'], e['name'], source_url,
                        method='bulbapedia_setlist',
                        note=f'Parsed from Bulbapedia page {title}; card names are page language/fallback names unless localized list was available.',
                        rarity=e.get('rarity')
                    )
                    if inserted:
                        stats['bulbapedia_cards'] += 1
            stats['sets_from_bulbapedia'] += 1
            report_rows.append({'set_id': set_id, 'title': title, 'method': resolve_method, 'entries': len(entries), 'status': 'bulbapedia'})
        else:
            # Explicit placeholders using official count. This is better than leaving no checklist,
            # and provenance makes the missing names auditable.
            n = int(count or 0)
            if n <= 0:
                stats['sets_unfilled_no_count'] += 1
                report_rows.append({'set_id': set_id, 'title': title, 'method': resolve_method, 'entries': 0, 'status': 'no_count'})
                continue
            width = 3 if n >= 100 else 2
            for lang2, local_name, local_count in langs:
                for i in range(1, n + 1):
                    local_id = f'{i:0{width}d}'
                    inserted = insert_card(
                        conn, lang2, set_id, local_id, f'Unknown card {local_id}', source_url,
                        method='official_count_placeholder',
                        note=f'Placeholder from official_count={n}; no parseable Bulbapedia/TCGdex card list resolved. Set name: {local_name}'
                    )
                    if inserted:
                        stats['placeholder_cards'] += 1
            stats['sets_placeholder'] += 1
            report_rows.append({'set_id': set_id, 'title': title, 'method': resolve_method, 'entries': n, 'status': 'placeholder'})
        conn.commit()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / 'missing_set_scrape_report.json').write_text(json.dumps(report_rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(stats)


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    ensure_provenance_table(conn)

    before_missing = conn.execute('''
        SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (
            SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id
        )
    ''').fetchone()[0]
    before_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    print(f'Before: cards={before_cards}, missing language/set rows={before_missing}')

    copied = fill_from_reference(conn)
    conn.commit()
    after_copy_missing = conn.execute('''
        SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (
            SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id
        )
    ''').fetchone()[0]
    print(f'Cross-language template inserted={copied}, missing now={after_copy_missing}')

    stats = scrape_unfillable(conn)
    conn.commit()

    after_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    after_missing = conn.execute('''
        SELECT COUNT(*) FROM sets s WHERE NOT EXISTS (
            SELECT 1 FROM cards c WHERE c.language_code=s.language_code AND c.set_id=s.set_id
        )
    ''').fetchone()[0]
    print('Scrape stats:', json.dumps(stats, ensure_ascii=False, indent=2))
    print(f'After: cards={after_cards}, inserted={after_cards-before_cards}, missing language/set rows={after_missing}')
    print('Cards by provenance method:')
    for method, count in conn.execute('SELECT method, COUNT(*) FROM card_source_provenance GROUP BY method ORDER BY COUNT(*) DESC'):
        print(f'  {method}: {count}')
    conn.close()


if __name__ == '__main__':
    main()
