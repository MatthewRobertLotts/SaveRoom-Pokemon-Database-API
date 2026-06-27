# v11 Market Evidence Model

Tags: #type/project #status/needs-review

Status: DESIGN_COMPLETE
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

This document designs the v11 market evidence schema. The schema is additive — it does not modify or replace existing v8 pricing tables (`price_observations`, `price_observation_matches`, `price_calculation_runs`, `price_snapshots`) or legacy `uk_price_history`.

All new tables use the `v11_` prefix.

## Design Decisions

### 1. How do we separate sold vs active listing vs guide price?

TCGdex provides **active listing market prices** only. It does not provide sold prices.

- `listing_type` field on `v11_price_observations` records the type: `active_listing`, `market_price`, `guide`, `sold`, `unknown`
- TCGdex observations use `listing_type = 'market_price'` (TCGPlayer marketPrice) or `listing_type = 'active_listing'` (TCGPlayer low/high range)
- Cardmarket `avg` uses `listing_type = 'market_price'` (it's an average of recent sales)
- Aggregations compute separately per `listing_type`
- If a future source provides sold prices, they get their own observations and aggregates

### 2. How do we separate raw vs graded?

TCGdex provides **raw (ungraded) market prices** only. It does not provide graded prices.

- `v11_price_observations` does not have a `grader` or `grade_value` field
- If a future source provides graded prices, they are stored as separate observations with `observation_type = 'graded'`
- Aggregations never mix raw and graded

### 3. How do we separate sealed vs single?

TCGdex provides **single card prices** only. It does not provide sealed product prices.

- `v11_price_observations.listing_type` for single cards is `active_listing` or `market_price`
- Sealed products would use `listing_type = 'sealed_product'`
- Aggregations never mix sealed and single

### 4. How do we represent ambiguous finish?

- `v11_price_observations.finish` records the finish from the source (e.g., `normal`, `reverse_holo`, `holo`)
- TCGdex provides separate pricing per variant — we store the variant as `finish`
- If a source does not provide finish-specific pricing, `finish = 'unknown'`
- Aggregations compute per finish bucket; `finish = 'unknown'` aggregates are indicative only
- We never create exact SKU prices from `finish = 'unknown'` observations

### 5. How do we attach observations to canonical/variant/SKU?

- `v11_price_observation_matches` links observations to v10 identity:
  - `canonical_printing_id` (nullable) — matched canonical printing
  - `commercial_variant_id` (nullable) — matched commercial variant
  - `sellable_sku_id` (nullable) — matched sellable SKU
- Match confidence is recorded on the match row
- One observation can match multiple targets (e.g., a TCGdex card matches a canonical printing AND its commercial variant)

### 6. How do we avoid false exact SKU price?

- SKU exact prices require `match_confidence = HIGH` AND `finish != 'unknown'`
- If finish is unknown, aggregates are only at canonical printing level (indicative)
- SKU aggregates from ambiguous finish get `confidence_label = LOW` and `confidence_reason = 'finish ambiguous'`

### 7. How do we handle original currency?

- All observations store `currency` (e.g., `USD`, `EUR`) and `amount` in original currency
- Aggregations compute per currency
- No FX conversion in v11.0 (would require a separate FX source)
- If aggregation across currencies is needed, it gets `confidence_label = LOW` with reason 'mixed currencies'

### 8. How do we store raw payloads without bloating main tables?

- `v11_price_source_cache` stores the full raw JSON response from the source
- `v11_price_observations.raw_payload_ref` points to the cache row (by `source_record_id`)
- This keeps the observations table lean while preserving full traceability

### 9. How do we expire/cache source data?

- `v11_price_source_cache.fetched_at` records when the response was fetched
- `v11_price_source_cache.ttl_hours` records the cache TTL (default 24 hours for TCGdex)
- Stale cache entries are refreshed on next observation run
- Cache entries are never deleted — they are historical evidence

### 10. How do we handle rate limits/failures?

- `v11_price_source_health` tracks per-source:
  - `last_success_at`, `last_failure_at`
  - `consecutive_failures`
  - `rate_limit_remaining` (if source reports it)
  - `status`: `healthy`, `degraded`, `failing`, `disabled`
- `v11_price_refresh_runs` records each refresh attempt with status and counts

## Schema Tables

### v11_price_sources

```sql
CREATE TABLE IF NOT EXISTS v11_price_sources (
    source_id TEXT PRIMARY KEY,
    source_code TEXT UNIQUE NOT NULL,          -- e.g., 'tcgdex'
    source_name TEXT NOT NULL,                 -- e.g., 'TCGdex Market API'
    source_url TEXT,                           -- e.g., 'https://api.tcgdex.net'
    api_key_required INTEGER NOT NULL DEFAULT 0,
    base_currency TEXT NOT NULL DEFAULT 'USD', -- source's native currency
    default_condition TEXT NOT NULL DEFAULT 'unknown', -- source's condition model
    default_listing_type TEXT NOT NULL DEFAULT 'market_price',
    capabilities_json TEXT,                    -- source capabilities description
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### v11_price_source_cache

```sql
CREATE TABLE IF NOT EXISTS v11_price_source_cache (
    cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,            -- source's card ID (e.g., 'swsh3-136')
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ttl_hours INTEGER NOT NULL DEFAULT 24,
    raw_payload_json TEXT NOT NULL,            -- full JSON response
    payload_hash TEXT NOT NULL,                -- SHA-256 of raw_payload_json
    query_params_json TEXT,                    -- query parameters used
    http_status INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
);
```

### v11_price_observations

```sql
CREATE TABLE IF NOT EXISTS v11_price_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,            -- links to cache
    observed_at TEXT NOT NULL,                 -- source's timestamp
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    currency TEXT NOT NULL,                    -- 'USD', 'EUR', etc.
    amount REAL NOT NULL,                      -- price in currency
    condition TEXT NOT NULL DEFAULT 'unknown', -- 'unknown', 'raw', 'graded'
    finish TEXT NOT NULL DEFAULT 'unknown',    -- 'unknown', 'normal', 'reverse_holo', 'holo'
    printing_label TEXT,                       -- human-readable variant label
    language TEXT,                             -- card language context
    marketplace TEXT NOT NULL DEFAULT 'unknown', -- 'tcgplayer', 'cardmarket', etc.
    listing_type TEXT NOT NULL DEFAULT 'unknown', -- 'active_listing', 'market_price', 'sold', 'guide', 'sealed_product'
    raw_title TEXT,                            -- source's card title
    raw_url TEXT,                              -- source URL if available
    raw_payload_ref TEXT,                      -- references cache.source_record_id
    observation_type TEXT NOT NULL DEFAULT 'market_price', -- 'market_price', 'active_listing', 'sold', 'guide'
    canonical_printing_id TEXT,                -- FK to v10_canonical_printings (nullable)
    commercial_variant_id TEXT,                -- FK to v10_commercial_variants (nullable)
    sellable_sku_id TEXT,                      -- FK to v10_sellable_skus (nullable)
    match_confidence TEXT,                     -- 'HIGH', 'MEDIUM', 'LOW', 'UNUSABLE'
    match_reason TEXT,                         -- explanation of confidence
    is_usable_for_aggregate INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
);
```

### v11_price_observation_matches

```sql
CREATE TABLE IF NOT EXISTS v11_price_observation_matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,                 -- 'canonical_printing', 'commercial_variant', 'sellable_sku'
    target_id TEXT NOT NULL,                   -- the ID of the target
    match_confidence TEXT NOT NULL,            -- 'HIGH', 'MEDIUM', 'LOW', 'UNUSABLE'
    match_reason TEXT NOT NULL,
    match_method TEXT NOT NULL,                -- 'set_code+collector_number', 'name_match', etc.
    source_set_code TEXT,                      -- set code from source
    source_collector_number TEXT,              -- collector number from source
    source_variant TEXT,                       -- variant/finish from source
    source_language TEXT,                      -- language from source
    condition_matched TEXT,                    -- condition if available
    finish_matched TEXT,                       -- finish if available
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (observation_id) REFERENCES v11_price_observations(observation_id)
);
```

### v11_price_aggregates

```sql
CREATE TABLE IF NOT EXISTS v11_price_aggregates (
    aggregate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,                 -- 'canonical_printing', 'commercial_variant', 'sellable_sku'
    target_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    listing_type TEXT NOT NULL,                -- 'active_listing', 'market_price', 'sold', 'guide'
    finish TEXT NOT NULL DEFAULT 'unknown',
    median_price REAL,
    low_price REAL,
    high_price REAL,
    mean_price REAL,
    observation_count INTEGER NOT NULL DEFAULT 0,
    source_count INTEGER NOT NULL DEFAULT 0,
    freshness_days REAL,                       -- avg age of observations
    confidence_label TEXT NOT NULL,            -- 'HIGH', 'MEDIUM', 'LOW', 'UNUSABLE'
    confidence_score REAL,
    confidence_reason TEXT,
    computed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### v11_price_refresh_runs

```sql
CREATE TABLE IF NOT EXISTS v11_price_refresh_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_type TEXT,                          -- null for bulk runs
    target_id TEXT,                            -- null for bulk runs
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',    -- 'pending', 'running', 'completed', 'failed', 'partial'
    observations_created INTEGER DEFAULT 0,
    observations_updated INTEGER DEFAULT 0,
    observations_skipped INTEGER DEFAULT 0,
    cache_rows_created INTEGER DEFAULT 0,
    error_message TEXT,
    error_details TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
);
```

### v11_price_source_health

```sql
CREATE TABLE IF NOT EXISTS v11_price_source_health (
    health_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    status TEXT NOT NULL DEFAULT 'unknown',    -- 'healthy', 'degraded', 'failing', 'disabled', 'unknown'
    last_success_at TEXT,
    last_failure_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    rate_limit_remaining INTEGER,
    rate_limit_reset_at TEXT,
    avg_response_ms REAL,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (source_id) REFERENCES v11_price_sources(source_id)
);
```

## Indexes

```sql
-- v11_price_source_cache
CREATE INDEX IF NOT EXISTS idx_v11_psc_source_record ON v11_price_source_cache(source_id, source_record_id);
CREATE INDEX IF NOT EXISTS idx_v11_psc_fetched ON v11_price_source_cache(fetched_at);

-- v11_price_observations
CREATE INDEX IF NOT EXISTS idx_v11_po_source ON v11_price_observations(source_id, source_record_id);
CREATE INDEX IF NOT EXISTS idx_v11_po_canonical ON v11_price_observations(canonical_printing_id);
CREATE INDEX IF NOT EXISTS idx_v11_po_variant ON v11_price_observations(commercial_variant_id);
CREATE INDEX IF NOT EXISTS idx_v11_po_sku ON v11_price_observations(sellable_sku_id);
CREATE INDEX IF NOT EXISTS idx_v11_po_currency ON v11_price_observations(currency);
CREATE INDEX IF NOT EXISTS idx_v11_po_condition ON v11_price_observations(condition);
CREATE INDEX IF NOT EXISTS idx_v11_po_finish ON v11_price_observations(finish);
CREATE INDEX IF NOT EXISTS idx_v11_po_listing_type ON v11_price_observations(listing_type);
CREATE INDEX IF NOT EXISTS idx_v11_po_fetched ON v11_price_observations(fetched_at);
CREATE INDEX IF NOT EXISTS idx_v11_po_usable ON v11_price_observations(is_usable_for_aggregate);
CREATE INDEX IF NOT EXISTS idx_v11_po_match_conf ON v11_price_observations(match_confidence);

-- v11_price_observation_matches
CREATE INDEX IF NOT EXISTS idx_v11_pom_obs ON v11_price_observation_matches(observation_id);
CREATE INDEX IF NOT EXISTS idx_v11_pom_target ON v11_price_observation_matches(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_v11_pom_confidence ON v11_price_observation_matches(match_confidence);

-- v11_price_aggregates
CREATE INDEX IF NOT EXISTS idx_v11_pa_target ON v11_price_aggregates(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_v11_pa_currency ON v11_price_aggregates(currency);
CREATE INDEX IF NOT EXISTS idx_v11_pa_listing_type ON v11_price_aggregates(listing_type);
CREATE INDEX IF NOT EXISTS idx_v11_pa_finish ON v11_price_aggregates(finish);
CREATE INDEX IF NOT EXISTS idx_v11_pa_computed ON v11_price_aggregates(computed_at);
CREATE INDEX IF NOT EXISTS idx_v11_pa_confidence ON v11_price_aggregates(confidence_label);

-- v11_price_refresh_runs
CREATE INDEX IF NOT EXISTS idx_v11_prr_source ON v11_price_refresh_runs(source_id);
CREATE INDEX IF NOT EXISTS idx_v11_prr_status ON v11_price_refresh_runs(status);
CREATE INDEX IF NOT EXISTS idx_v11_prr_started ON v11_price_refresh_runs(started_at);

-- v11_price_source_health
CREATE INDEX IF NOT EXISTS idx_v11_psh_source ON v11_price_source_health(source_id);
CREATE INDEX IF NOT EXISTS idx_v11_psh_status ON v11_price_source_health(status);
```

## Migration Numbers

Starting at `v66` (current max is `v65`):

| Migration | Content |
|-----------|---------|
| v66 | `v11_price_sources` table |
| v67 | `v11_price_source_cache` table + index |
| v68 | `v11_price_observations` table + indexes |
| v69 | `v11_price_observation_matches` table + indexes |
| v70 | `v11_price_aggregates` table + indexes |
| v71 | `v11_price_refresh_runs` table + indexes |
| v72 | `v11_price_source_health` table + indexes |

## Confidence Rules

### Observation-level confidence

| Condition | Confidence | Reason |
|-----------|-----------|--------|
| Source provides variant-level pricing, set+number match | HIGH | Exact identity + variant match |
| Source provides market-level pricing, set+number match | MEDIUM | Identity match but finish ambiguous |
| Source provides name-only match | LOW | Name match without structured identity |
| Source result too broad / missing identity | UNUSABLE | Cannot reliably attach to canonical |
| Wrong language | UNUSABLE | Language mismatch |
| Stale (>30 days) | LOW | Data too old for reliable aggregate |

### Aggregate-level confidence

| Condition | Confidence | Reason |
|-----------|-----------|--------|
| 5+ usable observations, single source, single currency, finish known | HIGH | Strong evidence base |
| 3-4 usable observations | MEDIUM | Moderate evidence base |
| 1-2 usable observations | LOW | Thin evidence |
| Finish unknown | LOW | Cannot create exact SKU price |
| Mixed currencies | LOW | No FX source |
| Only one source | MEDIUM | No cross-validation possible |
| Stale (>14 days) | LOW | Evidence too old |

## Links

- Related: [[V11_PREFLIGHT]]
- Related: [[V11_SOURCE_VALIDATION]]
- Related: [[V10_IDENTITY_MODEL]]
