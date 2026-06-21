#!/usr/bin/env python3
"""UK eBay sold-price scraper using the RapidAPI eBay Average Selling Price API.

This is a drop-in replacement for the HTML scraping / Browse API approaches.
It returns actual sold/completed listing prices from eBay UK.

Required env var: RAPIDAPI_KEY (get free key at rapidapi.com → eBay Average Selling Price API)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from pokemon_db_v3_config import DEFAULT_DB, DEFAULT_REPORTS_DIR

logger = logging.getLogger(__name__)

RAPIDAPI_URL = "https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems"
RAPIDAPI_HOST = "ebay-average-selling-price.p.rapidapi.com"
EBAY_UK_SITE_ID = "3"

# eBay category IDs for trading cards
# 183050 = "Trading Cards" — broad but helps focus results
TCG_CATEGORY_ID = "183050"

NEGATIVE_KEYWORDS = "proxy digital jumbo custom fake bundle joblot pack booster sleeve code online empty poster tin box playmat"


def get_rapidapi_key() -> str:
    key = os.environ.get("RAPIDAPI_KEY", "")
    if not key:
        raise ValueError(
            "RAPIDAPI_KEY env var is required. "
            "Get a free key at https://rapidapi.com/ecommet/api/ebay-average-selling-price"
        )
    return key


def search_ebay_sold(
    query: str,
    *,
    max_results: int = 60,
    rapidapi_key: str | None = None,
    category_id: str | None = None,
    exclude: str = NEGATIVE_KEYWORDS,
) -> dict[str, Any]:
    """Search eBay UK sold listings via RapidAPI.

    Returns the raw API response dict with keys:
    success, average_price, median_price, min_price, max_price,
    results, total_results, response_url, products[]
    """
    key = rapidapi_key or get_rapidapi_key()
    payload: dict[str, Any] = {
        "keywords": query,
        "max_search_results": str(max_results),
        "site_id": EBAY_UK_SITE_ID,
        "remove_outliers": False,
    }
    if category_id:
        payload["category_id"] = category_id
    if exclude:
        payload["excluded_keywords"] = exclude

    resp = requests.post(
        RAPIDAPI_URL,
        headers={
            "Content-Type": "application/json",
            "x-rapidapi-host": RAPIDAPI_HOST,
            "x-rapidapi-key": key,
        },
        data=json.dumps(payload),
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"RapidAPI error (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.json()


def parse_sold_response(
    response: dict[str, Any],
    card_id: str,
    card_name: str,
    collector_number: str | None = None,
    set_name: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse API response into sold listing rows + summary stats.

    Returns (listings, summary) where each listing has:
    card_id, title, sale_price, currency, condition, date_sold, link
    """
    products = response.get("products", [])
    listings: list[dict[str, Any]] = []

    for p in products:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        listings.append({
            "card_id": card_id,
            "card_name": card_name,
            "collector_number": collector_number,
            "set_name": set_name,
            "title": title,
            "sale_price": p.get("sale_price", 0),
            "currency": p.get("currency", "GBP"),
            "condition": p.get("condition", ""),
            "date_sold": p.get("date_sold", ""),
            "buying_format": p.get("buying_format", ""),
            "shipping_price": p.get("shipping_price"),
            "link": p.get("link", ""),
            "item_id": p.get("item_id", ""),
        })

    summary = {
        "card_id": card_id,
        "card_name": card_name,
        "average_price": response.get("average_price"),
        "median_price": response.get("median_price"),
        "min_price": response.get("min_price"),
        "max_price": response.get("max_price"),
        "results_returned": response.get("results", 0),
        "total_results": response.get("total_results", 0),
    }
    return listings, summary


def build_query(card_name: str, collector_number: str | None = None, set_name: str | None = None) -> str:
    parts = [card_name]
    if collector_number:
        parts.append(collector_number)
    if set_name:
        parts.append(set_name)
    parts.append("Pokémon card")
    return " ".join(str(p) for p in parts if p)


def setup_logging(reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    log_path = reports_dir / f"ebay_sold_scraper_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )
    return log_path


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
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
    """)
    conn.commit()


def select_cards(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict[str, Any]]:
    """Select English cards with display images, prioritizing iconic names."""
    iconic = [
        "Charizard", "Pikachu", "Umbreon", "Espeon", "Gengar", "Dragonite",
        "Mewtwo", "Mew", "Rayquaza", "Groudon", "Kyogre", "Arceus",
        "Darkrai", "Giratina", "Lugia", "Ho-Oh", "Celebi", "Deoxys",
        "Lucario", "Garchomp", "Tyranitar", "Salamence", "Metagross",
        "Gardevoir", "Gengar", "Alakazam", "Machamp", "Gyarados",
    ]
    placeholders = ",".join("?" for _ in iconic)
    cur = conn.cursor()
    rows = cur.execute(f"""
        SELECT card_id, card_name, local_id, core_set_name, core_set_id, rarity
        FROM v2_card_detail_api_cache
        WHERE language_code='en' AND card_name IN ({placeholders})
        AND has_display_image=1
        ORDER BY CASE card_name
            WHEN 'Charizard' THEN 0 WHEN 'Pikachu' THEN 1 WHEN 'Umbreon' THEN 2
            WHEN 'Espeon' THEN 3 WHEN 'Gengar' THEN 4 WHEN 'Dragonite' THEN 5
            WHEN 'Mewtwo' THEN 6 WHEN 'Mew' THEN 7 ELSE 8
        END, resolved_release_date DESC, card_id
        LIMIT ?
    """, (*iconic, limit)).fetchall()

    return [
        {
            "card_id": r[0],
            "card_name": r[1],
            "collector_number": r[2],
            "set_name": r[3],
            "set_id": r[4],
        }
        for r in rows
    ]


def write_csv(path: Path, listings: list[dict[str, Any]]) -> None:
    if not listings:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(listings[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(listings)


def write_summary_csv(path: Path, summaries: list[dict[str, Any]]) -> None:
    if not summaries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(summaries[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summaries)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape UK eBay SOLD prices via RapidAPI.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--limit-cards", type=int, default=10)
    parser.add_argument("--max-results", type=int, default=60, help="API results per card (60/120/240)")
    parser.add_argument("--out-csv", help="Output CSV for individual sold listings")
    parser.add_argument("--summary-csv", help="Output CSV for per-card summary stats")
    parser.add_argument("--insert", action="store_true", help="Insert into uk_price_history")
    parser.add_argument("--dry-run", action="store_true", help="Don't insert, just report")
    parser.add_argument("--sleep", type=float, default=3.0, help="Sleep between API calls (seconds)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = Path(args.db).expanduser().resolve()
    reports_dir = Path(args.reports_dir).expanduser().resolve()
    log_path = setup_logging(reports_dir)

    key = get_rapidapi_key()
    conn = sqlite3.connect(db)
    ensure_tables(conn)
    cards = select_cards(conn, limit=args.limit_cards)

    logging.info("Selected %d cards, max %d results per card", len(cards), args.max_results)

    all_listings: list[dict[str, Any]] = []
    all_summaries: list[dict[str, Any]] = []
    errors = 0

    for i, card in enumerate(cards, start=1):
        query = build_query(card["card_name"], card.get("collector_number"), card.get("set_name"))
        logging.info("(%d/%d) %s → %s", i, len(cards), card["card_id"], query)

        try:
            resp = search_ebay_sold(query, max_results=args.max_results, rapidapi_key=key)
            listings, summary = parse_sold_response(
                resp,
                card_id=card["card_id"],
                card_name=card["card_name"],
                collector_number=card.get("collector_number"),
                set_name=card.get("set_name"),
            )
            all_listings.extend(listings)
            all_summaries.append(summary)

            logging.info(
                "  %d sold listings | median £%s | range £%s–£%s",
                summary["results_returned"],
                summary["median_price"],
                summary["min_price"],
                summary["max_price"],
            )

            if args.insert and not args.dry_run:
                for row in listings:
                    conn.execute(
                        """INSERT INTO uk_price_history
                        (card_id, language_code, condition, price_gbp, sold_date, listing_url, source)
                        VALUES (?, ?, ?, ?, ?, ?, 'ebay_uk_sold')""",
                        (
                            row["card_id"],
                            "en",
                            row.get("condition"),
                            row["sale_price"],
                            row["date_sold"],
                            row["link"],
                        ),
                    )
                conn.commit()

        except Exception as e:
            errors += 1
            logging.error("  Error: %s", e)
            conn.execute(
                "INSERT INTO uk_price_scrape_failures (card_id, language_code, query, reason) VALUES (?, ?, ?, ?)",
                (card["card_id"], "en", query, str(e)[:200]),
            )
            conn.commit()

        if i < len(cards):
            time.sleep(args.sleep)

    # Write CSVs
    out_csv = Path(args.out_csv) if args.out_csv else reports_dir / f"ebay_sold_listings_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    summary_csv = Path(args.summary_csv) if args.summary_csv else reports_dir / f"ebay_sold_summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    write_csv(out_csv, all_listings)
    write_summary_csv(summary_csv, all_summaries)

    inserted = len(all_listings) if args.insert and not args.dry_run else 0
    result = {
        "ok": True,
        "cards_searched": len(cards),
        "total_sold_listings": len(all_listings),
        "inserted": inserted,
        "errors": errors,
        "out_csv": str(out_csv),
        "summary_csv": str(summary_csv),
        "log": str(log_path),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
