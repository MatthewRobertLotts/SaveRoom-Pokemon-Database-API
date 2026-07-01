# v12.1 Planning

## Status

`v12.1-next` is a planning branch for future v12.1 work.

v12.1 is not started until Matthew approves the first implementation milestone.

No product implementation should be added on this branch until that approval happens. Planning, scope notes, bug triage, documentation, and milestone selection are acceptable.

## Versioning guardrails

- `v12.0.0` remains stable on `main`.
- `v12.0.1` is reserved for bugfixes, documentation fixes, and polish only.
- `v12.1` is the next feature batch after Matthew approves the first milestone.
- Do not create v13 without explicit Matthew approval.
- Do not run live provider or marketplace calls as part of planning.

## Proposed next-work menu

### 1. POS/inventory app API polish

Candidate work:

- Tighten app-facing response shapes for inventory and POS use cases.
- Confirm stable identifiers for inventory item, canonical printing, commercial variant, SKU, listing draft, and local sale objects.
- Identify fields the POS/frontend needs before building client code.

Recommended first output: a short API contract review and route-by-route polish list.

### 2. Listing workflow quality-of-life endpoints

Candidate work:

- Add convenience reads or actions around listing draft state transitions.
- Improve filters for drafts by readiness, reservation state, inventory link, and sale state.
- Add app-facing helpers only where they reduce client-side ambiguity.

Recommended first output: a workflow map showing draft creation, reservation, ready state, sale completion, and cancellation/exception handling.

### 3. Local sales reporting/summary endpoints

Candidate work:

- Add read-only summaries by date range, platform, condition, source, SKU, or sale state.
- Keep reporting separate from market-pricing evidence.
- Preserve explicit boundaries between SaveRoom sales and external market evidence.

Recommended first output: a reporting schema proposal with sample response shapes and privacy/scope notes.

### 4. Inventory history/read APIs

Candidate work:

- Add inventory history and event-read endpoints if the underlying model supports it cleanly.
- Expose useful read paths for app audit trails without creating a write-heavy feature prematurely.
- Clarify which inventory changes should be first-class events.

Recommended first output: an inventory event taxonomy and current-schema gap check.

### 5. App-facing image/cache health endpoints

Candidate work:

- Add health/status endpoints for local image availability, cache coverage, and failed image lookups.
- Keep endpoints read-only and app-supportive.
- Avoid external fetches or provider calls in health checks unless explicitly approved later.

Recommended first output: a read-only image/cache health contract and fixture-backed tests.

### 6. Frontend/POS mock integration preparation

Candidate work:

- Prepare API fixtures and mock flows for a future POS/frontend integration.
- Keep this backend-focused until Matthew approves frontend work.
- Document realistic app flows against existing v12 endpoints.

Recommended first output: a mock integration checklist with example request/response fixtures.

### 7. v12.0.1 bugfix-only branch if needed

Candidate work:

- Create a separate patch branch only if a concrete bug, documentation error, or polish issue is identified.
- Keep the scope narrow and release as `v12.0.1` only after targeted verification.
- Do not mix v12.1 feature work into a patch branch.

Recommended first output: a bugfix triage checklist and go/no-go rule.

## Recommended first v12.1 milestone

Recommended first milestone: POS/inventory app API polish.

Reason: v12.0.0 established app-readiness primitives. Before adding deeper product features, the safest next step is to review and polish the app-facing API contracts around inventory, listing drafts, and local sales so the future POS/frontend can consume stable shapes instead of forcing later breaking changes.

## Non-goals for this planning branch

- No v13 work.
- No live provider calls.
- No marketplace or listing publication.
- No frontend build unless Matthew approves it as the selected milestone.
- No API-key handling.
- No raw provider payload storage.
