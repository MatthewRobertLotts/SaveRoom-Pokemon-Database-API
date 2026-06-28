# v12 App-Readiness Audit

Tags: #type/project #status/needs-review

Status: DRAFT
Date: 2026-06-28
Branch: v12-app-readiness-next

## Overview

Audit the current API/data platform against the needs of six consumer surfaces. For each consumer, assess what exists, what is missing, and what the corrected UK-first pricing strategy requires.

## Consumer 1: Scanner app

### What it needs

- Card identification from image/photo.
- Canonical card identity (name, set, collector number).
- Localized display fields.
- Image manifest for verification.
- UK-first pricing summary for identified card.
- Confidence indicator for the price.
- Offline/cache support for scanned cards.

### What exists

- v10 canonical printings, commercial variants, sellable SKUs.
- v10 identity API endpoints.
- Image gateway with signed URLs.
- v11 pricing evidence API (single-source TCGdex).
- v11.1 source comparison infrastructure.

### What is missing

- Image hash matching for identified cards.
- UK-first pricing summary in the card detail response.
- Fallback pricing evidence summary.
- Confidence and warnings in the card detail response.
- Offline/cache-friendly response shape.
- Scanner-specific endpoint.

### Image needs

- Primary image URL (signed).
- Image manifest (normal, holo, reverse, etc.).
- Fallback image chain.

### UK-first pricing needs

- `primary_price` in GBP when available.
- `fallback_price` with conversion metadata.
- `confidence` and `warnings`.

### Performance needs

- <500ms response for single-card lookup.
- Batch lookup for multi-scan sessions.

### Risk/limitations

- Scanner prototype is early. Image hash matching is not production-ready.
- UK pricing is not live; scanner would use TCGdex-only data until provider access is approved.

## Consumer 2: POS system

### What it needs

- Card identification (barcode/QR/manual search).
- Canonical identity for receipt display.
- Price estimate for checkout reference.
- Source attribution for receipt footnotes.
- Deterministic response shape.

### What exists

- v10 identity API.
- v11 pricing evidence API.
- Search endpoints.

### What is missing

- POS-specific endpoint with receipt-ready price summary.
- Source attribution text for receipts.
- Confidence display for staff.

### UK-first pricing needs

- `primary_price` in GBP.
- Receipt footnote: source, confidence, date.
- Fallback handling when no UK evidence.

### Auth/scopes needs

- POS client scope (read-only pricing, no write).
- Rate limit: moderate (burst during checkout).

### Risk/limitations

- POS is not built. This is a future product surface.

## Consumer 3: Inventory desktop app

### What it needs

- Full card detail with canonical identity.
- Image manifest.
- Variant/SKU breakdown.
- UK-first pricing summary.
- Full source breakdown for evidence inspector.
- Provider status indicators.
- Bulk pricing refresh.

### What exists

- v10 identity API with variants and SKUs.
- v11 pricing evidence API.
- v11.1 comparison API.
- Browser UI with evidence panel.

### What is missing

- App-ready card detail endpoint (combines identity + images + pricing + variants + SKUs in one response).
- Evidence inspector with tier badges and freshness indicators.
- Bulk pricing endpoint.
- Provider status in the response.

### Inventory/SKU needs

- SKU-level pricing (per condition/finish).
- Stock status integration.
- Purchase price vs market estimate tracking.

### Offline/cache needs

- Full card detail cache.
- Staleness indicator.
- Incremental refresh.

### Risk/limitations

- Inventory app is not built. This is a future product surface.

## Consumer 4: Web collection/tracker

### What it needs

- Card detail with pricing.
- Price history chart data.
- Source annotations on chart.
- Confidence trend.
- Fast response for page rendering.

### What exists

- v10 identity API.
- v11 pricing API with history.
- v11.1 comparison API.
- Browser UI.

### What is missing

- Chart-ready price history format (series with source annotations).
- Confidence trend data.
- UK-first pricing summary.
- Fast card detail endpoint.

### Performance needs

- <200ms for card detail response.
- CDN-friendly cache headers.

### Rate-limit needs

- Web client quota (higher than POS, lower than scanner burst).

### Risk/limitations

- Web tracker is not built as a standalone product. Browser UI exists but is internal.

## Consumer 5: Listing assistant

### What it needs

- Card identity + suggested listing price.
- Price justification note.
- Confidence badge.
- Warning when evidence is thin.
- Listing description generation support.

### What exists

- v10 identity API.
- v11 pricing evidence API.
- Search endpoints.

### What is missing

- Listing-specific endpoint with suggested price + justification.
- Confidence badge logic.
- Thin-evidence warning text.
- Description generation template data.

### UK-first pricing needs

- GBP primary price for UK marketplace listings.
- Source attribution for listing description.
- Fallback price with conversion note.

### Risk/limitations

- Listing assistant is not built. This is a future product surface.

## Consumer 6: External developer API

### What it needs

- Stable, versioned API contract.
- Full card detail endpoint.
- Pricing with source breakdown.
- API key auth with scopes.
- Rate limiting with clear headers.
- Documentation.

### What exists

- v10 identity API (versioned).
- v11 pricing API (versioned).
- API key management (tenants, scopes, quotas).
- 68 FastAPI routes.

### What is missing

- App-ready card detail endpoint (combines all sections).
- UK-first pricing in the response.
- Source breakdown in the response.
- Provider status in the response.
- API contract documentation for the new shape.

### Auth/scopes needs

- Developer API key with read scopes.
- Commercial use scope (future).
- Rate limit headers in every response.

### Rate-limit needs

- Per-key quota.
- Per-minute burst limit.
- Clear 429 response with retry-after.

### Risk/limitations

- External developer API is not publicly launched.
- Commercial use requires confirmed provider terms.

## Links

- Related: `docs/V12_API_GAP_ANALYSIS.md`
- Related: `docs/V12_IMPLEMENTATION_PLAN.md`
- Related: `docs/API_CONTRACT_V1.md`
