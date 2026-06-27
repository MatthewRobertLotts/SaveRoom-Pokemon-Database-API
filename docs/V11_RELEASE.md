# V11 Release Notes — Market Evidence Foundation

## Summary

v11.0 builds a trustworthy pricing/evidence engine on top of v10 canonical identity. It implements one excellent end-to-end pricing evidence pipeline through the TCGdex market API.

**This release is: v11.0 Market Evidence Foundation**

This release is NOT:
- pricing complete
- scanner-ready
- marketplace-ready
- POS-ready

## What v11.0 Implements

1. **Market evidence schema** — 7 new tables (sources, cache, observations, matches, aggregates, refresh runs, source health)
2. **Source adapter framework** — standard ABC for integrating pricing sources
3. **Raw response cache** — full JSON responses stored before normalisation
4. **First source end-to-end** — TCGdex (TCGPlayer + Cardmarket pricing)
5. **Normalised price observations** — currency, amount, finish, listing type, marketplace
6. **Observation-to-identity matching** — set_code + collector_number → canonical printing
7. **Conservative aggregate valuation** — median, low/high, confidence scoring
8. **Confidence scoring** — HIGH/MEDIUM/LOW/UNUSABLE with reasons
9. **Source health tracking** — success/failure, rate limits, response times
10. **Read-only API endpoints** — 6 endpoints under `/api/v1/prices`
11. **Manual refresh** — POST endpoint to trigger evidence collection
12. **Tests** — 113 new v11 tests

## Schema Changes

New tables (7):

```text
v11_price_sources
v11_price_source_cache
v11_price_observations
v11_price_observation_matches
v11_price_aggregates
v11_price_refresh_runs
v11_price_source_health
```

Migrations: v66-v72

No existing v10 or v9.2 tables are dropped or altered.

## API Endpoints Added

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/prices/sources` | List pricing sources |
| GET | `/api/v1/prices/sources/{source_code}/health` | Source health |
| GET | `/api/v1/prices/observations` | List observations |
| GET | `/api/v1/prices/observations/{id}` | Observation detail |
| GET | `/api/v1/prices/aggregate/{target_type}/{target_id}` | Aggregate valuation |
| POST | `/api/v1/prices/refresh/{target_type}/{target_id}` | Manual refresh |

## Breaking Changes

None. v11 is purely additive.

## Known Limitations

- Finish ambiguity: 90.4% of v10 variants have unknown finish. v11 does not invent finish-specific prices.
- No condition-specific pricing (TCGdex provides market-level only).
- No sold-price data (active listings only).
- Single source (TCGdex). Multi-source comparison is v11.1+.
- Admin UI is deferred. API can be consumed directly via curl.

## Deferred to v11.1+

- Second-source comparison (e.g., JustTCG when key is available)
- Finish enrichment (parse finish from listing titles)
- Thin admin UI for evidence inspection
- Multi-source aggregation with cross-validation
- FX conversion for cross-currency aggregates

## Test Results

```text
v11 tests:     113 passed
v10 critical:   65 passed
v9.2 critical:  33 passed
```

## How to Refresh Evidence

```bash
# Trigger refresh for a specific card
curl -X POST http://localhost:8765/api/v1/prices/refresh/canonical_printing/cp-sv03-125

# Check observations
curl "http://localhost:8765/api/v1/prices/observations?canonical_printing_id=cp-sv03-125"

# View aggregates
curl http://localhost:8765/api/v1/prices/aggregate/canonical_printing/cp-sv03-125
```

## Links

- Related: [[V11_MARKET_EVIDENCE_MODEL]]
- Related: [[V11_PRICE_ADAPTERS]]
- Related: [[V11_PRICE_API]]
- Related: [[V11_SOURCE_VALIDATION]]
- Related: [[V11_QUALITY_REPORT]]
