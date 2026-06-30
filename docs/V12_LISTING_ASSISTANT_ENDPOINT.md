# v12 Listing Assistant Endpoint

## Overview

This v12 milestone adds deterministic listing-ready output for SaveRoom app and marketplace workflows:

```text
POST /api/v1/listings/assist/cards/{card_key:path}
```

The endpoint prepares listing copy, platform guidance, optional image metadata, optional commercial identifiers, and optional pricing from the existing local UK-primary pricing recommendation layer.

It is not a publishing endpoint.

## Safety boundaries

The listing assistant does not:

- call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or any other live provider API;
- spend API credits;
- call `_get_justtcg_price_data()`;
- publish listings;
- use an LLM;
- add or require DB migrations;
- expose raw provider payloads, API keys, headers, account metadata, private provider payload paths, or raw filesystem paths.

## Request model

Model:

```text
ListingAssistantRequestV1
```

Fields:

```json
{
  "platform": "generic",
  "condition": null,
  "finish": null,
  "quantity": 1,
  "include_images": true,
  "include_pricing": true,
  "include_commercial": true,
  "pricing_strategy": "balanced",
  "title_style": "marketplace",
  "notes": null
}
```

Validation:

- `quantity >= 1`
- `platform` is one of `whatnot`, `ebay`, `shopify`, `generic`
- `pricing_strategy` is one of `conservative`, `balanced`, `premium`
- `title_style` is one of `compact`, `seo`, `marketplace`

## Response model

Model:

```text
ListingAssistantResponseV1
```

Top-level response:

```json
{
  "data": {
    "card": {},
    "listing": {},
    "pricing": {},
    "images": {},
    "commercial": {},
    "platform_guidance": {},
    "provider_status": {},
    "warnings": [],
    "metadata": {}
  },
  "warnings": [],
  "metadata": {}
}
```

## Pricing behavior

The listing assistant uses the local recommendation layer only.

It consumes the same fields exposed by:

```text
GET /api/v1/prices/cards/{card_key:path}
```

Specifically:

- `data.recommendation.recommended_listing_price`
- `data.recommendation.general_market_estimate`
- `data.recommendation.primary_uk_price`
- `data.recommendation.confidence`
- `data.recommendation.warnings`
- `data.recommendation.source_breakdown`

Mapping:

- `pricing.suggested_price` maps from `recommended_listing_price.amount`.
- `pricing.currency` maps from the recommendation price currency, falling back to GBP.
- `pricing.confidence` maps from recommendation confidence.
- `pricing.source_summary` carries recommendation basis, method, evidence count, and source breakdown.
- `pricing.based_on_recommendation` carries the recommendation price objects used to build listing pricing.

For this v12 milestone, `pricing_strategy` defaults to `balanced`. Conservative and premium request values validate, but the endpoint returns the balanced recommendation with a warning until the recommendation layer exposes those strategies safely.

The endpoint does not use raw JustTCG fallback data, USD/global prices, or live provider values.

## Include flags

```text
include_images=false -> data.images = null
include_pricing=false -> data.pricing = null
include_commercial=false -> data.commercial = null
```

When pricing is included, pricing bullets may include recommendation confidence and warnings. When pricing is omitted, listing copy remains deterministic and the response warns that pricing was omitted.

## Title behavior

Titles are deterministic and use known card/set fields only.

Platform defaults:

- `whatnot`: compact stream-safe title, capped at 80 characters.
- `ebay`: SEO-oriented title with `Pokémon Card`, capped at 80 characters.
- `shopify`: clean product title with an em dash separator, capped at 120 characters.
- `generic`: reusable listing title, capped at 120 characters.

Condition is not included unless the request supplies `condition`. The endpoint does not infer grade, condition, authenticity, or scarcity claims.

## Description bullets

Description bullets are deterministic and built from known data:

- card name;
- set;
- number;
- rarity;
- language;
- condition note if supplied;
- finish if supplied;
- quantity;
- pricing confidence/warnings when pricing is included.

No marketing hype or fake claims are generated.

## Platform guidance

The endpoint returns deterministic platform guidance.

| Platform | Title limit | Description limit | Required fields | Notes |
|---|---:|---:|---|---|
| `whatnot` | 80 | 500 | title, condition, quantity | Short stream-safe title; mention condition clearly. |
| `ebay` | 80 | 4000 | title, condition, item specifics, price | SEO title; include set, number, rarity, language. |
| `shopify` | 120 | 5000 | title, product_type, tags, price | Clean product title; useful tags and SKU/variant mapping. |
| `generic` | 120 | 2000 | title, description, condition | Reusable listing copy. |

## Provider status

Provider status is safe metadata only. It confirms the recommendation layer is used and that JustTCG/TotalTCG fallback providers are not fetched or used by the listing assistant endpoint.

## Tests

Coverage lives in:

```text
tests/test_v12_listing_assistant_api.py
```

The tests cover endpoint existence, 200/404 behavior, include flags, platform support, condition handling, deterministic bullets, recommendation-based pricing, JustTCG fetch guard, no live provider calls, no USD/fallback leakage, no filesystem path leakage, and request validation.
