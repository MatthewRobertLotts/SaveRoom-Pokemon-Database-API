# Architecture Notes

## Current shape

The public API is a released FastAPI service with one large legacy entrypoint, `pokemon_db_v2_fastapi.py`, plus supporting modules, pricing adapters, fixtures, tests, docs, and browser UI assets.

## Why the large entrypoint still exists

The API grew through v2-v12 while preserving local dataset paths, app-facing contracts, and release verification. Splitting it in one rewrite would be high-risk and would not improve current users by itself.

## Refactor path

Move one vertical slice at a time while keeping OpenAPI and tests stable:

1. health/readiness routes
2. fixture routes
3. image gateway routes
4. pricing routes
5. inventory/listing routes

Each move should leave a small compatibility import or router registration in the root entrypoint and run the portable CI subset before merge.

## Public CI

The public workflow runs portable tests that do not require private SQLite/image assets. Full local verification runs with the dataset mounted.
