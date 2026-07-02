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

#### 1. Inventory item list filters and POS search polish

Candidate filters:

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

This should remain read-only and should build on existing local tables:

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

#### 3. POS-ready fixture pack

Create stable sample API responses for frontend development and regression checks:

```text
card detail
inventory workflow
draft workflow
sales summary
listing draft filters
```

Fixtures must be synthetic/local and must not include private provider payloads, account metadata, headers, API keys, raw provider JSON, or sanitized candidates unless already approved and documented as public test fixtures.

#### 4. OpenAPI/client contract hardening

Tighten typed response models where flexible `dict[str, Any]` is still awkward for generated clients.

Candidate targets:

```text
listing draft response sections
workflow summary sections
local sales summary sections
listing assistant sections
```

Avoid broad refactors unless tests prove generated-client value.

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

Recommended first milestone:

```text
Inventory item list filters and POS search polish
```

Reason:

```text
v12.1 added workflow detail endpoints. The next frontend/POS gap is finding the right inventory items efficiently before opening their workflow pages.
```

Candidate endpoint to inspect first:

```text
GET /api/v1/inventory/items
```

Potential filter set:

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

- Preserve existing pagination and response shape.
- Add only optional filters.
- Use bound SQL parameters.
- Prefer `EXISTS` / `NOT EXISTS` for workflow-state filters.
- Keep the endpoint read-only.
- Do not call providers, marketplaces, network APIs, or LLMs.
- Do not mutate inventory, drafts, reservations, sales, or transaction rows.

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
