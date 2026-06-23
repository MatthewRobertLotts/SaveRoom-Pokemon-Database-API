### v9 Hardening Addendum (2026-06-23)

**Status transitions** are now validated — invalid transitions return 400.

**PUT /api/v1/inventory/items/{item_id}** no longer accepts `location_code` or `location_detail`. Use PATCH `/location` instead.

**Concurrency control**: PATCH /status and PATCH /location endpoints support `If-Match: <revision>` header. Expect 409 Conflict on stale writes.

**Authentication**: When `POKEMON_DB_REQUIRE_API_KEY=1`, tenant is derived from the API key's membership_id. Keys without membership need `admin:all` scope.

**Admin endpoints**:
- `POST /api/v1/admin/tenants` — creates tenant atomically with owner membership
- `GET /api/v1/admin/tenants`, `GET /api/v1/admin/tenants/{slug}`, `GET .../{slug}/keys`, `POST .../{slug}/keys`
- `POST /api/v1/admin/keys/{key_id}/deactivate`

**Valuation** (`GET /api/v1/inventory/valuation`): Response now returns `acquisition_cost_total_minor`, `current_market_value_total_minor`, `realised_sales_total_minor` separately. No external requests. Stale threshold: 7 days.