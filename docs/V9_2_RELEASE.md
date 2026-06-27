# v9.2 Release Notes

## Overview

v9.2 Commercial Foundation Stabilisation hardens the existing v9.1 SaveRoom Pokémon Card Database platform without starting v10 feature work. It focuses on deterministic tests, production configuration boundaries, SQLite reliability, operational backup/verification scripts, docs, and final smoke verification.

## Final Blocker

The final blocker was:

```text
tests/test_load_smoke_v9_2.py::test_concurrent_read_smoke_no_errors
sqlite3.OperationalError: duplicate column name: ebay_item_id
```

Failing path:

```text
v1_search_cards → v1_card_from_detail → v1_price_summary → ensure_price_support → ALTER TABLE uk_price_history ADD COLUMN ebay_item_id
```

Root cause: `ensure_price_support()` performed schema mutation from normal read paths and did not re-check actual SQLite table columns before each `ALTER TABLE`. Under concurrent first-use traffic, one request could add the column while another still attempted the same migration.

## Final Fix

- Added `_table_columns()` and `_add_column_if_missing()` for trusted internal table/column constants.
- Added a narrow in-process `_PRICE_SCHEMA_LOCK` around price schema setup.
- Reordered `ensure_price_support()` so required tables are created before column checks.
- Made `uk_price_history` v4/v5 additions individually idempotent.
- Made `uk_price_fetch_cache.algorithm_version` idempotent and safe when the table does not yet exist.
- Prepared price schema at application startup before cache cleanup/read traffic.
- Kept request-time `ensure_price_support()` calls as defensive no-op guards for older local DBs; removing them entirely is deferred.

No paid RapidAPI calls are made by this fix or by verification.

## Verification Evidence

Load smoke:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_load_smoke_v9_2.py
```

```text
1 passed, 1 warning in 14.61s
```

Price-support regressions:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_price_support_v9_2.py
```

```text
3 passed in 12.29s
```

Targeted v9.2 set:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q tests/test_health_readiness_v9_2.py tests/test_load_smoke_v9_2.py tests/test_config_v9_2.py tests/test_operations_scripts.py tests/test_signing_secret.py tests/test_physical_photos.py tests/test_price_support_v9_2.py
```

```text
33 passed, 2 warnings in 19.33s
```

Compileall:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall -q .
```

```text
exit_code=0
```

Full suite repeated three times:

```text
Run 1: 254 passed, 1 skipped, 19 warnings in 210.57s (0:03:30)
Run 2: 254 passed, 1 skipped, 19 warnings in 207.01s (0:03:27)
Run 3: 254 passed, 1 skipped, 19 warnings in 209.75s (0:03:29)
```

Physical-photo loop:

```bash
for i in 1 2 3 4 5; do
    /home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_physical_photos.py -q || exit 1
done
```

```text
15 passed in 14.97s
15 passed in 15.67s
15 passed in 14.94s
15 passed in 15.47s
15 passed in 15.50s
```

## Scope Confirmation

v9.2 does not implement v10 canonical identity work, scanner/OCR improvements, SKU population, marketplace sync, billing, developer portal, large database migrations, public deployment, or paid pricing calls.

## Deferred Cleanup

- Remove defensive request-time schema guards after a dedicated migration/startup path is formalised.
- Triage historical foreign-key backlog in the large SQLite DB.
- Strengthen API key storage before public/commercial launch.
- Move physical-photo production storage outside the repo tree for deployment.

## Links

- Related: `docs/V9_2_LOAD_SMOKE.md`
- Related: `docs/V9_2_SECURITY_REVIEW.md`
- Related: `docs/OPERATIONS.md`
- Related: `docs/RUNTIME_DATABASE_DECISION.md`
