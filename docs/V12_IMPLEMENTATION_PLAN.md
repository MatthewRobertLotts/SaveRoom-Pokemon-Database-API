# v12 Implementation Plan

Tags: #type/project #status/needs-review

Status: PLANNING
Date: 2026-06-28
Branch: v12-app-readiness-next

## Overview

Implementation plan for v12 app-readiness. This is a planning document — no code is implemented here.

## Recommended first implementation slice

**App-ready card detail response.**

### Reason

Scanner, POS, inventory, web tracker and listing assistant all need one reliable card payload with canonical identity, localized display fields, set info, image manifest, variants, SKUs, UK-first pricing summary, fallback evidence summary, confidence and warnings. Building this endpoint first unblocks all consumer surfaces and establishes the response contract that all other v12 work extends.

### What this slice includes

1. New `GET /api/v1/cards/{type}/detail/{id}` endpoint.
2. Response assembly logic that combines:
   - v10 canonical identity (existing)
   - Localized display fields (existing)
   - Set info (existing)
   - Image manifest (existing image gateway, new manifest shape)
   - Variants and SKUs (existing)
   - UK-first pricing summary (new shape, no live provider calls)
   - Fallback evidence summary (new shape)
   - Confidence and warnings (new logic)
   - Provider status (new logic)
3. Pydantic response models for the app-ready contract.
4. Unit tests for the response assembly with fixtures.
5. No live provider calls. Pricing summary uses existing TCGdex data + placeholder structure for future UK-first data.

### What this slice does NOT include

- Live provider adapter code.
- External API calls.
- Real provider payloads.
- Batch endpoint.
- Chart-ready history.
- Listing-specific endpoint.
- Scanner image recognition.

## Implementation slices (recommended order

### Slice 1: App-ready card detail response

- **Endpoint:** `GET /api/v1/cards/{card_key}/detail`
- **Status:** IMPLEMENTED
- **Effort:** medium
- **Depends on:** nothing
- **Unblocks:** all consumer surfaces

### Slice 2: Batch pricing endpoint

- **Endpoint:** `POST /api/v1/prices/batch/`
- **Effort:** small
- **Depends on:** Slice 1 (pricing summary logic)
- **Unblocks:** scanner multi-card, inventory bulk, web collection view

### Slice 3: Chart-ready price history

- **Endpoint:** `GET /api/v1/prices/chart/{type}/{id}`
- **Effort:** small
- **Depends on:** nothing (extends existing history)
- **Unblocks:** web tracker

### Slice 4: Listing assistant endpoint

- **Endpoint:** `GET /api/v1/prices/listing/{type}/{id}`
- **Effort:** small
- **Depends on:** Slice 1 (pricing summary + confidence)
- **Unblocks:** listing assistant

### Slice 5: Live provider adapter (blocked)

- **Endpoint:** uses existing adapter framework
- **Effort:** large
- **Depends on:** approved access/terms for at least one provider
- **Unblocks:** real multi-source pricing, UK-first sold evidence

## Estimated scope

| Slice | New endpoints | New models | New tests | Code risk |
|---|---|---|---|---|
| 1. Card detail | 1 | 3-4 | 10-15 | low |
| 2. Batch pricing | 0 | 1 | 4-6 | low |
| 3. Chart history | 0 | 1 | 4-6 | low |
| 4. Listing endpoint | 0 | 1 | 4-6 | low |
| 5. Live adapter | 0 | 3-5 | 10-15 | medium |

## Guardrails

- No live provider calls in slices 1-4.
- No external API calls.
- No real provider payloads.
- No paid credits.
- Pricing summary uses existing TCGdex data with the new shape.
- UK-first structure is in place but populated from TCGdex until live UK evidence is available.
- Every pricing summary includes `confidence: "LOW"` or `confidence: "NONE"` and appropriate warnings when no live UK evidence exists.

## Links

- Related: `docs/V12_PRICING_STRATEGY_CORRECTION.md`
- Related: `docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md`
- Related: `docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md`
- Related: `docs/V12_APP_READINESS_AUDIT.md`
- Related: `docs/V12_API_GAP_ANALYSIS.md`
- Related: `docs/V12_PREFLIGHT.md`
