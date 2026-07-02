# v12.2 OpenAPI Client Contract Hardening Audit

Tags: #type/doc #pokemon-db #v12-2 #openapi #client-contract

## Overview

v12.2 milestone 3 audits the app-facing API contract and generated OpenAPI schema for frontend/client-generation awkwardness.

This is an audit and planning milestone only. It does not change endpoint behaviour, response shapes, marketplace state, inventory state, or provider wiring.

## Body

### 1. Current branch and commit

```text
Branch: v12.2-next
Commit: 3781d0953c18ca83cbe3c1d8c7e2097fee26dabf
Subject: 3781d09 docs: add POS-ready fixture pack
```

### 2. v12.1.0 stable baseline

Stable release remains:

```text
v12.1.0 on main
main/tag commit: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
```

### 3. v12.2 current milestones

Implemented on `v12.2-next` before this audit:

```text
Milestone 1: Inventory item list filters and POS search polish — ee81207
Milestone 2: POS-ready fixture pack — 3781d09
Milestone 3: OpenAPI/client contract hardening audit — this document
```

### 4. Endpoints audited

```text
GET  /api/v1/cards/{card_key}/detail
POST /api/v1/cards/detail/batch
GET  /api/v1/inventory/items
GET  /api/v1/inventory/items/{item_id}
GET  /api/v1/inventory/items/{item_id}/workflow
GET  /api/v1/listings/drafts
GET  /api/v1/listings/drafts/{draft_id}
GET  /api/v1/listings/drafts/{draft_id}/workflow
GET  /api/v1/sales
GET  /api/v1/sales/{sale_id}
GET  /api/v1/sales/summary
```

### 5. OpenAPI schema summary

A direct local `app.openapi()` call currently fails before returning a schema because a global model reference is missing in `pokemon_db_v2_fastapi.py`:

```text
PydanticUserError: TypeAdapter[... ForwardRef('DeliveryPolicyUpdate') ...] is not fully defined
```

This is not caused by the v12.2 audited endpoints. It appears to come from the image delivery policy update route using `DeliveryPolicyUpdate` without importing that class into the FastAPI module namespace. This should be treated as the top OpenAPI hardening blocker because generated clients cannot rely on a schema that fails to build without a local monkeypatch.

For audit visibility only, a local no-network script temporarily injected `DeliveryPolicyUpdate` from `pokemon_db_v5_api_models` before calling `create_app().openapi()`. With that local-only workaround, the schema summary was:

```text
OPENAPI_VERSION 3.1.0
PATH_COUNT 89
SCHEMA_COUNT 116
```

The patched local OpenAPI build also emitted:

```text
UserWarning: Duplicate Operation ID v1_admin_deactivate_key_api_v1_admin_keys__key_id__deactivate_post
```

That duplicate operation ID is another generated-client hygiene issue, but lower priority than the schema-build blocker.

### 6. Response models audited

The audited response-model references from OpenAPI were:

```text
GET  /api/v1/cards/{card_key}/detail              -> AppReadyCardDetailResponseV1
POST /api/v1/cards/detail/batch                   -> AppReadyBatchResponseV1
GET  /api/v1/inventory/items                      -> InventoryListResponse
GET  /api/v1/inventory/items/{item_id}            -> InventoryItemResponse
GET  /api/v1/inventory/items/{item_id}/workflow   -> InventoryItemWorkflowResponseV1
GET  /api/v1/listings/drafts                      -> ListingDraftListResponseV1
GET  /api/v1/listings/drafts/{draft_id}           -> ListingDraftResponseV1
GET  /api/v1/listings/drafts/{draft_id}/workflow  -> ListingDraftWorkflowResponseV1
GET  /api/v1/sales                                -> LocalSaleListResponseV1
GET  /api/v1/sales/{sale_id}                      -> LocalSaleResponseV1
GET  /api/v1/sales/summary                        -> LocalSalesSummaryResponseV1
```

### 7. `dict[str, Any]` / flexible sections found

Current flexible sections that weaken generated clients:

| Model | Flexible section | Notes |
|---|---|---|
| `AppReadyCommercialV1` | `canonical_printing`, `commercial_variants`, `sellable_skus`, `external_references` | Stable enough conceptually, but broad v10/v12 identity payloads may still evolve. |
| `AppReadyBatchResponseV1` | `data: Any`, `metadata: Any` | `AppReadyBatchDataV1` exists but is not wired into the response schema. OpenAPI does not expose it. |
| `InventoryListResponse` | `pagination: dict[str, Any]` | Actual pagination shape is stable: `limit`, `offset`, `count`, `total`, `has_more`. |
| `InventoryItemWorkflowResponseV1` | `data: dict[str, Any]` | Workflow payload has stable top-level sections and summary booleans. |
| `ListingDraftResponseV1` | `data: dict[str, Any]` | Draft payload is stable enough for docs/fixtures but still includes assistant-derived listing fields. |
| `ListingDraftListResponseV1` | `data: list[dict[str, Any]]` | Draft list rows are weakly typed. |
| `ListingDraftWorkflowResponseV1` | `data: dict[str, Any]` | Workflow payload has stable top-level sections and summary booleans. |
| `LocalSaleResponseV1` | `data: dict[str, Any]` | Local sale row shape is produced by `_sale_row_to_response` and appears stable. |
| `LocalSaleListResponseV1` | `data: list[dict[str, Any]]` | Same sale row shape as detail/list. |
| `LocalSalesSummaryResponseV1` | `data: dict[str, Any]` | Aggregation block is stable and low-risk to type. |

### 8. Generated-client pain points

1. **OpenAPI cannot build cleanly** without fixing/importing `DeliveryPolicyUpdate`; this blocks client generation globally.
2. **Duplicate operation ID** for admin key deactivation may cause generated clients to overwrite or rename methods.
3. **`AppReadyBatchResponseV1.data: Any`** hides an existing typed `AppReadyBatchDataV1` model from generated clients.
4. **Workflow responses expose `data` as arbitrary object**, so clients do not get typed `current_state`, `summary`, `inventory_item`, `draft`, `reservation`, or `sale` sections.
5. **Local sales summary uses arbitrary object**, despite a stable aggregation shape that POS/reporting clients can consume directly.
6. **Listing draft rows and sale rows are duplicated as informal dict shapes**, making generated clients weaker than the runtime contract.
7. **Pagination typing is inconsistent**: listing drafts and sales use `PaginationMeta`; inventory lists and transaction lists still use `dict[str, Any]`.
8. **Nullable fields are real but not always documented at the model field level**, especially optional workflow links/reservations/sales, optional pricing sections, and nullable image URLs.

### 9. Stable sections safe to type

Low-risk stable sections:

```text
PaginationMeta-style pagination for inventory lists
Inventory workflow summary booleans
Listing draft workflow summary booleans
Workflow link snippet from _workflow_link_row_to_response
Reservation snippet from _reservation_row_to_response
Sale snippet from _sale_row_to_response
Local sales summary aggregation blocks
AppReadyBatchResponseV1.data using existing AppReadyBatchDataV1
```

The POS fixture pack now gives stable examples for these shapes, which makes future typed-model work easier to validate without provider or marketplace calls.

### 10. Sections that should stay flexible for now

Keep these flexible until a dedicated implementation milestone approves narrower contracts:

```text
AppReadyCommercialV1 canonical/commercial/SKU/external-reference details
AppReadyPricingV1 provider/source internals beyond already typed price/evidence shell
Listing assistant output and persisted assistant payloads
Listing draft description/listing payload internals
Image/source-provider diagnostic internals
```

Reason: these sections are useful app-facing data, but a broad type pass would churn high-surface identity/listing/pricing shapes and risks freezing internals too early.

### 11. Naming consistency findings

Current names are mostly understandable but inconsistent in places:

- `InventoryItemWorkflowResponseV1.data` uses `inventory_item`, `listing_draft_link`, `draft`, `reservation`, `sale`, `summary`.
- `ListingDraftWorkflowResponseV1.data` uses `draft`, `listing_draft_link`, `inventory_item`, `reservation`, `sale`, `summary`.
- Inventory workflow summary uses `has_listing_draft`, while listing workflow summary uses `is_inventory_linked` for the same relationship from the other direction. This is acceptable, but clients need docs if both are rendered in one UI.
- Reservation fields consistently use `reservation_id`, `draft_id`, `inventory_item_id`, `card_key`, `quantity`, `status`, timestamps, and release fields.
- Sale fields consistently use `sale_id`, `draft_id`, `reservation_id`, `inventory_item_id`, `card_key`, `quantity`, `platform`, `sale_price`, `currency`, `status`, `sold_at`, buyer/order references, notes, and timestamps.
- Metadata model naming is specific but not unified: `ListingDraftMetadataV1`, `LocalSaleMetadataV1`, `LocalSalesSummaryMetadataV1`, workflow-specific metadata models. That is acceptable for now.

### 12. Nullable-field documentation findings

Nullable fields should be documented before or alongside typed-model work:

```text
workflow listing_draft_link: null when no local inventory/draft link exists
workflow draft: null when no linked draft exists or linked draft is missing
workflow inventory_item: null when draft link points to an unavailable item
workflow reservation: null when no current/latest reservation exists
workflow sale: null when no completed local sale exists
card detail images/pricing/commercial sections: nullable when include flags are false or data is unavailable
sales summary currency: nullable when mixed currencies appear
pricing primary/fallback prices: nullable when no accepted evidence exists
```

### 13. Ranked hardening recommendations

1. **Fix OpenAPI generation blocker**: import or otherwise resolve `DeliveryPolicyUpdate` so `app.openapi()` works without monkeypatching. This is tiny and high-value, but should be a targeted bugfix/implementation milestone because it touches code.
2. **Fix duplicate operation ID warning** for admin key deactivation routes so generated clients have stable method names.
3. **Wire existing `AppReadyBatchDataV1` into `AppReadyBatchResponseV1.data`** and use typed metadata if available. This is likely low risk because the typed model already exists.
4. **Type local sales summary aggregation blocks**: define models for the summary data, grouped rows, and recent sale rows. This is the best first POS-facing hardening target after OpenAPI can build cleanly.
5. **Type workflow summary booleans only** for inventory and listing draft workflows, keeping nested item/draft/reservation/sale sections flexible initially.
6. **Type workflow link/reservation/sale snippets** if the summary-only pass is clean and tests confirm no response shape drift.
7. **Use a common pagination model for inventory list responses** once backwards-compatible schema impact is acceptable.
8. **Defer broad listing draft and app-ready commercial/pricing typing** until frontend client generation proves the exact fields needed.

### 14. No-go refactors

Do not do these in the first hardening implementation:

```text
Do not refactor every dict[str, Any] response at once.
Do not alter endpoint behaviour or response payload keys.
Do not rename workflow fields for aesthetics.
Do not change card-detail commercial/pricing/provider internals broadly.
Do not mix OpenAPI schema fixes with marketplace/provider/listing behaviour changes.
Do not call providers, marketplaces, network APIs, or LLM APIs.
Do not create v13 work.
```

### 15. Recommended first implementation milestone

Recommended first implementation milestone:

```text
OpenAPI schema generation hygiene + local sales summary typed aggregation blocks
```

Recommended sequence:

1. Fix the `DeliveryPolicyUpdate` OpenAPI generation blocker.
2. Fix duplicate operation ID if the duplicate route can be identified safely.
3. Add typed Pydantic models for `LocalSalesSummaryResponseV1.data` because that shape is stable, local-only, and used by the POS fixture pack.
4. Keep workflow summary typing as the next milestone if local sales summary typing lands cleanly.

Why this beats “type workflow summary booleans only” as first implementation: generated-client work is blocked globally until OpenAPI builds cleanly, and local sales summary has a compact aggregation shape with less nested object churn than workflow responses.

## Links

- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12.2 POS-Ready Fixture Pack](V12_2_POS_READY_FIXTURE_PACK.md)
- Related: [V12.2 Inventory Item List Filters](V12_2_INVENTORY_ITEM_LIST_FILTERS.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
- Related: [V12.1 Inventory Item Workflow Endpoint](V12_1_INVENTORY_ITEM_WORKFLOW_ENDPOINT.md)
- Related: [V12.1 Listing Draft Workflow Endpoint](V12_1_LISTING_DRAFT_WORKFLOW_ENDPOINT.md)
