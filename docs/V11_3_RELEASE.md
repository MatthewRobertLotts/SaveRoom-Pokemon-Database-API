# v11.3.0-rc — Provider Fixture Adapter Harness

Tags: #type/project #status/release-candidate

Status: RELEASE_CANDIDATE (not merged, not tagged)
Date: 2026-06-28
Branch: v11.3-provider-fixture-adapter-next
Previous release: v11.2.0 (tag `v11.2.0`, commit `75dd436`)

## Summary

v11.3 adds a **fixture-only adapter harness** for testing the provider adapter pipeline without external API calls. It does **not** include a live provider adapter or real provider data.

## What's New

### Fixture Loader

**File:** `pricing_sources/fixtures.py`

Loads provider fixture JSON files from `tests/fixtures/pricing_sources/{provider}/`:
- Validates metadata (provider_code, permission_basis, allowed_for_unit_tests)
- Redacts secrets (JustTCG/PokéWallet/generic token patterns)
- Refuses invalid/missing permission metadata
- Never makes network calls

### Fixture-Only Adapter

**File:** `pricing_sources/fixture_adapter.py`

`FixtureOnlyAdapter` extends `PriceSourceAdapter`:
- `source_code = "internal_fixture"` (not a real provider)
- `requires_access_gate() → False` (never makes live calls)
- Loads fixtures from disk via `fetch()`
- Normalises synthetic records into `PriceObservationCandidate` objects
- Matches observations to v10 identity targets

### Synthetic Fixture Policy

**File:** `tests/fixtures/pricing_sources/internal_synthetic/synthetic_pokemon_cards_2026.json`

One synthetic fixture with 3 clearly labelled internal records:
- `provider_code: internal_synthetic`
- `permission_basis: internally generated synthetic data, not provider data`
- No real provider data, no API keys, no secrets

### Secret Safety

Automatic redaction of:
- `tcg_[A-Za-z0-9]{20,}` (JustTCG-style keys)
- `pk_(live|test)_[A-Za-z0-9]{20,}` (PokéWallet-style keys)
- `[A-Za-z0-9]{32,}` (generic long tokens)

### No-Network Guarantee

- No `requests`, `httpx`, `aiohttp`, or `urllib` in production code
- Tests assert absence of network libraries

## What's Not Included

- No live provider adapter (JustTCG, PokéWallet, Cardmarket, eBay)
- No real provider data
- No multi-source pricing
- No provider API calls

## Tests

| Suite | Tests |
|---|---|
| `test_v11_3_fixture_loader.py` | 16 |
| `test_v11_3_fixture_adapter.py` | 12 |
| Existing v11.2 suites | 39 |
| Existing v11.1 suites | 76 |
| Existing v11.0 suites | 97 |
| **Total** | **~240** |

All passing. `compileall` clean. `git diff --check` clean.

## Known Blockers

Real provider integration requires approved access/terms:
- **JustTCG**: preferred target, awaiting key/terms/caching confirmation
- **PokéWallet**: fallback structured candidate, awaiting cache/fixture permission
- **Cardmarket direct**: not accepting API applications
- **eBay sold comps**: paid/third-party providers, terms review needed

## Release Recommendation

v11.3 is ready as a **fixture-harness release candidate**. The harness is complete and tested. It prepares future approved provider payload parsing safely.

**Do not merge to main yet.** Hold until explicit approval to merge/tag.

No live provider integration should begin until approved source terms/access/fixture permission are confirmed.

## Commits in v11.3 (not in v11.2)

```
2a3af7c pricing: add v11.3 fixture-only adapter harness
```

## Links

- Related: `docs/V11_3_QUALITY_REPORT.md`
- Related: `docs/V11_3_PREFLIGHT.md`
- Related: `docs/V11_3_FIXTURE_ADAPTER_HARNESS.md`
- Previous release: `docs/V11_2_RELEASE.md`
