# Pokémon DB v4 — Pricing Pipeline + Private GitHub Setup

## Scope

v4 adds local-first pricing controls around the RapidAPI eBay Average Selling Price integration. Dashboard, queue, history, and batch-estimate endpoints use the local SQLite database only unless the user explicitly presses a fetch button or calls `/api/prices/fetch` for a missing/stale cache entry.

## Cost guard

- RapidAPI key is read from `RAPIDAPI_KEY`, `/tmp/rapidapi_key.txt`, or `/home/matt/.hermes/hermes-agent/rapidapi_key.txt`.
- Default local monthly guard: `POKEMON_PRICE_MONTHLY_LIMIT=1400`.
- Default cache TTL: `POKEMON_PRICE_CACHE_TTL_HOURS=168`.
- Same query + language + max_results cache key returns cached data and spends 0 extra requests.
- Dashboard, usage, history, queue generation, and batch estimate spend 0 requests.

## New/updated API endpoints

```text
GET  /api/prices/usage
GET  /api/prices/dashboard
GET  /api/prices/history?card_id=...&language_code=...&bucket=raw&limit=50
POST /api/prices/batch-estimate
GET  /api/prices/queue/high-value?language_code=en&limit=500
GET  /api/prices/fetch?query=...&max_results=60&language=en&card_id=...
```

`/api/prices/fetch` still performs the live RapidAPI call when the cache is missing/stale (unless blocked by the local guard). When it receives live data, it now stores cleaned/enriched listing rows into `uk_price_history` with bucket/provenance fields.

## v4 DB migration

The app safely creates or alters local price tables. `uk_price_history` retains existing rows and adds these v4 columns when missing:

```text
raw_title
bucket
match_notes
query
source_site
is_recommended_input
cache_key
fetched_at
```

No price/history table is dropped. Duplicate live-listing inserts are avoided by checking `card_id + language_code + listing_url + sold_date + price_gbp` before inserting.

## Browser UI

The browser UI now has a visible **Pricing Dashboard** section showing:

- monthly RapidAPI usage and remaining local guard;
- cached query count;
- price-history/listing counts;
- distinct cards with sold/active prices;
- top priced cards;
- recently fetched queries;
- recent failed fetches;
- guard warning when usage is close to the local limit.

Card detail pricing no longer silently spends a request on modal open. It shows stored recent raw sample listings and a clear **Fetch/update UK sold prices** button. Pressing that button confirms spend risk and uses cache first.

## Visible-results batch flow

The **Fetch prices for visible results** button:

1. sends only the currently visible result cards (max 50) to `/api/prices/batch-estimate`;
2. reports visible cards, cached/deduped rows, estimated new RapidAPI requests, current monthly usage, and remaining guard;
3. blocks if the estimate exceeds the local guard;
4. asks for confirmation before spending;
5. runs sequential client-side calls to `/api/prices/fetch`, with a brief delay between cards;
6. updates progress and refreshes the dashboard/search after completion.

## High-value queue

`GET /api/prices/queue/high-value?language_code=en&limit=500` generates a CSV under `full_tcgdex/reports/` without fetching prices. It prioritizes English high-value/hobby-relevant names and rarity terms, excludes Energy and low-value Trainer rows by default, deduplicates by query, and estimates which rows would require a new request.

## Language-specific pricing rule

Prices are stored with `language_code`. Non-English queries include a language hint where useful. If a language-specific eBay UK search is sparse or returns no usable raw rows, that is recorded as no evidence; the UI does not silently show English prices as a fallback.

## Start and verify

```bash
cd "/media/matt/Storage/Brain/Pokemon Card Database"
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/ui/
http://127.0.0.1:8765/api/prices/dashboard
```

Cached no-spend proof pattern:

```bash
curl 'http://127.0.0.1:8765/api/prices/fetch?query=Charizard%20ex%20223%20Obsidian%20Flames%20Pok%C3%A9mon%20card&max_results=60&language=en&card_id=sv03-223' | python3 -m json.tool
```

Expected: `cached: true` and `cost_guard.spent_request: false` when the cache is fresh.
