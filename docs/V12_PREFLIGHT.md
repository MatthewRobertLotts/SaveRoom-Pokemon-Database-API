# v12 Preflight

Tags: #type/project #status/needs-review

Status: PLANNING
Date: 2026-06-28
Branch: v12-app-readiness-next
Previous release: v11.3.0 (tag `v11.3.0`, commit `7c7a832`)

## Overview

v12 is the **app-readiness** release. It prepares the platform's API responses, data contracts, and consumer-facing surfaces for real product usage — scanner, POS, inventory, web tracker, listing assistant, and external developer API.

Slice 0 (this commit) is the **strategy correction and planning** slice. No code is changed.

## What this slice delivers

1. Pricing strategy correction (UK-first external pricing).
2. UK-first external pricing plan (hierarchy, outputs, rules).
3. App-ready pricing response contract draft.
4. App-readiness audit across 6 consumer surfaces.
5. API gap analysis.
6. Implementation plan.

## What this slice does NOT deliver

- No live provider adapter code.
- No external API calls.
- No real provider payloads.
- No API key handling.
- No paid credit usage.
- No marketplace logic.
- No scanner/POS/inventory/listing UI implementation.

## Blockers

- Live JustTCG/PokéWallet/Cardmarket/eBay provider adapters remain blocked pending approved access, terms, caching, fixture and display permissions.
- No live second-source provider until access is confirmed and terms are approved.

## Readiness checklist

- [x] Pricing strategy corrected to UK-first external.
- [x] UK-first pricing plan defined.
- [x] App-ready pricing response contract drafted.
- [x] App-readiness audit created.
- [x] API gap analysis created.
- [x] Implementation plan created.
- [x] Brain notes updated.
- [ ] App-ready card detail endpoint implemented.
- [ ] Live provider adapter (blocked).

## Links

- Related: `docs/V12_PRICING_STRATEGY_CORRECTION.md`
- Related: `docs/V12_UK_FIRST_EXTERNAL_PRICING_PLAN.md`
- Related: `docs/V12_APP_READY_PRICING_RESPONSE_CONTRACT.md`
- Related: `docs/V12_APP_READINESS_AUDIT.md`
- Related: `docs/V12_API_GAP_ANALYSIS.md`
- Related: `docs/V12_IMPLEMENTATION_PLAN.md`
- Previous release: `docs/V11_3_RELEASE.md`
