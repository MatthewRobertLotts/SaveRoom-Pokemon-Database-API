#!/usr/bin/env python3
"""UK eBay sold-price scraper MVP for SaveRoom Pokémon cards.

Script-first ingestion only: no FastAPI endpoints, no writes unless --insert is
passed. Dry runs write CSV/audit files under full_tcgdex/reports by default.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin

import requests
try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover - runtime dependency message
    raise SystemExit('BeautifulSoup is required. Install/use a Python with bs4 available: python3 -m pip install beautifulsoup4') from exc

from pokemon_db_v3_config import DEFAULT_DB, DEFAULT_REPORTS_DIR

from pokemon_db_v3_ebay_api import EbayBuyAPI, parse_api_listings

EBAY_SEARCH_URL = 'https://www.ebay.co.uk/sch/i.html?_nkw={query}&_sacat=0&LH_Complete=1&LH_Sold=1'
SOURCE = 'ebay_uk'
SEED_HIGH_VALUE_NAMES = ('Charizard', 'Pikachu', 'Umbreon', 'Espeon', 'Gengar', 'Dragonite')
NEGATIVE_TERMS = (
    'proxy', 'digital', 'jumbo', 'custom', 'fake', 'bundle', 'joblot', 'job lot',
    'pack', 'booster', 'sleeve', 'coin', 'code card', 'online code', 'empty',
    'poster', 'sticker', 'tin', 'box', 'playmat', 'deck box', 'graded card stand',
)
GRADED_TERMS = ('psa', 'bgs', 'cgc', 'ace grading', 'sgc')
CONDITION_PATTERNS: list[tuple[str, str]] = [
    (r'\b(psa|bgs|cgc|ace|sgc)\s*\d+(?:\.\d+)?\b', 'graded'),
    (r'\bnear\s*mint\b|\bnm\b', 'near_mint'),
    (r'\blight(?:ly)?\s*played\b|\blp\b|\bexcellent\b|\bex\b', 'light_played'),
    (r'\bmoderate(?:ly)?\s*played\b|\bmp\b|\bplayed\b', 'moderate_played'),
    (r'\bheavy(?:ily)?\s*played\b|\bhp\b', 'heavy_played'),
    (r'\bdamaged\b|\bdmg\b|\bpoor\b', 'damaged'),
]


@dataclass(frozen=True)
class CardSeed:
    card_id: str
    language_code: str | None
    card_name: str
    collector_number: str | None = None
    set_name: str | None = None
    set_code: str | None = None


@dataclass(frozen=True)
class Listing:
    card: CardSeed
    query: str
    raw_title: str
    price_gbp: float
    sold_date: str
    condition: str | None
    listing_url: str | None
    confidence_score: float
    match_notes: str
    source: str = SOURCE


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d_%H%M%S')


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def setup_logging(reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    log_path = reports_dir / f'ebay_uk_price_scraper_{stamp()}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(log_path, encoding='utf-8')],
    )
    return log_path


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript('''
CREATE TABLE IF NOT EXISTS uk_price_history (
    id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL,
    language_code TEXT,
    condition TEXT,
    price_gbp REAL NOT NULL,
    sold_date TEXT NOT NULL,
    listing_url TEXT,
    source TEXT DEFAULT 'ebay_uk',
    confidence_score REAL,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_uk_price_history_card ON uk_price_history(card_id, language_code);
CREATE INDEX IF NOT EXISTS idx_uk_price_history_sold_date ON uk_price_history(sold_date);
CREATE TABLE IF NOT EXISTS uk_price_scrape_failures (
    id INTEGER PRIMARY KEY,
    card_id TEXT,
    language_code TEXT,
    query TEXT,
    reason TEXT,
    raw_title TEXT,
    listing_url TEXT,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP
);
''')
    conn.commit()


def normalize_text(value: str | None) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip()).lower()


def compact_card_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', name.lower())


def parse_price(text: str) -> float | None:
    text = text.replace(',', '')
    match = re.search(r'£\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
    return float(match.group(1)) if match else None


def parse_sold_date(text: str) -> str | None:
    cleaned = re.sub(r'\bSold\b|\bEnded\b', '', text, flags=re.I).strip(' :\n\t')
    if not cleaned:
        return None
    today = dt.date.today()
    for fmt in ('%d %b %Y', '%d %B %Y', '%b %d, %Y', '%d %b'):
        try:
            parsed = dt.datetime.strptime(cleaned, fmt).date()
            if fmt == '%d %b':
                parsed = parsed.replace(year=today.year)
            return parsed.isoformat()
        except ValueError:
            continue
    return cleaned


def extract_condition(title: str) -> str | None:
    lower = normalize_text(title)
    for pattern, condition in CONDITION_PATTERNS:
        if re.search(pattern, lower, flags=re.I):
            return condition
    return None


def make_query(card: CardSeed) -> str:
    parts = [card.card_name]
    if card.collector_number:
        parts.append(card.collector_number)
    if card.set_name:
        parts.append(card.set_name)
    elif card.set_code:
        parts.append(card.set_code)
    parts.append('Pokémon card')
    return ' '.join(str(p) for p in parts if p)


def _dict_to_listing(row: dict[str, Any], card: CardSeed, query: str) -> Listing:
    """Convert an API-parsed dict row back to a Listing dataclass for CSV/insert compatibility."""
    return Listing(
        card=card,
        query=query,
        raw_title=row.get('raw_title', ''),
        price_gbp=row.get('price_gbp', 0.0),
        sold_date=row.get('sold_date', ''),
        condition=row.get('condition'),
        listing_url=row.get('listing_url'),
        confidence_score=row.get('confidence_score', 0.0),
        match_notes=row.get('match_notes', ''),
        source=row.get('source', SOURCE),
    )


def score_listing(card: CardSeed, title: str, *, raw_only: bool) -> tuple[float, list[str]]:
    lower = normalize_text(title)
    notes: list[str] = []
    score = 0.0
    name_norm = normalize_text(card.card_name)
    if name_norm and name_norm in lower:
        score += 0.45
        notes.append('name_exact')
    elif compact_card_name(card.card_name) and compact_card_name(card.card_name) in compact_card_name(title):
        score += 0.30
        notes.append('name_compact')
    if card.collector_number and normalize_text(card.collector_number) in lower:
        score += 0.20
        notes.append('collector_number')
    if card.set_name and normalize_text(card.set_name) in lower:
        score += 0.15
        notes.append('set_name')
    if card.set_code and normalize_text(card.set_code) in lower:
        score += 0.10
        notes.append('set_code')
    if 'pokemon' in lower or 'pokémon' in lower:
        score += 0.05
        notes.append('pokemon')
    negatives = [term for term in NEGATIVE_TERMS if term in lower]
    if negatives:
        score -= 0.35
        notes.append('negative_terms=' + '|'.join(negatives[:5]))
    graded = [term for term in GRADED_TERMS if re.search(rf'\b{re.escape(term)}\b', lower)]
    if graded:
        notes.append('graded=' + '|'.join(graded))
        if raw_only:
            score -= 0.25
    return max(0.0, min(1.0, round(score, 3))), notes


def item_text(item: Any, selector: str) -> str:
    found = item.select_one(selector)
    return found.get_text(' ', strip=True) if found else ''


def parse_listings(html: str, card: CardSeed, query: str, *, max_listings: int, raw_only: bool) -> tuple[list[Listing], list[dict[str, str]]]:
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('li.s-item')
    listings: list[Listing] = []
    failures: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in items:
        if len(listings) >= max_listings:
            break
        title = item_text(item, '.s-item__title')
        if not title or title.lower() == 'shop on ebay':
            continue
        price_text = item_text(item, '.s-item__price')
        price = parse_price(price_text)
        link_el = item.select_one('a.s-item__link')
        url = link_el.get('href') if link_el else ''
        if url:
            url = url.split('?')[0]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        date_text = ' '.join(
            part for part in [
                item_text(item, '.s-item__ended-date'),
                item_text(item, '.s-item__title--tagblock'),
                item_text(item, '.s-item__caption--signal'),
            ] if part
        )
        sold_date = parse_sold_date(date_text) or now_utc()[:10]
        if price is None:
            failures.append({'reason': 'missing_gbp_price', 'raw_title': title, 'listing_url': url or ''})
            continue
        score, notes = score_listing(card, title, raw_only=raw_only)
        condition = extract_condition(title)
        if condition:
            notes.append(f'condition={condition}')
        listing = Listing(
            card=card,
            query=query,
            raw_title=title,
            price_gbp=price,
            sold_date=sold_date,
            condition=condition,
            listing_url=url or None,
            confidence_score=score,
            match_notes=';'.join(notes),
        )
        listings.append(listing)
        if score < 0.45:
            failures.append({'reason': f'low_confidence_{score}', 'raw_title': title, 'listing_url': url or ''})
    return listings, failures


def fetch_ebay(query: str, *, timeout: int = 30) -> requests.Response:
    url = EBAY_SEARCH_URL.format(query=quote_plus(query))
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 SaveRoomPriceResearch/0.1',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    return requests.get(url, headers=headers, timeout=timeout)


def select_cards(conn: sqlite3.Connection, *, query: str | None, seed_high_value: bool, limit_cards: int) -> list[CardSeed]:
    if query:
        return [CardSeed(card_id=f'manual:{compact_card_name(query)[:40] or "query"}', language_code=None, card_name=query)]
    cur = conn.cursor()
    if seed_high_value:
        placeholders = ','.join('?' for _ in SEED_HIGH_VALUE_NAMES)
        sql = f'''
SELECT card_id, language_code, card_name, local_id, core_set_name, core_set_id
FROM v2_card_detail_api_cache
WHERE language_code='en' AND card_name IN ({placeholders})
ORDER BY CASE card_name
  WHEN 'Charizard' THEN 0 WHEN 'Pikachu' THEN 1 WHEN 'Umbreon' THEN 2
  WHEN 'Espeon' THEN 3 WHEN 'Gengar' THEN 4 WHEN 'Dragonite' THEN 5 ELSE 6 END,
  has_display_image DESC, resolved_release_date DESC, card_id
LIMIT ?
'''
        params: Iterable[Any] = (*SEED_HIGH_VALUE_NAMES, limit_cards)
    else:
        sql = '''
SELECT card_id, language_code, card_name, local_id, core_set_name, core_set_id
FROM v2_card_detail_api_cache
WHERE language_code='en'
ORDER BY has_display_image DESC, resolved_release_date DESC, card_id
LIMIT ?
'''
        params = (limit_cards,)
    rows = cur.execute(sql, tuple(params)).fetchall()
    return [CardSeed(
        card_id=row['card_id'],
        language_code=row['language_code'],
        card_name=row['card_name'],
        collector_number=row['local_id'],
        set_name=row['core_set_name'],
        set_code=row['core_set_id'],
    ) for row in rows]


def write_listing_csv(path: Path, listings: list[Listing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['card_id', 'language_code', 'card_name', 'collector_number', 'set_name', 'query', 'condition', 'price_gbp', 'sold_date', 'listing_url', 'source', 'confidence_score', 'raw_title', 'match_notes']
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in listings:
            writer.writerow({
                'card_id': item.card.card_id,
                'language_code': item.card.language_code,
                'card_name': item.card.card_name,
                'collector_number': item.card.collector_number,
                'set_name': item.card.set_name,
                'query': item.query,
                'condition': item.condition,
                'price_gbp': item.price_gbp,
                'sold_date': item.sold_date,
                'listing_url': item.listing_url,
                'source': item.source,
                'confidence_score': item.confidence_score,
                'raw_title': item.raw_title,
                'match_notes': item.match_notes,
            })


def write_failure_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['card_id', 'language_code', 'query', 'reason', 'raw_title', 'listing_url']
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def insert_listings(conn: sqlite3.Connection, listings: list[Listing], *, min_confidence: float) -> int:
    eligible = [item for item in listings if item.confidence_score >= min_confidence and not item.card.card_id.startswith('manual:')]
    conn.executemany('''
INSERT INTO uk_price_history (
  card_id, language_code, condition, price_gbp, sold_date, listing_url, source, confidence_score
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
''', [(
        item.card.card_id,
        item.card.language_code,
        item.condition,
        item.price_gbp,
        item.sold_date,
        item.listing_url,
        item.source,
        item.confidence_score,
    ) for item in eligible])
    conn.commit()
    return len(eligible)


def insert_failures(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    conn.executemany('''
INSERT INTO uk_price_scrape_failures (card_id, language_code, query, reason, raw_title, listing_url)
VALUES (?, ?, ?, ?, ?, ?)
''', [(r.get('card_id'), r.get('language_code'), r.get('query'), r.get('reason'), r.get('raw_title'), r.get('listing_url')) for r in rows])
    conn.commit()
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Scrape recent UK eBay sold listings for Pokémon card price history.')
    parser.add_argument('--db', default=str(DEFAULT_DB), help='SQLite database path.')
    parser.add_argument('--reports-dir', default=str(DEFAULT_REPORTS_DIR), help='Report/log directory.')
    parser.add_argument('--query', help='Manual eBay query, e.g. "Charizard 101 Pokémon card".')
    parser.add_argument('--seed-high-value', action='store_true', help='Use a DB-backed seed list: Charizard, Pikachu, Umbreon, Espeon, Gengar, Dragonite.')
    parser.add_argument('--limit-cards', type=int, default=10)
    parser.add_argument('--max-listings', type=int, default=20)
    parser.add_argument('--out-csv', help='Dry-run/listing CSV path. Defaults to reports/ebay_uk_price_test_<stamp>.csv.')
    parser.add_argument('--failures-csv', help='Failure/low-confidence CSV path. Defaults beside reports.')
    parser.add_argument('--dry-run', action='store_true', help='Explicit no-insert mode (default). Included for readable commands.')
    parser.add_argument('--insert', action='store_true', help='Insert high-confidence DB-backed rows into uk_price_history.')
    parser.add_argument('--min-confidence', type=float, default=0.45)
    parser.add_argument('--sleep-min', type=float, default=1.0)
    parser.add_argument('--sleep-max', type=float, default=2.0)
    parser.add_argument('--raw-only', action='store_true', help='Penalize PSA/BGS/CGC/ACE graded listings.')
    parser.add_argument('--use-api', action='store_true', default=True, help='Use eBay Buy API (Browse API) instead of HTML scraping. Default: on.')
    parser.add_argument('--use-html', action='store_true', help='Force HTML scraping fallback instead of API.')
    parser.add_argument('--ebay-env', default=None, help='eBay API environment: sandbox or production. Defaults to EBAY_ENV env var or sandbox.')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = Path(args.db).expanduser().resolve()
    reports_dir = Path(args.reports_dir).expanduser().resolve()
    log_path = setup_logging(reports_dir)
    out_csv = Path(args.out_csv).expanduser().resolve() if args.out_csv else reports_dir / f'ebay_uk_price_test_{stamp()}.csv'
    failures_csv = Path(args.failures_csv).expanduser().resolve() if args.failures_csv else reports_dir / f'ebay_uk_price_failures_{stamp()}.csv'

    conn = connect(db)
    ensure_tables(conn)
    cards = select_cards(conn, query=args.query, seed_high_value=args.seed_high_value, limit_cards=args.limit_cards)
    logging.info('Selected %s card/query seed(s)', len(cards))

    all_listings: list[Listing] = []
    all_failures: list[dict[str, str]] = []
    blocked = False

    use_api = args.use_api and not args.use_html
    api: EbayBuyAPI | None = None
    if use_api:
        try:
            api = EbayBuyAPI(env=args.ebay_env)
            logging.info('eBay Buy API client initialised (env=%s)', api.env)
        except ValueError as exc:
            logging.warning('eBay API credentials not configured: %s. Falling back to HTML scraping.', exc)
            use_api = False

    for index, card in enumerate(cards, start=1):
        query = args.query if args.query else make_query(card)
        logging.info('(%s/%s) Fetching eBay UK sold listings via %s: %s', index, len(cards), 'API' if use_api else 'HTML', query)
        listings, failures = [], []
        if use_api and api is not None:
            try:
                api_response = api.search(query, limit=args.max_listings, sold_items=True, completed_items=True)
                api_listings, api_failures = parse_api_listings(
                    api_response,
                    card_id=card.card_id,
                    language_code=card.language_code,
                    card_name=card.card_name,
                    collector_number=card.collector_number,
                    set_name=card.set_name,
                    set_code=card.set_code,
                    raw_only=args.raw_only,
                )
                # Convert API dict rows to Listing objects for CSV compatibility
                for row in api_listings:
                    row['query'] = query
                    all_listings.append(_dict_to_listing(row, card, query))
                for f in api_failures:
                    f.setdefault('card_id', card.card_id)
                    f.setdefault('language_code', card.language_code or '')
                    f.setdefault('query', query)
                all_failures.extend(api_failures)
                total = api_response.get('total', '?')
                logging.info('API returned %s listing(s) (total available: %s), %s audit row(s)', len(api_listings), total, len(api_failures))
            except RuntimeError as exc:
                logging.exception('API request failed for %s', query)
                all_failures.append({'card_id': card.card_id, 'language_code': card.language_code or '', 'query': query, 'reason': f'api_error:{exc}', 'raw_title': '', 'listing_url': ''})
        else:
            try:
                response = fetch_ebay(query)
            except requests.RequestException as exc:
                logging.exception('Request failed for %s', query)
                all_failures.append({'card_id': card.card_id, 'language_code': card.language_code or '', 'query': query, 'reason': f'request_failed:{exc}', 'raw_title': '', 'listing_url': ''})
                continue
            if response.status_code in (403, 429) or 'captcha' in response.text[:5000].lower():
                blocked = True
                reason = f'blocked_or_rate_limited_http_{response.status_code}'
                logging.error('%s for query %s', reason, query)
                all_failures.append({'card_id': card.card_id, 'language_code': card.language_code or '', 'query': query, 'reason': reason, 'raw_title': response.text[:200], 'listing_url': response.url})
                break
            if not response.ok:
                reason = f'http_{response.status_code}'
                logging.warning('%s for query %s', reason, query)
                all_failures.append({'card_id': card.card_id, 'language_code': card.language_code or '', 'query': query, 'reason': reason, 'raw_title': response.text[:200], 'listing_url': response.url})
                continue
            listings, failures = parse_listings(response.text, card, query, max_listings=args.max_listings, raw_only=args.raw_only)
        all_listings.extend(listings)
        for failure in failures:
            failure.update({'card_id': card.card_id, 'language_code': card.language_code or '', 'query': query})
        if not listings:
            failures.append({'card_id': card.card_id, 'language_code': card.language_code or '', 'query': query, 'reason': 'no_parseable_listings', 'raw_title': '', 'listing_url': response.url if not use_api else ''})
        all_failures.extend(failures)
        logging.info('Parsed %s listing(s), %s audit row(s)', len(listings), len(failures))
        if index < len(cards):
            time.sleep(random.uniform(args.sleep_min, args.sleep_max))

    write_listing_csv(out_csv, all_listings)
    write_failure_csv(failures_csv, all_failures)
    inserted = 0
    inserted_failures = 0
    if args.insert and not blocked:
        inserted = insert_listings(conn, all_listings, min_confidence=args.min_confidence)
        inserted_failures = insert_failures(conn, all_failures)
        logging.info('Inserted %s price row(s) and %s failure/audit row(s)', inserted, inserted_failures)
    summary = {
        'ok': not blocked,
        'blocked': blocked,
        'db': str(db),
        'cards': len(cards),
        'listings': len(all_listings),
        'failures_or_low_confidence': len(all_failures),
        'inserted': inserted,
        'inserted_failures': inserted_failures,
        'out_csv': str(out_csv),
        'failures_csv': str(failures_csv),
        'log': str(log_path),
        'sample_rows': [
            {
                'card_id': item.card.card_id,
                'language_code': item.card.language_code,
                'title': item.raw_title,
                'price_gbp': item.price_gbp,
                'sold_date': item.sold_date,
                'condition': item.condition,
                'confidence_score': item.confidence_score,
                'notes': item.match_notes,
                'url': item.listing_url,
            }
            for item in all_listings[:10]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if blocked else 0


if __name__ == '__main__':
    raise SystemExit(main())
