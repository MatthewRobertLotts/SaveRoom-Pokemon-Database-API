# v11 Admin UI

Tags: #type/project #status/needs-review

Status: IMPLEMENTED
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

The v11 Market Evidence admin UI is implemented as a panel in the existing browser UI (`pokemon_db_v2_browser_ui/`). It provides read-only inspection of TCGdex-sourced pricing evidence attached to v10 canonical identity.

## How to Open

1. Start the API server: `POKEMON_DB_REQUIRE_API_KEY= python pokemon_db_v2_fastapi.py`
2. Open http://127.0.0.1:8765/ui/
3. Scroll down to the "v11 Pricing Evidence" panel (below the existing Pricing Dashboard)

## Views / Features

### Source Health View

- Click "Check source health" to see TCGdex status (healthy/degraded/failing)
- Shows response time and last success timestamp

### SKU/Card Evidence Panel

- Enter a target ID (e.g., `cp-001` or a card key like `en:sv03-223`)
- Optionally filter by currency (USD/EUR)
- Click "Load evidence" to fetch observations and aggregates

### Observation List / Detail

The observations table shows:
- Observation ID
- Marketplace source (tcgplayer / cardmarket)
- Amount
- Currency
- Finish (normal / reverse_holo / holo / unknown)
- Listing type (market_price / active_listing)
- Match confidence (HIGH / MEDIUM / LOW / UNUSABLE) with color coding
- Match reason (why confidence was assigned)

### Aggregate Explanation

For each (currency, listing_type, finish) bucket:
- Median price
- Low / High range
- Observation count
- Confidence label and reason

### Manual Refresh

- Click "Refresh evidence" to trigger a TCGdex fetch for the entered target
- Confirmation dialog before executing
- Shows result (completed/failed) with counts

## What It Answers

- **What source returned**: Observations show marketplace (tcgplayer/cardmarket)
- **What was cached**: Raw responses stored in `v11_price_source_cache`
- **What was normalised**: Amount, currency, finish, listing_type columns
- **What matched**: Match reason explains identity attachment logic
- **What confidence was assigned**: Color-coded HIGH/MEDIUM/LOW/UNUSABLE
- **What aggregate was computed**: Median, low, high per bucket
- **Why exact pricing was or not allowed**: Confidence reason explains finish ambiguity

## Limitations

- Read-only inspection; bulk refresh is not supported (one target at a time)
- No sold-price evidence (TCGdex provides market prices only)
- No condition-specific pricing
- No finish enrichment (90.4% unknown finish remains)
- Refresh button requires manual target entry; no auto-discovery of targets

## Files Modified

| File | Change |
|------|--------|
| `pokemon_db_v2_browser_ui/index.html` | Added evidence panel section |
| `pokemon_db_v2_browser_ui/styles.css` | Added evidence panel styles |
| `pokemon_db_v2_browser_ui/app.js` | Added evidence panel JavaScript |
| `tests/test_v11_admin_ui_smoke.py` | Added 13 smoke tests |

## Links

- Related: [[V11_PRICE_API]]
- Related: [[V11_QUALITY_REPORT]]
