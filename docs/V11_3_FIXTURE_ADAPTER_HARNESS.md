# v11.3 Fixture Adapter Harness

Tags: #type/project #status/needs-review

Status: IMPLEMENTED (harness only, no live provider)
Date: 2026-06-28
Branch: v11.3-provider-fixture-adapter-next

## Overview

v11.3 adds a **fixture-only adapter harness** for testing the provider adapter pipeline without making external API calls. This is NOT a real provider integration.

## What the Harness Does

- Loads fixture JSON files from `tests/fixtures/pricing_sources/`
- Validates fixture metadata (provider code, permission basis, unit-test approval)
- Redacts apparent secrets from payloads
- Exercises the full adapter pipeline: build_queries → fetch → normalise → match
- Uses synthetic internal data (not real provider data)

## What It Does Not Do

- Make external API calls
- Read `.env` or require API keys
- Store real provider data
- Claim to be a real provider

## Files

| File | Purpose |
|---|---|
| `pricing_sources/fixtures.py` | Fixture loading, validation, secret redaction |
| `pricing_sources/fixture_adapter.py` | Fixture-only adapter skeleton |
| `tests/test_v11_3_fixture_loader.py` | Fixture loader tests |
| `tests/test_v11_3_fixture_adapter.py` | Fixture adapter tests |
| `tests/fixtures/pricing_sources/internal_synthetic/` | Synthetic test fixture |

## Metadata Requirements

Every fixture file MUST include `_metadata` with:

| Field | Required | Description |
|---|---|---|
| `provider_code` | Yes | Must match folder name |
| `fixture_name` | Yes | Descriptive name |
| `permission_basis` | Yes | Why this data can be stored/used |
| `allowed_for_unit_tests` | Yes | Must be `true` |
| `source_url_or_doc` | No | Where the data came from |
| `captured_at` | No | Date captured |
| `contains_raw_provider_response` | No | Whether this is raw provider JSON |
| `notes` | No | Additional context |

## Secret Redaction Rules

The fixture loader automatically redacts strings matching:
- `tcg_[A-Za-z0-9]{20,}` (JustTCG-style keys)
- `pk_(live|test)_[A-Za-z0-9]{20,}` (PokéWallet-style keys)
- `[A-Za-z0-9]{32,}` (generic long tokens)

Redaction count is reported in the `LoadedFixture` result.

## Why Internal Synthetic Fixtures Are Allowed

`internal_synthetic` fixtures are:
- Generated internally (not copied from any provider)
- Clearly labelled with `permission_basis: internally generated synthetic data`
- Used only for testing the adapter pipeline
- Not real provider data

## Why Real Provider Fixtures Require Explicit Permission

Real provider fixtures (JustTCG, PokéWallet, etc.) require:
1. Provider terms explicitly permit caching/storing responses
2. `permission_basis` documents the permission
3. No API keys or tokens in the payload
4. Minimal representative samples only (no bulk dumps)

## How Future Provider Work Should Use This Harness

1. Get approved provider access/terms
2. Capture minimal sample payloads
3. Save to `tests/fixtures/pricing_sources/{provider_code}/`
4. Include proper metadata
5. Run through the fixture loader for validation
6. Build the real adapter using `FixtureOnlyAdapter` as a structural reference
7. The real adapter MUST use the v11.2 access gate (`requires_access_gate() → True`)

## Current Status

**No live second-source adapter exists yet. No real provider data is included.**

## Links

- Related: `docs/V11_3_PREFLIGHT.md`
- Related: `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`
- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
- Implementation: `pricing_sources/fixtures.py`, `pricing_sources/fixture_adapter.py`
