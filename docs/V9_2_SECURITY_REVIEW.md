# v9.2 Security Review

## Overview

This is a focused commercial API security review for v9.2 stabilisation. It is not a claim that the platform is secure in an absolute sense.

## Fixed in v9.2

| Area | Finding | v9.2 action |
|---|---|---|
| Signing-secret policy | An ignored scratch test for production signing-secret rejection existed with a syntax error. | Replaced with tracked deterministic tests in `tests/test_signing_secret.py`. Production missing/short secrets are rejected; development can still use an ephemeral local secret. |
| Production config | Production could rely on local/default DB and missing/placeholder secrets. | Added production validation in `pokemon_db_v3_config.py`: explicit DB required, API key auth required, non-placeholder 32+ signing secret required, debug rejected. |
| SQLite handle lifetime | Physical-photo routes and auth/log middleware opened SQLite connections without guaranteed close. | Added explicit `closing(connect(...))` scopes and shortened physical-photo write transactions. |
| Physical-photo upload transaction length | Upload route held a DB connection while reading/decoding image bytes and writing the file. | Split item ownership check, image validation/file write and DB insert into short phases; uploaded file handles are closed. |
| Test isolation | Physical-photo tests used the configured real database, creating lock and data-leak risk. | Moved physical-photo tests to a temporary seeded database. |
| Backup safety | No minimal safe SQLite backup script existed. | Added `scripts/backup_database.py` and `scripts/verify_database.py`. |
| Price-schema concurrency | `ensure_price_support()` could run first-use `ALTER TABLE` work from read paths and race under concurrent requests. | Added idempotent trusted-column helper, startup price-schema preparation, in-process schema lock, and duplicate-column race guard; covered by `tests/test_price_support_v9_2.py`. |

## Accepted for Local/Private Use

| Area | Current status |
|---|---|
| API keys | Raw API keys are hashed with SHA-256 in SQLite. This is acceptable for local/private v9.2 but should move to keyed hashing or stronger token storage before paid commercial launch. |
| Auth model | API keys and scopes are sufficient for local/private/internal operation. OAuth/customer self-service is deferred. |
| Pricing | RapidAPI live fetch remains internal and must not be triggered without explicit permission. |
| SQLite foreign-key backlog | Large historical DBs report many `PRAGMA foreign_key_check` rows. v9.2 documents this as a data-quality backlog. |
| Scanner endpoint | Average-hash matching is a prototype boundary only, not a security-sensitive recognition product. |

## Required Before Public Beta

- Formal rate limiting for all public API-key traffic, not only image delivery.
- Token generation and rotation process for developer API keys.
- Stronger API-key storage/comparison design.
- Public deployment behind TLS with explicit proxy/header handling.
- Formal upload storage root outside the repository tree.
- File-size and decompression-bomb controls reviewed against Pillow defaults.
- Error responses reviewed for all admin routes.
- Image/legal terms reviewed before public image delivery.
- Foreign-key backlog triaged or accepted with a documented migration plan.

## Required Before Paid Commercial Launch

- Customer account lifecycle and billing gates.
- Developer portal or equivalent key issuance/audit workflow.
- Abuse monitoring and quota dashboards.
- Backup retention policy off the same disk.
- Incident response and takedown operating procedure.
- Licensing/terms review for all external source data and images.
- Security review by a human reviewer before accepting paid external traffic.

## Notes by Area

| Area | Review notes |
|---|---|
| Signed URLs | HMAC token validation and expiry remain enforced; v9.2 did not weaken signatures, policy checks, quotas or takedowns. |
| Tenant isolation | Existing tenant-aware inventory/photo tests still pass and cross-tenant photo operations return 404 or empty lists. |
| Upload validation | Physical-photo upload allows JPEG/PNG/WebP only, validates image decode and stores UUID filenames. |
| Path traversal | Photo upload does not use client filename for storage path. Image gateway path-resolution protections remain documented. |
| SQL parameterisation | Touched routes continue to use bound SQLite parameters. |
| Schema mutation boundary | Price schema setup now normally runs at startup. Defensive request-time guards remain for compatibility and are documented as deferred cleanup rather than public-facing risk. |
| Secrets | `.env.example` contains placeholders only; no real `.env` was created. |

## Links

- Related: `docs/API_CONTRACT_V1.md`
- Related: `docs/OPERATIONS.md`
