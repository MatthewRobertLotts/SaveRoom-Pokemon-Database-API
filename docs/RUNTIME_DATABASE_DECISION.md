# v9.2 Runtime Database Decision

## Overview

v9.2 formalises how the project selects the SQLite runtime database so development, tests and production do not accidentally operate on different datasets.

## Candidates Inspected

| Database | Size bytes | Mtime | Tables/views | Key state |
|---|---:|---|---|---|
| `full_tcgdex/staging_v9_baseline.sqlite` | 1,255,698,432 | 2026-06-26T20:50:35 | 80 / 9 | Highest current runtime state: 298,688 cards, 240,737 catalogue image assets, 73 tenants, 1,362 physical items, 658 photos, 739 inventory transactions, 1 scanner hash. |
| `full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite` | 1,251,442,688 | 2026-06-26T20:41:34 | 80 / 9 | Same core card/search/image tables and migration count, but lower runtime/business state: 19 tenants, 91 physical items, 11 photos, 145 transactions, 0 scanner hashes. |
| `full_tcgdex/staging_v9.1_final.sqlite` | 1,206,743,040 | 2026-06-24T00:45:34 | 77 / 9 | Older v9.1 candidate: no `catalogue_image_assets`, no `card_image_hashes`, 90 migrations, 0 physical photos. |

Older `pokemon_tcg_set_knowledge_base.backup_*` files were also observed. They are historical backups and are not runtime candidates.

## Important Count Differences

| Metric | `staging_v9_baseline` | `pokemon_tcg_set_knowledge_base` | `staging_v9.1_final` |
|---|---:|---:|---:|
| `cards` | 298,688 | 298,688 | 298,688 |
| `v2_card_search_fts` | 298,688 | 298,688 | 298,688 |
| `card_image_local_cache` | 252,514 | 252,514 | 252,514 |
| `catalogue_image_assets` | 240,737 | 240,737 | missing |
| `uk_price_history` | 3,848 | 3,848 | 3,848 |
| `schema_migrations` | 99 | 99 | 90 |
| `tenants` | 73 | 19 | 50 |
| `physical_items` | 1,362 | 91 | 265 |
| `physical_item_photos` | 658 | 11 | 0 |
| `inventory_transactions` | 739 | 145 | 488 |
| `card_image_hashes` | 1 | 0 | missing |

`PRAGMA quick_check` returned `ok` for the three primary candidates. `PRAGMA foreign_key_check` returns many historical rows on the large candidate databases; v9.2 documents this as a data-quality/integrity backlog rather than silently ignoring it.

## Decision

The authoritative current v9.2 runtime dataset is:

```text
full_tcgdex/staging_v9_baseline.sqlite
```

Reason:

1. It has the latest measured business/runtime state.
2. It includes the v57/v57b scanner-hash schema migrations.
3. It contains the largest/current tenant, inventory, transaction and physical-photo state.
4. It includes the v9.1 stable image gateway tables and current catalogue image assets.

The historical default filename remains:

```text
full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite
```

but it is not as complete for current v9.2 runtime/business state. It should be treated as a development-compatible database until the authoritative dataset is promoted to a stable production filename.

## Development, Test and Production Selection

Runtime precedence:

1. CLI `--db` argument.
2. `POKEMON_DB_DB` environment variable.
3. Development default in `pokemon_db_v3_config.py`.

Development remains convenient and may use the default local database.

Tests must create and use temporary isolated SQLite databases. v9.2 moves physical-photo tests off the real runtime database and into a seeded temporary database.

Production must set:

```text
POKEMON_DB_ENV=production
POKEMON_DB_DB=/absolute/path/to/authoritative.sqlite
POKEMON_DB_REQUIRE_API_KEY=1
POKEMON_DB_SIGNED_URL_SECRET=<real 32+ character secret>
```

Production startup refuses to use the default database silently.

## Migration and Backup Expectations

- Every schema change must be idempotent.
- Do not copy a live database with a raw filesystem copy as the normal backup method.
- Use `scripts/backup_database.py` for SQLite online backup.
- Use `scripts/verify_database.py` for integrity verification.
- Before promoting `staging_v9_baseline.sqlite` to a stable production filename, take a verified backup and document the promotion.

## Rollback Procedure

1. Stop the API process.
2. Verify the target rollback database with `scripts/verify_database.py`.
3. Update `POKEMON_DB_DB` to point to the verified rollback database.
4. Start the API with `POKEMON_DB_ENV=production` and explicit config.
5. Run `/api/v1/health`, `/api/v1/search/cards`, `/api/v1/languages` and `/api/v1/images/health` smoke checks.
6. Do not overwrite or delete the failed database until a postmortem is complete.

## Links

- Related: `docs/V9_2_PREFLIGHT.md`
- Related: `docs/OPERATIONS.md`
