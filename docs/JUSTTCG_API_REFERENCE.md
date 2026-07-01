# JustTCG API Reference Summary

Source: https://justtcg.com/docs (observed 2026-06-28)

## Base URL
```
https://api.justtcg.com/v1
```

## Authentication
- Header: `x-api-key: tcg_your_api_key_here`
- SDK: `JUSTTCG_API_KEY` environment variable

## Key Endpoints

### GET /v1/games
List all supported games. No parameters.

### GET /v1/sets
List sets. Optional `game` filter (e.g., `pokemon`).

### GET /v1/cards
One card lookup or search. Key parameters:
- `cardId` - Direct lookup by card ID
- `variantId` - Direct lookup by variant ID (fastest)
- `tcgplayerId` - TCGplayer product ID
- `game` - Filter by game (e.g., `pokemon`)
- `set` - Filter by set ID
- `condition` - Comma-separated: `NM,LP,MP,HP,D`
- `printing` - Comma-separated: `Normal,Foil,1st Edition,Unlimited`
- `number` - Card number within set
- `orderBy` - `price`, `24h`, `7d`, `30d`
- `order` - `asc`, `desc`
- `limit` - Max cards per request (20/100/100/200 by plan)
- `offset` - Pagination
- `priceHistoryDuration` - `7d`, `30d`, `90d`, `180d`, `1y`
- `min_price` - Minimum price filter
- `include_null_prices` - Include cards without pricing
- `include_price_history` - Include price history
- `include_statistics` - Include statistics
- `updated_after` - Unix timestamp filter

### POST /v1/cards
Batch lookup (up to 200 cards). Body: array of identifier objects:
```json
[{"tcgplayerId": "219042"}, {"tcgplayerId": "25788"}]
```

## Response Shape
```json
{
  "data": [...],
  "meta": {"total": 1, "limit": 20, "offset": 0, "hasMore": false},
  "_metadata": {
    "apiPlan": "Pro",
    "apiRequestsRemaining": 49213,
    "apiDailyRequestsRemaining": 4321,
    "apiRateLimit": 100
  }
}
```

## Card Object
```json
{
  "uuid": "f8c3de3d-... (stable, recommended primary key)",
  "id": "pokemon-battle-academy-fire-energy-22-charizard-stamped (legacy slug)",
  "name": "Fire Energy (#22 Charizard Stamped)",
  "game": "Pokemon",
  "set": "battle-academy-pokemon",
  "set_name": "Battle Academy",
  "number": "22",
  "tcgplayerId": "219042",
  "rarity": "Promo",
  "variants": [...]
}
```

## Variant Object (pricing lives here)
```json
{
  "uuid": "a1b2c3d4-... (stable)",
  "id": "pokemon-..._near-mint (legacy)",
  "condition": "Near Mint",
  "printing": "Normal",
  "language": "English",
  "tcgplayerSkuId": "1234567",
  "price": 4.99,
  "lastUpdated": 1743100261,
  "priceChange24hr": 0.5,
  "priceChange7d": -2.1,
  "avgPrice": ...,
  "priceHistory": [{"p": 0.14, "t": 1780358400}],
  "minPrice7d": ...,
  "maxPrice7d": ...,
  "trendSlope7d": ...,
  "priceChange30d": ...,
  "avgPrice30d": ...,
  "priceHistory30d": [...],
  "minPriceAllTime": ...,
  "maxPriceAllTime": ...
}
```

## Condition Values
- `NM` - Near Mint
- `LP` - Lightly Played
- `MP` - Moderately Played
- `HP` - Heavily Played
- `D` - Damaged

## Printing Values
- `Normal`
- `Foil`
- `1st Edition`
- `Unlimited`
- etc.

## Identifiers (v1 → v2 migration)
- `card.uuid` → recommended primary key (stable UUID v5)
- `card.id` → legacy slug (human-readable but mutable)
- `variant.uuid` → recommended variant key
- `variant.id` → legacy slug

## Rate Limits
| Plan | Monthly | Daily | Per minute |
|---|---|---|---|
| Free | 1,000 | 100 | 10 |
| Starter | 10,000 | 1,000 | 50 |
| Professional | 50,000 | 5,000 | 100 |
| Enterprise | 500,000 | 50,000 | 500 |

## Error Codes
- `MISSING_API_KEY` - No key provided
- `INVALID_API_KEY` - Key invalid/revoked
- `INVALID_REQUEST` - Missing/invalid parameter
- `RATE_LIMIT_EXCEEDED` - Per-minute limit hit
- `DAILY_LIMIT_EXCEEDED` - Daily limit hit
- `REQUEST_LIMIT_EXCEEDED` - Monthly limit hit

## SDK
- npm: `justtcg-js`
- Reads `JUSTTCG_API_KEY` from env
- TypeScript support

## MCP Endpoint (Beta)
```
https://mcp.justtcg.com
```

## Key Observations for SaveRoom Integration

1. **Condition-specific pricing**: Yes — `condition` parameter with NM/LP/MP/HP/D values
2. **Finish/variant separation**: Yes — `printing` parameter (Normal, Foil, 1st Edition, etc.)
3. **Price type**: Market price (not sold comps) — similar to TCGPlayer marketPrice
4. **Stable identifiers**: UUID v5 recommended; tcgplayerId also available for cross-referencing
5. **Price history**: 7d/30d/90d/180d/1y windows available
6. **Statistics**: 24hr/7d/30d/90d changes, avg/min/max, trend slope, stddev
7. **Currency**: USD only (from docs)
8. **Batch support**: POST up to 200 cards per request
9. **Usage tracking**: Every response includes `_metadata` with remaining requests
10. **Free tier limitations**: 20 cards/request, 100/day — too limited for production

## Terms Approval (2026-06-29)

JustTCG has approved SaveRoom's integration with the following permissions:

- Commercial backend use: ✅
- Raw API response cache: ✅ (no retention limit stated)
- Normalized observation storage: ✅
- Aggregate storage: ✅
- Fixture storage: ✅
- Internal display: ✅
- Customer-facing display: ✅
- Soft attribution requested: "Pricing data provided by JustTCG"
- Identifier mapping: ✅
- Price semantics: market price (not sold/listing)
- Source currency: USD only

**Critical restriction:** The integration **cannot be wrapped into a secondary API that acts as a standalone pricing service or competing data product for external parties.** JustTCG-derived pricing is for SaveRoom ecosystem apps only (scanner, POS, inventory, web tracker, listing assistant, admin, customer-facing app). Not for standalone external developer pricing API.

## Recommended Integration Approach

1. Use `GET /v1/cards?game=pokemon&set={set_id}&condition=NM,LP,MP&printing=Normal,Foil` for set sync
2. Use `POST /v1/cards` with `tcgplayerId` for batch lookups
3. Store `variant.uuid` as primary key, `tcgplayerId` for cross-reference
4. Map `condition` → v11 observation condition field
5. Map `printing` → v11 observation finish field
6. Store `price` as `amount` in USD
7. Use `priceHistory` for trend analysis
8. Monitor `_metadata.apiRequestsRemaining` for quota management
