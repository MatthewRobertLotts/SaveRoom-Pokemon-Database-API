# v11.2 Preflight — Provider Access Readiness

Tags: #type/project #status/needs-review

Status: PREFLIGHT
Date: 2026-06-28
Branch: v11.2-provider-access-next
Previous release: v11.1.0 (Source-Neutral Comparison Foundation)

## Overview

v11.2 prepares **provider access guardrails** so that a real second-source adapter can be added later safely. It does **not** implement any live provider adapter.

## Current Release State

- v11.1.0 is released, merged to main, tagged, pushed.
- v11.1.0 delivered: source-neutral comparison module, read-only comparison API, comparison UI, source research/procurement docs, image fallback fix.
- Current branch: `v11.2-provider-access-next`.

## What v11.1.0 Delivered

1. `pricing_sources/comparison.py` — provider-neutral bucket comparison
2. `GET /api/v1/prices/comparison/{type}/{id}` — read-only comparison API
3. Browser comparison UI panel
4. Source validation docs, public terms research, procurement pack
5. Image fallback fix

## Why v11.2 Exists

Real second-source value is **blocked pending approved access/terms/caching permission**. Before any live adapter is written, we need:

- A safe access gate that defaults to blocked
- Clear env-var configuration with explicit opt-in for every permission
- Tests proving the gate blocks unsafe operations
- Documentation for safe fixture intake
- Protection against accidental secret exposure or credit spend

## Provider Access Blockers

| Provider | Status | Blocker |
|---|---|---|
| JustTCG | BLOCKED | API key + terms/caching/commercial-use confirmation |
| PokéWallet | BLOCKED | API key + caching/fixture permission |
| Cardmarket direct | BLOCKED | Not accepting API applications |
| eBay sold providers | BLOCKED | Paid access + terms review |

## Safe Implementation Sequence

1. ✅ Define access gate module (`pricing_sources/provider_access.py`)
2. ✅ Define env-var naming convention
3. ✅ Write tests proving default-blocked behavior
4. ✅ Document fixture intake rules
5. ✅ Update `.env.example` with placeholder flags
6. ⬜ Future: add adapter behind the gate after terms confirmed
7. ⬜ Future: capture approved fixtures
8. ⬜ Future: enable live calls with monitoring

## Files Likely to Change

- `pricing_sources/provider_access.py` (new)
- `tests/test_v11_2_provider_access.py` (new)
- `.env.example` (updated)
- `.gitignore` (ensure `.env` ignored)
- `docs/V11_2_PROVIDER_ACCESS_READINESS.md` (new)
- `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md` (new)
- `docs/V11_PRICE_ADAPTERS.md` (add gate reference)

## Strict No-Secret/No-Credit Rules

1. **Default blocked**: Missing config = provider cannot make live calls.
2. **No secret in logs/repr**: API keys must never appear in error messages or decision strings.
3. **Explicit opt-in required**: Each permission (live calls, caching, fixtures, commercial use) needs its own explicit flag.
4. **No paid credits without confirmation**: Live calls only when `ENABLED=true AND TERMS_CONFIRMED=true`.
5. **No `.env` in Git**: `.env` must be gitignored; only `.env.example` is committed.
6. **Fixtures require permission**: Only save provider fixtures if terms explicitly permit it.
7. **No bulk dumps**: Fixtures are minimal representative payloads for tests only.

## Important Clarification

**v11.2 is NOT provider integration yet.** v11.2 is access readiness and guardrails. No external API calls are made. No real provider data is stored.

## Links

- Related: `docs/V11_1_RELEASE.md`
- Related: `docs/V11_1_QUALITY_REPORT.md`
- Related: `docs/V11_1_SOURCE_ACCESS_PROCUREMENT.md`
- Related: `docs/V11_PRICE_ADAPTERS.md`
- Implementation: `pricing_sources/provider_access.py`
- Tests: `tests/test_v11_2_provider_access.py`
