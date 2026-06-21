#!/usr/bin/env python3
"""Shopify-ready CSV/JSON export from the Pokémon DB v2 search layer.

Modes:
  search "charizard" --limit 50
  set svp --language-code en
  card en ex3-100

Exports are written under full_tcgdex/reports/ and are safe/read-only: this
script reads the v2 API cache/FTS tables and does not mutate card facts.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pokemon_db_v2_search_api import (  # noqa: E402
    CACHE_TABLE,
    DB,
    DETAIL_COLUMNS,
    REPORTS,
    connect,
    get_card_detail,
    normalize_row,
    search_cards,
    setup_fts,
)

VENDOR = 'SaveRoom'
PRODUCT_TYPE = 'Pokémon Single Card'
CSV_FIELDS = [
    'Handle', 'Title', 'Body (HTML)', 'Vendor', 'Product Category', 'Type', 'Tags',
    'Published', 'Option1 Name', 'Option1 Value', 'Variant SKU', 'Variant Inventory Tracker',
    'Variant Inventory Qty', 'Variant Inventory Policy', 'Variant Fulfillment Service',
    'Variant Price', 'Variant Requires Shipping', 'Variant Taxable', 'Image Src',
    'Image Alt Text', 'SEO Title', 'SEO Description', 'Status',
    'Metafield: custom.language_code [single_line_text_field]',
    'Metafield: custom.card_id [single_line_text_field]',
    'Metafield: custom.collector_number [single_line_text_field]',
    'Metafield: custom.core_set_id [single_line_text_field]',
    'Metafield: custom.resolved_set_id [single_line_text_field]',
    'Metafield: custom.rarity [single_line_text_field]',
    'Metafield: custom.image_confidence [single_line_text_field]',
    'Metafield: custom.export_readiness [single_line_text_field]',
]


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime('%Y-%m-%d_%H%M%S')


def slugify(value: str) -> str:
    text = value.lower().replace('é', 'e').replace('—', '-')
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return re.sub(r'-+', '-', text).strip('-')[:180] or 'pokemon-card'


def text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def display_set(card: dict[str, Any]) -> str:
    s = card.get('set') or {}
    return s.get('resolved_set_name') or s.get('core_set_name') or s.get('resolved_set_id') or s.get('core_set_id') or 'Unknown Set'


def language_name(card: dict[str, Any]) -> str:
    return card.get('language_name') or card.get('language_code') or 'Unknown Language'


def product_title(card: dict[str, Any]) -> str:
    number = f" — {card.get('collector_number')}" if card.get('collector_number') else ''
    return f"{card.get('name') or 'Unknown card'}{number} — {display_set(card)} — {language_name(card)} Pokémon Card"


def image_url(card: dict[str, Any]) -> str:
    images = card.get('images') or {}
    return images.get('display_image_url') or images.get('exact_image_url') or ''


def image_confidence(card: dict[str, Any]) -> str:
    images = card.get('images') or {}
    return images.get('display_image_source_type') or 'none'


def readiness(card: dict[str, Any]) -> str:
    images = card.get('images') or {}
    c = card.get('card') or {}
    prov = card.get('provenance') or {}
    has_detail = bool(c.get('rarity') or c.get('hp') or c.get('types') or (card.get('rules_text') or {}).get('description') or (card.get('rules_text') or {}).get('attacks'))
    has_prov = int(prov.get('v2_count') or 0) + int(prov.get('legacy_count') or 0) > 0
    if not images.get('has_display_image'):
        return 'needs_image'
    if not has_detail:
        return 'needs_detail'
    if not has_prov:
        return 'provenance_weak'
    if images.get('has_exact_image'):
        return 'ready'
    return 'usable_fallback_image'


def tags(card: dict[str, Any]) -> list[str]:
    c = card.get('card') or {}
    s = card.get('set') or {}
    return sorted(set(filter(None, [
        'Pokemon', 'Pokémon', 'Single Card', PRODUCT_TYPE, card.get('name'), display_set(card),
        language_name(card), c.get('rarity'), s.get('core_set_id'), s.get('resolved_set_id'),
        readiness(card), image_confidence(card),
    ])))


def body_html(card: dict[str, Any]) -> str:
    c = card.get('card') or {}
    s = card.get('set') or {}
    bits = [
        f"<p><strong>{text(card.get('name'))}</strong> from <strong>{text(display_set(card))}</strong>.</p>",
        '<ul>',
        f"<li>Language: {text(language_name(card))}</li>",
        f"<li>Collector number: {text(card.get('collector_number') or 'Unknown')}</li>",
        f"<li>Rarity: {text(c.get('rarity') or 'Unknown')}</li>",
        f"<li>Core set: {text(s.get('core_set_id') or '')}</li>",
        f"<li>Image source: {text(image_confidence(card))}</li>",
        '</ul>',
    ]
    return ''.join(bits)


def shopify_record(card: dict[str, Any], *, price: str = '', quantity: int = 0, status: str = 'draft') -> dict[str, Any]:
    title = product_title(card)
    c = card.get('card') or {}
    s = card.get('set') or {}
    handle = slugify(f"{card.get('name')} {card.get('collector_number')} {display_set(card)} {card.get('language_code')} {card.get('card_id')}")
    seo = f"{card.get('name') or 'Pokémon card'} from {display_set(card)} ({language_name(card)}). Collector number {card.get('collector_number') or 'unknown'}; rarity {c.get('rarity') or 'unknown'}."
    return {
        'Handle': handle,
        'Title': title,
        'Body (HTML)': body_html(card),
        'Vendor': VENDOR,
        'Product Category': 'Toys & Games > Games > Card Games',
        'Type': PRODUCT_TYPE,
        'Tags': ', '.join(tags(card)),
        'Published': 'FALSE',
        'Option1 Name': 'Condition',
        'Option1 Value': 'Near Mint',
        'Variant SKU': f"PKM-{card.get('language_code','xx').upper()}-{slugify(card.get('card_id') or '')}"[:64],
        'Variant Inventory Tracker': 'shopify',
        'Variant Inventory Qty': str(quantity),
        'Variant Inventory Policy': 'deny',
        'Variant Fulfillment Service': 'manual',
        'Variant Price': price,
        'Variant Requires Shipping': 'TRUE',
        'Variant Taxable': 'TRUE',
        'Image Src': image_url(card),
        'Image Alt Text': title,
        'SEO Title': title[:70],
        'SEO Description': seo[:320],
        'Status': status,
        'Metafield: custom.language_code [single_line_text_field]': card.get('language_code') or '',
        'Metafield: custom.card_id [single_line_text_field]': card.get('card_id') or '',
        'Metafield: custom.collector_number [single_line_text_field]': card.get('collector_number') or '',
        'Metafield: custom.core_set_id [single_line_text_field]': s.get('core_set_id') or '',
        'Metafield: custom.resolved_set_id [single_line_text_field]': s.get('resolved_set_id') or '',
        'Metafield: custom.rarity [single_line_text_field]': c.get('rarity') or '',
        'Metafield: custom.image_confidence [single_line_text_field]': image_confidence(card),
        'Metafield: custom.export_readiness [single_line_text_field]': readiness(card),
    }


def app_json_record(card: dict[str, Any], shopify: dict[str, Any]) -> dict[str, Any]:
    return {
        'shopify': shopify,
        'card': card,
        'export': {
            'readiness': readiness(card),
            'image_url': image_url(card),
            'image_confidence': image_confidence(card),
            'tags': tags(card),
        },
    }


def ensure_support(db: Path) -> None:
    conn = connect(db)
    cur = conn.cursor()
    try:
        fts = cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='v2_card_search_fts'").fetchone()[0]
        cache = cur.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE name='{CACHE_TABLE}'").fetchone()[0]
        if fts and cache:
            return
    finally:
        conn.close()
    setup_fts(db)


def detail_from_cache(conn: sqlite3.Connection, language_code: str, card_id: str) -> dict[str, Any] | None:
    cols = ', '.join(DETAIL_COLUMNS)
    row = conn.execute(f"SELECT {cols} FROM {CACHE_TABLE} WHERE language_code=? AND card_id=? LIMIT 1", (language_code, card_id)).fetchone()
    return normalize_row(dict(row), detail=True) if row else None


def product_key(card: dict[str, Any]) -> tuple[str, str, str, str]:
    s = card.get('set') or {}
    return (
        card.get('language_code') or '',
        s.get('core_set_id') or s.get('resolved_set_id') or s.get('raw_set_id') or '',
        card.get('collector_number') or '',
        card.get('name') or '',
    )


def product_score(card: dict[str, Any]) -> tuple[int, int, int, int]:
    images = card.get('images') or {}
    prov = card.get('provenance') or {}
    c = card.get('card') or {}
    return (
        1 if images.get('has_exact_image') else 0,
        1 if images.get('has_display_image') else 0,
        int(prov.get('v2_count') or 0) + int(prov.get('legacy_count') or 0),
        sum(1 for v in [c.get('rarity'), c.get('hp'), c.get('types'), c.get('stage'), c.get('illustrator')] if v),
    )


def dedupe_products(cards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for card in cards:
        key = product_key(card)
        if key not in best or product_score(card) > product_score(best[key]):
            best[key] = card
    return list(best.values()), len(cards) - len(best)


def fetch_cards(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    db = Path(args.db)
    ensure_support(db)
    conn = connect(db)
    start = time.perf_counter()
    meta: dict[str, Any] = {'mode': args.command}
    cards: list[dict[str, Any]] = []
    if args.command == 'search':
        summaries, elapsed = search_cards(conn, args.query, language_code=args.language_code, core_set_id=args.core_set_id, has_display_image=args.has_display_image, limit=args.limit)
        for c in summaries:
            detail = detail_from_cache(conn, c['language_code'], c['card_id'])
            if detail:
                cards.append(detail)
        meta.update({'query': args.query, 'search_elapsed_ms': round(elapsed, 3)})
    elif args.command == 'set':
        summaries, elapsed = search_cards(conn, '', language_code=args.language_code, core_set_id=args.core_set_id, has_display_image=args.has_display_image, limit=args.limit)
        for c in summaries:
            detail = detail_from_cache(conn, c['language_code'], c['card_id'])
            if detail:
                cards.append(detail)
        meta.update({'core_set_id': args.core_set_id, 'search_elapsed_ms': round(elapsed, 3)})
    elif args.command == 'card':
        detail, elapsed = get_card_detail(conn, args.language_code, args.card_id)
        cards = [detail] if detail else []
        meta.update({'language_code': args.language_code, 'card_id': args.card_id, 'detail_elapsed_ms': round(elapsed, 3)})
    meta['fetch_elapsed_ms'] = round((time.perf_counter() - start) * 1000, 3)
    before_dedupe = len(cards)
    if not getattr(args, 'include_duplicates', False):
        cards, removed = dedupe_products(cards)
    else:
        removed = 0
    meta['rows_before_product_dedupe'] = before_dedupe
    meta['product_duplicates_removed'] = removed
    return cards, meta


def write_outputs(cards: list[dict[str, Any]], meta: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    prefix = args.out_prefix or f"v2_shopify_export_{meta['mode']}_{stamp()}"
    csv_path = REPORTS / f'{prefix}.csv'
    json_path = REPORTS / f'{prefix}.json'
    report_path = REPORTS / f'{prefix}_verification.json'
    shopify_rows = [shopify_record(c, price=args.price, quantity=args.quantity, status=args.status) for c in cards]
    json_rows = [app_json_record(c, s) for c, s in zip(cards, shopify_rows)]

    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(shopify_rows)
    json_path.write_text(json.dumps({'generated_at': now_utc(), 'meta': meta, 'count': len(json_rows), 'records': json_rows}, ensure_ascii=False, indent=2), encoding='utf-8')

    readiness_counts: dict[str, int] = {}
    image_counts: dict[str, int] = {}
    for card in cards:
        readiness_counts[readiness(card)] = readiness_counts.get(readiness(card), 0) + 1
        image_counts[image_confidence(card)] = image_counts.get(image_confidence(card), 0) + 1
    report = {
        'generated_at': now_utc(),
        'database': str(Path(args.db)),
        'meta': meta,
        'count': len(cards),
        'csv_path': str(csv_path),
        'json_path': str(json_path),
        'readiness_counts': readiness_counts,
        'image_confidence_counts': image_counts,
        'sample_titles': [product_title(c) for c in cards[:5]],
        'pass': len(cards) > 0 and csv_path.exists() and json_path.exists(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**report, 'report_path': str(report_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Export Shopify-ready Pokémon card product CSV/JSON from v2.')
    parser.add_argument('--db', default=str(DB))
    parser.add_argument('--out-prefix', help='Output filename prefix under reports/.')
    parser.add_argument('--price', default='', help='Optional Variant Price value. Blank by default.')
    parser.add_argument('--quantity', type=int, default=0, help='Default inventory quantity. Default 0/draft.')
    parser.add_argument('--status', default='draft', choices=['draft', 'active', 'archived'])
    parser.add_argument('--include-duplicates', action='store_true', help='Keep alias/raw duplicate product rows instead of deduping by language/core set/collector/name.')
    sub = parser.add_subparsers(dest='command', required=True)

    search = sub.add_parser('search')
    search.add_argument('query')
    search.add_argument('--limit', type=int, default=50)
    search.add_argument('--language-code')
    search.add_argument('--core-set-id')
    search.add_argument('--has-display-image', action='store_true')

    set_cmd = sub.add_parser('set')
    set_cmd.add_argument('core_set_id')
    set_cmd.add_argument('--limit', type=int, default=500)
    set_cmd.add_argument('--language-code')
    set_cmd.add_argument('--has-display-image', action='store_true')

    card = sub.add_parser('card')
    card.add_argument('language_code')
    card.add_argument('card_id')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cards, meta = fetch_cards(args)
    result = write_outputs(cards, meta, args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
