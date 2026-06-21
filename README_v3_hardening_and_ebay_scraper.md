# Pokémon DB v3 Hardening + UK eBay Price Scraper MVP

## Summary

Both Phase 1 (v3 hardening) and Phase 2 (eBay scraper MVP) are complete and verified.

---

## Phase 1 — v3 Hardening / Deployment Readiness

### What changed

- **`pokemon_db_v3_config.py`** — New config boundary module
  - `PokemonDBSettings` dataclass with `db`, `ui_dir`, `image_cache_dir`, `reports_dir`, `host`, `port`, `cors_origins`
  - Supports CLI args, env vars (`POKEMON_DB_*`), and safe defaults
  - `validate_settings()` checks paths before serving
  - `public_settings()` returns path-safe info for API responses
  - `startup_lines()` for console-only startup logging

- **`pokemon_db_v2_fastapi.py`** — Refactored
  - Uses `PokemonDBSettings` instead of hardcoded globals
  - `--db`, `--ui-dir`, `--image-cache-dir`, `--reports-dir`, `--host`, `--port`, `--cors-origin` CLI args
  - Startup logging shows DB/UI/image/report/bind/cache status
  - CORS defaults to `http://127.0.0.1:8765,http://localhost:8765` (not wildcard)
  - Health endpoint returns `runtime` (path-safe) instead of full local paths
  - Version bumped to `0.2.0`

- **`pokemon_db_v2_search_api.py`** — Updated
  - DB and reports paths now come from config
  - `--reports-dir` CLI arg added

- **`pokemon_db_v2_fastapi_smoke.py`** — Updated
  - Now checks `/ui/` endpoint
  - Checks a mounted cached image URL from real search results
  - Reports dir from config

### Local default still works

```bash
cd "/media/matt/Storage/Brain/Pokemon Card Database"
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi.py --host 127.0.0.1 --port 8765
```

### Portable run with explicit paths

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi.py \
  --db full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite \
  --ui-dir pokemon_db_v2_browser_ui \
  --image-cache-dir image_cache/webp_q72_512 \
  --host 0.0.0.0 \
  --port 8765
```

### Environment variables (optional, `POKEMON_DB_` prefix)

- `POKEMON_DB_DB`
- `POKEMON_DB_UI_DIR`
- `POKEMON_DB_IMAGE_CACHE_DIR`
- `POKEMON_DB_REPORTS_DIR`
- `POKEMON_DB_HOST`
- `POKEMON_DB_PORT`
- `POKEMON_DB_CORS_ORIGINS` (comma-separated)

### Smoke test

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi_smoke.py --base-url http://127.0.0.1:8765
```

### Verified state

```
PRAGMA quick_check: ok
cards: 298,688
v2_card_search: 298,688
v2_card_search_fts: 298,688
v2_card_detail_api_cache: 298,688
rows_without_display_image: 23,442
smoke_test: pass (all checks green)
```

---

## Phase 2 — UK eBay Price Scraper MVP

### What changed

- **`pokemon_db_v3_ebay_api.py`** — New eBay Buy API client
  - `EbayBuyAPI` class with OAuth 2.0 `client_credentials` grant
  - `search()` method using `/item_summary/search` endpoint
  - `parse_api_listings()` converts API responses to scraper row format
  - Supports sandbox and production via `EBAY_ENV` env var

- **`pokemon_db_v3_ebay_uk_price_scraper.py`** — Updated
  - `--use-api` (default) uses eBay Buy API instead of HTML scraping
  - `--use-html` forces HTML scraping fallback
  - `--ebay-env` selects sandbox or production
  - All other features unchanged (CSV logging, confidence scoring, etc.)

### DB tables created

```sql
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
```

### eBay API credentials

Set as environment variables:

```bash
export EBAY_CLIENT_ID="MatthewL-PokemonD-PRD-5dce64f37-59b0515f"
export EBAY_CLIENT_SECRET="<production-cert-id>"
export EBAY_ENV="production"
```

### Usage

Dry-run one query:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v3_ebay_uk_price_scraper.py \
  --query "Charizard 101 Pokémon card" \
  --max-listings 10 \
  --use-api
```

Dry-run DB-backed seed cards (5 high-value Charizard cards):

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v3_ebay_uk_price_scraper.py \
  --seed-high-value \
  --limit-cards 5 \
  --max-listings 5 \
  --use-api \
  --out-csv full_tcgdex/reports/ebay_uk_price_test.csv
```

Insert after reviewing CSV:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v3_ebay_uk_price_scraper.py \
  --seed-high-value \
  --limit-cards 5 \
  --max-listings 5 \
  --use-api \
  --insert \
  --min-confidence 0.45
```

Scale to 100 cards:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v3_ebay_uk_price_scraper.py \
  --seed-high-value \
  --limit-cards 100 \
  --max-listings 20 \
  --use-api \
  --out-csv full_tcgdex/reports/ebay_uk_price_100cards.csv
```

### Verified results

Test run on 5 Charizard cards from DB:
- **15 price rows inserted** into `uk_price_history`
- **5 failure/audit rows** inserted into `uk_price_scrape_failures`
- Prices range from £2.49 to £101.38 across different Charizard variants
- All listings have eBay UK URLs, confidence scores, and match notes

Sample data:
| Card ID | Title | Price (GBP) | Condition |
|---------|-------|-------------|-----------|
| B1a-013 | Charizard EX 011/080 Double Rare Wild Blaze | 10.79 | Ungraded |
| B1a-013 | Charizard ex SSR | 73.30 | Ungraded |
| B1a-013 | Charizard ex SSR | 97.96 | Ungraded |
| B1a-091 | Charizard EXSV3125/108SR | 101.38 | Ungraded |
| 2024sv-1 | Charizard 1 McDonald's Collection 2024 | 3.31-52.70 | Ungraded |

### Known limitations

- The Browse API returns active listings, not historical sold data (the `soldItems`/`completedItems` filters don't filter in the current API version)
- For true sold/completed data, consider the Trading API's `GetSellerTransactions` or `GetOrders` (requires user token, not app token)
- Confidence scoring is basic — name exact match gets 0.45, collector number 0.20, set name 0.15, "pokemon" keyword 0.05
- Negative terms (proxy, digital, fake, bundle, etc.) reduce score by 0.35
- Graded cards (PSA/BGS/CGC) are flagged; `--raw-only` mode penalizes them
