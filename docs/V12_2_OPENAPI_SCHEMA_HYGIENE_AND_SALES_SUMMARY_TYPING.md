# v12.2 OpenAPI Schema Hygiene and Sales Summary Typing

Tags: #type/doc #pokemon-db #v12-2 #openapi #client-contract #local-sales

## Overview

v12.2 milestone 4 implements the first low-risk OpenAPI/client contract hardening pass from the v12.2 audit.

The milestone fixes local OpenAPI schema generation hygiene and types the compact local sales summary aggregation response without changing the JSON payload keys or endpoint behaviour.

## Body

### Scope

Implemented scope:

```text
OpenAPI blocker fixed
DeliveryPolicyUpdate resolved in FastAPI module imports
duplicate admin key deactivate operationId warning fixed
LocalSalesSummaryResponseV1.data typed with compact Pydantic models
runtime JSON keys preserved
no endpoint behaviour change
```

Deferred scope:

```text
card detail commercial/pricing/provider internals
listing assistant payload internals
listing draft payload internals
workflow nested object typing
broad response-model refactors
```

### DeliveryPolicyUpdate resolution

`DeliveryPolicyUpdate` is defined in `pokemon_db_v5_api_models.py` and is now imported into `pokemon_db_v2_fastapi.py` with the other API models. This lets `create_app().openapi()` resolve the delivery-policy update route without monkeypatching.

### Duplicate operationId fix

The two existing `POST /api/v1/admin/keys/{key_id}/deactivate` route registrations keep their endpoint path and runtime behaviour, but now have explicit unique OpenAPI operation IDs:

```text
v1_admin_deactivate_key_legacy
v1_admin_deactivate_key_tenant
```

This removes the duplicate operationId warning for generated clients without renaming paths or changing payload behaviour.

### Typed local sales summary models

`LocalSalesSummaryResponseV1.data` is no longer `dict[str, Any]`. It now references typed models:

```text
LocalSalesSummaryFiltersV1
LocalSalesSummaryTotalsV1
LocalSalesSummaryPlatformRowV1
LocalSalesSummaryStatusRowV1
LocalSalesSummaryCurrencyRowV1
LocalSalesSummaryDataV1
LocalSalesSummaryResponseV1
```

The JSON keys remain unchanged:

```text
data.filters
data.summary
data.by_platform
data.by_status
data.by_currency
metadata
```

Grouped row key names are preserved:

```text
by_platform[].platform
by_status[].status
by_currency[].currency
```

### OpenAPI result

Direct local OpenAPI generation now works without monkeypatching:

```text
OPENAPI_VERSION 3.1.0
PATH_COUNT 89
SCHEMA_COUNT 122
OPERATION_ID_COUNT 102
DUPLICATE_OPERATION_IDS []
```

The typed local sales summary schemas appear in OpenAPI components.

### Behaviour boundary

This milestone changes schema/model typing only. It does not:

```text
change endpoint paths
change response payload keys
change aggregation semantics
call providers
call marketplaces
call network APIs
call LLM APIs
publish listings
import orders
capture payments
process refunds
create fulfilment or shipping state
create v13 work
```

### Remaining deferred typing areas

The following remain intentionally flexible:

```text
AppReadyCommercialV1 canonical/commercial/SKU/external-reference internals
AppReadyPricingV1 provider/source internals
AppReadyBatchResponseV1.data
Listing draft response data
Listing draft list row data
Workflow nested item/draft/reservation/sale sections
Local sale detail/list row data
```

### Recommended next implementation milestone

Recommended next milestone:

```text
App-ready batch response typing + workflow summary booleans
```

Rationale:

```text
AppReadyBatchDataV1 already exists but is not wired into AppReadyBatchResponseV1.data.
Workflow summary blocks are small and stable, while nested workflow objects can remain flexible.
```

## Links

- Related: [V12.2 OpenAPI Client Contract Hardening Audit](V12_2_OPENAPI_CLIENT_CONTRACT_HARDENING_AUDIT.md)
- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12.1 Local Sales Summary Endpoint](V12_1_LOCAL_SALES_SUMMARY_ENDPOINT.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
