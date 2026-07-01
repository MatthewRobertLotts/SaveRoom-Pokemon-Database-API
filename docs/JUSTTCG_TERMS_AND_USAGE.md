# JustTCG Terms and Usage — SaveRoom

Tags: #type/project #status/current

Status: FINAL TERMS CLARIFICATION RECORDED
Date: 2026-06-30
Provider: JustTCG
Scope: JustTCG only; does not apply to TotalTCG

## Overview

This document records the final JustTCG written terms clarification for SaveRoom's intended architecture.

JustTCG-derived pricing may be used inside SaveRoom-owned apps and tools through the SaveRoom backend, including paid SaveRoom products. The key restriction is that SaveRoom must not expose a public standalone pricing API, data feed, or competing data product that lets third-party developers fetch JustTCG-derived pricing.

## Confirmed allowed

JustTCG confirmed the following are allowed:

- SaveRoom-owned apps and tools may use JustTCG-derived pricing through the SaveRoom backend.
- Allowed SaveRoom surfaces include:
  - scanner app;
  - POS system;
  - inventory desktop app;
  - web tracker;
  - listing assistant;
  - admin panel;
  - customer-facing SaveRoom app.
- These SaveRoom apps may be paid products.
- The SaveRoom backend may return JustTCG-derived prices inside SaveRoom app responses.
- Internal/customer SaveRoom app use is allowed.
- Raw API responses may be cached for internal audit/provenance.
- There is no retention limit on cached data.
- Normalized observations and aggregate pricing data may be stored permanently.
- A small number of sanitized API responses may be saved as automated test fixtures.
- Source-derived prices may be shown in internal admin UI and future customer-facing SaveRoom products.

## Confirmed restrictions

JustTCG confirmed the key restriction:

```text
The SaveRoom backend must not expose a public standalone pricing API, data feed, or competing data product for third-party developers to fetch JustTCG-derived pricing.
```

Correct architecture:

| Surface | JustTCG-derived pricing policy |
|---|---|
| Internal/admin SaveRoom tools | Allowed |
| Customer SaveRoom app | Allowed |
| SaveRoom-owned paid apps/tools | Allowed |
| External developer API | Blocked/redacted |
| Standalone pricing API/data feed | Blocked |
| Competing data product | Blocked |

Do not weaken the external developer API block.

Do not expose raw JustTCG payloads publicly.

## Attribution

JustTCG confirmed this attribution is sufficient:

```text
Pricing data provided by JustTCG
```

Allowed locations:

- About page;
- Settings page;
- Data sources page;
- footer.

## Price semantics

JustTCG clarified that its price field should be labelled as:

```text
Market Price
```

Meaning:

```text
Volume-weighted average of completed marketplace sales.
```

Do not label JustTCG price as:

- UK sold price;
- UK market price;
- active listing price;
- live listing price.

Recommended internal naming:

```text
justtcg_market_price
provider_market_price
completed_sales_market_price
```

Avoid naming:

```text
uk_sold_price
uk_market_price
active_listing_price
listing_price
```

## Subscription cancellation and retention

If the JustTCG subscription is cancelled:

- normalized and aggregate JustTCG-derived data already stored in the SaveRoom database can remain permanently;
- cached data does not need to be deleted solely because the subscription ended;
- SaveRoom should stop receiving live JustTCG updates after cancellation.

## Code policy implication

The intended exposure policy remains:

```text
internal_admin: allowed
customer_saveroom_app: allowed
saveroom_owned_paid_apps: allowed
external_developer_api: blocked/redacted
standalone_pricing_api: blocked
```

Current code-enforced policy lives in:

```text
pricing_sources/exposure_policy.py
```

The permanent guard remains:

```text
JUSTTCG_EXTERNAL_RESALE_PERMANENTLY_BLOCKED = True
```

## Implementation boundaries

This clarification does not by itself require live provider calls or runtime pricing behavior changes.

Do not:

- run live JustTCG calls to validate this document;
- spend API credits;
- expose raw JustTCG API payloads publicly;
- publish JustTCG-derived standalone pricing endpoints;
- treat JustTCG market price as UK sold/completed evidence.

## Links

- Related: `docs/V12_PRICING_SOURCE_EXPOSURE_POLICY.md`
- Related: `docs/V12_UK_PRIMARY_FALLBACK_PRICING_MODEL.md`
- Related: `docs/API_CONTRACT_V1.md`
- Related: `pricing_sources/exposure_policy.py`
