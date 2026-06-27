# V10 Identity Quality Report

## Summary

Status: **v10 complete. Full population executed successfully against v9.2 runtime DB.**

## Population Results

```
Total cards:                298,688
Mapped cards:               297,194 (99.5%)
Unmapped cards:             1,494 (0.5%)
Canonical printings:        121,771
Card links:                 297,194
Commercial variants:        208,894
Sellable SKUs:              208,894
External references:        187,102
Build runs:                 1
High confidence:            121,771 (100%)
Unknown finish:             188,961 (90.4% of variants)
Warnings:                   0
Errors:                     0
```

## Variants by Finish

| Finish | Count | % |
|--------|-------|---|
| unknown | 188,961 | 90.4% |
| reverse | 10,778 | 5.2% |
| holo | 7,480 | 3.6% |
| reverse_holo | 1,557 | 0.7% |
| normal | 118 | 0.1% |

## Coverage Analysis

The 90.4% `unknown` finish rate reflects cards where the `variants` JSON field
exists but contains no parseable finish flags (e.g., all values are `false` or
the field is empty). Cards that DO have holo/reverse evidence (9.6% of variants)
are correctly identified.

## Unmapped Cards

1,494 cards (0.5%) have no mapping. Top causes:
- Legacy sets (gym1/gym2 from early expansions, McDonald's collections)
- Cards with non-standard `core_set_id` patterns that don't group cleanly

## Quality Risks

1. **Finish backfill needed**: 90% `unknown` is honest but limits pricing/inventory use
2. **Single-language canonicals in v10**: Each language gets its own canonical printing — should be consolidated for cross-language collectors in v10.1
3. **Graded/sealed SKUs deferred**: Only single-card SKUs in v10

All 314 tests pass (60 v10 + 254 existing).

Full build command: `scripts/build_v10_identity.py --db full_tcgdex/staging_v9_baseline.sqlite --json`

## Links

- Related: [[V10 Identity Model]]
- Related: [[V10 Preflight]]
- Related: [[V10 Identity Schema Audit]]
- Related: [[V10 Identity Build]]
- Related: [[V10 Identity API]]
- Related: [[V10 Release Notes]]
