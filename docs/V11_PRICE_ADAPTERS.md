# v11 Price Adapters

Tags: #type/project #status/needs-review

Status: DESIGN_COMPLETE
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

This document describes the v11 pricing source adapter framework and the first source implementation (TCGdex).

## Adapter Framework

The adapter framework lives in `pricing_sources/base.py`. Every adapter implements:

```python
class PriceSourceAdapter(abc.ABC):
    @property
    def source_code(self) -> str: ...

    @property
    def source_name(self) -> str: ...

    def capabilities(self) -> dict[str, Any]: ...

    def health_check(self) -> SourceHealthResult: ...

    def build_queries(self, query: PriceQuery) -> list[dict[str, Any]]: ...

    def fetch(self, query: dict[str, Any]) -> dict[str, Any] | None: ...

    def normalise(self, raw_response: dict[str, Any], query: PriceQuery) -> list[PriceObservationCandidate]: ...

    def match_observations(self, observations: list[PriceObservationCandidate], query: PriceQuery) -> list[MatchedPriceObservation]: ...
```

## Data Types

| Type | Purpose |
|------|---------|
| `PriceObservationCandidate` | Normalised observation before identity matching |
| `MatchedPriceObservation` | Observation matched to a v10 identity target |
| `SourceHealthResult` | Health check result |
| `PriceQuery` | Query to send to a source |
| `ConfidenceLabel` | HIGH / MEDIUM / LOW / UNUSABLE |
| `ListingType` | active_listing / market_price / sold / guide / sealed_product |
| `MatchConfidence` | HIGH / MEDIUM / LOW / UNUSABLE |

## First Source: TCGdex

**File:** `pricing_sources/tcgdex.py`

TCGdex (https://tcgdex.dev) is a free, open-source Pokémon TCG API that aggregates pricing from TCGPlayer (USD) and Cardmarket (EUR).

### Why TCGdex was chosen

1. **Free and keyless** — no API key, no authentication, no cost
2. **Multi-marketplace** — TCGPlayer (North America) + Cardmarket (Europe) in one call
3. **Variant-aware** — separate pricing for normal, reverse-holo, holo
4. **Fresh** — updates hourly (TCGPlayer) to daily (Cardmarket)
5. **Fast** — ~50ms per request, no observed rate limits
6. **Legal** — open data aggregation, no scraping required
7. **Reliable** — consistent responses, 23,000+ cards covered

### Why other sources were rejected for v11.0

| Source | Reason for rejection |
|--------|---------------------|
| JustTCG | Requires paid API key — cannot develop without credentials |
| PokéWallet | Requires API key — sign-up needed for access |
| eBay Browse API | Requires OAuth app token, no free tier, complex for background pipeline |
| RapidAPI eBay | Requires `RAPIDAPI_KEY` env var — key may not be configured |

### TCGdex Data Quality Notes

- TCGPlayer `lowPrice` is the **lowest listed price** (can be outlier). Use `marketPrice` as primary indicator.
- Cardmarket `avg` is the average selling price over 30 days — reliable.
- Separate pricing for normal and holo variants.
- No condition-specific pricing (only market-level).
- No sold-price data (active listings only).
- No finish granularity beyond normal/reverse/holo.

### Integration Architecture

```
PriceQuery → TCGdexAdapter.build_queries() → query dicts
         → TCGdexAdapter.fetch() → raw JSON response
         → v11_price_source_cache (raw storage)
         → TCGdexAdapter.normalise() → PriceObservationCandidate list
         → TCGdexAdapter.match_observations() → MatchedPriceObservation list
         → v11_price_observations + v11_price_observation_matches
         → aggregator → v11_price_aggregates
```

## Links

- Related: [[V11_SOURCE_VALIDATION]]
- Related: [[V11_MARKET_EVIDENCE_MODEL]]
- Related: [[V11_PRICE_API]]
- TCGdex docs: https://tcgdex.dev/markets-prices
