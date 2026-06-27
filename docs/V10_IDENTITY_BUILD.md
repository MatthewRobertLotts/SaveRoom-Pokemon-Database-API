# V10 Identity Build

## Overview

The v10 identity build derives canonical commercial identity from the existing
card catalogue. It transforms 298,688 multilingual card rows into queryable
identity: canonical printings → commercial variants → sellable SKUs.

## What It Does

1. Groups source card rows by `(core_set_id, card_name, local_id)` into canonical printings
2. Links every source row to its canonical printing via `v10_canonical_printing_cards`
3. Creates one commercial variant per `(printing, language, finish)` triple
4. Creates one sellable SKU per commercial variant (initially `raw_conditioned` policy)
5. Records internal external references for traceability
6. Tracks every execution in `v10_identity_build_runs`

## Build Command

Dry-run first:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python scripts/build_v10_identity.py \
  --db full_tcgdex/staging_v9_baseline.sqlite \
  --dry-run --json
```

Limited run (single set):

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python scripts/build_v10_identity.py \
  --db full_tcgdex/staging_v9_baseline.sqlite \
  --core-set-id sv01 --limit 1000 --json
```

Full build:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python scripts/build_v10_identity.py \
  --db full_tcgdex/staging_v9_baseline.sqlite --json
```

## Safety Requirements

Before any write build:

1. Verify database: `scripts/verify_database.py <DB_PATH>`
2. Back up: `scripts/backup_database.py <DB_PATH>`
3. Run dry-run
4. Run a limited sample against a set with variant evidence
5. Only then run the full build

The build is idempotent: `INSERT OR IGNORE` is used throughout. Interrupting
and rerunning is safe. Rerunning does not duplicate rows.

## Confidence Model

| Label  | Score | Reason Example |
|--------|-------|----------------|
| HIGH   | 0.85  | exact core_set_id + local_id group, N card row(s) |
| MEDIUM | —     | (not used in v10 — reserved for translation-only matches) |
| LOW    | —     | (not used in v10 — reserved for name-only matches) |

All v10 identity is derived from HIGH-confidence evidence (set + number).

## Finish Handling

The build parses `v2_card_detail_api_cache.variants` JSON:

- `holo: true` → `finish='holo'`
- `reverse: true` → `finish='reverse'`
- both → `finish='reverse_holo'`
- `normal: true` only → `finish='normal'`
- none true / missing → `finish='unknown'`

Finish is **never guessed**. When evidence is absent, `unknown` is used.

## Known Limitations

- Single-language (`primary_language`) is the grouping identity — not fully cross-language merged
- Only `single_card` / `raw_conditioned` SKUs in v10
- No graded, sealed, or accessory SKUs
- `finish='unknown'` will dominate until richer evidence is backfilled
- Confidence model is simplified (HIGH only) — v10.1 should add MEDIUM/LOW tiers
- Build runtime is proportional to 298K cards (~5-15 min estimated)

## Rollback

The build only inserts into `v10_*` tables. To reset:

```bash
sqlite3 full_tcgdex/staging_v9_baseline.sqlite "DELETE FROM v10_external_references; DELETE FROM v10_sellable_skus; DELETE FROM v10_commercial_variants; DELETE FROM v10_canonical_printing_cards; DELETE FROM v10_canonical_printings; DELETE FROM v10_identity_build_runs; DELETE FROM v10_identity_build_events; DELETE FROM v10_inventory_sku_links;"
```

This preserves all v9.2 data.
