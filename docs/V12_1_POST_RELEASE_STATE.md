# v12.1 Post-Release State

Tags: #type/report #pokemon-db #v12-1 #post-release

## Overview

`v12.1.0` is released on `main`.

This note records the post-release state before starting the next planning branch. It is a release record only; it does not start v12.2 implementation and does not create v13 work.

Recorded at: `2026-07-02T14:18:19Z`.

## Body

### Release identity

```text
Release name: v12.1.0
Release tag: v12.1.0
Release theme: POS inventory workflow polish
```

### Main and tag state

```text
main HEAD: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
main commit: 9bba2e4 docs: add v12.1 release candidate audit
Tag object: 443a4c8dba64092be729f8e059db87d58e6f6a48
Tag dereferenced commit: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
origin/main: 9bba2e4a984ad14f95122f51b93bb05ac23b10d4
```

`main`, `origin/main`, and the dereferenced `v12.1.0` tag all point at the same release commit.

### Verification result

Latest post-merge verification on `main`:

```text
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall -q .
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests -q
git diff --check
```

Result:

```text
916 passed, 1 skipped, 20 warnings in 481.30s (0:08:01)
```

Warnings were the known existing test-suite/Pillow deprecation warnings and were not release blockers.

### Major v12.1 contents

v12.1.0 added local/POS workflow-readiness polish on top of the v12.0.0 app-readiness release.

Implemented contents:

```text
GET /api/v1/inventory/items/{item_id}/workflow
GET /api/v1/listings/drafts/{draft_id}/workflow
GET /api/v1/listings/drafts filters:
  status
  platform
  card_key
  inventory_item_id
  has_reservation
  has_sale
GET /api/v1/sales/summary
docs/V12_1_RELEASE_CANDIDATE_AUDIT.md
```

The v12.1 workflow/read endpoints are local-only and read-only. They help POS/frontends find and inspect inventory/draft/reservation/sale workflow state without adding marketplace integrations.

### Safety boundaries

The v12.1 release keeps these boundaries:

```text
No live provider calls.
No API-credit spend.
No _get_justtcg_price_data() calls from v12.1 read endpoints.
No JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM API calls.
No marketplace publishing.
No marketplace order import.
No payment capture.
No refund processing.
No fulfilment/shipping state.
No API keys, headers, account metadata, private provider payloads, raw provider JSON, sanitized candidates, or raw filesystem paths exposed by the read endpoints.
No v13 work.
```

### Known unrelated untracked files

These files were present and intentionally excluded from release and post-release commits:

```text
docs/SAVEROOM_POKEMON_CARD_DATABASE_PROJECT_REPORT_V1130.md
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.drawio
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.url.txt
```

### Versioning policy after v12.1.0

```text
v12.1.1 = bugfix/docs/polish only against v12.1.0
v12.2 = next normal feature batch
v13 = major architecture/external product shift only with explicit Matthew approval
```

Do not add more feature work directly to `main`.

### Recommended next branch

```text
v12.2-next
```

`v12.2-next` should begin as a planning branch only. No v12.2 implementation work should start until Matthew approves the first v12.2 implementation milestone.

## Links

- Related: [V12.1 Release Candidate Audit](V12_1_RELEASE_CANDIDATE_AUDIT.md)
- Related: [V12.2 Planning](V12_2_PLANNING.md)
- Related: [V12 Post Release State](V12_POST_RELEASE_STATE.md)
- Related: [API Contract v1](API_CONTRACT_V1.md)
- Related: [V12.1 POS Inventory API Polish Plan](V12_1_POS_INVENTORY_API_POLISH_PLAN.md)
