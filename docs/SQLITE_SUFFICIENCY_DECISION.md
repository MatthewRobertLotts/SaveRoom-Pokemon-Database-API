# SQLite Sufficiency Decision for SaveRoom Pokémon DB API

**Date:** 2026-06-21
**Status:** Decision required before multi-client API licensing

## Context

The current API runs on SQLite via `pokemon_db_v2_fastapi.py`. The database is ~300K card rows with FTS5 and cache tables, served by a single FastAPI process with `uvicorn`.

## SQLite strengths for this project

- **Zero infrastructure cost.** No separate DB server, no connection pooling, no managed service.
- **Single-file portability.** The entire DB is one file — easy to back up, copy, snapshot.
- **Read performance is excellent.** With proper indexes and FTS5, read latency is sub-millisecond for single-row lookups and low tens of ms for filtered search.
- **Sufficient for current scale.** 300K rows × ~15 languages fits comfortably in SQLite's practical limits.
- **No concurrency writes.** The API is read-only for canonical data. Price writes are internal/batched, not concurrent multi-client.

## SQLite limitations that matter for multi-client API

| Concern | SQLite behavior | Impact |
|---------|----------------|--------|
| **Concurrent writes** | Single-writer model; WAL mode helps reads but writes serialize | Only matters for price fetch writes, not client reads |
| **Connection per process** | Each uvicorn worker opens its own connection | Fine for read-heavy; workers don't block each other on reads |
| **No network access** | File-local only | Must be on same host as API; no distributed API tier |
| **No user/role system** | File-level permissions only | API-key auth is application-level, which we already have |
| **Max DB size** | 281 TB theoretical | Not a concern at current scale |
| **Backup** | File copy or `.dump` | Simpler than pg_dump but no point-in-time recovery |

## Decision matrix

### Scenario A: Single-tenant internal API (current)

SQLite is **fully sufficient**. One API server, one DB file, internal use only. No changes needed.

### Scenario B: Multi-client hosted API (leased developer access)

SQLite is **sufficient for early-stage/low-traffic multi-client** with these constraints:

- Single API server instance (or multiple workers on same host sharing the file)
- Read-heavy workload (card search, detail, images, price reads)
- Writes only from internal price fetch jobs, not from clients
- Up to ~50-100 concurrent API clients (uvicorn async handles this)
- No need for cross-host DB access

SQLite becomes **insufficient** if:

- You need multiple API servers on different hosts accessing the same DB
- You need >1000 concurrent clients with high read throughput
- You need real-time replication or failover
- You need row-level security or database-level user roles
- You need to scale writes from multiple concurrent sources

## Recommendation

**Stay on SQLite for now.** The current product direction (scanner app, POS, inventory desktop, web tracker) can all be served by:

1. A single FastAPI instance on one host with SQLite
2. Each desktop/mobile app can also bundle its own SQLite copy for offline use
3. The "leased API access" model works for early-stage third-party developers at moderate scale

**Migration trigger:** When you need to deploy the API across multiple hosts for HA/load balancing, or when concurrent client count exceeds ~100 sustained, migrate to PostgreSQL. The FastAPI code uses raw SQL with standard syntax, so migration is primarily a connection-string and deployment change — not a rewrite.

## Migration path (when needed)

1. PostgreSQL 16+ on the same host (or managed service like Supabase/Railway)
2. `sqlite3 .dump` → `pgloader` or custom import script
3. Replace `sqlite3.connect()` with `asyncpg` or `psycopg` connection pool
4. FTS5 → PostgreSQL `tsvector`/`tsquery` (or keep FTS in application layer)
5. API-key tables and request log benefit most from PG's concurrent write support

## Verdict

| Phase | DB | Rationale |
|-------|----|-----------|
| v1 API (current) | SQLite | Correct choice — fast, simple, zero cost |
| Early multi-client (≤50 clients) | SQLite | Still sufficient; add read replicas via file copy if needed |
| Scale-up (>100 clients, multi-host) | PostgreSQL | Migrate when operational needs demand it |

**Do not migrate prematurely.** The API contract (v1 endpoints, response envelopes, error codes) is independent of the database backend. Keep the foundation solid, and migrate the storage layer only when operational metrics justify it.
