# V10 Release Notes — Canonical Commercial Foundation

## Summary

v10 transforms the platform from a large multilingual card catalogue into a commercial identity API foundation. It introduces canonical printings, commercial variants, sellable SKUs, and external references as a layered identity model that scanner, pricing, inventory, POS, and marketplace tools can build on.

## What v10 Implements

1. **Canonical printing model** — stable identity for a specific printed card across localized rows
2. **Commercial variant model** — market-visible version (language-aware, finish-aware)
3. **Sellable SKU model** — business product identity (initially single-card/raw)
4. **External reference mapping** — links platform identity to internal/external systems
5. **Identity build script** — deterministic, idempotent population
6. **7 API endpoints** — read-only identity lookup, health, lists, and filters
7. **Confidence/provenance model** — every identity carries score, label, and reason
8. **Build run tracking** — every build execution is logged with counts and status

## Schema Changes

New tables (7):

```text
v10_canonical_printings
v10_canonical_printing_cards
v10_commercial_variants
v10_sellable_skus
v10_external_references
v10_identity_build_runs
v10_identity_build_events
v10_inventory_sku_links
```

Migrations: v58-v65

No existing v9.2 tables are dropped or altered.

## Population Results (full build)

| Metric | Count |
|--------|-------|
| Total cards | 298,688 |
| Mapped cards | 297,194 (99.5%) |
| Canonical printings | 121,771 |
| Commercial variants | 208,894 |
| Sellable SKUs | 208,894 |
| External references | 187,102 |
| Card links | 297,194 |

## API Endpoints Added

- `GET /api/v1/identity/health`
- `GET /api/v1/identity/canonical-printings`
- `GET /api/v1/identity/canonical-printings/{id}`
- `GET /api/v1/identity/cards/{card_key}`
- `GET /api/v1/identity/sellable-skus`
- `GET /api/v1/identity/sellable-skus/{id}`
- `GET /api/v1/identity/external-references`

## Breaking Changes

None. v10 is purely additive.

## Tests

- 79 new v10 tests pass (26 migration + 22 build + 16 API + 15 quality/reporting)
- 314 full suite passes
- Existing v9.2 contracts remain intact

## Known Limitations

- Confidence is simplified (all HIGH in v10)
- Cross-language canonical merging deferred to v10.1
- Finish is unknown for 90.4% of variants (no parseable evidence, not a bug)
- Graded/sealed/accessory SKUs deferred
- Scanner integration is NOT production-ready
- Pricing intelligence is NOT complete

## Deferred to v11

- Pricing intelligence and market evidence foundation (depends on identity coverage)
- Tiered confidence scoring (MEDIUM/LOW)
- SKU condition population from inventory data

## How to Rebuild Identity

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python scripts/build_v10_identity.py \
  --db full_tcgdex/staging_v9_baseline.sqlite --json
```

The build is idempotent and safe to rerun.

## Git Tag

Pending human review.

## Links

- Related: [[V10 Identity Model]]
- Related: [[V10 Identity Schema Audit]]
- Related: [[V10 Identity Build]]
- Related: [[V10 Identity API]]
- Related: [[V10 Identity Quality]]
