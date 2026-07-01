# v12 Release-Candidate Audit

## Status

```text
v12.0.0 release candidate — feature complete pending merge/tag
```

This audit freezes v12 feature work. No new product features should be added before merge/tag unless required to fix a broken v12 contract, failing test, missing safety documentation, or unsafe behaviour.

## Branch and commit

```text
Branch: v12-app-readiness-next
HEAD: bf1a749baa63b5349a96030659bafddc56c7a62e
Commit: bf1a749 api: add local sales read endpoints
Audit timestamp: 2026-07-01T17:22:16Z
Remote: origin/v12-app-readiness-next aligned at bf1a749 before this audit doc commit
```

Expected unrelated untracked files intentionally excluded from this release-candidate commit:

```text
docs/SAVEROOM_POKEMON_CARD_DATABASE_PROJECT_REPORT_V1130.md
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.drawio
docs/SAVEROOM_POKEMON_DB_API_V12_VISUAL_BREAKDOWN.url.txt
```

## Endpoint inventory

Confirmed v12 app-readiness endpoints in code and/or API contract docs:

```text
GET  /api/v1/cards/{card_key}/detail
POST /api/v1/cards/detail/batch
GET  /api/v1/prices/chart/cards/{card_key}
GET  /api/v1/prices/cards/{card_key} with data.recommendation
POST /api/v1/listings/assist/cards/{card_key}
POST /api/v1/listings/drafts/cards/{card_key}
GET  /api/v1/listings/drafts/{draft_id}
GET  /api/v1/listings/drafts
PATCH /api/v1/listings/drafts/{draft_id}
POST /api/v1/listings/drafts/{draft_id}/archive
POST /api/v1/inventory/items/{item_id}/listing-draft
POST /api/v1/listings/drafts/{draft_id}/ready
POST /api/v1/listings/drafts/{draft_id}/reserve
POST /api/v1/listings/drafts/{draft_id}/unreserve
GET  /api/v1/listings/drafts/{draft_id}/reservation
POST /api/v1/listings/drafts/{draft_id}/complete-sale
GET  /api/v1/sales/{sale_id}
GET  /api/v1/sales
```

Older v1 contract endpoints remain covered by `tests/test_api_v1_contract.py`.

## Major v12 milestones

Implemented v12 milestones:

1. App-ready single-card detail endpoint.
2. Batch app-ready card detail endpoint.
3. Chart-ready price history endpoint.
4. UK-primary pricing recommendation response wiring, using existing local GBP evidence only.
5. Deterministic listing assistant endpoint.
6. Local listing draft persistence.
7. Inventory-to-listing-draft bridge.
8. Local listing draft ready/reserve/unreserve/reservation workflow.
9. Explicit local sale completion workflow.
10. Read-only local sales get/list API.

## Docs audited

The following docs exist and were audited for v12 release-candidate consistency:

```text
docs/API_CONTRACT_V1.md
docs/V12_UK_PRIMARY_FALLBACK_PRICING_MODEL.md
docs/V12_LISTING_ASSISTANT_ENDPOINT.md
docs/V12_LISTING_DRAFTS.md
docs/V12_INVENTORY_TO_LISTING_DRAFT_BRIDGE.md
docs/V12_LISTING_DRAFT_RESERVATIONS.md
docs/V12_LISTING_DRAFT_SALE_COMPLETION.md
docs/V12_LOCAL_SALES_READ_API.md
docs/JUSTTCG_TERMS_AND_USAGE.md
docs/V12_PRICING_SOURCE_EXPOSURE_POLICY.md
```

The audited docs state the relevant boundaries:

- local-only listing draft, reservation, sale-completion, and local-sales read workflows;
- no marketplace publishing from v12 local workflow endpoints;
- no live provider calls for v12 local workflow endpoints;
- no API keys needed for local workflow endpoints;
- JustTCG-derived pricing is allowed inside SaveRoom-owned apps/tools through the SaveRoom backend with attribution;
- JustTCG-derived pricing is blocked/redacted for external developer API or standalone pricing/data-feed surfaces;
- TotalTCG and JustTCG are separate providers and v12 does not implement TotalTCG blending;
- v12 does not include marketplace auth, publishing, fulfilment, shipping, order import, refunds, or payment capture.

## Safety boundaries

Release-candidate safety boundaries confirmed:

```text
No live provider calls required for v12 local workflow endpoints.
No API credits required for v12 local workflow endpoints.
No marketplace publishing.
No marketplace auth.
No marketplace order import.
No payment capture.
No refunds.
No fulfilment or shipping.
No customer app frontend.
No external developer pricing API exposure for JustTCG-derived pricing.
No v13 work.
```

The tests for listing assistant, listing drafts, reservations, sale completion, and local sales read patch provider/network paths so they fail if `_get_justtcg_price_data()` or network provider calls are made.

## Known exclusions from v12

The following are intentionally excluded from v12.0.0:

```text
marketplace publishing
Whatnot/eBay/Shopify auth
order import
refunds
fulfilment/shipping
analytics dashboards
bulk SKU inventory
TotalTCG blending
customer app frontend
external developer API productisation
v13 work
```

## Verification

Targeted verification run:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall -q .
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_api_v1_contract.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_local_sales_read_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_listing_draft_sale_completion_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_listing_draft_reservation_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_inventory_listing_draft_bridge_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_listing_drafts_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_listing_assistant_api.py
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_v12_prices_endpoint_recommendation_model.py tests/test_v12_uk_pricing_model.py
git diff --check
```

Targeted results:

```text
tests/test_api_v1_contract.py: 52 passed in 69.81s
tests/test_v12_local_sales_read_api.py: 12 passed in 31.59s
tests/test_v12_listing_draft_sale_completion_api.py: 13 passed in 30.57s
tests/test_v12_listing_draft_reservation_api.py: 15 passed in 29.74s
tests/test_v12_inventory_listing_draft_bridge_api.py: 13 passed in 25.94s
tests/test_v12_listing_drafts_api.py: 17 passed in 27.07s
tests/test_v12_listing_assistant_api.py: 15 passed in 24.71s
tests/test_v12_prices_endpoint_recommendation_model.py + tests/test_v12_uk_pricing_model.py: 29 passed in 23.66s
compileall passed silently
git diff --check passed silently
```

Full suite run:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests -q
```

Full suite result:

```text
875 passed, 1 skipped, 19 warnings in 403.48s (0:06:43)
```

Warnings are existing Pillow deprecation warnings around `Image.Image.getdata`.

## Release recommendation

Recommendation:

```text
Approve v12.0.0 merge/tag after human review.
```

Do not add another v12 feature before merge/tag. If Matthew approves release, merge the feature branch to `main`, verify on `main`, tag `v12.0.0` on the merge commit, and push main plus tag.

Recommended commands for Matthew approval step only — not run during this audit:

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff v12-app-readiness-next -m "Merge v12 app readiness release candidate"
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall -q .
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests -q
git tag -a v12.0.0 -m "v12.0.0: app readiness API foundation"
git push origin main
git push origin v12.0.0
```

## Final freeze statement

```text
V12 feature work is frozen. Recommended next action is Matthew approval for merge/tag as v12.0.0.
```
