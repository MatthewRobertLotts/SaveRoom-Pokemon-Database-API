# v11.2.0-rc — Provider Access Safety Gate

Tags: #type/project #status/release-candidate

Status: RELEASE_CANDIDATE (not merged, not tagged)
Date: 2026-06-28
Branch: v11.2-provider-access-next
Previous release: v11.1.0 (tag `v11.1.0`, commit `d003b1f`)

## Summary

v11.2 adds a **provider access safety gate** that prevents future live adapters from making external API calls without explicit key + enabled flag + terms confirmation. It does **not** add a live provider adapter.

## What's New

### Provider Access Gate

**File:** `pricing_sources/provider_access.py`

Conservative access-control model with default-blocked behavior:

- 5 access statuses: NOT_CONFIGURED → CONFIGURED_DISABLED → ENABLED_TERMS_UNCONFIRMED → ENABLED_TERMS_CONFIRMED → BLOCKED
- 7 granular permissions: live_calls, raw_cache, fixture_storage, normalized_storage, internal_display, customer_display, commercial_use
- Secrets never appear in error messages or decision strings
- `require_provider_live_access()` raises PermissionError for any unsafe operation

### Adapter Framework Wiring

**File:** `pricing_sources/base.py`

Three new methods on `PriceSourceAdapter`:

- `requires_access_gate()` → False by default (keyless adapters like TCGdex unaffected)
- `live_calls_enabled(config)` → checks gate for keyed adapters
- `require_live_access(config)` → raises PermissionError if not allowed

Future keyed adapters MUST:
1. Override `requires_access_gate()` → True
2. Call `self.require_live_access(config)` before every HTTP call

### Env Placeholders

**File:** `.env.example`

Added placeholder flags for JustTCG (all default to false/empty):
```
POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY=
POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED=false
POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_FIXTURES=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_COMMERCIAL_USE=false
```

`.env` is gitignored. No real secrets committed.

### Fixture Intake Documentation

**File:** `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`

Rules for safely saving approved provider fixtures later. No fixtures stored yet.

## What's Not Included

- No live second-source adapter (JustTCG, PokéWallet, Cardmarket, eBay)
- No real multi-source pricing
- No provider API calls
- No real provider data

## Tests

| Suite | Tests |
|---|---|
| `test_v11_2_provider_access.py` | 24 |
| `test_v11_2_adapter_access_gate.py` | 15 |
| Existing v11.1 suites | ~199 |
| **Total** | **~238** |

All passing. `compileall` clean. `git diff --check` clean.

## Known Blockers

Real provider integration requires approved access/terms:
- **JustTCG**: preferred target, awaiting key/terms/caching confirmation
- **PokéWallet**: fallback structured candidate, awaiting cache/fixture permission
- **Cardmarket direct**: not accepting API applications
- **eBay sold comps**: paid/third-party providers, terms review needed

## Release Recommendation

v11.2 is ready as a **provider-access safety release candidate**. The gate infrastructure is complete and tested. It prevents future live adapters from bypassing safety checks.

**Do not merge to main yet.** Hold until explicit approval to merge/tag.

No live provider integration should begin until approved source terms/access are confirmed.

## Commits in v11.2 (not in v11.1)

```
c7f96c4 pricing: require access gate support for live adapters
f6008ae pricing: add v11.2 provider access safety gate
```

## Links

- Related: `docs/V11_2_QUALITY_REPORT.md`
- Related: `docs/V11_2_PREFLIGHT.md`
- Related: `docs/V11_2_PROVIDER_ACCESS_READINESS.md`
- Related: `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`
- Previous release: `docs/V11_1_RELEASE.md`
