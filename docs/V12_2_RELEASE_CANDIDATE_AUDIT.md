# v12.2 Release Candidate Audit

Tags: #type/audit #pokemon-db #v12-2 #release-candidate

## Overview

Status: `v12.2.0 release candidate — feature complete pending merge/tag`.

This audit verifies `v12.2-next` as the API/client/app-readiness release candidate. It does not add product features, start v13, create the app repo, or implement future auth/billing/scanner backend work.

## Body

### 1. Branch and HEAD

Audited branch and HEAD:

```text
Branch: v12.2-next
HEAD: 69c9c61a228ca1f4708ae2c1bfb1d540ceb92624
Subject: 69c9c61 docs: add v12.2 app transition plan
Remote: origin/v12.2-next aligned at audit start
```

### 2. Baseline v12.1.0 reference

Stable baseline:

```text
main: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
v12.1.0^{}: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
origin/main: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
origin tag v12.1.0 object: 443a4c8dba64092be729f8e059db87d58e6f6a48
```

`main` remains stable at the v12.1.0 release commit.

### 3. v12.2 release theme

Treat v12.2 as:

```text
v12.2.0 — API/client/app-readiness release
```

The release is intended to make the API a cleaner reusable backend brain/platform for the future scanner/collector app and future SaveRoom products.

### 4. v12.2 endpoint/change inventory

Confirmed v12.2 contents:

```text
Inventory item list filters and POS search polish
POS-ready fixture pack
OpenAPI schema hygiene
Typed local sales summary aggregation
Clean OpenAPI generation
Unique operationIds
App transition plan
Brain/vault project-state update
```

Inventory item list filters confirmed:

```text
GET /api/v1/inventory/items
  sku_id
  card_key
  condition
  status
  location_code
  has_listing_draft
  has_active_reservation
  has_completed_sale
```

POS fixture pack confirmed:

```text
docs/fixtures/v12_2_pos/
tests/test_v12_2_pos_ready_fixtures.py
```

OpenAPI schema hygiene confirmed:

```text
create_app().openapi() builds directly
DeliveryPolicyUpdate is resolved
operationIds are unique
LocalSalesSummaryResponseV1.data is typed as LocalSalesSummaryDataV1
```

App transition plan confirmed:

```text
docs/V12_2_APP_TRANSITION_PLAN.md
```

v12.1 foundations still present:

```text
GET /api/v1/inventory/items/{item_id}/workflow
GET /api/v1/listings/drafts/{draft_id}/workflow
GET /api/v1/listings/drafts filters
GET /api/v1/sales/summary
```

v12.0/v12.1 core foundations remain test-covered:

```text
card detail
batch card detail
chart-ready price history
UK-primary pricing recommendation
listing assistant
local listing drafts
inventory-to-draft bridge
draft ready/reservation workflow
explicit local sale completion
local sales read/list API
JustTCG exposure policy guard
```

### 5. OpenAPI direct build result

Direct OpenAPI build was run without monkeypatching:

```text
OPENAPI_VERSION 3.1.0
PATH_COUNT 89
SCHEMA_COUNT 122
OPERATION_ID_COUNT 102
DUPLICATE_OPERATION_IDS []
```

Required components were present:

```text
DeliveryPolicyUpdate
LocalSalesSummaryResponseV1
LocalSalesSummaryDataV1
LocalSalesSummaryFiltersV1
LocalSalesSummaryTotalsV1
LocalSalesSummaryPlatformRowV1
LocalSalesSummaryStatusRowV1
LocalSalesSummaryCurrencyRowV1
```

Confirmed:

```text
LocalSalesSummaryResponseV1.properties.data == {"$ref": "#/components/schemas/LocalSalesSummaryDataV1"}
```

### 6. OperationId uniqueness result

Confirmed:

```text
DUPLICATE_OPERATION_IDS []
```

### 7. Test results

Targeted verification:

```text
compileall -q .: passed

tests/test_v12_2_openapi_schema_hygiene.py: 4 passed in 61.27s
tests/test_v12_2_pos_ready_fixtures.py: 10 passed in 0.13s
tests/test_v12_2_inventory_item_list_filters_api.py: 7 passed in 27.93s
tests/test_v12_1_local_sales_summary_api.py: 8 passed in 32.88s
tests/test_v12_1_inventory_item_workflow_api.py: 11 passed in 28.23s
tests/test_v12_1_listing_draft_workflow_api.py: 12 passed in 28.14s
tests/test_v12_1_listing_draft_list_filters_api.py: 10 passed in 32.71s
tests/test_api_v1_contract.py: 52 passed in 69.96s

git diff --check: passed
```

Full suite:

```text
937 passed, 1 skipped, 19 warnings in 587.58s (0:09:47)
```

### 8. Docs audited

Confirmed these docs exist:

```text
docs/API_CONTRACT_V1.md
docs/V12_1_POST_RELEASE_STATE.md
docs/V12_2_PLANNING.md
docs/V12_2_INVENTORY_ITEM_LIST_FILTERS.md
docs/V12_2_POS_READY_FIXTURE_PACK.md
docs/V12_2_OPENAPI_CLIENT_CONTRACT_HARDENING_AUDIT.md
docs/V12_2_OPENAPI_SCHEMA_HYGIENE_AND_SALES_SUMMARY_TYPING.md
docs/V12_2_APP_TRANSITION_PLAN.md
docs/V12_1_RELEASE_CANDIDATE_AUDIT.md
docs/V12_RELEASE_CANDIDATE_AUDIT.md
docs/JUSTTCG_TERMS_AND_USAGE.md
docs/V12_PRICING_SOURCE_EXPOSURE_POLICY.md
```

Docs consistently record:

```text
v12.2 is API/client/app-readiness work
the scanner/collector app should be a separate repo
the API is the backend brain/platform
normal app users should not receive raw API keys
billing integration is deferred
v12.3 is auth/entitlement foundation
v12.4 is scanner/collector backend foundation
v12.5 is paid beta readiness
v13 requires explicit Matthew approval
```

### 9. Brain/vault updates performed

Brain/vault project-state notes were updated during this audit to record release-candidate readiness and the app-transition plan:

```text
Projects/Pokemon Card Database - CURRENT STATE.md
Projects/Pokemon Card Database - Hermes Context Pack.md
Projects/Pokemon Card Database - Index.md
References/Brain Index.md
References/vault-state.md
```

Brain audit result:

```text
brain_notes=97 issues=0
```

### 10. App transition plan summary

Recorded product direction:

```text
SaveRoom-Pokemon-Database-API = backend brain/platform
SaveRoom-Scanner-App = future separate Flutter/mobile/frontend repo
```

The scanner/collector app should consume the API and should not embed database, pricing, provenance, tier, provider, or entitlement logic.

### 11. Separate app repo decision

Confirmed:

```text
Future scanner/collector frontend work belongs in a separate SaveRoom-Scanner-App repo.
Do not create that repo during v12.2 RC audit.
```

### 12. Future version plan

Recorded plan:

```text
v12.2.0 = API/client/app-readiness release
v12.3.0 = app user/auth/entitlement foundation
v12.4.0 = scanner/collector backend foundation
v12.5.0 = paid beta readiness
v13.0 = major commercial platform / external product ecosystem shift only with explicit Matthew approval
```

### 13. Safety boundaries

Confirmed this audit did not:

```text
run live provider calls
spend API credits
call _get_justtcg_price_data()
call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs from the project
publish listings
create marketplace listings
import marketplace orders
capture payments
process refunds
create fulfilment/shipping state
ask Matthew for API keys
print API keys
start v13
create the app repo
```

### 14. Known exclusions from v12.2

Excluded from v12.2:

```text
user accounts
subscription records
payment provider integration
app login
scanner/collector collection tables
new app repository
marketplace publishing
marketplace order import
billing/refunds
fulfilment/shipping state
tax/accounting
v13 work
```

These are planned for v12.3/v12.4/v12.5 as appropriate, not for v12.2.0.

### 15. Known unrelated untracked files

Known unrelated untracked files remain intentionally uncommitted:

```text
docs/SAVEROOM_POKEMON_CARD_DATABASE_PROJECT_REPORT_V1130.md
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.drawio
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.url.txt
```

### 16. Release recommendation

Release recommendation:

```text
v12.2-next is release-candidate ready.
v12.2 feature work is frozen.
Recommended next action is Matthew approval for merge/tag as v12.2.0.
```

### 17. Exact recommended merge/tag commands — do not run yet

Do not run these without explicit Matthew approval:

```bash
cd "/media/matt/Storage/Brain/Pokemon Card Database"

git checkout main
git pull --ff-only origin main
git merge --ff-only v12.2-next
git tag -a v12.2.0 -m "v12.2.0: API/client/app-readiness release"
git push origin main
git push origin v12.2.0
```

If fast-forward merge is not possible, stop and inspect before choosing a merge strategy.

## Links

- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12.2 App Transition Plan](V12_2_APP_TRANSITION_PLAN.md)
- Related: [V12.2 Inventory Item List Filters](V12_2_INVENTORY_ITEM_LIST_FILTERS.md)
- Related: [V12.2 POS-Ready Fixture Pack](V12_2_POS_READY_FIXTURE_PACK.md)
- Related: [V12.2 OpenAPI Client Contract Hardening Audit](V12_2_OPENAPI_CLIENT_CONTRACT_HARDENING_AUDIT.md)
- Related: [V12.2 OpenAPI Schema Hygiene and Sales Summary Typing](V12_2_OPENAPI_SCHEMA_HYGIENE_AND_SALES_SUMMARY_TYPING.md)
