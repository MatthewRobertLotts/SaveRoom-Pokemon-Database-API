# v11.2 Quality Report — Provider Access Safety Gate

Tags: #type/project #status/release-candidate

Status: RELEASE_CANDIDATE
Date: 2026-06-28
Branch: v11.2-provider-access-next
Latest commit: c7f96c4
Previous release: v11.1.0 (Source-Neutral Comparison Foundation)

## Overview

v11.2 adds **provider access safety infrastructure**. It does **not** add a live provider adapter. The gate prevents future live adapters from bypassing key/enabled/terms checks.

## What v11.2 Adds

1. **Provider access gate** (`pricing_sources/provider_access.py`)
   - 5 access statuses from NOT_CONFIGURED to ENABLED_TERMS_CONFIRMED
   - 7 granular permissions (live_calls, raw_cache, fixture_storage, etc.)
   - Default-blocked: missing config = no live calls possible
   - Secrets never exposed in error messages or decision strings

2. **Adapter framework wiring** (`pricing_sources/base.py`)
   - `requires_access_gate()` — defaults False (keyless adapters unaffected)
   - `live_calls_enabled(config)` — checks gate for keyed adapters
   - `require_live_access(config)` — raises PermissionError if blocked
   - TCGdex continues to work unchanged (keyless)

3. **Env placeholders** (`.env.example`)
   - All provider flags default to false/empty
   - `.env` is gitignored

4. **Fixture intake documentation** (`docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`)
   - Rules for safely saving approved provider fixtures later
   - No fixtures stored yet

5. **Pre-flight and readiness docs**
   - `docs/V11_2_PREFLIGHT.md`
   - `docs/V11_2_PROVIDER_ACCESS_READINESS.md`

## Provider Access Gate Summary

| Status | Meaning | Live Calls? |
|---|---|---|
| NOT_CONFIGURED | No API key | ❌ |
| CONFIGURED_DISABLED | Key present, not enabled | ❌ |
| ENABLED_TERMS_UNCONFIRMED | Enabled, terms not confirmed | ❌ |
| ENABLED_TERMS_CONFIRMED | Fully approved | ✅ |

Each permission (caching, fixtures, commercial use, display) requires its own explicit opt-in flag.

## Adapter Framework Integration Summary

- Keyless adapters (TCGdex): `requires_access_gate()` returns `False` → no gate
- Keyed adapters: MUST override `requires_access_gate()` → `True`
- Keyed adapters: MUST call `self.require_live_access(config)` before HTTP
- Error messages never include API key values

## Env/.gitignore Safety

- `.env` is gitignored (line 2 of `.gitignore`)
- `.env.example` contains only placeholder flags (all false/empty)
- No real secrets committed

## Fixture Intake Safety

- Fixtures require explicit `ALLOW_FIXTURES=true` AND terms confirmation
- Only minimal representative payloads
- No bulk dumps, no paid-only data beyond terms allowance
- No fixtures stored yet

## Tests

| Suite | Tests | Status |
|---|---|---|
| `test_v11_2_provider_access.py` | 24 | PASS |
| `test_v11_2_adapter_access_gate.py` | 15 | PASS |
| `test_v11_1_cross_source_comparison.py` | 52 | PASS |
| `test_v11_1_price_comparison_api.py` | 10 | PASS |
| `test_v11_1_comparison_ui_smoke.py` | 14 | PASS |
| `test_v11_price_adapter_framework.py` | 28 | PASS |
| `test_v11_tcgdex_adapter.py` | 22 | PASS |
| `test_v11_price_api.py` | 12 | PASS |
| `test_v11_admin_ui_smoke.py` | 12 | PASS |
| `test_v11_image_ui_smoke.py` | 25 | PASS |
| **Total v11.x** | **~214** | **PASS** |

## Known Limitations

- No live provider adapter implemented
- No real multi-source pricing yet
- Comparison infrastructure (v11.1) returns INSUFFICIENT_EVIDENCE until second source exists
- Gate is inert until a keyed adapter is added and configured

## Remaining Blockers

| Provider | Status | Blocker |
|---|---|---|
| JustTCG | BLOCKED | API key + terms/caching/commercial-use confirmation |
| PokéWallet | BLOCKED | API key + caching/fixture permission |
| Cardmarket direct | BLOCKED | Not accepting API applications |
| eBay sold providers | BLOCKED | Paid access + terms review |

## Recommendation

v11.2 can be treated as a **provider-access safety release candidate**. The gate infrastructure is complete and tested. It prevents future live adapters from bypassing safety checks. However, **no live provider integration should begin until approved source terms/access are confirmed**.

Do not merge to main until explicit approval.

## Links

- Related: `docs/V11_2_RELEASE.md`
- Related: `docs/V11_2_PREFLIGHT.md`
- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
- Related: `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`
- Related: `docs/V11_1_QUALITY_REPORT.md`
- Implementation: `pricing_sources/provider_access.py`, `pricing_sources/base.py`
- Tests: `tests/test_v11_2_provider_access.py`, `tests/test_v11_2_adapter_access_gate.py`
