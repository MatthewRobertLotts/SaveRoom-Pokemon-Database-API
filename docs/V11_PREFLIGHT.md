# v11 Preflight — Market Evidence Foundation

Tags: #type/project #status/needs-review

Status: PREFLIGHT_COMPLETE
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation
Commit: ddb6ec2 (v10.0.0)
Working tree: clean

## Overview

This document captures the preflight state before implementing v11 market evidence schema and pipeline. It records what exists, what is missing, and the implementation sequence.

## Current v10 Identity Counts

```text
Total cards:            298,688
Mapped cards:           297,194 / 99.5%
Unmapped cards:         1,494 / 0.5%
Canonical printings:    121,771
Card links:             297,194
Commercial variants:    208,894
Sellable SKUs:          208,894
External references:    187,102
Build runs:             1
High confidence:        121,771
```

## Existing Pricing Tables / Code

### Legacy tables (still present in DB)

| Table | Era | Purpose |
|-------|-----|---------|
| `uk_price_history` | v3 | eBay UK sold-price scraper results (3,848 rows) |
| `uk_price_fetch_cache` | v3 | RapidAPI eBay cache |
| `uk_price_fetch_usage` | v3 | RapidAPI quota tracking |
| `uk_price_scrape_failures` | v3 | Scrape failure log |

### v8 pricing tables (present in DB, schema migrations v9-v17)

| Table | Purpose |
|-------|---------|
| `price_observations` | Immutable source evidence from provider |
| `price_observation_matches` | Algorithm interpretation linking observations to identities |
| `price_calculation_runs` | Reproducible calculation metadata |
| `price_snapshots` | Published reproducible price records |

### Current pricing API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/prices/cards/{card_key}` | Card price summary (v1 contract) |
| GET | `/api/v1/prices/history/cards/{card_key}` | Card price history (v1 contract) |
| GET | `/api/prices/summary` | Legacy price summary |
| GET | `/api/prices/history` | Legacy price history |
| GET | `/api/prices/top` | Top priced cards |
| GET | `/api/prices/usage` | RapidAPI usage stats |
| GET | `/api/prices/dashboard` | Pricing dashboard data |
| POST | `/api/prices/batch-estimate` | Batch price estimation |
| GET | `/api/prices/queue/high-value` | High-value queue |
| GET | `/api/prices/fetch` | Live RapidAPI fetch (internal) |

### Key pricing source files

| File | Purpose |
|------|---------|
| `pokemon_db_v3_ebay_uk_price_scraper.py` | v3 eBay UK HTML scraper |
| `pokemon_db_v3_ebay_api.py` | v3 eBay Buy API client |
| `pokemon_db_v3_ebay_sold_scraper.py` | v3 RapidAPI eBay sold scraper |
| `pokemon_db_v2_fastapi.py` | Main API (6,518 lines), contains v8 pricing pipeline |

### v8 pricing algorithm

- Algorithm version: `pricing-v8.0`
- Identity classification: `exact_match`, `variant_match`, `identity_unknown`, `no_match`
- Selection order: identity classification → condition filter → postage filter → IQR trimming
- Confidence scoring: `HIGH` / `MEDIUM` / `LOW` with reasons and weaknesses
- Source: RapidAPI eBay Average Selling Price (active listings, not confirmed sold)

## What v11 Must Add

### New schema (v11_ prefixed, non-destructive)

1. `v11_price_sources` — source registry
2. `v11_price_source_cache` — raw response cache
3. `v11_price_observations` — normalised observations
4. `v11_price_observation_matches` — observation-to-identity matching
5. `v11_price_aggregates` — conservative aggregate valuations
6. `v11_price_refresh_runs` — refresh run tracking
7. `v11_price_source_health` — source health/rate-limit/failure tracking

### New code

- `pricing_sources/base.py` — adapter framework ABC
- `pricing_sources/<source_code>.py` — first source adapter
- API endpoints under `/api/v1/prices/...` (read-only evidence)
- Admin/manual UI for evidence inspection
- Tests for each layer

### Migration numbering

Current max migration: `v65`. v11 migrations start at `v66`.

## Known Risks

1. **Core file size**: `pokemon_db_v2_fastapi.py` is 6,518 lines. Adding more code here is risky. New pricing code should live in separate modules.
2. **v8 coexistence**: v8 `price_observations`/`price_snapshots` exist but are not populated from live sources. v11 tables must be separate to avoid confusion.
3. **Legacy `uk_price_history`**: 3,848 rows of old eBay data. Must be preserved. Do not use as v11 evidence (source is stale, API may not work).
4. **Finish unknown**: 90.4% of variants have `finish = 'unknown'`. v11 must not invent finish-specific prices without evidence.
5. **Single source**: v11.0 implements exactly one source. Multi-source comparison is v11.1+.
6. **No RapidAPI key**: The v3 RapidAPI scraper required `RAPIDAPI_KEY`. This key may not be configured. First source must work without paid credentials during development.

## First-Source Candidates

| Source | Reachable? | Key Required? | Free Tier | Pokemon? | Condition? | Finish? | Sold/Active | Cacheable? |
|--------|-----------|---------------|-----------|----------|------------|---------|-------------|------------|
| TCGPrice Lookup | Check | Maybe | Check | Yes | Yes | Partial | Active | Check |
| JustTCG | Check | Maybe | Check | Yes | Yes | No | Active | Check |
| TCGdex market API | Check | No | N/A | Yes | No | No | Market | Yes |
| eBay Browse API | Yes | Yes (OAuth) | No free tier | Yes | Yes | No | Both | Check |

**Decision**: Validate in Workstream B.

## Proposed Implementation Sequence

1. Schema design doc (`V11_MARKET_EVIDENCE_MODEL.md`)
2. Idempotent migrations (v66-v72) + tests
3. Adapter framework (`pricing_sources/base.py`) + tests
4. Source validation spike (Workstream B)
5. First source adapter implementation
6. Matching and confidence logic + tests
7. Aggregation logic + tests
8. Read-only API endpoints + tests
9. Thin admin UI
10. Documentation + Brain update

## Files Expected to Be Modified

### New files

- `docs/V11_PREFLIGHT.md` (this file)
- `docs/V11_SOURCE_VALIDATION.md`
- `docs/V11_MARKET_EVIDENCE_MODEL.md`
- `docs/V11_PRICE_ADAPTERS.md`
- `docs/V11_PRICE_API.md`
- `docs/V11_ADMIN_UI.md`
- `docs/V11_QUALITY_REPORT.md`
- `docs/V11_RELEASE.md`
- `pricing_sources/__init__.py`
- `pricing_sources/base.py`
- `pricing_sources/<source_code>.py`
- `pricing_sources/matcher.py`
- `pricing_sources/aggregator.py`
- `tests/test_v11_market_evidence_migrations.py`
- `tests/test_v11_price_adapter_framework.py`
- `tests/test_v11_price_matching_confidence.py`
- `tests/test_v11_price_aggregation.py`
- `tests/test_v11_price_api.py`

### Modified files

- `pokemon_db_v2_fastapi.py` — register new v11 routes (minimal change)
- `docs/API_CONTRACT_V1.md` — add v11 pricing endpoints
- `pokemon_db_v3_config.py` — add v11 source config schema

### Updated Brain notes

- `Projects/Pokemon Card Database - CURRENT STATE.md`
- `Projects/Pokemon Card Database - Hermes Context Pack.md`
- `Projects/Pokemon Card Database v11 Pricing Intelligence.md`
- `References/vault-state.md`

## Links

- Related: [[V10_RELEASE]]
- Related: [[V10_IDENTITY_MODEL]]
- Related: [[Pokemon Card Database v11 Pricing Intelligence]]
- Related: [[API_CONTRACT_V1]]
