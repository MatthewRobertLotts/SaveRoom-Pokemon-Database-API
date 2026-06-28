# v11.3 Preflight — Provider Fixture Adapter Harness

Tags: #type/project #status/needs-review

Status: PREFLIGHT
Date: 2026-06-28
Branch: v11.3-provider-fixture-adapter-next
Previous release: v11.2.0 (Provider Access Safety Gate)

## Overview

v11.3 creates a **fixture-only adapter harness** that future approved provider payloads can use. It does **not** implement any live provider integration.

## Current Release State

- v11.2.0 released, merged to main, tagged, pushed.
- v11.2.0 delivered: provider access gate, adapter framework wiring, env placeholders, fixture intake docs.
- Current branch: `v11.3-provider-fixture-adapter-next`.

## What v11.2 Delivered

1. Provider access gate (`pricing_sources/provider_access.py`)
2. Adapter framework wiring (`pricing_sources/base.py`)
3. Env placeholders (`.env.example`)
4. Fixture intake documentation

## Why v11.3 Exists

Before adding real provider adapters, we need:
- A safe fixture loading pipeline
- Metadata validation and secret redaction
- A fixture-only adapter that exercises the normalisation/matching path
- Tests proving the harness works without live calls

## Fixture-Only Scope

v11.3 creates:
- `pricing_sources/fixtures.py` — fixture loading, validation, secret redaction
- `pricing_sources/fixture_adapter.py` — fixture-only adapter skeleton
- `tests/fixtures/pricing_sources/internal_synthetic/` — synthetic test fixture
- Tests for both modules

## Strict No-Live-Call Rules

1. No `requests`, `httpx`, `aiohttp` imports
2. No external URL calls
3. No `.env` reading
4. No API key requirements
5. No real provider payloads unless explicitly approved

## Where Approved Fixtures Will Live

```
tests/fixtures/pricing_sources/{provider_code}/
  {provider}_{card_reference}_{date}.json
  _metadata.json (per fixture)
```

## What Is Blocked Until Provider Access/Terms Confirmed

- Live JustTCG/PokéWallet/Cardmarket/eBay adapter code
- Real provider API calls
- Real provider data storage
- Commercial pricing display

## Important Clarification

**v11.3 is NOT a provider integration release.** v11.3 prepares the test harness and adapter contract for future approved provider fixtures.

## Links

- Related: `docs/V11_2_RELEASE.md`
- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
- Related: `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`
- Implementation: `pricing_sources/fixtures.py`, `pricing_sources/fixture_adapter.py`
- Tests: `tests/test_v11_3_fixture_loader.py`, `tests/test_v11_3_fixture_adapter.py`
