# v9.2 Operations

## Overview

This document records the minimal operational baseline for running, backing up and verifying the SaveRoom Pokémon Card Database API after v9.2 stabilisation.

## Production Startup

Use explicit production configuration. Do not rely on development defaults.

```bash
cd "/media/matt/Storage/Brain/Pokemon Card Database"
export POKEMON_DB_ENV=production
export POKEMON_DB_DB="/absolute/path/to/authoritative.sqlite"
export POKEMON_DB_REQUIRE_API_KEY=1
export POKEMON_DB_SIGNED_URL_SECRET="<32+ character secret from a secret manager>"
export POKEMON_DB_IMAGE_ROOT="/absolute/path/to/image/root"
export POKEMON_DB_PUBLIC_BASE_URL="https://api.example.invalid"
/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi.py --host 127.0.0.1 --port 8765
```

For local development, the default bind remains `127.0.0.1:8765` and API-key auth remains optional unless configured.

## Configuration Boundary

| Setting | Purpose | Production requirement |
|---|---|---|
| `POKEMON_DB_ENV` | `development`, `test` or `production` | Must be `production` for production service. |
| `POKEMON_DB_DB` | SQLite runtime DB path | Required in production. |
| `POKEMON_DB_REQUIRE_API_KEY` | Enforce `/api/v1` API keys | Required in production. |
| `POKEMON_DB_SIGNED_URL_SECRET` | HMAC secret for signed image URLs | Required, non-placeholder, 32+ chars in production. |
| `POKEMON_DB_IMAGE_ROOT` | Catalogue image root | Required for real image delivery. |
| `POKEMON_DB_PHYSICAL_PHOTO_ROOT` | Physical-item photo storage root | Recommended outside the repo tree. |
| `POKEMON_DB_PUBLIC_BASE_URL` | Public base URL for generated links | Required when publicly bound. |
| `POKEMON_DB_DEBUG` | Debug mode | Must be disabled in production. |
| `POKEMON_DB_LOG_LEVEL` | Log threshold | `INFO` recommended. |

Sensitive values are not printed in startup logs.

## Backup

Use SQLite's online backup API via:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python scripts/backup_database.py \
  full_tcgdex/staging_v9_baseline.sqlite \
  --backup-dir full_tcgdex/backups
```

The script:

- refuses to overwrite an existing destination;
- creates parent directories;
- uses `sqlite3.Connection.backup()` instead of a blind file copy;
- runs integrity verification on the backup;
- writes adjacent JSON metadata containing source, destination, timestamps and sizes;
- returns non-zero on failure.

Use `--json` for machine-readable output.

## Verification

Verify a database before startup, before restore and after backup:

```bash
/home/matt/.hermes/hermes-agent/venv/bin/python scripts/verify_database.py \
  full_tcgdex/staging_v9_baseline.sqlite
```

The script runs:

- `PRAGMA integrity_check`;
- `PRAGMA foreign_key_check` count reporting;
- required app-table presence checks by default.

Historical databases currently report many foreign-key check rows. This is recorded as a data-quality backlog, not a reason to skip integrity checks.

## Price Schema Preparation

v9.2 prepares local price-support tables and columns during application startup by calling `ensure_price_support()` before normal read traffic. The helper is idempotent and guarded against the final v9.2 duplicate-column race (`ebay_item_id`) seen during concurrent smoke testing.

Request-time price code still calls `ensure_price_support()` defensively for backward compatibility with older local DBs and scripts. Those calls should normally be no-ops after startup. Removing all request-time schema guards is deferred to a future cleanup, not v9.2.

## Restore Guidance

Do not overwrite the live database casually.

Safe restore pattern:

1. Stop the API process.
2. Verify the backup with `scripts/verify_database.py`.
3. Move the current live database aside or update `POKEMON_DB_DB` to point at the verified backup.
4. Start the API with explicit production settings.
5. Run health and smoke checks.
6. Keep the failed database for postmortem until the issue is understood.

A destructive overwrite restore should require an explicit human command and should be preceded by a fresh backup of the current live file.

## Health and Readiness Checks

Minimum post-start smoke checks:

```text
GET /api/v1/health
GET /api/v1/readiness
GET /api/v1/search/cards?q=charizard&limit=2&has_display_image=true
GET /api/v1/languages
GET /api/v1/images/health
```

`/api/v1/health` confirms process, DB support object counts and auth mode. `/api/v1/readiness` checks the database, support objects, image root and configuration boundary. `/api/v1/images/health` confirms image gateway policy state and image-root availability.

## Example systemd Unit

Do not install this automatically. Save and adapt it when deploying a dedicated service account.

```ini
[Unit]
Description=SaveRoom Pokemon Card Database API
After=network.target

[Service]
Type=simple
WorkingDirectory=/media/matt/Storage/Brain/Pokemon Card Database
Environment=POKEMON_DB_ENV=production
Environment=POKEMON_DB_DB=/absolute/path/to/authoritative.sqlite
Environment=POKEMON_DB_REQUIRE_API_KEY=1
Environment=POKEMON_DB_IMAGE_ROOT=/absolute/path/to/image/root
Environment=POKEMON_DB_PUBLIC_BASE_URL=https://api.example.invalid
EnvironmentFile=/etc/saveroom-pokemon-db.env
ExecStart=/home/matt/.hermes/hermes-agent/venv/bin/python pokemon_db_v2_fastapi.py --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`/etc/saveroom-pokemon-db.env` should contain secrets such as `POKEMON_DB_SIGNED_URL_SECRET`; do not commit it.

## Retention Guidance

- Keep at least one verified backup before each schema migration or deployment.
- Keep recent daily backups for operational rollback.
- Move long-term backups off the same physical disk for real disaster recovery.
- Do not commit backups, databases, WAL files, image caches or physical-photo storage.

## Links

- Related: `docs/RUNTIME_DATABASE_DECISION.md`
- Related: `docs/V9_2_SECURITY_REVIEW.md`
