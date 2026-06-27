# V10 Identity Schema Audit

## Existing canonical/commercial tables

### `canonical_printings` (2 rows)

| Column | Type | Description |
|--------|------|-------------|
| printing_id | INTEGER PK | Auto-increment |
| canonical_card_key | TEXT | Language-set-number key |
| source_card_id | TEXT | Original card_id |
| language_code | TEXT | Language |
| set_id | TEXT | Source set_id |
| set_code | TEXT | Set abbreviation |
| collector_number | TEXT | Collector number |
| collector_number_normalized | TEXT | Normalized number |
| printed_total | INTEGER | Printed total |
| name_localized | TEXT | Local name |
| name_english | TEXT | English name |
| release_date | TEXT | Release date |
| rarity | TEXT | Rarity |
| is_promo | INTEGER | Promo flag |
| status | TEXT | Status |
| created_at / updated_at | TEXT | Timestamps |

**Indexes:**
- `idx_canonical_printings_unique` UNIQUE on (canonical_card_key, language_code, set_code, collector_number_normalized)
- `idx_canonical_printings_card` on (canonical_card_key)
- `idx_canonical_printings_set` on (set_code, collector_number_normalized)

**Assessment:** Old ID format. Missing: confidence, provenance, game, card_kind, status per row. Integer PK limits future flexibility. Unique constraint is overly strict — prevents same key across genuinely different printings.

### `commercial_variants` (2 rows)

| Column | Type | Description |
|--------|------|-------------|
| variant_id | INTEGER PK | Auto-increment |
| printing_id | INTEGER FK | Links to canonical_printings |
| finish | TEXT | `normal` |
| edition | TEXT | `Standard` |
| stamp | TEXT | Stamp info |
| parallel_type | TEXT | Parallel type |
| is_first_edition | INTEGER | 0/1 |
| is_unlimited | INTEGER | 0/1 |
| variant_label | TEXT | Display label |
| status | TEXT | Status |

**Assessment:** Missing: language_code, reverse_holo, is_holo, is_promo, market_region, confidence. No unique constraint on identity.

### `sellable_skus` (4 rows)

| Column | Type | Description |
|--------|------|-------------|
| sku_id | INTEGER PK | Auto-increment |
| printing_id | INTEGER FK | Links to canonical_printings |
| variant_id | INTEGER FK | Links to commercial_variants |
| language_code | TEXT | Language |
| condition_code | TEXT | `NM`, `Mint`, etc. |
| sku_key | TEXT | Composite key |
| status | TEXT | Status |

**Indexes:**
- `idx_sellable_skus_key_unique` UNIQUE on `sku_key`
- `idx_sellable_skus_printing` on (printing_id)
- `idx_sellable_skus_key` on (sku_key)

**Assessment:** Condition as one SKU per condition creates combinatorial explosion. Missing: item_class, confidence, display_title, pricing_key, inventory/listing/scanner flags. Integer FK to old canonical_printings table.

### `external_references` (0 rows)

| Column | Type | Description |
|--------|------|-------------|
| external_reference_id | INTEGER PK | Auto-increment |
| entity_type | TEXT | Entity type |
| entity_id | INTEGER | FK (integer) |
| source_name | TEXT | External source name |
| external_id | TEXT | External identifier |
| external_url | TEXT | URL |
| confidence | REAL | 0.0-1.0 |
| status | TEXT | Status |

**Assessment:** entity_id is INTEGER but new tables will use TEXT PKs. Missing: entity_type coverage for canonical/variant/sku, match_method, confidence_label/reason.

## Related tables for identity source data

### `v2_card_detail_api_cache` (298,688 rows)

Carries pre-normalized card data including:
- `card_id` — source-specific card ID (e.g., `base1-4`, `Base Set-4`)
- `raw_set_id` — original set ID
- `resolved_set_id` — normalized set ID
- `core_set_id` — cross-language grouping ID (e.g., `base1`, `A1`, `sv03`)
- `core_set_name` — canonical set name
- `local_id` — collector number / position
- `card_name` — card name in source language
- `language_code` — language
- `category` — Pokémon, Trainer, Energy
- `rarity` — rarity
- `variants` — variant info (for 22,936 cards)
- `types`, `hp`, `stage` — game data

This is the **primary source** for v10 identity derivation.

### `card_name_translations` (252,020 rows)

Links non-English card_id to English equivalent:
- Sources: `db_join`, `pokemon_names_exact`, `latin_passthrough`, `google_translate`
- Used for cross-language matching

### `sets_core` (514 rows)

Maps source set_ids to a canonical core set:
- `core_set_id` — stable grouping ID
- `canonical_set_id` — representative set_id
- `source_method` — provenance (always `v2_existing_sets_grouped_by_set_id`)
- `confidence` — 0.95

## Recommendation

**Create new v10-prefixed tables. Preserve old tables.**

Rationale:
1. Old tables use INTEGER PKs — new model needs TEXT keys (deterministic, external-reference-friendly)
2. Old unique constraints don't match v10 identity granularity
3. Adding columns to old tables risks breaking v9.2 API consumers
4. New tables can reference old tables for forward/backward compatibility
5. Old price/observation tables use `printing_id` and `sku_id` integer FKs — these must continue working

**Migration strategy:**
- Old tables remain untouched
- New `v10_*` tables built in parallel
- Bridge table `v10_sku_links` maps v10 SKU keys to old `sellable_skus.sku_id` for backward compatibility
- Physical items continue using `sellable_skus.sku_id` until a migration to v10 SKUs is designed
