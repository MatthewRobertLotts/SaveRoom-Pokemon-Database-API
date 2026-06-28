# v12 App-Ready Pricing Response Contract

Tags: #type/project #status/needs-review

Status: DRAFT — proposed v12 contract, not implemented yet
Date: 2026-06-28
Branch: v12-app-readiness-next

## Purpose

Define what scanner/POS/inventory/web/listing tools need from pricing responses. This contract ensures the API returns a consistent, consumer-ready shape that downstream applications can rely on without interpreting raw source data.

**This is a proposed v12 contract draft. Do not claim implementation exists yet.**

## Response sections

### primary_price

The headline price for the card in the requested region (default UK).

```json
{
  "amount": 2.50,
  "currency": "GBP",
  "region": "UK",
  "price_type": "sold",
  "source": "ebay_uk",
  "evidence_count": 8,
  "confidence": "HIGH"
}
```

When no Tier 1 evidence exists, `primary_price` is `null` and the consumer should display `fallback_price` with appropriate UI treatment.

### fallback_price

The best available estimate when the primary UK evidence is absent or thin.

```json
{
  "amount": 2.46,
  "currency": "GBP",
  "region": "UK",
  "price_type": "market_converted",
  "original_currency": "USD",
  "original_amount": 3.10,
  "source": "justtcg",
  "fx_rate": 0.7935,
  "fx_rate_source": "ecb",
  "fx_rate_timestamp": "2026-06-28T00:00:00Z",
  "confidence": "LOW"
}
```

### source_breakdown

Per-source contribution list for provenance and debugging.

```json
[
  {
    "tier": 1,
    "source": "ebay_uk",
    "currency": "GBP",
    "price_type": "sold",
    "evidence_count": 8,
    "median_gbp": 2.50,
    "low_gbp": 1.80,
    "high_gbp": 3.20,
    "sample_date": "2026-06-25T10:00:00Z"
  }
]
```

### evidence_summary

Human-readable summary of the evidence state.

```json
{
  "total_evidence": 9,
  "uk_evidence": 8,
  "uk_tier_1_source": "ebay_uk",
  "has UK_sold_evidence": true,
  "has_converted_evidence": true,
  "oldest_evidence_date": "2026-06-15T00:00:00Z",
  "newest_evidence_date": "2026-06-25T10:00:00Z"
}
```

### confidence

Overall confidence in the primary estimate.

| Value | Meaning |
|---|---|
| `HIGH` | Strong Tier 1 evidence (5+ UK sold records, recent) |
| `MEDIUM` | Moderate Tier 1 evidence (2-4 records, or older) |
| `LOW` | Thin evidence, fallback-only, or converted currency |
| `NONE` | No evidence available |

### warnings

Array of human-readable warnings about the estimate.

```json
[
  "Only 2 UK sold records — treat as indicative.",
  "Fallback price converted from USD at ECB rate 2026-06-28."
]
```

### provider_status

Status of each downstream provider for this card.

```json
{
  "ebay_uk": "planned",
  "justtcg": "blocked_pending_terms",
  "cardmarket": "blocked_access_closed",
  "tcgplayer": "blocked_pending_access"
}
```

### last_refresh

ISO timestamp of when this pricing response was computed.

## Consumer notes

### Scanner app

- Needs: `primary_price` (or `fallback_price` with warning badge), `confidence`, `last_refresh`.
- Display: show primary price with confidence indicator. If primary is null, show fallback with "estimated from USD" badge.
- Offline: cache the last response per card. Show staleness warning if `last_refresh` is >24h old.

### POS system

- Needs: `primary_price` for checkout reference, `confidence` for staff guidance, `warnings` for receipt footnotes.
- Display: show price with source attribution on receipt. Never show converted-converted price without original currency note.
- Requirement: deterministic response shape so POS software can parse reliably.

### Inventory desktop app

- Needs: full `source_breakdown`, `evidence_summary`, `provider_status`.
- Display: evidence inspector panel showing per-source contribution, tier badges, freshness indicators.
- Bulk: needs batch pricing response (multiple cards in one request).

### Web tracker

- Needs: `primary_price`, `fallback_price`, `last_refresh`, `source_breakdown`.
- Display: price history chart with source annotations. Confidence trend over time.
- Performance: needs fast response (<200ms) for page-load rendering.

### Listing assistant

- Needs: `primary_price`, `fallback_price`, `confidence`, `warnings`, `evidence_summary`.
- Display: suggested listing price with confidence badge. Warning if evidence is thin.
- Output: auto-generate listing description with price justification note.

### External developer API

- Needs: all sections. Full contract is the developer-facing interface.
- Rate limit: standard API key quota.
- Stability: field additions are additive (new fields, not renames). Breaking changes require version bump.

## Proposed response shape (full)

```json
{
  "card_id": "cp-501e65fd75e0",
  "canonical_name": "Exeggcute",
  "set_code": "swsh9",
  "collector_number": "001",
  "primary_price": {
    "amount": 2.50,
    "currency": "GBP",
    "region": "UK",
    "price_type": "sold",
    "source": "ebay_uk",
    "evidence_count": 8,
    "confidence": "HIGH"
  },
  "fallback_price": {
    "amount": 2.46,
    "currency": "GBP",
    "region": "UK",
    "price_type": "market_converted",
    "original_currency": "USD",
    "original_amount": 3.10,
    "source": "justtcg",
    "fx_rate": 0.7935,
    "fx_rate_source": "ecb",
    "fx_rate_timestamp": "2026-06-28T00:00:00Z",
    "confidence": "LOW"
  },
  "source_breakdown": [...],
  "evidence_summary": {...},
  "confidence": "HIGH",
  "warnings": [],
  "provider_status": {...},
  "last_refresh": "2026-06-28T12:00:00Z"
}
```

## Links

- Related: `docs/V12_PRICING_STRATEGY_CORRECTION.md`
- Related: `docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md`
- Related: `docs/V12_APP_READINESS_AUDIT.md`
- Related: `docs/API_CONTRACT_V1.md`
