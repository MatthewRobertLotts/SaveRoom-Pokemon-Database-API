# v11.2 Provider Access Readiness

Tags: #type/project #status/needs-review

Status: IMPLEMENTED (gate module, no live adapters)
Date: 2026-06-28
Branch: v11.2-provider-access-next

## Overview

v11.2 adds a **provider access safety gate** that defaults to BLOCKED for every provider permission. Future adapters MUST use this gate before making any external API calls.

## Access Gate Module

**File:** `pricing_sources/provider_access.py`

### Status Model

| Status | Meaning | Live Calls? |
|---|---|---|
| `NOT_CONFIGURED` | No API key present | ❌ |
| `CONFIGURED_DISABLED` | Key present but not enabled | ❌ |
| `ENABLED_TERMS_UNCONFIRMED` | Enabled but terms not confirmed | ❌ |
| `ENABLED_TERMS_CONFIRMED` | Fully approved | ✅ |
| `BLOCKED` | Explicitly blocked | ❌ |

### Permission Model

Each permission requires its own explicit opt-in flag:

| Permission | Env Var Pattern | Default |
|---|---|---|
| Live API calls | Requires key + enabled + terms | ❌ |
| Raw response cache | `ALLOW_RAW_CACHE` | ❌ |
| Fixture storage | `ALLOW_FIXTURES` | ❌ |
| Normalized storage | `ALLOW_NORMALIZED_STORAGE` | ❌ |
| Internal display | `ALLOW_INTERNAL_DISPLAY` | ❌ |
| Customer display | `ALLOW_CUSTOMER_DISPLAY` | ❌ |
| Commercial use | `ALLOW_COMMERCIAL_USE` | ❌ |

### Required Env Flags (example: JustTCG)

```
POKEMON_PRICE_SOURCE_JUSTTCG_API_KEY=
POKEMON_PRICE_SOURCE_JUSTTCG_ENABLED=false
POKEMON_PRICE_SOURCE_JUSTTCG_TERMS_CONFIRMED=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_RAW_CACHE=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_FIXTURES=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_INTERNAL_DISPLAY=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_CUSTOMER_DISPLAY=false
POKEMON_PRICE_SOURCE_JUSTTCG_ALLOW_COMMERCIAL_USE=false
```

## How This Protects Credits/Secrets/Terms

1. **Default blocked**: Missing config = no live calls possible.
2. **No secret in logs**: API keys never appear in error messages or decision `__str__`/`__repr__`.
3. **Explicit opt-in**: Each permission needs its own flag — no accidental enablement.
4. **Terms confirmation required**: Even with a key and enabled flag, live calls require `TERMS_CONFIRMED=true`.
5. **No paid credits without confirmation**: The gate prevents accidental API calls during development.

## How Future Adapters Should Use the Gate

```python
from pricing_sources.provider_access import require_provider_live_access
import os

# Before making any external call:
require_provider_live_access("justtcg", os.environ)

# Now safe to make the API call
response = make_justtcg_request(...)
```

## What Remains Blocked

- No live provider adapter code
- No external API calls
- No real provider data stored
- No fixtures captured

All of these require:
1. Approved provider access (key/credentials)
2. Confirmed terms of service (caching, commercial use, display)
3. Explicit env-var opt-in for each permission

## Tests

**File:** `tests/test_v11_2_provider_access.py` (28 tests)

All tests verify default-blocked behavior:
- Missing key blocks provider
- Key present but disabled blocks live calls
- Enabled but terms unconfirmed blocks live calls
- Raw caching requires explicit allow flag
- Fixture storage requires explicit allow flag
- Commercial use requires explicit allow flag
- Live calls allowed only with key + enabled + terms confirmed
- Unknown provider is blocked
- Secrets are not printed in decision repr/string
- Error messages do not include API key value

## Links

- Related: `docs/V11_2_PREFLIGHT.md`
- Related: `docs/V11_2_PROVIDER_FIXTURE_INTAKE.md`
- Related: `docs/V11_PRICE_ADAPTERS.md`
- Implementation: `pricing_sources/provider_access.py`
- Tests: `tests/test_v11_2_provider_access.py`
