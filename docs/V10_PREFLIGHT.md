# V10 Preflight — Canonical Identity, Commercial Variants and Sellable SKU Foundation

## Git state

```
branch: v10-canonical-commercial-foundation
HEAD: d966212 (tag: v9.2.0)
working tree: clean
base: v9.2.0 / d966212 Merge v9.2 commercial foundation stabilisation
remote: https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API.git
```

## Runtime database

```
path: full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite
size: ~1.2 GB
integrity: ok
```

## Table counts — identity-related

| table | count | notes |
|-------|-------|-------|
| cards | 298,688 | One row per (card_id, language_code) |
| sets | 1,587 | One row per (set_id, language_code) |
| localized_sets | 1,587 | Mirrors sets |
| languages | 18 | 18 supported languages |
| v2_card_detail_api_cache | 298,688 | Normalized card detail with core_set_id |
| v2_card_search_fts | 298,688 | FTS5 search index |
| card_name_translations | 252,020 | Cross-language name links |
| catalogue_image_assets | 240,737 | Image asset records |
| canonical_printings | 2 | Near-empty placeholder |
| commercial_variants | 2 | Near-empty placeholder |
| sellable_skus | 4 | Near-empty placeholder |
| external_references | 0 | Empty |
| price_observations | 0 | Empty |
| uk_price_history | 3,848 | Legacy pricing data |
| physical_items | 133 | Inventory items, linked to sku_id 900001 |
| inventory_transactions | 222 | Transaction log |
| inventory_snapshots | 222 | Current inventory state |

## Key evidence for v10 modelling

### Distinct (core_set_id, local_id) printing slots

```
distinct combos: 55,501
average languages per slot: 3.4
min/max languages per slot: 1 / 8
```

This tells us: a "printing slot" (same set + collector number) averages 3-4 language variants. These are NOT necessarily the same card across languages (e.g. McDonald's collection has 5 different physical cards in slot 1).

### Cards per language

| language | cards |
|----------|-------|
| en | 46,668 |
| fr | 43,597 |
| de | 40,837 |
| it | 36,483 |
| es | 33,582 |
| pt | 31,746 |
| ja | 15,869 |
| ko | 10,023 |
| zh-tw | 9,846 |
| id | 9,128 |

### Existing identity infrastructure

1. **sets_core** (514 rows): Maps `set_id` to `core_set_id` across languages. This EXISTS but is only for set-level grouping, not card-level identity.
2. **v2_card_detail_api_cache**: Already carries `core_set_id`, `resolved_set_id`, `local_id`, `card_name`, `category`, `rarity`, `variants`, `core_set_name` for all 298,688 rows. This IS the card-level data source.
3. **card_name_translations** (252,020 rows): Links card_id to English names with high confidence for `db_join` source (196,982 rows).

### Existing canonical tables (v18-v21 migration batch)

The existing `canonical_printings`, `commercial_variants`, `sellable_skus`, and `external_references` tables were created by migrations v18-v21 and v22-v27 (indexes). They have:

- Canonical identity via `canonical_card_key` and `printing_id`
- Variant finish/edition (text fields only, no reverse holo, no language)
- SKU via `sku_key` conditioned on `condition_code`
- External references are integer entity_id based
- **No confidence scoring** on any identity row
- **No build run tracking**
- **No language-aware variant model**

These existing tables are structurally insufficient for v10 but must be preserved.

## Files expected to be modified/created

### Modified
- `pokemon_db_v2_fastapi.py` — Add migrations v58+, add identity health endpoint
- `tests/` — Update existing tests for compatibility

### Created
- `scripts/build_v10_identity.py` — Identity build/population script
- `scripts/report_v10_identity_quality.py` — Quality report script
- `tests/test_v10_identity_migrations.py`
- `tests/test_v10_identity_build.py`
- `tests/test_v10_identity_api.py`
- `tests/test_v10_identity_quality.py`
- `docs/V10_IDENTITY_SCHEMA_AUDIT.md`
- `docs/V10_IDENTITY_MODEL.md`
- `docs/V10_IDENTITY_BUILD.md`
- `docs/V10_IDENTITY_API.md`
- `docs/V10_IDENTITY_QUALITY.md`
- `docs/API_CONTRACT_V1.md` — Updated
- `docs/V10_RELEASE.md`

## Known v10 risks

1. **Memory/CPU**: 298K+ card rows require batched processing against a 1.2GB DB
2. **Slot ambiguity**: Same `core_set_id + local_id` may represent different physical cards (not just translations) — verified in McDonald's Collection where slot 1 contains 5 different Snivy/Klink/Pidove/Audino/Maractus
3. **Finish unknown**: No reliable local evidence for holo/reverse/per collector number — must use `finish='unknown'` with lowered confidence
4. **Inventory linkage**: Existing `physical_items.sku_id` uses the old `sellable_skus` table's integer PK (900001); v10 must either bridge or defer destructive changes
5. **card_id variance**: Same card has different card_ids in same language (e.g. `base1-4` and `Base Set-4`) — these share `core_set_id + local_id`
6. **Migration idempotency**: Must not break v18-v27 migration pattern
7. **No external lookups**: v10 cannot query external APIs for finish/variant evidence

## Proposed migration approach

1. Create new `v10_*` tables (not modify old tables)
2. Run identity build script (batched, idempotent)
3. Add read-only API endpoints
4. Add bridge table for inventory compatibility
5. Old tables preserved untouched

## Next step

Proceed to Workstream B — schema audit of existing identity tables.
