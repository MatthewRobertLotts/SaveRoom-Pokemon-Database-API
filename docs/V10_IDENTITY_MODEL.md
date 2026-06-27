# V10 Identity Model

## Overview

This document defines the canonical commercial identity model for the Pokémon
Card Database v10. It transforms the existing 298,688 multilingual card rows
into queryable commercial identity: canonical printings → commercial variants
→ sellable SKUs.

## Conceptual model

```
cards (source truth, per-language)
    ↓
v10_canonical_printings (card identity across languages)
    ↓
v10_canonical_printing_cards (links source rows to canonical identity)
    ↓
v10_commercial_variants (market-visible version, language-aware)
    ↓
v10_sellable_skus (business product unit)
    ↓
v10_external_references (maps to external systems)
```

## Design decisions

### Canonical printing — language-aware, not language-collapsed

**Decision**: A canonical printing represents `core_set_id + canonical card identity`.
It is NOT aggressively collapsed across languages because:

1. Same slot number may contain DIFFERENT physical cards across languages
   (verified in McDonald's Collection 2011 slot 1: Snivy/Vipélierre/Slam/Souplesse/Growlithe
   — these are different Pokémon, not translations of the same card).
2. For single-language collectors, the language IS the identity.

**Resolution strategy**: If card_name_translations with `source='db_join'` or
`source='pokemon_names_exact'` links two card rows with the same
`core_set_id + local_id`, they are the SAME physical printing. If no translation
confirms they are the same card, they remain separate canonical printings with
lower confidence.

### Commercial variant — language-aware with explicit unknown finish

**Decision**: Each language version of a canonical printing gets its own
commercial variant. Finish is parsed from `v2_card_detail_api_cache.variants`
when available; otherwise `finish='unknown'`.

### Sellable SKU — condition policy, not one-per-condition

**Decision**: A sellable SKU has a `condition_policy` rather than one SKU per
condition tier. The inventory `physical_items` table carries the actual condition
for graded/raw items.

**Initial SKU strategy**:
- One SKU per (commercial_variant, condition_policy) for `raw_conditioned`
- Graded SKUs deferred unless existing data supports them
- Sealed product SKUs deferred unless existing data supports them

### Confidence model — three-tier with explicit reason

**Tiers**:
- `HIGH` — exact core_set_id + local_id + name match from translation layer
- `MEDIUM` — set_id + local_id without cross-language confirmation, OR
              set_id + local_id with name-only link
- `LOW` — name-only, ambiguous match, or unknown finish

Confidence score is REAL (0.0-1.0) computed from match quality.
Confidence label is TEXT for filtering.
Confidence reason explains WHY (e.g., `exact_set_id + local_id + translation_db_join`).

## Table definitions

### v10_canonical_printings

```sql
CREATE TABLE IF NOT EXISTS v10_canonical_printings (
    canonical_printing_id TEXT PRIMARY KEY,       -- 'cp-' || lower(hex(uuid))[:12]
    canonical_key TEXT UNIQUE NOT NULL,           -- stable lookup key, e.g. 'pk_tcg:base1-4-en'
    game TEXT NOT NULL DEFAULT 'pokemon_tcg',      -- franchise family
    core_set_id TEXT NOT NULL,                     -- from v2_card_detail_api_cache
    set_id TEXT,                                    -- representative source set_id
    set_code TEXT,                                 -- abbreviation
    collector_number TEXT,                         -- as-printed number
    collector_number_sort TEXT,                    -- zero-padded for sorting
    canonical_name TEXT NOT NULL,                  -- canonical display name
    name_english TEXT,                             -- English equivalent if available
    primary_language TEXT NOT NULL,                 -- representative language
    card_kind TEXT,                                -- Pokemon, Trainer, Energy, etc.
    rarity TEXT,                                   -- rarity from source
    first_seen_source TEXT NOT NULL,               -- 'v2_import:v9_backup:...'
    status TEXT NOT NULL DEFAULT 'active',         -- active|deprecated
    confidence_score REAL NOT NULL,                -- 0.0-1.0
    confidence_label TEXT NOT NULL,                -- HIGH|MEDIUM|LOW
    confidence_reason TEXT NOT NULL,               -- explanation
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

**Indexes**:
- `idx_v10_cp_core_set` on (core_set_id, collector_number_sort)
- `idx_v10_cp_name` on (canonical_name)
- `idx_v10_cp_set_code` on (set_code, collector_number_sort)
- `idx_v10_cp_confidence` on (confidence_label)

### v10_canonical_printing_cards

Links source card rows to canonical printings.

```sql
CREATE TABLE IF NOT EXISTS v10_canonical_printing_cards (
    canonical_printing_id TEXT NOT NULL,
    card_key TEXT NOT NULL,                        -- 'lang:card_id' from source
    language_code TEXT NOT NULL,
    source_card_id TEXT,                           -- original card_id
    match_method TEXT NOT NULL,                    -- exact_set_number_translation|exact_set_number|name_only|source_specific
    confidence_score REAL NOT NULL,
    confidence_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (canonical_printing_id, card_key)
);
```

**Indexes**:
- `idx_v10_cpc_card_key` on (card_key)
- `idx_v10_cpc_lang` on (language_code)

### v10_commercial_variants

Represents market-visible versions of a canonical printing.

```sql
CREATE TABLE IF NOT EXISTS v10_commercial_variants (
    commercial_variant_id TEXT PRIMARY KEY,         -- 'cv-' || lower(hex(uuid))[:12]
    canonical_printing_id TEXT NOT NULL,
    variant_key TEXT UNIQUE NOT NULL,              -- stable lookup key, e.g. 'base1-4-en-unknown'
    language_code TEXT NOT NULL,
    finish TEXT NOT NULL DEFAULT 'unknown',        -- normal|holo|reverse_holo|unknown
    variant_type TEXT NOT NULL DEFAULT 'standard',  -- standard|promo|special
    stamp TEXT,                                    -- stamp/event mark
    edition TEXT,                                 -- first_edition|unlimited|.other
    is_reverse_holo INTEGER NOT NULL DEFAULT 0,
    is_holo INTEGER,                               -- NULL=unknown, 0=no, 1=yes
    is_promo INTEGER NOT NULL DEFAULT 0,
    market_region TEXT,                            -- e.g. 'jp','en','eu'
    status TEXT NOT NULL DEFAULT 'active',
    confidence_score REAL NOT NULL,
    confidence_label TEXT NOT NULL,
    confidence_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

**Indexes**:
- `idx_v10_cv_canonical` on (canonical_printing_id)
- `idx_v10_cv_language` on (language_code)
- `idx_v10_cv_finish` on (finish)
- `idx_v10_cv_set` on (variant_key) — for lookup

### v10_sellable_skus

Business-level product identities.

```sql
CREATE TABLE IF NOT EXISTS v10_sellable_skus (
    sellable_sku_id TEXT PRIMARY KEY,              -- 'sku-' || lower(hex(uuid))[:12]
    commercial_variant_id TEXT NOT NULL,
    sku_key TEXT UNIQUE NOT NULL,                  -- e.g. 'pk_tcg:base1-4-en-unknown-raw'
    item_class TEXT NOT NULL DEFAULT 'single_card', -- single_card|graded_card|sealed_product|accessory|unknown
    condition_policy TEXT NOT NULL DEFAULT 'raw_conditioned', -- raw_conditioned|graded_conditioned|sealed|not_applicable
    display_title TEXT NOT NULL,
    pricing_key TEXT,                              -- for future pricing lookup
    inventory_enabled INTEGER NOT NULL DEFAULT 1,
    listing_enabled INTEGER NOT NULL DEFAULT 1,
    scanner_enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    confidence_score REAL NOT NULL,
    confidence_label TEXT NOT NULL,
    confidence_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

**Indexes**:
- `idx_v10_sku_variant` on (commercial_variant_id)
- `idx_v10_sku_item_class` on (item_class)
- `idx_v10_sku_status` on (status)

### v10_external_references

Maps platform identities to external systems.

```sql
CREATE TABLE IF NOT EXISTS v10_external_references (
    external_reference_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,                     -- canonical_printing|commercial_variant|sellable_sku
    entity_id TEXT NOT NULL,                       -- v10_* PK
    source_name TEXT NOT NULL,                     -- tcgdex|pokemon_tcg_api|bulbapedia|ebay|cardmarket|internal
    source_entity_type TEXT,                        -- type in external system
    source_identifier TEXT NOT NULL,
    source_url TEXT,
    match_method TEXT NOT NULL,                    -- exact|fuzzy|derived
    confidence_score REAL NOT NULL,
    confidence_label TEXT NOT NULL,
    confidence_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(entity_type, entity_id, source_name, source_identifier)
);
```

**Indexes**:
- `idx_v10_er_entity` on (entity_type, entity_id)
- `idx_v10_er_source` on (source_name, source_identifier)

### v10_identity_build_runs

Tracks population build executions.

```sql
CREATE TABLE IF NOT EXISTS v10_identity_build_runs (
    build_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,                          -- running|completed|failed
    source_db_path TEXT,
    algorithm_version TEXT NOT NULL DEFAULT '1.0.0',
    cards_seen INTEGER DEFAULT 0,
    canonical_printings_created INTEGER DEFAULT 0,
    commercial_variants_created INTEGER DEFAULT 0,
    sellable_skus_created INTEGER DEFAULT 0,
    external_references_created INTEGER DEFAULT 0,
    warnings_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    notes TEXT
);
```

### v10_identity_build_events

Per-build warning/error log.

```sql
CREATE TABLE IF NOT EXISTS v10_identity_build_events (
    event_id TEXT PRIMARY KEY,
    build_run_id TEXT NOT NULL,
    severity TEXT NOT NULL,                         -- INFO|WARNING|ERROR
    entity_type TEXT,
    entity_id TEXT,
    message TEXT NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### v10_inventory_sku_links

Maps v10 sellable SKUs to old sellable_skus for backward compatibility.

```sql
CREATE TABLE IF NOT EXISTS v10_inventory_sku_links (
    link_id TEXT PRIMARY KEY,
    sellable_sku_id TEXT NOT NULL,                 -- v10 UUID
    legacy_sku_id INTEGER NOT NULL,                -- old sellable_skus.sku_id
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(sellable_sku_id, legacy_sku_id)
);
```

## Population strategy

### Phase 1: Canonical printings from English + translations

1. Start with `language_code='en'` cards — most commercially meaningful for pricing
2. Group by `core_set_id + local_id` → create one canonical printing per group
3. Use `card_name_translations` to merge non-English slots into English canonical

### Phase 2: Link non-English cards

1. For each non-English card, check if its English equivalent (via translation)
   matches an existing canonical printing
2. If yes: link with HIGH confidence
3. If no: create new canonical printing for that language with MEDIUM confidence

### Phase 3: Commercial variants

1. For each canonical printing + language combo, parse finish from `variants` JSON
2. Create one commercial variant per (canonical, language, finish) triple

### Phase 4: Sellable SKUs

1. For each commercial variant, create one SKU with `condition_policy='raw_conditioned'`
2. SKU key derived from variant key

### Phase 5: External references

1. From existing `card_id` patterns, infer TCGdex / Pokémon TCG API identifiers
2. Internal references: map old `sellable_skus.sku_id` values

## API endpoint plan

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v1/identity/health | Identity build health/stats |
| GET | /api/v1/identity/canonical-printings | List with filters |
| GET | /api/v1/identity/canonical-printings/{id} | Single with card links |
| GET | /api/v1/identity/cards/{card_key} | Card-to-identity lookup |
| GET | /api/v1/identity/commercial-variants/{id} | Variant detail |
| GET | /api/v1/identity/sellable-skus | List with filters |
| GET | /api/v1/identity/sellable-skus/{id} | SKU detail |
| GET | /api/v1/identity/external-references | List with filters |

## Rollback / compatibility

- v10 migration runs after v57b in the existing `apply_migrations()` function
- All new tables use `CREATE TABLE IF NOT EXISTS`
- No old tables are modified
- Old API endpoints are untouched
- `inventory_links` table remains available for future wiring

## Deferred

- Finish population from external sources (requires API calls)
- Graded card SKU population
- Sealed product SKU population
- Marketplace listing sync
- Scanner integration hardening
- Multi-region pricing identity
