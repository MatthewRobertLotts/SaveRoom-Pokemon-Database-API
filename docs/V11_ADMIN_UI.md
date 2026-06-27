# v11 Admin UI

Tags: #type/project #status/needs-review

Status: NOT_IMPLEMENTED
Date: 2026-06-27
Branch: v11-pricing-intelligence-foundation

## Overview

The thin admin UI for v11 market evidence inspection has **not been implemented** in this phase.

## Current State

The v11 API provides all the data endpoints needed for an admin UI:
- `/api/v1/prices/sources` — source registry
- `/api/v1/prices/sources/{source_code}/health` — source health
- `/api/v1/prices/observations` — observation list with filtering
- `/api/v1/prices/observations/{observation_id}` — observation detail with matches
- `/api/v1/prices/aggregate/{target_type}/{target_id}` — aggregate valuations
- `/api/v1/prices/refresh/{target_type}/{target_id}` — manual refresh

## Planned Views

| View | Purpose | API Endpoint |
|------|---------|-------------|
| Source Health | Show source status, last success/failure | `GET /api/v1/prices/sources/{code}/health` |
| Evidence Panel | Show observations + aggregates for a card | `GET /api/v1/prices/observations` + `aggregate` |
| Observation Detail | Show raw payload, match confidence, source | `GET /api/v1/prices/observations/{id}` |
| Manual Refresh | Trigger refresh for a target | `POST /api/v1/prices/refresh/...` |
| Problem Cases | List low-confidence / stale observations | `GET /api/v1/prices/observations?confidence=LOW` |

## Implementation Status

**Deferred to v11.0 follow-up / v11.1.**

The backend refresh pipeline works end-to-end. The admin UI requires a thin React/Vue layer over the API endpoints. This is intentionally deferred because:

1. The API contract is stable and can be consumed by any frontend.
2. The primary v11.0 goal is evidence pipeline correctness, not UI.
3. The `/api/v1/prices/refresh` endpoint can be called directly via `curl` for manual testing.

## How to Test Without UI

```bash
# Check source health
curl http://localhost:8765/api/v1/prices/sources/tcgdex/health

# List observations for a card
curl "http://localhost:8765/api/v1/prices/observations?canonical_printing_id=cp-001"

# Trigger refresh
curl -X POST http://localhost:8765/api/v1/prices/refresh/canonical_printing/cp-sv03-125

# View aggregates
curl http://localhost:8765/api/v1/prices/aggregate/canonical_printing/cp-001
```

## Links

- Related: [[V11_PRICE_API]]
- Related: [[V11_ADMIN_UI]] (this document)
