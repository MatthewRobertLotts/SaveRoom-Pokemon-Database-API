# v12.2 Planning

Tags: #type/plan #pokemon-db #v12-2 #planning

## Overview

`v12.2-next` is a planning branch only until Matthew approves the first v12.2 implementation milestone.

`v12.1.0` remains stable on `main`.

This document records candidate directions for the next normal feature batch after v12.1.0. It does not implement v12.2 features and does not start v13.

## Body

### Branch state

```text
Planning branch: v12.2-next
Base release: v12.1.0
Base commit: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
Base tag dereferenced commit: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
```

### Versioning policy

```text
v12.1.1 = bugfix/docs/polish only against v12.1.0
v12.2 = next normal feature batch
v13 = major architecture/external product shift only with explicit Matthew approval
```

Rules:

- Do not add more feature work directly to `main`.
- Do not implement v12.2 features until Matthew approves the first v12.2 implementation milestone.
- Do not start v13 without explicit Matthew approval.
- Keep safety boundaries from v12.1 active unless Matthew explicitly changes scope.

### Active safety boundaries

```text
No live provider calls.
No API-credit spend.
No _get_justtcg_price_data() calls unless a future approved milestone explicitly requires and safely gates them.
No JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM API calls.
No marketplace publishing.
No marketplace order import.
No payment capture.
No refund processing.
No fulfilment/shipping state.
No API keys, headers, account metadata, private provider payloads, raw provider JSON, sanitized candidates, or raw filesystem paths committed or exposed.
No v13 work.
```

### v12.2 candidate menu

#### 1. Implemented: inventory item list filters and POS search polish

Implemented in v12.2 milestone 1. Candidate filters:

```text
sku_id
card_key
condition
status
location_code
has_listing_draft
has_active_reservation
has_completed_sale
```

Goal: make it easier for POS/frontends to find the right physical inventory item before opening item workflow detail pages.

Implementation status: `GET /api/v1/inventory/items` now preserves existing `limit`, `offset`, `q`, `status`, `location_code`, response shape, and pagination while adding optional filters for `sku_id`, `card_key`, `condition`, `has_listing_draft`, `has_active_reservation`, and `has_completed_sale`.

This remains read-only and builds on existing local tables:

```text
physical_items
sellable_skus
canonical_printings
inventory_listing_draft_links
listing_draft_inventory_reservations
listing_draft_sales
```

#### 2. Inventory item history/detail polish

Build on existing inventory transaction endpoints only if there is a real frontend gap.

Candidate shape:

```text
GET /api/v1/inventory/items/{item_id}/history
```

This should be read-only and should not duplicate or mutate inventory transaction state.

#### 3. Implemented: POS-ready fixture pack

Implemented in v12.2 milestone 2. Creates stable sample API responses for frontend development and regression checks:

```text
card detail
inventory workflow
draft workflow
sales summary
listing draft filters
inventory item list filters
```

Fixture files live under `docs/fixtures/v12_2_pos/` with a focused doc at `docs/V12_2_POS_READY_FIXTURE_PACK.md`.

Fixtures are synthetic/local and must not include private provider payloads, account metadata, headers, API keys, raw provider JSON, or sanitized candidates unless already approved and documented as public test fixtures.

#### 4. Implemented: OpenAPI/client contract hardening

Audit/planning milestone completed in v12.2 milestone 3. First implementation milestone completed in v12.2 milestone 4.

Implemented hygiene and typing:

```text
app.openapi() now builds without the DeliveryPolicyUpdate monkeypatch
admin key deactivate route registrations now have unique operation IDs
LocalSalesSummaryResponseV1.data is typed with compact aggregation models
local sales summary JSON keys and behaviour are preserved
```

Still deferred:

```text
AppReadyBatchResponseV1.data typing
workflow summary booleans
workflow nested object typing
listing draft payload internals
card detail commercial/pricing/provider internals
```

Previous hardening follow-up candidate:

```text
App-ready batch response typing + workflow summary booleans
```

Hold this unless a real release-candidate blocker appears. The current recommendation is to move v12.2 toward release-candidate audit rather than adding more backend hardening.

#### 5. App-facing image/status polish

Clarify card image status versus physical item photos and add read-only health where useful.

Important distinction:

```text
card image = reference/display art for the card
physical item photo = photo of the specific SaveRoom inventory item
```

Do not expose raw filesystem paths or bypass existing authenticated image delivery policy.

#### 6. Local sales reporting v2

Add date buckets or platform/card summaries only if needed.

Allowed only if kept out of accounting/payment scope:

```text
date buckets
platform summaries
card_key summaries
inventory item summaries
```

Avoid:

```text
tax/accounting advice
payment capture
refund processing
fulfilment/shipping state
marketplace reconciliation
market-pricing evidence claims
```

#### 7. v12.1.1 bugfix branch

Use only if a release bug is found.

Scope:

```text
bugfixes
docs corrections
small polish
no normal feature batch
```

### Recommended first v12.2 implementation milestone

Implemented first milestone:

```text
Inventory item list filters and POS search polish
```

Reason:

```text
v12.1 added workflow detail endpoints. The next frontend/POS gap was finding the right inventory items efficiently before opening their workflow pages.
```

Endpoint updated:

```text
GET /api/v1/inventory/items
```

Implemented filter set:

```text
sku_id
card_key
condition
status
location_code
has_listing_draft
has_active_reservation
has_completed_sale
```

Recommended implementation constraints:

- Existing pagination and response shape preserved.
- Only optional filters added.
- User-supplied values use bound SQL parameters.
- Workflow-state filters use `EXISTS` / `NOT EXISTS`.
- Endpoint remains read-only.
- No provider, marketplace, network API, or LLM calls.
- No inventory, draft, reservation, sale, or transaction row mutation.

### v12.2 release-candidate audit

Release-candidate audit completed for `v12.2-next` at source HEAD `69c9c61`.

Status:

```text
v12.2.0 release candidate — feature complete pending merge/tag
```

Audit result:

```text
OpenAPI builds directly
DUPLICATE_OPERATION_IDS []
Targeted v12.2/v12.1 contract tests passed
Full suite: 937 passed, 1 skipped, 19 warnings
Brain/vault state updated
```

Recommended next action is Matthew approval for merge/tag as `v12.2.0`. Do not start new v12.2 feature work unless a release blocker is found.

### App transition decision after v12.2

`v12.2.0` should now be treated as the API/client readiness release. After it is tagged, the next major work can move to a separate app repository rather than continuing to harden backend surfaces just because more hardening is possible.

Recorded direction:

```text
API repo: SaveRoom-Pokemon-Database-API = backend brain/platform
Future app repo: SaveRoom-Scanner-App = Flutter/mobile/frontend product
```

The app should consume the API; it should not embed the API/database brain. Start the app with fixture mode and real API mode using the v12.2 fixtures/OpenAPI contract.

Future version plan:

```text
v12.2.0 = API/client/app-readiness release
v12.3.0 = app user/auth/entitlement foundation
v12.4.0 = scanner/collector backend foundation
v12.5.0 = paid beta readiness
v13.0 = major commercial platform / external product ecosystem shift only with explicit Matthew approval
```

Normal mobile users should not receive raw API keys. Future app access should use app-user auth/session tokens, while developer API keys/scopes/quotas remain for external developers and business integrations.

Billing provider integration should wait until the app has enough value to charge for. Do not start user accounts, subscription records, payment integration, app login, collection tables, the app repo, or v13 during v12.2.

Recommended next step:

```text
v12.2 release-candidate audit, then tag v12.2.0 if clean
```

### Not approved yet

The following are not approved by this planning document:

```text
marketplace publishing
Whatnot/eBay/Shopify auth
order import
refunds
fulfilment/shipping
payment capture
tax/accounting
TotalTCG blending
customer app frontend
external developer API productisation
v13 work
```

## Links

- Related: [V12.1 Post-Release State](V12_1_POST_RELEASE_STATE.md)
- Related: [V12.1 Release Candidate Audit](V12_1_RELEASE_CANDIDATE_AUDIT.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
- Related: [V12.1 POS Inventory API Polish Plan](V12_1_POS_INVENTORY_API_POLISH_PLAN.md)
- Related: [V12.2 Inventory Item List Filters](V12_2_INVENTORY_ITEM_LIST_FILTERS.md)
- Related: [V12.2 POS-Ready Fixture Pack](V12_2_POS_READY_FIXTURE_PACK.md)
- Related: [V12.2 OpenAPI Client Contract Hardening Audit](V12_2_OPENAPI_CLIENT_CONTRACT_HARDENING_AUDIT.md)
- Related: [V12.2 OpenAPI Schema Hygiene and Sales Summary Typing](V12_2_OPENAPI_SCHEMA_HYGIENE_AND_SALES_SUMMARY_TYPING.md)
- Related: [V12.2 App Transition Plan](V12_2_APP_TRANSITION_PLAN.md)
- Related: [V12.2 Release Candidate Audit](V12_2_RELEASE_CANDIDATE_AUDIT.md)
