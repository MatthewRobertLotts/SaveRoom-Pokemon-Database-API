# v9.2 Preflight Evidence

## Overview

This note captures the pre-change state for v9.2 Commercial Foundation Stabilisation. It was written before code changes in this phase.

## Repository and Branch

- Authoritative path: `/media/matt/Storage/Brain/Pokemon Card Database`
- Current branch: `v9.2-next-phase`
- Current HEAD: `ec76171 docs: complete v9.1 release record with merge and tag info`
- Remote: `origin https://github.com/MatthewRobertLotts/SaveRoom-Pokemon-Database-API.git`
- Tags pointing at HEAD: none
- Recent expected history present: `80fb8cd` v9.1 merge, `8b4569d` signed URL browser integration, `d017603` v9 inventory, `fbe3984` v8 pricing evidence.

## Working Tree State

`git status --short` was clean at preflight.

Ignored/untracked local runtime artefacts included:

- `.pytest_cache/`
- `__pycache__/`
- `full_tcgdex/`
- `image_cache/`
- `images`
- `pokemon_db_v7_scanner.py`
- `prototype/`
- `ptcg_db_repo/`
- `recovered_images/`
- `scripts/__pycache__/`
- `tests/__pycache__/`
- `tests/test_signing_secret.py`

## Current Database Candidates

Known candidate files under `full_tcgdex/`:

- `staging_v9_baseline.sqlite` — measured runtime database from investigation; contains v57/v57b scanner hash migrations and latest v9.1/v9.2-ish local state.
- `pokemon_tcg_set_knowledge_base.sqlite` — historical/default filename; also contains v57/v57b migrations but lower current runtime inventory/log counts than staging baseline.
- `staging_v9.1_final.sqlite` — v9.1 release candidate; older migration level and lower image/admin/log counts.
- `staging_v9_only.sqlite`, `staging_v9.1_pre.sqlite`, `staging_v9.1_remediated.sqlite` — staging/pre-release candidates.

Current config default in `pokemon_db_v3_config.py` is `full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite` via `DEFAULT_DB` unless overridden by `POKEMON_DB_DB` or `--db`.

## Current Database Path Selection Sites

Primary path selection is currently in:

- `pokemon_db_v3_config.py`: `DEFAULT_DB`, `settings_from_env()`, `settings_from_args()`.
- `pokemon_db_v2_fastapi.py`: `create_app(settings=None)` calls `settings_from_env()`; `main()` merges args over env.
- `pokemon_db_v2_search_api.py`: imports `DEFAULT_DB` and uses it as module-level `DB`.
- Tests currently create `TestClient(create_app())` in some modules, which means they may use the default configured database unless explicitly passed `PokemonDBSettings`.

## Current Test Commands

Intended v9.2 verification commands:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall .
/home/matt/.hermes/hermes-agent/venv/bin/python -m compileall tests
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest tests -q
TRACKED_TESTS=$(git ls-files 'tests/test_*.py' 'tests/conftest.py' | tr '
' ' ')
/home/matt/.hermes/hermes-agent/venv/bin/python -m pytest -q $TRACKED_TESTS
```

## Known Failures Before v9.2

- `tests/test_signing_secret.py` is ignored but exists locally with a syntax error: `setattr(pm, 'SIGNED_URL_SECRET', None` missing a closing parenthesis. A normal `pytest tests` discovers it and fails collection.
- The tracked suite previously produced one SQLite lock failure in `tests/test_physical_photos.py::test_upload_jpeg`; the same test passed when run alone.
- Several test modules instantiate `TestClient(create_app())` at import/module scope, and some direct SQLite helper connections use default timeout/transaction behaviour.

## Documentation Mismatches

- `docs/API_CONTRACT_V1.md` says physical-item photos are schema-only/not yet implemented, but current code implements upload/list/retrieve/delete routes.
- Scanner endpoint exists in current code as `/api/v1/scanner/scan`, but is not documented as an early prototype/foundation route.
- Current runtime image gateway implementation and health endpoint need clearer operational documentation.
- Multiple DB filenames exist without a formal commercial runtime database decision note.

## Proposed v9.2 Changes

- Remove or repair the ignored corrupt signing-secret test; preserve real signing-secret coverage if already present or add deterministic tracked coverage.
- Tighten SQLite connection lifecycle around auth middleware, request logging, physical photo routes, and direct test helpers.
- Formalise database selection and production validation in config while preserving local development convenience.
- Add safe backup/verification scripts and operations docs.
- Update API contract, v9.2 release notes, security review, and load-smoke documentation.
- Add targeted tests for configuration, backup/verify tooling, signing, physical photos, and lightweight concurrency where practical.

## Files Expected To Be Modified

Likely files:

- `.git/info/exclude` or project ignore handling for obsolete local scratch test entry.
- `tests/test_signing_secret.py` deletion or replacement as tracked test.
- `tests/test_signed_urls.py` and/or new tracked tests for signing secret policy.
- `tests/test_physical_photos.py` and maybe `tests/conftest.py` for safer setup/connection isolation.
- `pokemon_db_v2_fastapi.py` for connection closure/readiness/config fixes.
- `pokemon_db_v3_config.py` for environment/database/production validation.
- `.env.example`.
- `scripts/backup_database.py`.
- `scripts/verify_database.py`.
- `docs/API_CONTRACT_V1.md`.
- `docs/RUNTIME_DATABASE_DECISION.md`.
- `docs/OPERATIONS.md`.
- `docs/V9_2_SECURITY_REVIEW.md`.
- `docs/V9_2_LOAD_SMOKE.md`.
- `docs/V9_2_RELEASE.md`.

## Links

- Related: `docs/V9_1_RELEASE.md`
- Related: `docs/API_CONTRACT_V1.md`
- Related: `docs/v9_addendum.md`
