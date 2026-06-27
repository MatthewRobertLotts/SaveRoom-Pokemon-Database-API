# v11 Source Validation — Market Evidence Foundation

Tags: #type/project #status/needs-review

Status: VALIDATED
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

This document records the results of validating candidate pricing sources for v11.0 market evidence foundation. Each candidate was checked for reachability, data quality, caching viability, and compatibility with the v10 canonical/commercial/SKU identity model.

## Candidate Sources Evaluated

### 1. TCGdex (api.tcgdex.net)

**Verdict: CHOSEN AS FIRST SOURCE**

| Criterion | Result |
|-----------|--------|
| Reachable | Yes — HTTP 200, ~50ms response time |
| API key required | No |
| Free tier | Entirely free, no authentication |
| Pokémon coverage | Yes — 23,315 cards across all sets/languages |
| Condition data | No — market-level pricing only |
| Finish awareness | Partial — separate pricing for normal/reverse/holo |
| Marketplace source | TCGPlayer (USD) + Cardmarket (EUR) |
| Sold vs active | Active listings (market prices, not sold) |
| Rate limits | None observed (5 rapid requests OK) |
| Caching | No explicit restrictions; responses are public data |
| Terms | Open-source project, data from Cardmarket/TCGPlayer |
| Update frequency | TCGPlayer: hourly-daily, Cardmarket: daily |

**Data available per card:**
- Cardmarket: avg, low, trend, avg1, avg7, avg30 (normal + holo variants)
- TCGPlayer: lowPrice, midPrice, highPrice, marketPrice, directLowPrice (normal, reverse, holo variants)

**Strengths:**
- Free, no key, no rate limits
- Two marketplaces in one call
- Variant-level pricing (normal/reverse/holo)
- Historical averages (1/7/30 day)
- Fast and reliable
- Covers all languages

**Limitations:**
- No condition-specific pricing (only market-level)
- No sold-price data (active listings only)
- No finish granularity beyond normal/reverse/holo
- Card IDs are TCGdex internal IDs, not collector numbers
- No search by name that works reliably (must fetch by ID or iterate full list)
- TCGPlayer `lowPrice` can be outlier (lowest listed, not typical)

**Integration approach:**
1. Fetch full card detail by TCGdex ID
2. Extract pricing from `pricing.tcgplayer` and `pricing.cardmarket`
3. Match TCGdex card IDs to v10 canonical printings via set + collector number
4. Store raw response in cache table
5. Normalise into observations with confidence scoring

### 2. JustTCG (api.justtcg.com)

**Verdict: REJECTED — requires paid API key**

| Criterion | Result |
|-----------|--------|
| Reachable | Yes |
| API key required | Yes — returns 401 without key |
| Free tier | No — requires sign-up + subscription |
| Pokémon coverage | Yes (including Japanese OCG) |
| Condition data | Yes — condition-specific pricing |
| Finish awareness | Yes |
| Caching | Requires key |

**Reason for rejection:** Cannot use without API key. Cannot store key for development. Condition-specific pricing is valuable but requires paid access.

### 3. PokéWallet (api.pokewallet.io)

**Verdict: REJECTED — requires API key**

| Criterion | Result |
|-----------|--------|
| Reachable | Unknown (not tested) |
| API key required | Yes |
| Free tier | Limited |
| Pokémon coverage | Yes |

**Reason for rejection:** Requires API key. Not viable for development without key.

### 4. eBay Browse API

**Verdict: REJECTED — requires OAuth, no free tier**

| Criterion | Result |
|-----------|--------|
| Reachable | Yes |
| API key required | Yes (OAuth app token) |
| Free tier | No |
| Pokémon coverage | Yes |
| Condition data | Yes |
| Sold vs active | Both available |

**Reason for rejection:** Requires paid developer account. The legacy v3 scraper is broken. OAuth flow is complex for a background pricing pipeline.

## Chosen Source: TCGdex

TCGdex is the first source for v11.0 because:
1. **Free and keyless** — can be queried reliably now with no credentials
2. **Multi-marketplace** — TCGPlayer + Cardmarket in one call
3. **Variant-aware** — separate pricing for normal/reverse/holo
4. **Fresh** — updates hourly-daily
5. **Fast** — ~50ms per request
6. **Legal** — open data aggregation, no scraping required
7. **Reliable** — no rate limits observed, consistent responses

## Integration Architecture

```
TCGdex API
    ↓
pricing_sources/tcgdex.py (adapter)
    ↓
Raw response → v11_price_source_cache
    ↓
Normalise → v11_price_observations
    ↓
Match → v11_price_observation_matches
    ↓
Aggregate → v11_price_aggregates
    ↓
API endpoints → /api/v1/prices/...
```

## Matching Strategy

TCGdex uses internal card IDs (e.g., `swsh3-136`). To match to v10 identity:

1. Fetch TCGdex card detail → get `set.id` and `localId` (collector number)
2. Match `set.id` to v10 `set_code` (e.g., `swsh3` → `swsh3`)
3. Match `localId` to v10 `collector_number` (e.g., `136` → `136`)
4. This gives a canonical printing match
5. Variant (normal/reverse/holo) maps to v10 commercial variant finish

**Confidence implications:**
- Exact set + number match → HIGH confidence for canonical printing
- Variant match depends on TCGdex variant flags vs v10 finish values
- Cards not in TCGdex → no evidence (not LOW, just absent)
- Common cards with thin market → LOW confidence (high price dispersion)

## Data Quality Notes

1. **TCGPlayer `lowPrice` is misleading** — it's the lowest listed price, which can be an outlier. Use `marketPrice` as primary indicator.
2. **Cardmarket `avg` is reliable** — it's the average selling price over 30 days.
3. **Holo/normal separation** — TCGdex provides separate pricing for normal, reverse-holo, and holo variants. This maps well to v10 finish model.
4. **No condition data** — all TCGdex prices are market-level aggregates. We cannot distinguish Mint vs Played prices. This means v11 observations will be indicative, not SKU-exact.

## Links

- Related: [[V11_PREFLIGHT]]
- Related: [[V11_MARKET_EVIDENCE_MODEL]]
- TCGdex docs: https://tcgdex.dev/markets-prices
- TCGdex card object: https://tcgdex.dev/reference/card
