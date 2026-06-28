# v12 API Gap Analysis

Tags: #type/project #status/needs-review

Status: DRAFT
Date: 2026-06-28
Branch: v12-app-readiness-next

## Overview

Identify gaps between what the current API provides and what the six app-ready consumers need. This feeds the implementation plan.

## Current API surface

### v10 identity endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/cards/` | Card list with pagination |
| `GET /api/v1/cards/{type}/{id}` | Card detail by type/id |
| `GET /api/v1/cards/search/` | Search cards |
| `GET /api/v1/sets/` | Set list |
| `GET /api/v1/sets/{set_id}` | Set detail |
| `GET /api/v1/sets/{set_id}/cards` | Cards in set |
| `GET /api/v1/languages/` | Language list |
| `GET /api/v1/images/{type}/{id}` | Image gateway |

### v11 pricing endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/prices/{type}/{id}` | Price evidence for card |
| `POST /api/v1/prices/refresh/{type}/{id}` | Trigger price refresh |
| `GET /api/v1/prices/history/{type}/{id}` | Price history |
| `GET /api/v1/prices/aggregate/{type}/{id}` | Aggregated price |
| `GET /api/v1/prices/sources/` | Source list |
| `GET /api/v1/prices/refresh/status` | Refresh status |

### v11.1 comparison endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/prices/comparison/{type}/{id}` | Cross-source comparison |

### v11.3 fixture endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/prices/fixtures/` | Fixture management (internal) |

## Gaps

### Gap 1: No app-ready card detail endpoint

**Consumers affected:** all 6.

**Current state:** scanner/POS/inventory/web/listing/external API consumers must call multiple endpoints (identity, pricing, images, variants, SKUs) and assemble the card detail themselves.

**Required:** a single `GET /api/v1/cards/{type}/detail/{id}` (or similar) that returns canonical identity + localized display + set info + image manifest + variants + SKUs + UK-first pricing summary + fallback evidence summary + confidence + warnings in one response.

### Gap 2: No UK-first pricing summary

**Consumers affected:** scanner, POS, inventory, web, listing, external API.

**Current state:** v11 pricing endpoints return TCGdex-only evidence. No GBP headline, no source breakdown, no tier labelling, no FX conversion metadata.

**Required:** pricing summary section in the card detail response with `primary_price`, `fallback_price`, `source_breakdown`, `confidence`, `warnings`, `provider_status`.

### Gap 3: No fallback evidence summary

**Consumers affected:** scanner, POS, inventory, listing.

**Current state:** When no TCGdex evidence exists, the consumer sees an empty response with no guidance on why or what to display instead.

**Required:** explicit fallback evidence summary with source availability, conversion metadata, and consumer-facing warnings.

### Gap 4: No provider status in response

**Consumers affected:** inventory, web, external API.

**Current state:** provider status is not exposed in API responses. Consumers cannot show "eBay UK: planned" or "JustTCG: blocked" badges.

**Required:** `provider_status` section in the card detail response.

### Gap 5: No batch pricing endpoint

**Consumers affected:** scanner (multi-card), inventory (bulk refresh), web (collection view).

**Current state:** pricing is queried per-card. No batch endpoint.

**Required:** `POST /api/v1/prices/batch/` with array of card IDs, returning pricing summaries for each.

### Gap 6: No chart-ready price history

**Consumers affected:** web tracker.

**Current state:** price history returns raw observations. No time-series aggregation, no source annotations, no confidence trend.

**Required:** chart-ready series format with date buckets, per-source series, confidence trend line.

### Gap 7: No listing-specific endpoint

**Consumers affected:** listing assistant.

**Current state:** no endpoint returns suggested listing price + justification text.

**Required:** listing-specific endpoint or section with suggested price, confidence badge, thin-evidence warning, and description template data.

### Gap 8: No image manifest in card detail

**Consumers affected:** scanner, inventory, web.

**Current state:** image gateway returns a single signed URL. No manifest of available images (normal, holo, reverse, etc.).

**Required:** image manifest array in card detail response.

## Priority for first implementation slice

**Gap 1 (app-ready card detail endpoint)** is the highest priority because it unblocks all other consumers. The remaining gaps are sections within that endpoint or follow-on endpoints.

## Links

- Related: `docs/V12_APP_READINESS_AUDIT.md`
- Related: `docs/V12_IMPLEMENTATION_PLAN.md`
- Related: `docs/API_CONTRACT_V1.md`
