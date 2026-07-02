# v12.1 Release Candidate Audit

Tags: #type/report #pokemon-db #v12-1 #release-candidate

## Overview

v12.1 status: **v12.1.0 release candidate — feature complete pending merge/tag**.

This audit confirms that `v12.1-next` is ready for Matthew to approve merge/tag as `v12.1.0`, subject to the normal explicit checkpoint before irreversible release actions.

Audit timestamp: `2026-07-02T13:36:59Z`.

## Body

### Branch and commit

```text
Branch: v12.1-next
HEAD: e07983bc236d0f802549dcc0103d38d572d9100a
HEAD summary: e07983b api: add local sales summary endpoint
Upstream: origin/v12.1-next
Upstream status at audit: aligned with local HEAD
```

Tracked files were clean before the audit document was created. The only unrelated untracked files observed were:

```text
docs/SAVEROOM_POKEMON_CARD_DATABASE_PROJECT_REPORT_V1130.md
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.drawio
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.url.txt
```

These files are intentionally excluded from this audit and release-candidate commit.

### Baseline v12.0.0 reference

```text
main: aee25bb793676f445d2b3b8e3f9a62212a989588
Tag: v12.0.0
```

`main` remains on the v12.0.0 release lineage. `v12.1-next` builds on top of the v12.0.0 app-readiness release candidate lineage without starting v13.

### v12.1 endpoint inventory

Confirmed v12.1 additions:

| Milestone | Endpoint/change | Status | Boundary |
|---|---|---|---|
| 2 | `GET /api/v1/inventory/items/{item_id}/workflow` | Implemented | Read-only POS/inventory workflow summary. |
| 3 | `GET /api/v1/listings/drafts/{draft_id}/workflow` | Implemented | Read-only listing draft workflow summary. |
| 4 | `GET /api/v1/listings/drafts` filters | Implemented | Read-only list filtering; no list item workflow expansion. |
| 5 | `GET /api/v1/sales/summary` | Implemented | Read-only local sales aggregation. |

Listing draft list filters confirmed:

```text
status
platform
card_key
inventory_item_id
has_reservation
has_sale
```

### Major v12.1 milestones

1. `docs/V12_1_PLANNING.md` and `docs/V12_1_POS_INVENTORY_API_POLISH_PLAN.md` established the POS/inventory polish scope.
2. Inventory item workflow summary added a read-only item-first workflow view over local inventory/draft/reservation/sale state.
3. Listing draft workflow summary added a read-only draft-first workflow view over local draft/inventory/reservation/sale state.
4. Listing draft list filters added workflow-relevant filtering while preserving pagination, `include_archived`, and the existing list response shape.
5. Local sales summary added read-only aggregate reporting over explicit local sale-completion rows.
6. This release-candidate audit freezes v12.1 feature work pending Matthew approval for merge/tag.

### v12.0.0 foundations still intact

The audit and targeted tests confirm that v12.0.0 foundations still exist and remain covered by the suite:

```text
card detail
batch card detail
chart-ready price history
UK-primary pricing recommendation
listing assistant
local listing drafts
inventory-to-draft bridge
draft ready/reservation workflow
explicit local sale completion
local sales read/list API
JustTCG exposure policy guard
```

No v12.1 work replaces or widens these foundations beyond the approved local/POS-readiness polish.

### Docs audited

The following docs exist and were included in the release-candidate audit:

```text
docs/API_CONTRACT_V1.md
docs/V12_POST_RELEASE_STATE.md
docs/V12_1_PLANNING.md
docs/V12_1_POS_INVENTORY_API_POLISH_PLAN.md
docs/V12_1_INVENTORY_ITEM_WORKFLOW_ENDPOINT.md
docs/V12_1_LISTING_DRAFT_WORKFLOW_ENDPOINT.md
docs/V12_1_LISTING_DRAFT_LIST_FILTERS.md
docs/V12_1_LOCAL_SALES_SUMMARY_ENDPOINT.md
docs/V12_RELEASE_CANDIDATE_AUDIT.md
docs/JUSTTCG_TERMS_AND_USAGE.md
docs/V12_PRICING_SOURCE_EXPOSURE_POLICY.md
```

The v12.1 docs clearly state the important boundaries:

- v12.1 is local/POS-readiness polish;
- workflow endpoints are read-only;
- listing draft list filters are read-only;
- sales summary is read-only;
- local sales summary is not marketplace/payment/accounting reporting;
- no provider calls;
- no marketplace calls;
- no inventory/draft/reservation/sale mutation from read endpoints;
- no v13 work.

### Safety boundaries

Confirmed active boundaries for v12.1:

```text
Do not run live provider calls.
Do not spend API credits.
Do not call _get_justtcg_price_data() from v12.1 read endpoints.
Do not call JustTCG, TotalTCG, TCGplayer, Cardmarket, eBay, Whatnot, Shopify, or LLM APIs.
Do not publish listings.
Do not create marketplace listings.
Do not import marketplace orders.
Do not capture payments.
Do not process refunds.
Do not create fulfilment/shipping state.
Do not expose API keys, headers, account metadata, private provider payloads, raw provider JSON, sanitized candidates, or raw filesystem paths.
Do not start v13.
```

The v12.1 read endpoints are explicitly local-only and read-only.

### Known exclusions

v12.1 intentionally excludes:

```text
marketplace publishing
Whatnot/eBay/Shopify auth
order import
refunds
fulfilment/shipping
payment capture
tax/accounting
TotalTCG blending
customer app frontend
external developer API productisation
v13 work
```

The local sales summary endpoint is SaveRoom workflow reporting only. It is not marketplace reconciliation, payment reporting, fulfilment reporting, tax/accounting advice, live pricing evidence, or market sales evidence.

### Test results

Targeted verification command set:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall -q .
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_1_local_sales_summary_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_1_listing_draft_list_filters_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_1_listing_draft_workflow_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_1_inventory_item_workflow_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_local_sales_read_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_listing_draft_sale_completion_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_listing_draft_reservation_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_inventory_listing_draft_bridge_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_api_v1_contract.py
git diff --check
```

Targeted results:

```text
tests/test_v12_1_local_sales_summary_api.py: 8 passed
tests/test_v12_1_listing_draft_list_filters_api.py: 10 passed
tests/test_v12_1_listing_draft_workflow_api.py: 12 passed
tests/test_v12_1_inventory_item_workflow_api.py: 11 passed
tests/test_v12_local_sales_read_api.py: 12 passed
tests/test_v12_listing_draft_sale_completion_api.py: 13 passed
tests/test_v12_listing_draft_reservation_api.py: 15 passed
tests/test_v12_inventory_listing_draft_bridge_api.py: 13 passed
tests/test_api_v1_contract.py: 52 passed
compileall: passed
git diff --check: passed
```

Full suite command:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests -q
```

Full suite result:

```text
916 passed, 1 skipped, 20 warnings in 481.46s (0:08:01)
```

Warnings are existing deprecation/test-suite warnings and are not new release blockers from this audit.

### Release recommendation

Recommendation: **v12.1 is ready for Matthew approval to merge/tag as `v12.1.0`.**

Do not merge or tag without Matthew's explicit approval checkpoint.

Suggested release commands after approval only:

```bash
git checkout main
git pull --ff-only origin main
git merge --ff-only v12.1-next
git tag -a v12.1.0 -m "v12.1.0"
git push origin main
git push origin v12.1.0
```

If fast-forward merge is not possible, stop and inspect before using any non-ff merge strategy.

## Links

- Related: [API Contract v1](API_CONTRACT_V1.md)
- Related: [V12 Post Release State](V12_POST_RELEASE_STATE.md)
- Related: [V12.1 Planning](V12_1_PLANNING.md)
- Related: [V12.1 POS Inventory API Polish Plan](V12_1_POS_INVENTORY_API_POLISH_PLAN.md)
- Related: [V12.1 Inventory Item Workflow Endpoint](V12_1_INVENTORY_ITEM_WORKFLOW_ENDPOINT.md)
- Related: [V12.1 Listing Draft Workflow Endpoint](V12_1_LISTING_DRAFT_WORKFLOW_ENDPOINT.md)
- Related: [V12.1 Listing Draft List Filters](V12_1_LISTING_DRAFT_LIST_FILTERS.md)
- Related: [V12.1 Local Sales Summary Endpoint](V12_1_LOCAL_SALES_SUMMARY_ENDPOINT.md)
- Related: [V12 Release Candidate Audit](V12_RELEASE_CANDIDATE_AUDIT.md)
- Related: [JustTCG Terms and Usage](JUSTTCG_TERMS_AND_USAGE.md)
- Related: [V12 Pricing Source Exposure Policy](V12_PRICING_SOURCE_EXPOSURE_POLICY.md)
