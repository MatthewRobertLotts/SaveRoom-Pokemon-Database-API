# v9.2 Load Smoke

## Overview

v9.2 adds lightweight local smoke coverage to detect obvious connection leaks, database locking and response failures without stress-testing the real production-sized database.

## Method

Test file:

```text
tests/test_load_smoke_v9_2.py
```

The test uses the existing isolated gateway fixture, not the real runtime database. It creates a temporary SQLite database, seeded image assets and a `TestClient` with API-key auth enabled.

Concurrent read smoke:

- workers: 8
- request batches: 8 loops x 4 route types = 32 requests
- route types:
  - `GET /api/v1/health`
  - `GET /api/v1/readiness`
  - `GET /api/v1/search/cards?limit=2`
  - `GET /api/v1/images/assets/{image_id}/content?size=thumbnail`

Physical-photo write smoke is covered by:

```text
tests/test_physical_photos.py::test_repeated_upload_list_delete_does_not_lock_database
```

That regression performs five upload/list/delete cycles against an isolated temporary database and verifies each cycle succeeds.

## Purpose

The smoke checks are designed to detect:

- unclosed SQLite handles;
- request-log write contention;
- obvious database locks;
- image gateway errors under light concurrency;
- health/readiness regressions;
- physical-photo upload/list/delete lifecycle failures;
- request-time price-schema setup races.

## Final Blocker Found and Fixed

The final v9.2 blocker was exposed by this smoke test:

```text
tests/test_load_smoke_v9_2.py::test_concurrent_read_smoke_no_errors
sqlite3.OperationalError: duplicate column name: ebay_item_id
```

Root cause: `ensure_price_support()` used a stale one-time column set and could run first-use `ALTER TABLE` work from read paths such as `/api/v1/search/cards` → `v1_price_summary()`. Under lightweight concurrent requests, two connections could observe the same missing column and one could attempt the duplicate `ALTER TABLE` after another connection had already added it.

Fix: v9.2 now prepares price schema at application startup, serialises in-process price schema setup with a narrow lock, checks actual table columns before each trusted internal `ALTER TABLE`, and treats the specific duplicate-column race as already migrated after rechecking the table. Request-time calls remain as defensive compatibility guards, but normal startup prepares the schema before read traffic. A broader cleanup to remove all request-time schema guards is deferred.

Regression coverage: `tests/test_price_support_v9_2.py` covers repeated idempotency, partial existing schema upgrades, and bounded concurrency.

## Current Result

Targeted v9.2 smoke/regression command:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q \
  tests/test_health_readiness_v9_2.py \
  tests/test_load_smoke_v9_2.py \
  tests/test_config_v9_2.py \
  tests/test_operations_scripts.py \
  tests/test_signing_secret.py \
  tests/test_physical_photos.py \
  tests/test_price_support_v9_2.py
```

Observed final targeted result after the blocker fix:

```text
33 passed, 2 warnings in 19.33s
```

Load-smoke-only result:

```text
1 passed, 1 warning in 14.61s
```

Price-support regression result:

```text
3 passed in 12.29s
```

Warnings were Pillow deprecation warnings from derivative generation and were not load-smoke failures.

## Limitations

- This is not an internet-scale capacity test.
- It does not use the full 1.2 GB runtime database.
- It does not perform paid pricing requests.
- It does not prove long-running memory stability.
- It does not exercise POS, marketplace, billing or full scanner workflows.

## Links

- Related: `docs/OPERATIONS.md`
- Related: `docs/V9_2_SECURITY_REVIEW.md`
