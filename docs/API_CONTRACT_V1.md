# SaveRoom Pokémon Card Database — API Contract v1

## Intended public API purpose

The `/api/v1/...` API is the stable read-only foundation for future SaveRoom and third-party products that need canonical Pokémon card reference data, localized card/set data, display images, and locally cached pricing evidence.

The API is intended to support a product family: scanner apps, POS systems, desktop inventory tools, web trackers, listing/marketplace workflows, and paid/leased developer access. It is **not** a SaveRoom-only browser UI contract.

## Internal vs public routes

Current legacy/internal routes may remain for local tooling and compatibility:

- `/health`
- `/search`
- `/cards/{language_code}/{card_id}`
- `/reports/coverage`
- `/api/prices/*`
- `/ui/`

Those routes are not the long-term external contract. The public contract lives under:

- `/api/v1/...`

v1 routes should hide implementation details such as `v2_card_search`, `v2_card_search_fts`, and `v2_card_detail_api_cache` behind documented response envelopes.

## Public resource model

Initial v1 resources:

- `GET /api/v1/health` — service, DB support, and auth mode status.
- `GET /api/v1/cards` — future paginated card list alias; may share filters with search.
- `GET /api/v1/cards/{card_key}` — canonical localized card detail.
- `GET /api/v1/sets` — future set list.
- `GET /api/v1/sets/{set_key}` — future set detail.
- `GET /api/v1/languages` — future language list.
- `GET /api/v1/search/cards` — paginated card search.
- `GET /api/v1/images/cards/{card_key}` — future card image metadata/redirect endpoint.
- `GET /api/v1/prices/cards/{card_key}` — future local price summary endpoint.
- `GET /api/v1/prices/history/cards/{card_key}` — future local price evidence history endpoint.

Implemented first in v5 phase 1:

- `GET /api/v1/health`
- `GET /api/v1/search/cards`
- `GET /api/v1/cards/{card_key}`

## Canonical IDs

### Card key

The durable public foreign key for external clients is:

```text
{language_code}:{card_id}
```

Example:

```text
en:sv03-223
```

The slash alias `en/sv03-223` may be accepted as a convenience in URL paths, but the canonical serialized value returned by the API is always colon form.

External developers should store `card_key`, not raw `card_id`, as their durable foreign key. Raw `card_id` alone must not be assumed globally unique across languages, imports, or future product domains.

### ID fields and meanings

- `card_key` — canonical v1 public key, `{language_code}:{card_id}`.
- `language_code` — language/localization code for the row (`en`, `ja`, `zh-tw`, etc.).
- `card_id` — source/import card ID within the language/source context.
- `set_id` / `raw_set_id` — source set ID as imported.
- `resolved_set_id` — resolved language-specific set ID where available.
- `core_set_id` — normalized cross-language set grouping used for filtering.
- `local_id` / `collector_number` — printed collector/local number on the card.

## Language/localization model

Each card resource is language-specific. v1 must never silently fall back to another language for names, card text, images, or price evidence.

Rules:

- `language_code=en` filters must only return English rows.
- `/api/v1/cards/en:sv03-223` returns only the English row for `sv03-223`.
- If a localized row has no image or no price evidence, the API reports that absence instead of substituting English data.
- Cross-language grouping belongs in explicit future fields/endpoints, not implicit fallback behavior.

## Image model

Image metadata is separate from raw card facts. v1 exposes:

- `has_exact_image`
- `has_display_image`
- `exact_image_url`
- `display_image_url`
- `local_display_image_url`
- `local_display_image_cache_profile`
- `local_display_image_bytes`
- `display_image_source_type`
- `display_image_source_language_code`
- `language_matches_card`

`display_image_url` may come from a source/candidate/cache layer, but provenance fields must make that auditable. Local cached app images are preferred where available. Missing images remain explicit and filterable.

## Pricing evidence model

Pricing is local evidence, not canonical card truth. It must remain auditable and language-aware.

v1 card detail may include a local `price` summary from `uk_price_history` only when evidence exists for the same `card_id` and same `language_code` (or explicitly null language in legacy data only if documented by the pipeline). Non-English cards must not fall back to English prices.

Price summaries should prefer recommended raw inputs, excluding graded/bundles/noise. Evidence rows retain raw listing titles, bucket, match notes, query, source site, cache key, and fetch timestamp.

Live RapidAPI fetches are deliberately out of scope for read-only public v1 endpoints. Fetching/updating prices remains under internal `/api/prices/*` until pricing auth, quota, billing, and abuse controls are production-grade.

## Pagination standard

List endpoints use offset/limit pagination:

```json
{
  "data": [],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "count": 50,
    "total": 1234,
    "has_more": true
  }
}
```

Rules:

- Default `limit`: 50.
- Maximum `limit`: 200.
- `offset` must be non-negative.
- `total` uses the same filters as the data query.
- SQL must use bound parameters and avoid loading all rows into memory.

## Filtering standard

Initial `/api/v1/search/cards` filters:

- `q` — full-text query, optional.
- `language_code` — exact language row filter.
- `set_id` — raw or resolved set ID.
- `core_set_id` — normalized set grouping.
- `has_display_image` — boolean.
- `has_price` — boolean, local DB only, no live fetch.

Unsupported filters should produce a structured v1 error once validation is added, not be silently ignored.

## Sorting standard

Initial sort values:

- `relevance` / `default` — current search ordering: display-image preference, FTS rank where applicable, English/Japanese preference for unfiltered broad searches, language, set, local number, card ID.

Unsupported sort values return:

```json
{
  "error": {
    "code": "unsupported_sort",
    "message": "Unsupported sort value",
    "details": {"allowed": ["relevance", "default"]}
  }
}
```

Future stable sort options should be documented before release.

## Response envelopes

Single resource:

```json
{"data": {}}
```

List resource:

```json
{"data": [], "pagination": {}}
```

Error:

```json
{
  "error": {
    "code": "card_not_found",
    "message": "Card not found",
    "details": {"card_key": "en:missing"}
  }
}
```

## Error envelope

Initial v1 error codes:

- `invalid_card_key`
- `card_not_found`
- `invalid_limit`
- `invalid_offset`
- `unsupported_sort`
- `api_key_required`
- `invalid_api_key`
- `insufficient_scope`
- `internal_error`

Legacy routes may keep their older error shapes for compatibility.

## Auth/API-key direction

v1 supports optional API-key enforcement:

- Default local/dev mode: no key required.
- Set `POKEMON_DB_REQUIRE_API_KEY=1` to require a key for `/api/v1` routes.
- Clients may send `X-API-Key: ...` or `Authorization: Bearer TOKEN`.
- Raw keys must not be stored in SQLite. Store a SHA-256 hash only.

Initial developer key table:

- `developer_api_keys`
- `id`
- `key_hash`
- `label`
- `scopes` JSON/TEXT
- `monthly_quota`
- `is_active`
- `created_at`
- `last_used_at`

Future scopes:

- `cards:read`
- `prices:read`
- `prices:fetch`
- `images:read`
- `inventory:read`
- `inventory:write`
- `admin`

## Quota/rate-limit direction

v1 should log requests now and enforce quotas later. Initial request log table:

- `api_request_log`
- `id`
- `api_key_id` nullable
- `route`
- `method`
- `status_code`
- `requested_at`
- `elapsed_ms`
- `client_host_hash` nullable

External developer quotas should be per API key/workspace, monthly, and separate from RapidAPI spend guards. Pricing fetch quotas must be stricter than read quotas because they can create real cost.

## Versioning/deprecation policy

- `/api/v1` contracts are additive within v1 where possible.
- Breaking response-field removals or semantic changes require `/api/v2`.
- Deprecated fields should remain for at least one documented migration window.
- Legacy/internal routes can remain but should not be advertised as public contracts.
- DB tables/views are implementation details unless explicitly documented as API resources.

## Canonical vs application/business data boundary

Canonical/reference data belongs in the shared foundation:

- cards
- sets
- languages
- images
- provenance
- price evidence

Future app/business data must stay separate:

- users
- API keys
- workspaces/tenants
- inventory items
- scan events
- POS transactions
- listing/export jobs

Do not pollute canonical card tables with inventory, POS, scanner, tenant, or user data.

## Deliberately out of scope for v1

- Scanner app workflows.
- POS transactions.
- Inventory ownership/quantities/locations.
- User accounts/workspaces beyond API-key groundwork.
- Public live price fetching that spends RapidAPI requests.
- Marketplace listing publication.
- Write endpoints for canonical data.
- Cross-language fallback/substitution.
- Production billing, SLA, and external developer portal.

## Translation / internationalization layer

Every card response includes a `name_english` field that provides the English translation of the card name. This is critical for non-English cards when searching on English-language marketplaces like eBay UK.

### How it works

1. **English cards**: `name_english` is the same as `name`
2. **European languages** (de/fr/it/es/pt): Translated via direct DB join (same `card_id` has an English row)
3. **Japanese/Korean/Chinese/Thai**: Translated via PokéAPI species name mapping + TCG term dictionary + Google Translate fallback
4. **Untranslated names**: `name_english` is `null` (only ~293 Chinese TW names remain untranslatable)

### Final coverage: 99.6% (247,727 / 252,020)

| Language | Code | Coverage | Method |
|----------|------|----------|--------|
| English | en | 100% | Native |
| French | fr | 100% | DB join |
| German | de | 100% | DB join |
| Italian | it | 100% | DB join |
| Spanish | es | 100% | DB join |
| Portuguese | pt | 100% | DB join |
| Indonesian | id | 100% | Latin passthrough |
| Japanese | ja | 100% | PokéAPI + dictionary + Google Translate |
| Korean | ko | 100% | PokéAPI + dictionary + Google Translate |
| Thai | th | 100% | PokéAPI + dictionary + Google Translate |
| Simplified Chinese | zh-cn | 100% | PokéAPI + dictionary + Google Translate |
| Traditional Chinese | zh-tw | 97.0% | PokéAPI + dictionary + Google Translate (293 names need manual review) |
| Russian | ru | 100% | DB join |
| Polish | pl | 100% | DB join |
| Dutch | nl | 100% | DB join |

### Translation sources

| Source | Description | Coverage |
|--------|-------------|----------|
| `db_join` | Same card_id has English row in DB | ~197K cards |
| `pokemon_names_exact` | Exact match in PokéAPI species names | ~12K cards |
| `google_translate` | Google Translate API fallback | ~3.8K cards |
| `pokemon_substring` | Pokémon name found as substring | ~3.5K cards |
| `latin_passthrough` | Latin script names (already English) | ~24K cards |
| `latin_recognized` | Recognized Latin-script Pokémon names | ~2.2K cards |
| `pokeapi` | PokéAPI species name reverse lookup | ~1.7K cards |
| `tcg_terms` | Trainer/item/energy dictionary | ~897 cards |
| `suffix_strip` | Suffix stripping + dictionary match | ~702 cards |
| `zh-tw_pokemon_suffix` | Chinese TW suffix stripping | ~561 cards |
| `zh-cn_pokemon_suffix` | Chinese CN suffix stripping | ~515 cards |
| `pokemon_names_suffix_strip` | Pokémon name + suffix (ex/V/GX) | ~455 cards |
| `ja_tcg_terms` | Japanese TCG term dictionary | ~141 cards |
| `ja_compound_pokemon` | Japanese compound name extraction | ~132 cards |
| `id_contains_english` | Indonesian names containing English | ~112 cards |
| `zh-tw_compound_pokemon` | Chinese compound name extraction | ~62 cards |
| `zh-cn_compound_pokemon` | Chinese compound name extraction | ~24 cards |
| `id_tcg_terms` | Indonesian TCG term dictionary | ~23 cards |
| `zh-cn_tcg_terms` | Chinese Simplified TCG terms | ~10 cards |
| `pokemon_suffix` | Suffix stripping | ~9 cards |
| `compound_extract` | Generic compound extraction | ~1 card |

### Price query behavior

The `build_price_query` function (used for eBay UK price searches) automatically uses `name_english` instead of the local name. This means:
- A German card "Glurak-ex" generates query "Charizard ex Pokémon card"
- A Japanese card "リザードンex" generates query "Charizard ex Pokémon card"
- A Chinese card "噴火龍ex" generates query "Charizard ex Pokémon card"

### Coverage endpoint

```
GET /api/v1/i18n/coverage
```

Returns translation coverage statistics by language.

### Remaining untranslated names

~293 Traditional Chinese names could not be translated (mostly trainer cards, items, and location names with no standard English equivalent). These are logged in `references/skipped_translations.csv` for manual review.

### Search quality features

#### Cross-language search
Searching "Charizard" finds cards in all languages (Japanese リザードン, German Glurak, French Dracaufeu, etc.) via the `name_english` column in the FTS index.

#### Synonym expansion
Common nicknames and abbreviations are automatically expanded:
- Pokémon nicknames: "zard" → Charizard, "pika" → Pikachu, "gren" → Greninja
- Set abbreviations: "obsidian" → Obsidian Flames, "151" → 151, "evolving" → Evolving Skies
- eBay terms: "holo" → Holo, "nm" → Near Mint, "fa" → Full Art

#### Fuzzy matching
Misspelled queries like "charzard" or "pikachuu" still find the correct cards via trigram similarity matching.

#### Autocomplete
```
GET /api/v1/search/autocomplete?q=char&limit=10
```
Returns matching card names, set names, and synonym expansions for search-as-you-type UI.

#### Fuzzy search
```
GET /api/v1/search/fuzzy?q=charzard&limit=10
```
Returns cards sorted by trigram similarity score for handling misspellings.

### Price query field

The card detail endpoint (`GET /api/v1/cards/{language}/{card_id}`) now includes a `price_query` field with the optimal eBay UK search query for that card:

```json
{
  "data": {
    ...,
    "price_query": "Pokemon Charizard 212 S12a Fire Pokémon card"
  }
}
```

The query always uses:
- English card name (looked up from translation data for non-English cards)
- Set code (e.g., `S12a`, `sv03`)  
- Collector number
- Card type/rarity (when available)

This field is intended for use by the price fetch UI to ensure eBay searches always use English terms, maximizing result coverage for non-English cards.

### Price fetch auto-correction

When calling `GET /api/prices/fetch` with a `card_id` for a non-English card, the API now **auto-generates the correct eBay search query** using `build_price_query()` — overriding whatever query you pass. This ensures:

- Japanese cards like `リザードンVSTAR` get queried as "Charizard VSTAR"
- Japanese set names like `黒炎の支配者` are replaced with the set code `SV3`
- The language tag (e.g., "Japanese") is appended to help eBay filter

Previously, the UI was constructing queries with Japanese text, e.g.:
```
❌ リザードンVSTAR 212 VSTAR Semesta Japanese Pokémon card  → 0 results
✅ Pokemon Charizard 212 S12a Fire Japanese Pokémon card    → likely results
```

### Developer quick-start examples

All examples below use `http://localhost:8765` as the base URL. Replace with your deployed URL.

### Health check

```bash
curl -s http://localhost:8765/api/v1/health | python3 -m json.tool
```

Response:

```json
{
  "data": {
    "ok": true,
    "service": "saveroom-pokemon-api",
    "version": "v1",
    "started_at": "2026-06-21T12:00:00+00:00",
    "checked_at": "2026-06-21T12:01:00+00:00",
    "counts": { "support_ready": true, ... },
    "auth": { "api_key_required": false }
  }
}
```

### Search for cards

```bash
# Basic search (default: 50 results, relevance sort)
curl -s "http://localhost:8765/api/v1/search/cards?q=charizard&limit=3" | python3 -m json.tool

# Language-filtered search (English only, no cross-language fallback)
curl -s "http://localhost:8765/api/v1/search/cards?q=charizard&language_code=en&limit=5" | python3 -m json.tool

# Filter by core set
curl -s "http://localhost:8765/api/v1/search/cards?core_set_id=sv03&limit=5" | python3 -m json.tool

# Only cards with display images
curl -s "http://localhost:8765/api/v1/search/cards?q=pikachu&has_display_image=true&limit=5" | python3 -m json.tool

# Only cards with local price evidence
curl -s "http://localhost:8765/api/v1/search/cards?q=charizard&has_price=true&limit=5" | python3 -m json.tool

# Pagination
curl -s "http://localhost:8765/api/v1/search/cards?q=charizard&limit=10&offset=10" | python3 -m json.tool
```

### Get card detail

```bash
# Canonical card key (colon form)
curl -s http://localhost:8765/api/v1/cards/en:sv03-223 | python3 -m json.tool

# Slash alias (also accepted)
curl -s http://localhost:8765/api/v1/cards/en/sv03-223 | python3 -m json.tool
```

Response includes: `card_key`, `language`, `card_id`, `name`, `set`, `images`, `price` (local evidence), `provenance`, and full card detail fields.

### Get card images only

```bash
curl -s http://localhost:8765/api/v1/images/cards/en:sv03-223 | python3 -m json.tool
```

### Get card price summary

```bash
curl -s http://localhost:8765/api/v1/prices/cards/en:sv03-223 | python3 -m json.tool
```

### Get card price history

```bash
# All evidence
curl -s "http://localhost:8765/api/v1/prices/history/cards/en:sv03-223?limit=10" | python3 -m json.tool

# Filtered to raw bucket only
curl -s "http://localhost:8765/api/v1/prices/history/cards/en:sv03-223?bucket=raw&limit=10" | python3 -m json.tool
```

### List sets

```bash
curl -s "http://localhost:8765/api/v1/sets?limit=5" | python3 -m json.tool

# Language-filtered
curl -s "http://localhost:8765/api/v1/sets?language_code=en&limit=5" | python3 -m json.tool

# Name search
curl -s "http://localhost:8765/api/v1/sets?q=obsidian&limit=5" | python3 -m json.tool
```

### Get set detail

```bash
curl -s http://localhost:8765/api/v1/sets/sv03 | python3 -m json.tool
```

### List languages

```bash
curl -s http://localhost:8765/api/v1/languages | python3 -m json.tool
```

### API key management (admin scope required)

```bash
# Create an API key
curl -s -X POST http://localhost:8765/api/v1/admin/keys \
  -H "Content-Type: application/json" \
  -d '{"label": "my-app", "scopes": ["cards:read", "admin"], "monthly_quota": 1000}' \
  | python3 -m json.tool

# List keys (no raw keys returned)
curl -s http://localhost:8765/api/v1/admin/keys | python3 -m json.tool

# Deactivate a key
curl -s -X POST http://localhost:8765/api/v1/admin/keys/1/deactivate | python3 -m json.tool

# Check quota usage
curl -s "http://localhost:8765/api/v1/admin/quota?key_id=1" | python3 -m json.tool
```

### Using an API key

When `POKEMON_DB_REQUIRE_API_KEY=1` is set on the server:

```bash
curl -s http://localhost:8765/api/v1/health \
  -H "X-API-Key: your-api-key-here" | python3 -m json.tool

# Or via Authorization header
curl -s http://localhost:8765/api/v1/health \
  -H "Authorization: Bearer your-api-key-here" | python3 -m json.tool
```

### Error responses

All v1 errors follow the standard envelope:

```json
{
  "error": {
    "code": "card_not_found",
    "message": "Card not found",
    "details": { "card_key": "en:missing" }
  }
}
```

Common error codes:

| Code | HTTP | Meaning |
|------|------|---------|
| `invalid_card_key` | 400 | Card key format is wrong |
| `card_not_found` | 404 | No card for that key |
| `invalid_limit` | 400 | Limit exceeds 200 |
| `invalid_offset` | 400 | Offset is negative |
| `unsupported_sort` | 400 | Sort value not allowed |
| `set_not_found` | 404 | No set for that ID |
| `api_key_required` | 401 | No API key provided |
| `invalid_api_key` | 401 | Key is invalid or inactive |
| `insufficient_scope` | 403 | Key lacks required scope |
| `quota_exceeded` | 429 | Monthly quota exhausted |
| `api_key_not_found` | 404 | Admin key ID not found |

### Python SDK example

```python
import requests

class PokemonTCGClient:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key

    def health(self) -> dict:
        r = requests.get(f"{self.base_url}/api/v1/health", headers=self.headers)
        r.raise_for_status()
        return r.json()["data"]

    def search(self, q: str, **filters) -> dict:
        params = {"q": q, **filters}
        r = requests.get(f"{self.base_url}/api/v1/search/cards", params=params, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def card(self, card_key: str) -> dict:
        r = requests.get(f"{self.base_url}/api/v1/cards/{card_key}", headers=self.headers)
        r.raise_for_status()
        return r.json()["data"]

    def card_price(self, card_key: str) -> dict:
        r = requests.get(f"{self.base_url}/api/v1/prices/cards/{card_key}", headers=self.headers)
        r.raise_for_status()
        return r.json()["data"]

    def card_price_history(self, card_key: str, **filters) -> dict:
        r = requests.get(f"{self.base_url}/api/v1/prices/history/cards/{card_key}", params=filters, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def sets(self, **filters) -> dict:
        r = requests.get(f"{self.base_url}/api/v1/sets", params=filters, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def set_detail(self, set_id: str) -> dict:
        r = requests.get(f"{self.base_url}/api/v1/sets/{set_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()["data"]

    def languages(self) -> list:
        r = requests.get(f"{self.base_url}/api/v1/languages", headers=self.headers)
        r.raise_for_status()
        return r.json()["data"]


# Usage
client = PokemonTCGClient("http://localhost:8765")
print(client.health())
print(client.search("charizard", limit=3, language_code="en"))
print(client.card("en:sv03-223"))
print(client.card_price("en:sv03-223"))
```

---

## v8 Pricing Evidence and Canonical Identity (2026-06-22)

### Pricing algorithm version: `pricing-v8.0`

### What changed in v8

v8 makes the pricing recommendation depend on **exact commercial identity** rather than loose name similarity. Key correctness fixes:

1. **Exact identity controls recommendation** — Only `exact_match` listings (matching set code AND collector number) enter the primary raw recommendation. Wrong-number variants are excluded before statistical filtering.
2. **Identity classification** — Every listing is classified as `exact_match`, `variant_match`, `identity_unknown`, or `no_match`.
3. **Selection order** — Identity classification → condition filtering → postage filtering → IQR trimming. Statistics are computed on the correctly-isolated population.
4. **Fallback preserves set code** — Fallback removes only the collector number (`Misty's Determination CP6-085` → `Misty's Determination CP6`), never producing a name-only query.
5. **Fallback triggers on exact evidence** — Fallback triggers when fewer than 3 eligible exact matches exist, not when raw count is low.
6. **Language persistence** — Price evidence is stored with the target card's actual language, not forced to `en`.
7. **Condition exclusion** — Played and Poor condition listings are excluded from the raw recommendation.
8. **Postage handling** — Listings with abnormal postage (>£25) are excluded from the price population but retained for audit.
9. **Source semantics** — Provider data is described truthfully as "eBay marketplace listing observations" (active listings, not confirmed sold data).
10. **Algorithm version** — Cache entries include `pricing-v8.0` version. Older-version caches are automatically invalidated.

### New optional API fields

All new fields are **optional and backwards-compatible**. Existing fields retain their meaning and type.

#### Enhanced matching response

```json
{
  "matching": {
    "confidence": "HIGH",
    "confidence_score": 0.85,
    "confidence_reasons": ["12 exact matches", "Low price dispersion"],
    "confidence_weaknesses": ["Fallback query required"],
    "exact_match_listings": 12,
    "variant_match_listings": 4,
    "identity_unknown_listings": 2,
    "no_match_listings": 1
  }
}
```

#### Selection transparency

```json
{
  "selection": {
    "raw_eligible": 8,
    "graded_eligible": 3,
    "duplicates_excluded": 1,
    "condition_excluded": 2,
    "postage_excluded": 1,
    "identity_excluded": 5
  }
}
```

#### Source transparency

```json
{
  "source": {
    "provider": "RapidAPI eBay Average Selling Price",
    "observation_type": "active_listing",
    "description": "eBay marketplace listing observations"
  }
}
```

#### Algorithm version

```json
{
  "algorithm_version": "pricing-v8.0"
}
```

### Identity classification meanings

| Classification | Meaning |
|---------------|---------|
| `exact_match` | Set code AND collector number match the target (including variant notation like `085/087`) |
| `variant_match` | Set matches but collector number differs, or number matches but set differs |
| `identity_unknown` | Listing lacks enough structured identity to prove or reject an exact match |
| `no_match` | Listing contains conflicting identity evidence (different set AND different number) |

### Supported collector number formats

- `CP6-085` (hyphen-separated)
- `CP6 085/087` (space + variant notation)
- `085/087 CP6` (variant first)
- `5/102` (fraction number)
- `SWSH12-TG01` (set code with letter suffix)
- `SV-P-001` (set code with hyphen)

### New schema tables (migration v9-v27)

| Table | Purpose |
|-------|---------|
| `price_observations` | Immutable source evidence from provider |
| `price_observation_matches` | Algorithm interpretation of observations |
| `price_calculation_runs` | Reproducible calculation metadata |
| `price_snapshots` | Published reproducible price records |
| `canonical_printings` | Exact printed card identity |
| `commercial_variants` | Controlled variant model (holo, reverse, etc.) |
| `sellable_skus` | Deterministic sellable valuation buckets |
| `external_references` | Generic external reference links |

### Backwards compatibility

- All existing `/api/v1/` endpoints continue to work unchanged.
- Existing response fields retain their current meaning and type.
- The legacy `uk_price_history` and `uk_price_fetch_cache` tables remain intact.
- Legacy aggregate graded fields are retained for compatibility but the new `matching` structure is preferred.
|- The `price_source` field is deprecated; use `source.description` instead.

---

## v9 — Inventory & Tenant Management (2026-06-23)

### New schema tables (migration v28-v33)

| Table | Purpose |
|-------|---------|
| `tenants` | Multi-tenant/single-tenant support |
| `users` | Tenant-scoped users with roles |
| `physical_items` | Physical card/slab/package instances |
| `item_images` | Images attached to physical items |
| `inventory_transactions` | Immutable inventory transaction log |
| `inventory_snapshots` | Denormalized current-state cache |

### Authentication and scope model

All v9 endpoints accept `X-API-Key` header for optional auth. When auth is enforced:

| Scope | Access |
|-------|--------|
| `cards:read` | Existing v1 access |
| `read:inventory` | View inventory items, transactions, valuation |
| `write:inventory` | Add/edit/move inventory items |
| `admin:tenant` | Manage tenant settings and users |
| `admin` | Legacy full admin access |

By default, auth is optional. When `POKEMON_DB_REQUIRE_API_KEY=true`, keys must have the appropriate scope for each operation.

### Inventory endpoints

#### `GET /api/v1/inventory/items`
List physical items with pagination and filtering.

**Query parameters:** `limit` (max 200), `offset`, `status`, `location_code`, `q` (search)

**Response:**
```json
{
  "data": [
    {
      "item_id": "uuid-string",
      "sku_id": 900001,
      "sku_identity": {
        "sku_id": 900001,
        "sku_key": "en-sv03-223-NM",
        "language_code": "en",
        "condition_code": "NM",
        "set_code": "sv03",
        "collector_number": "223",
        "name_english": "Charizard ex"
      },
      "certification_number": null,
      "certification_company": null,
      "certification_grade": null,
      "item_condition": "Near Mint",
      "acquired_date": "2026-06-22",
      "acquired_price": 19.99,
      "acquired_currency": "GBP",
      "acquired_source": "eBay",
      "location_code": "Shelf A1",
      "status": "owned",
      "notes": "Test item",
      "current_value": null,
      "current_value_currency": "GBP",
      "images": [],
      "last_transaction": { ... },
      "tenant_id": 1,
      "created_at": "2026-06-23T12:00:00Z",
      "updated_at": "2026-06-23T12:00:00Z"
    }
  ],
  "pagination": { "limit": 50, "offset": 0, "count": 1, "total": 1, "has_more": false }
}
```

#### `POST /api/v1/inventory/items`
Add a physical item to inventory. Creates an `acquired` transaction automatically.

**Body:**
```json
{
  "sku_id": 900001,
  "item_condition": "Near Mint",
  "acquired_date": "2026-06-22",
  "acquired_price": 19.99,
  "acquired_currency": "GBP",
  "acquired_source": "eBay",
  "location_code": "Shelf A1",
  "status": "owned",
  "notes": "Optional notes",
  "certification_number": "12345678",
  "certification_company": "PSA",
  "certification_grade": 10,
  "price_snapshot_id": 123
}
```

**Validation:**
- SKU must exist in `sellable_skus` table (v8)
- Certification number + company must be unique
- price_snapshot_id (optional) links to v8 pricing evidence

#### `GET /api/v1/inventory/items/{item_id}`
Get physical item details including SKU identity, images, last transaction, and current value (from v8 price snapshots).

#### `PUT /api/v1/inventory/items/{item_id}`
Update non-transactional metadata (condition, notes, location). Does NOT create a transaction record.

**Body:** `InventoryItemUpdate` — fields: `item_condition`, `notes`, `location_code`, `location_detail`

#### `PATCH /api/v1/inventory/items/{item_id}/status`
Change item status (e.g., owned → consigned → sold). Creates an immutable transaction.

**Body:**
```json
{
  "status": "consigned",
  "price": 25.00,
  "currency": "GBP",
  "counterparty": "TCGPlayer",
  "reference": "order-123",
  "notes": "Sent for consignment"
}
```

#### `PATCH /api/v1/inventory/items/{item_id}/location`
Change item location. Creates an immutable move transaction.

**Body:**
```json
{
  "location_code": "Safe Box B2",
  "location_detail": "Row 3, Slot 7",
  "notes": "Moved to secure storage"
}
```

#### `GET /api/v1/inventory/items/{item_id}/transactions`
Get transaction history for a specific item. Paginated, most recent first.

**Query parameters:** `limit` (max 200), `offset`

#### `POST /api/v1/inventory/items/{item_id}/transactions`
Add a manual or correction transaction. Also updates the physical item's status/location if provided.

**Body:**
```json
{
  "transaction_type": "audit_correction",
  "notes": "Manual correction during stocktake",
  "to_status": "owned",
  "to_location": "Shelf A1"
}
```

#### `GET /api/v1/inventory/transactions`
Global transaction feed with optional filters.

**Query parameters:** `limit`, `offset`, `transaction_type`, `item_id`

#### `GET /api/v1/inventory/locations`
List all locations used in the tenant with item counts and status summaries.

#### `GET /api/v1/inventory/valuation`
Calculate the current market value of inventory using v8 price snapshots.

**Response:**
```json
{
  "data": {
    "total_valuation": 4567.89,
    "currency": "GBP",
    "valuation_basis": {
      "raw_items": 42,
      "graded_items": 15,
      "total_items": 57
    },
    "valuation_breakdown": {
      "raw_value": 1250.00,
      "graded_value": 3317.89
    },
    "confidence": "MEDIUM",
    "as_of": "2026-06-23T12:00:00Z"
  }
}
```

### Tenant endpoints

#### `GET /api/v1/tenants`
List all tenants (admin/tenant scope required).

#### `POST /api/v1/tenants`
Create a new tenant.

**Body:** `{"tenant_name": "My Shop", "tenant_slug": "my-shop", "is_active": true}`

**Validation:** `tenant_slug` must be unique.

#### `GET /api/v1/tenants/{slug}`
Get tenant details by slug.

#### `GET /api/v1/tenants/{slug}/users`
List users in a tenant.

#### `POST /api/v1/tenants/{slug}/users`
Add a user to a tenant.

**Body:** `{"username": "collector1", "email": "c@example.com", "role": "manager", "password": "..."}`

**Validation:** username must be unique within the tenant.

#### `DELETE /api/v1/tenants/{slug}/users/{user_id}`
Remove a user from a tenant.

### Transaction types

| Type | Description |
|------|-------------|
| `acquired` | Item entered inventory (purchase, trade, gift) |
| `moved` | Item changed location |
| `consigned` | Item sent for consignment |
| `sold` | Item sold |
| `lost` | Item lost/missing |
| `found` | Item found/recovered |
| `returned` | Item returned |
| `audit_correction` | Manual correction during stocktake |

### Key design decisions

- **Transactions are immutable.** Once created, a transaction cannot be edited or deleted. Corrections must be made with new transactions.
- **Current state is derived.** The current status/location of an item is always the most recent transaction for that item.
- **Inventory snapshots** are maintained as a performance cache and can be rebuilt from the transaction log.
- **Tenant isolation** is enforced at the application layer via `WHERE tenant_id = ?` on every query.
- **Default tenant (1)** exists for single-user mode; multi-tenant is future-compatible.
- **Price evidence integration** links acquisitions to v8 `price_snapshots` and `price_observations` tables.
- **Certification uniqueness** is enforced at the database level via partial unique index.

### Backwards compatibility

- All existing `/api/v1/` endpoints continue to work unchanged.
- New inventory and tenant endpoints are additive — no existing responses are modified.
- Auth is optional by default; existing keys without inventory scopes can still access v1 card/search endpoints.
- The `developer_api_keys` table and legacy auth model remain intact.
- Default tenant (slug: `default`) is auto-created on first run via migration v28b.

---

### v9.1 Appendix — Controlled Image Delivery Gateway

#### Image Delivery Endpoints

All image delivery is controlled by the image gateway. The legacy `/images` static mount has been removed.

| Route | Description | Auth Scope |
|-------|-------------|------------|
| `GET /api/v1/images/assets/{image_id}/content` | Deliver a card image (policy-gated, with size selection) | `images:read` or signed URL |
| `POST /api/v1/images/assets/signed-url` | Generate a time-limited signed URL for browser/mobile | `images:read` |

**Supported sizes:** `thumbnail` (150×210), `small` (245×342), `medium` (350×489), `large` (510×712). Images are never enlarged beyond their original dimensions.

#### Policy Evaluation

Delivery policies are evaluated at every request. Most-specific scope wins:

```
image → card → set → language → source → global
```

- **Global policy**: Emergency switch. Requires `admin:all` scope to change.
- **Source policy**: Controls per-source-type (e.g., `asia_official`, `tcgdex`). A known source without an explicit policy falls through to global.
- **Unknown sources**: Images with `null` or empty source type are **blocked by default** and do not fall through to global.

Signed URLs are also subject to policy evaluation at delivery time.

#### Admin Endpoints

| Route | Description | Auth Scope |
|-------|-------------|------------|
| `GET /api/v1/admin/images/policies` | List all delivery policies | `images:admin` |
| `POST /api/v1/admin/images/policies` | Create a policy | `images:admin` |
| `PUT /api/v1/admin/images/policies/global` | Set global emergency switch | `admin:all` |
| `GET /api/v1/admin/images/takedown/cases` | List takedown cases | `images:admin` |
| `POST /api/v1/admin/images/takedown/cases` | Open a takedown case | `images:admin` |
| `PUT /api/v1/admin/images/takedown/cases/{id}/resolve` | Resolve (restore or remove) | `images:admin` |

Takedown operations are atomic: event + policy update + audit log in a single transaction.

#### Rate Limits

| Limit | Scope | Value |
|-------|-------|-------|
| Burst | Per API key | 200 requests/minute |
| Burst | Per identity (key or signed URL) | 120 requests/minute |

Image delivery is subject to rate limits. Policy blocks are recorded but not counted against delivery quotas. Rate-limit violations return `429 Too Many Requests`.

#### Delivery Logging

All image delivery attempts are logged to `image_delivery_policy_records`:
- `image_id`, `card_key`, `tenant_id`, `api_key_id`
- `requested_size`, `policy_decision`, `response_status`
- `request_id`, `created_at`

**Retention:** Raw log entries are retained for 30 days, then deleted. Daily aggregation and permanent retention are not yet implemented.

#### Image Authentication Methods

1. **API key with `images:read` scope** — for server-to-server clients
2. **Signed URL** — HMAC-SHA256 tokens with expiration (300-86400s) for browser/mobile clients

Signed URLs specify the image ID, permitted size, expiry timestamp, and are cryptographically signed. They remain subject to policy evaluation at delivery time.

#### Security Protections

- Canonical path resolution within approved image root only
- Symlink escape prevention (`Path.relative_to` validation)
- MIME-type allow-list (image/webp, image/jpeg)
- No filesystem paths accepted from clients
- No localhost/private-IP trust bypass — all requests authenticate
- Image decoding validation via Pillow (preventing malformed files)
- Maximum pixel dimensions per size (never enlarged)
- Metadata stripping on derivative generation
- Safe error handling (no server paths in error messages)

#### Non-Affiliation Notice

> **SaveRoom Pokémon Card Database is not affiliated with, endorsed by, or sponsored by Nintendo, Creatures Inc., GAME FREAK Inc., or The Pokémon Company. Pokémon and Pokémon character names are trademarks of Nintendo.**
>
> Card images are sourced from publicly available reference archives for catalogue and inventory management purposes. This service does not create, sell, or distribute unlicensed copies of Pokémon cards. Image sources are disclosed in card metadata (`display_image_source_type`).
>
> API users must not:
> - Bulk harvest card images
> - Mirror the catalogue collection
> - Republish the complete image set
> - Resell or sublicense image access
> - Use the API as a general-purpose CDN
> - Create competing image datasets
> - Remove required attribution from images
> - Attempt to bypass quotas or delivery policies

#### Derivative Caching

Generated derivatives (resized images) use deterministic cache keys:

```
{sha256_hash_of_original}_{size}_v{cache_version}
```

Derivatives are stored outside the public web root. They are regenerated when the source changes (hash mismatch). The original file is never overwritten or modified.

#### Physical-Item Photos (Schema Only)

The `physical_item_photos` table provides a tenant-isolated foundation for user-uploaded photos of physical inventory items. Upload endpoints are not yet implemented. Key properties:

- Each photo belongs to exactly one tenant (`tenant_id` FK)
- Photos are linked to a `physical_items` record
- Photos are never automatically promoted to the global catalogue
- Published/unpublished flag controls visibility
