# SaveRoom Pokémon Card Database v5 — API Foundation Hardening

v5 starts the move from local/internal FastAPI helpers toward a versioned API and DB foundation that future scanner, POS, inventory, web tracker, listing, and third-party developer products can safely depend on.

This is **not** a scanner/POS/inventory product phase. v5 keeps those products deliberately out of scope until the API/DB contract is stronger.

## Start the local server

```bash
cd "/media/matt/Storage/Brain/Pokemon Card Database"
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/docs
http://127.0.0.1:8765/ui/
```

## Public v1 route namespace

The future public API contract lives under:

```text
/api/v1/...
```

Legacy/internal routes remain available for compatibility:

```text
/health
/search
/cards/{language_code}/{card_id}
/reports/coverage
/api/prices/*
/ui/
```

## Implemented v1 endpoints

```text
GET /api/v1/health
GET /api/v1/search/cards
GET /api/v1/cards/{card_key}
```

Planned v1 resources are documented in `docs/API_CONTRACT_V1.md`.

## Response envelopes

Single resource:

```json
{"data": {}}
```

List resource:

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

## Canonical card key

v1 chooses this canonical card key format:

```text
{language_code}:{card_id}
```

Example:

```text
en:sv03-223
```

The endpoint also accepts the URL path alias:

```text
/api/v1/cards/en/sv03-223
```

But responses always serialize the canonical colon form. External developers should store `card_key`, not raw `card_id`, as their durable foreign key.

## Language-specific behavior

v1 resources are language-specific. The API must not silently fall back to English or another language for names, rules text, images, or price evidence.

Examples:

```bash
curl -fsS 'http://127.0.0.1:8765/api/v1/search/cards?q=charizard&language_code=en&limit=5'
curl -fsS 'http://127.0.0.1:8765/api/v1/cards/en:sv03-223'
```

A non-English card with no same-language pricing should show an auditable no-evidence state rather than English prices.

## Search filters

`GET /api/v1/search/cards` supports:

- `q`
- `language_code`
- `set_id`
- `core_set_id`
- `has_display_image`
- `has_price` — local DB evidence only, no RapidAPI fetch
- `limit` — default 50, max 200
- `offset` — default 0
- `sort` — currently `relevance` / `default`

## Pricing limitations

v1 card detail includes local same-language price summary from `uk_price_history` when available. It does **not** perform live RapidAPI fetches.

Live/cache fetch behavior remains under the internal `/api/prices/*` endpoints until auth, billing, quota, and abuse controls are production-grade.

RapidAPI guardrails remain:

```text
POKEMON_PRICE_MONTHLY_LIMIT=1400 default
POKEMON_PRICE_CACHE_TTL_HOURS=168 default
```

## Optional API key mode

Local/dev behavior allows v1 reads without an API key by default.

To require keys for `/api/v1` routes:

```bash
export POKEMON_DB_REQUIRE_API_KEY=1
```

Clients may send:

```text
X-API-Key: <key>
Authorization: Bearer <key>
```

Raw API keys are not stored. The DB stores only SHA-256 hashes in `developer_api_keys`.

Groundwork tables created non-destructively:

```text
developer_api_keys
api_request_log
```

Future scopes include `cards:read`, `prices:read`, `prices:fetch`, `images:read`, `inventory:read`, `inventory:write`, and `admin`. v5 currently uses only simple `cards:read`/`admin` checks when key mode is enabled.

## Contract tests

Run:

```bash
cd "/media/matt/Storage/Brain/Pokemon Card Database"
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_api_v1_contract.py -q
```

If pytest is missing in the Hermes venv, install it with uv:

```bash
uv pip install --python /home/matt/.hermes/hermes-agent/venv/bin/python pytest
```

The tests do not call RapidAPI and do not spend price requests.

## Current limitations before product-family development

The API foundation is stronger after v5 phase 1, but not yet sufficient for scanner/POS/inventory products or commercial third-party API licensing.

Remaining foundation work before dependent products should start:

1. Add `/api/v1/sets`, `/api/v1/languages`, image, and price-history endpoints.
2. Add real API-key creation/rotation/admin tooling.
3. Add quota enforcement, not just request logging.
4. Add curated OpenAPI examples and developer onboarding docs.
5. Add migration/version discipline for DB schema changes.
6. Decide whether SQLite remains acceptable for expected multi-client load or whether a server DB is needed for hosted API access.
7. Expand contract tests to cover sets, languages, images, prices, auth, and error invariants.

## Files introduced in v5 phase 1

```text
docs/API_CONTRACT_V1.md
pokemon_db_v5_api_models.py
tests/test_api_v1_contract.py
README_v5_api_foundation.md
```
