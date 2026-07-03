# v12.2 App Transition Plan

Tags: #type/plan #pokemon-db #v12-2 #app-transition

## Overview

`v12.2.0` is the API/client/app-readiness line for moving serious visual frontend work into a separate scanner/collector app repository.

The Pokémon Card Database API should remain the reusable backend brain/platform; the scanner/collector app should consume the API rather than embedding database, pricing, provenance, inventory, auth, or entitlement logic.

## Body

### 1. Current API state

Current state at this planning checkpoint:

```text
Stable release: v12.1.0 on main
Current branch: v12.2-next
Current HEAD: 1b1fa91e2bcfc7a978cd4ee7bb24355028f18ae1
Latest full-suite verification: 937 passed, 1 skipped, 20 warnings
Remote: origin/v12.2-next aligned
```

Current v12.2 contents:

```text
inventory item list filters and POS search polish
POS-ready fixture pack
OpenAPI client contract audit
OpenAPI schema hygiene
unique operationIds
typed local sales summary aggregation
clean direct app.openapi() build
```

### 2. Why v12.2.0 is the app-readiness line

`v12.2.0` should be treated as the API/client readiness release because it gives frontend/app work the stable backend surface it needs to start seriously:

```text
app-facing inventory search/filtering
stable POS/frontend fixture responses
clean OpenAPI schema generation
generated-client hygiene baseline
typed local sales summary aggregation
read-only workflow/state endpoints from v12.1
```

This does not mean every future app/account/billing endpoint is complete. It means the API has enough stable contract surface for real UI/product exploration to begin.

### 3. Separate repo decision

The scanner/collector app should be a separate repository/project:

```text
SaveRoom-Scanner-App
```

Do not build the app inside `SaveRoom-Pokemon-Database-API`.

The API repo remains:

```text
SaveRoom-Pokemon-Database-API
= backend brain/platform
= database, pricing, images, provenance, inventory, listing, sales, auth, OpenAPI, fixtures, contracts
```

The future app repo becomes:

```text
SaveRoom-Scanner-App
= Flutter/mobile/frontend product
= UI, camera/scanner flow, collection screens, local state, generated API client, fixture mode, real API mode
```

### 4. API-as-brain architecture

Preferred architecture:

```text
Flutter Scanner/Collector App
→ SaveRoom API
→ Database / pricing / images / auth / subscriptions / scanner logic
```

Do not ship the API/database brain inside the mobile app.

Reasons:

```text
tier checks stay server-side
pricing logic stays server-side
provenance and provider boundaries stay server-side
updates are easier
one API brain can power many future products
mobile clients avoid raw database/intelligence logic
```

### 5. App repo responsibilities

The app repo should own:

```text
Flutter/mobile UI
camera/scanner flow
collection and card screens
local client state/cache
fixture mode using docs/fixtures/v12_2_pos
real API mode using generated client
mobile-friendly error states/loading states
visual UX iteration
```

The app should not own:

```text
canonical card database
pricing intelligence
provider credentials
marketplace credentials
subscription entitlement truth
raw database migrations
server-side tier enforcement
```

### 6. What can start after v12.2.0

After `v12.2.0` is tagged, Matthew can start the visual scanner/collector frontend seriously.

The first app work should start with:

```text
fixture mode
real API mode
OpenAPI-generated client spike
card detail screen
inventory/search screen if useful
scanner flow UI shell
collection screen mockups
```

Do not wait for complete billing integration before app UI work. The correct process is a cohesive back-and-forth:

```text
API reaches app-ready baseline
→ start visual app/frontend
→ app exposes missing backend needs
→ add focused API endpoints
→ update app
→ repeat
```

### 7. What should wait until v12.3/v12.4/v12.5

Planned sequence:

```text
v12.2.0 = API/client/app-readiness release
v12.3.0 = app user/auth/entitlement foundation
v12.4.0 = scanner/collector backend foundation
v12.5.0 = paid beta readiness
v13.0 = major commercial platform / external product ecosystem shift only with explicit Matthew approval
```

`v12.3.0` should cover:

```text
user accounts
app login/session tokens
/me endpoint
manual free/pro/admin tiers
entitlement checks
app-safe rate limits
admin tier override
```

`v12.4.0` should cover:

```text
collection records
wishlist/favourites
owned-card records
scan candidate response shape
mobile-safe collection endpoints
```

`v12.5.0` should cover:

```text
billing provider integration
webhooks/receipt validation
subscription status syncing
paid-tier enforcement
upgrade/downgrade/cancel flows
```

### 8. Subscription/auth plan

Do not give normal mobile users raw API keys.

Use two future auth layers:

#### App user auth

For scanner/collector/POS users:

```text
email/login/session token/JWT-style app access
user profile
mobile session lifecycle
/me endpoint
free/pro/admin tier state
entitlement-aware API behaviour
```

#### Developer API key auth

For external developers/business integrations:

```text
API keys
scopes
quotas
developer/business integration access
machine-to-machine usage
```

Current API-key auth is useful but is closer to developer/business API access than mobile app login.

Billing provider integration should wait until the app has enough value to charge for. Start visual app/UI work first, then let real product gaps define the smallest useful paid-beta backend.

### 9. What not to build yet

Do not build these before the v12.2 release-candidate audit:

```text
user accounts
subscription records
payment provider integration
app login
scanner/collector collection tables
new app repository
v13 work
```

Do not keep adding backend hardening just because it is possible. Only add more v12.2 backend work if a real release blocker is found.

### 10. Recommended next step

Recommended next step:

```text
v12.2 release-candidate audit
```

If the audit is clean, tag:

```text
v12.2.0
```

Then move serious visual/frontend work into the separate scanner app project.

### 11. Release-candidate audit status

The v12.2 release-candidate audit confirmed:

```text
v12.2.0 release candidate — feature complete pending merge/tag
Full suite: 937 passed, 1 skipped, 19 warnings
OpenAPI direct build: clean
Operation IDs: unique
```

Feature work is frozen unless a release blocker is found. Recommended next action is Matthew approval for merge/tag as `v12.2.0`.

## Links

- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12.2 OpenAPI Schema Hygiene and Sales Summary Typing](V12_2_OPENAPI_SCHEMA_HYGIENE_AND_SALES_SUMMARY_TYPING.md)
- Related: [V12.2 POS-Ready Fixture Pack](V12_2_POS_READY_FIXTURE_PACK.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
- Related: [V12.2 Release Candidate Audit](V12_2_RELEASE_CANDIDATE_AUDIT.md)
