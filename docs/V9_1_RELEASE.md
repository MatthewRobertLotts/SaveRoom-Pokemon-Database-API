# SaveRoom Pokémon Database v9.1 Release

## Overview

v9.0 was primarily an API and inventory release covering the inventory ledger, tenant isolation, and hardened endpoints.

v9.1 introduced the **controlled image delivery gateway**, replacing raw unauthenticated `/images/` mounts with signed, policy-gated, and quota-enforced delivery, followed by full browser UI integration.

## Phase 1 — Gateway Foundation

**Commit range:** `b84fb84` → `919d197`

Completed work:

- Stable catalogue image identity through `catalogue_image_assets`.
- Explicit stable `image_id` primary keys instead of SQLite `rowid`.
- HMAC signed image URLs.
- Token-bound delivery using: `{expires}:{signature}:{image_id}:{size}:{key_id}`.
- Six-level image-policy precedence: image → card → set → language → source → global.
- Transactional takedown and restoration workflow.
- Previous-policy state preservation.
- Immutable takedown and administrative audit records.
- Per-identity burst, hourly, and daily quota enforcement.
- Delivery logging with policy decisions and resolved image identity.
- Default blocking of unregistered or unknown image sources.

## Phase 2 — Hardening and Remediation

**Commit range:** `9353520` → `353c2e8`

Completed work:

- Removed hardcoded personal and machine-specific paths.
- Added settings-based dependency injection for tests and runtime.
- Added WAL-safe test teardown.
- Fixed reverse-order and CLI timeout issues.
- Added unknown-source policy blocking.
- Fixed rollback and transaction tests.
- Added delivery-log aggregation by day and tenant.
- Added tenant-isolated physical item photos.
- Fixed delivery-log test lock contention.
- Added isolated gateway fixtures using the real application factory.
- Added atomic hourly and daily quota windows.
- Added transactional image takedown tests.

## Phase 3 — Browser Integration

**Commit range:** `d8c23e9` → `8b4569d`

Completed work:

- Full signed delivery flow: resolve asset → evaluate policy → generate signed token → verify token → enforce quota → serve image or derivative → log delivery.
- Stable asset-content route.
- Card-key compatibility route: `/api/v1/images/card/{card_key}/content`.
- Signed URL secret hardening: minimum secret length, environment/configuration resolution, development-only ephemeral handling.
- Browser UI prefers `signed_image_url` rather than protected raw paths.
- Image-root configuration through runtime settings and `IMAGE_ROOT`.
- Compatibility-route and CLI cleanup.
- Signed image URLs injected into: legacy search, `/api/v1/search/cards`, `/api/v1/cards/{card_key}`, `/sets/{set_id}/cards`.
- Missing stable assets return `null` and display placeholders.
- Pricing-provider absence changed from generic HTTP 400 to structured HTTP 503.

## Production Behaviour Change

| Before v9.1 | After v9.1 |
|---|---|
| Raw unauthenticated `/images/...` static delivery | Expiring signed image URLs |
| Browser uses local protected image paths | Browser receives gateway-compatible signed URLs |
| Any image source may be selected | Unknown sources blocked by default |
| No delivery rate limits | Per-identity burst, hourly and daily limits |
| No image policy controls | Six-level policy precedence |
| No transactional takedown restoration | Transactional takedown with exact policy restoration |
| Image identity may depend on database internals | Stable explicit `catalogue_image_assets.image_id` |
| Generic pricing configuration error | Structured HTTP 503 with clear message |

## Final Acceptance

```
237 passed, 1 skipped, 0 failed, 0 xfailed
```

Skip reason: `test_signed_url_delivers_200_when_file_exists` intentionally skips when the test environment cannot resolve a source image file on disk. This does not bypass required v9.1 behaviour.

## Runtime Acceptance

| Check | Result |
|---|---|
| `GET /api/v1/health` → 200 | ✅ |
| Signed asset URL → 200 with image content | ✅ (34526 bytes image/webp) |
| Card without local asset → `signed_image_url: null` | ✅ |
| Pricing fetch without RAPIDAPI_KEY → structured 503 | ✅ |
| Signed URL contains positive asset ID | ✅ (90264) |
| No raw `/images/` request required for browser display | ✅ |

## Required Runtime Settings

| Setting | Description |
|---|---|
| `POKEMON_DB_DB` | Path to SQLite database (e.g., `full_tcgdex/staging_v9_baseline.sqlite`) |
| `POKEMON_DB_IMAGE_ROOT` | Directory containing image files (resolves `{IMAGE_ROOT}/images/{lang}/{set}/{card}.webp`) |
| `POKEMON_DB_SIGNED_URL_SECRET` | HMAC secret, minimum 32 characters |
| `RAPIDAPI_KEY` | (Optional) Enables live price fetching |

## Deferred Work

These are **not v9.1 release blockers**:

### Concurrent-load OOM

The server can exit with code 137 under heavy concurrent image load. Record as a separate performance task involving potential: connection pooling, bounded concurrency, derivative-cache optimisation, memory profiling, response streaming. Normal single-user operation has been verified.

### Permanent Image-root Configuration

The production service needs a permanent runtime value for `POKEMON_DB_IMAGE_ROOT` (or the project's equivalent `IMAGE_ROOT` setting). The current symlink workaround may remain temporarily but should be replaced.

### Live Pricing Configuration

The pricing code is complete, but live requests require `RAPIDAPI_KEY` in the actual application service environment. Without it, the intended result is `503 pricing_provider_not_configured`.

### Future Performance Improvements

- Connection pooling for SQLite under concurrent load.
- Derivative cache optimisation (pre-generate common sizes).
- Memory profiling under sustained load.
- Response streaming for large image files.

## Release

- **Final release commit:** `8b4569d`
- **Tag:** `v9.1.0`
- **Branch:** `v9.1-image-gateway`
