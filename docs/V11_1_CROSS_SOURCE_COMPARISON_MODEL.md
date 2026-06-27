# v11.1 Cross-Source Comparison Model

Tags: #type/project #status/needs-review

Status: DESIGN_COMPLETE
Date: 2026-06-27
Branch: v11.1-market-evidence-next
Baseline commit: 32418f0

## Overview

This document designs the provider-neutral comparison layer for v11.1. It does **not** implement any specific second-source adapter. It defines how two or more independent evidence streams can be compared safely and how agreement/disagreement translates into a confidence signal.

This layer is intentionally independent of JustTCG, PokéWallet, Cardmarket, eBay, or any other provider. It operates on the existing v11 aggregate records and observation records produced by whatever adapters are registered.

## Design Decisions

### 1. What is being compared?

Comparison operates on **aggregate buckets**, not raw observations. A bucket is the full tuple:

```text
(target_type, target_id, currency, listing_type, finish, condition)
```

Only aggregates with the same bucket can be compared. Different buckets produce `MIXED_SEMANTICS`.

### 2. How do we compare two sources?

For a given bucket, each source may contribute zero or one aggregate row. Comparison requires **at least two sources** with usable aggregates in the same bucket.

Comparison uses the **median_price** from each source as the primary comparison value. Low/high/mean are informational only.

### 3. How do we compare medians?

We compute:

```python
abs_diff = abs(median_a - median_b)
pct_diff = abs_diff / max(median_a, median_b, epsilon)
```

where `epsilon` is a small positive value to avoid division by zero.

The percentage difference drives the agreement band:

| Band | Range | Meaning |
|---|---|---|
| `AGREE` | 0–15% | medians are close enough to reinforce confidence |
| `MINOR_DISAGREEMENT` | >15–35% | medians diverge modestly; confidence is reduced |
| `MAJOR_DISAGREEMENT` | >35% | medians diverge sharply; confidence is reduced more |

### 4. How do we handle missing second source?

If fewer than two sources have usable aggregates in the bucket, the comparison result is:

```text
agreement_band = INSUFFICIENT_EVIDENCE
confidence_impact = NONE
```

No comparison is recorded. Single-source confidence remains whatever the existing v11 aggregation logic already computed.

### 5. How do we handle stale sources?

Each aggregate has `computed_at` and the underlying observations have `fetched_at`. A source is considered stale if:

- the newest observation behind the aggregate is older than `stale_threshold_days` (default 30), **or**
- the aggregate's `computed_at` is older than `stale_threshold_days`.

If one source is stale and the other is fresh:

```text
agreement_band = STALE_SOURCE
confidence_impact = REDUCED
comparison_reason includes "stale source: {source_id}"
```

If both are stale:

```text
agreement_band = STALE_SOURCE
confidence_impact = REDUCED
comparison_reason = "both sources stale"
```

### 6. How do we handle currency mismatch?

Different currencies produce `MIXED_SEMANTICS`. No FX conversion is performed. The comparison layer never compares across currencies.

### 7. How do we handle listing type mismatch?

Different listing types (e.g., `sold` vs `market_price` vs `active_listing`) produce `MIXED_SEMANTICS`. Sold prices and active listings are fundamentally different evidence types and must not be compared as if equal.

### 8. How do we handle finish mismatch?

- Same finish → comparable.
- Both unknown → comparable but flagged with `MIXED_SEMANTICS` because the bucket is ambiguous.
- One known, one unknown → `MIXED_SEMANTICS`.
- Known but different finishes (e.g., `holo` vs `reverse_holo`) → `MIXED_SEMANTICS`.

### 9. How do we handle condition mismatch?

- Same condition value → comparable.
- Both unknown → comparable but flagged with `MIXED_SEMANTICS`.
- One known, one unknown → `MIXED_SEMANTICS`.
- Known but different (e.g., `raw` vs `graded`) → `MIXED_SEMANTICS`.

### 10. How does agreement improve confidence?

Agreement can only **maintain or modestly improve** confidence. It cannot create `HIGH` confidence from a single source. Rules:

- If existing aggregate confidence is `MEDIUM` and two sources `AGREE`, confidence may be raised to `HIGH` only if all other quality gates are also met (observation count, finish known, freshness OK).
- If existing confidence is `LOW`, agreement can raise it at most to `MEDIUM`.
- Agreement never raises confidence by more than one band.

### 11. How does disagreement lower confidence?

| Band | Confidence Impact |
|---|---|
| `AGREE` | `NONE` or slight boost |
| `MINOR_DISAGREEMENT` | `REDUCED` (one band down) |
| `MAJOR_DISAGREEMENT` | `REDUCED` (one band down, minimum `LOW`) |

Disagreement never produces `UNUSABLE` by itself; `UNUSABLE` is reserved for data-quality failures, not disagreement.

### 12. How does the admin UI explain this?

Future UI elements (not implemented in this commit):

- **Comparison card** per bucket showing:
  - source A median / source B median
  - percentage difference
  - agreement/disagreement badge
  - confidence impact reason
  - source freshness warning
  - single-source warning
- **Badge colours**:
  - green for `AGREE`
  - yellow for `MINOR_DISAGREEMENT`
  - red for `MAJOR_DISAGREEMENT`
  - grey for `INSUFFICIENT_EVIDENCE` / `MIXED_SEMANTICS` / `STALE_SOURCE`

## Important Non-Goals

This layer does **not**:

- make prices "correct";
- solve pricing;
- replace the existing v11 aggregation logic;
- perform FX conversion;
- infer missing finishes or conditions;
- create exact SKU prices from ambiguous evidence;
- raise confidence from one source only.

It only explains **source agreement/disagreement** in a conservative, auditable way.

## Data Shape

Comparison operates on plain dicts/dataclasses shaped like the existing `v11_price_aggregates` row. No live database connection is required for the core comparison function.

Required input fields per source:

```python
target_type: str
target_id: str
currency: str
listing_type: str
finish: str
condition: str
median_price: float
computed_at: str
fetched_at: str  # newest observation fetch behind this aggregate
source_id: str
```

## Links

- Related: `docs/V11_1_PREFLIGHT.md`
- Related: `docs/V11_MARKET_EVIDENCE_MODEL.md`
- Related: `docs/V11_PRICE_ADAPTERS.md`
- Related: `docs/V11_1_SECOND_SOURCE_VALIDATION.md`
- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_1_PUBLIC_SOURCE_TERMS_RESEARCH.md`
- Implementation: `pricing_sources/comparison.py`
- Tests: `tests/test_v11_1_cross_source_comparison.py`
