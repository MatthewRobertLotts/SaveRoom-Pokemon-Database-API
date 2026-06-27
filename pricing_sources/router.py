"""v11 pricing evidence API endpoints.

Provides read-only access to v11 market evidence: sources, observations,
aggregates, and source health. Also provides a refresh endpoint for triggering
manual evidence collection.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from pokemon_db_v3_config import settings_from_env

# Singleton adapter instance
_tcgdex_adapter = None


def _get_tcgdex():
    global _tcgdex_adapter
    if _tcgdex_adapter is None:
        from pricing_sources.tcgdex import TCGdexAdapter
        _tcgdex_adapter = TCGdexAdapter()
    return _tcgdex_adapter


v11_pricing_router = APIRouter(prefix="/api/v1/prices", tags=["prices-v11"])


def _get_db(request: Request) -> sqlite3.Connection:
    """Get the database connection from app state."""
    from pokemon_db_v2_search_api import connect
    return connect(request.app.state.db)


@v11_pricing_router.get("/sources")
def list_sources(request: Request) -> dict[str, Any]:
    """List all registered pricing sources."""
    conn = _get_db(request)
    cur = conn.cursor()
    cur.execute(
        """SELECT source_id, source_code, source_name, source_url, base_currency,
                  default_condition, default_listing_type, is_enabled, capabilities_json,
                  created_at, updated_at
           FROM v11_price_sources
           ORDER BY source_name"""
    )
    cols = [d[0] for d in cur.description]
    sources = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"data": sources}


@v11_pricing_router.get("/sources/{source_code:path}/health")
def get_source_health(source_code: str, request: Request) -> dict[str, Any]:
    """Get health status for a specific source."""
    conn = _get_db(request)
    cur = conn.cursor()
    cur.execute(
        """SELECT health_id, source_id, checked_at, status, last_success_at,
                  last_failure_at, consecutive_failures, rate_limit_remaining,
                  avg_response_ms, last_error_code, last_error_message
           FROM v11_price_source_health
           WHERE source_id = (SELECT source_id FROM v11_price_sources WHERE source_code = ?)
           ORDER BY checked_at DESC
           LIMIT 1""",
        (source_code,)
    )
    row = cur.fetchone()
    if not row:
        # Fall back to adapter health check
        adapter = _get_tcgdex()
        if adapter.source_code == source_code:
            health = adapter.health_check()
            return {"data": {
                "source_code": health.source_code,
                "status": health.status,
                "response_ms": health.response_ms,
                "last_success_at": health.last_success_at,
                "last_failure_at": health.last_failure_at,
                "error_message": health.error_message,
            }}
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Source '{source_code}' not found")

    cols = [d[0] for d in cur.description]
    return {"data": dict(zip(cols, row))}


@v11_pricing_router.get("/observations")
def list_observations(
    request: Request,
    source_code: str | None = Query(None),
    canonical_printing_id: str | None = Query(None),
    commercial_variant_id: str | None = Query(None),
    currency: str | None = Query(None),
    listing_type: str | None = Query(None),
    confidence: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List v11 price observations with filtering."""
    conn = _get_db(request)
    cur = conn.cursor()

    conditions = []
    params: list[Any] = []

    if source_code:
        conditions.append("(SELECT source_id FROM v11_price_sources WHERE source_code = ?) = o.source_id")
        params.append(source_code)
    if canonical_printing_id:
        conditions.append("o.canonical_printing_id = ?")
        params.append(canonical_printing_id)
    if commercial_variant_id:
        conditions.append("o.commercial_variant_id = ?")
        params.append(commercial_variant_id)
    if currency:
        conditions.append("o.currency = ?")
        params.append(currency)
    if listing_type:
        conditions.append("o.listing_type = ?")
        params.append(listing_type)
    if confidence:
        conditions.append("o.match_confidence = ?")
        params.append(confidence)

    where = " AND ".join(conditions) if conditions else "1=1"

    total = int(cur.execute(
        f"SELECT COUNT(*) FROM v11_price_observations o WHERE {where}", params
    ).fetchone()[0])

    query = f"""SELECT o.observation_id, o.source_id, o.source_record_id, o.observed_at,
                       o.fetched_at, o.currency, o.amount, o.condition, o.finish,
                       o.printing_label, o.language, o.marketplace, o.listing_type,
                       o.raw_title, o.observation_type, o.canonical_printing_id,
                       o.commercial_variant_id, o.sellable_sku_id, o.match_confidence,
                       o.match_reason, o.is_usable_for_aggregate
                FROM v11_price_observations o
                WHERE {where}
                ORDER BY o.fetched_at DESC
                LIMIT ? OFFSET ?"""
    params.extend([limit, offset])
    cur.execute(query, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {
        "data": rows,
        "pagination": {
            "limit": limit, "offset": offset, "count": len(rows),
            "total": total, "has_more": offset + len(rows) < total,
        },
    }


@v11_pricing_router.get("/observations/{observation_id}")
def get_observation(observation_id: int, request: Request) -> dict[str, Any]:
    """Get a single observation by ID, including its matches."""
    conn = _get_db(request)
    cur = conn.cursor()

    cur.execute(
        """SELECT observation_id, source_id, source_record_id, observed_at, fetched_at,
                  currency, amount, condition, finish, printing_label, language,
                  marketplace, listing_type, raw_title, raw_url, observation_type,
                  canonical_printing_id, commercial_variant_id, sellable_sku_id,
                  match_confidence, match_reason, is_usable_for_aggregate
           FROM v11_price_observations
           WHERE observation_id = ?""",
        (observation_id,)
    )
    row = cur.fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Observation {observation_id} not found")

    cols = [d[0] for d in cur.description]
    observation = dict(zip(cols, row))

    # Get matches
    cur.execute(
        """SELECT match_id, target_type, target_id, match_confidence, match_reason,
                  match_method, source_set_code, source_collector_number,
                  source_variant, source_language
           FROM v11_price_observation_matches
           WHERE observation_id = ?""",
        (observation_id,)
    )
    match_cols = [d[0] for d in cur.description]
    matches = [dict(zip(match_cols, r)) for r in cur.fetchall()]

    observation["matches"] = matches
    return {"data": observation}


@v11_pricing_router.get("/aggregate/{target_type}/{target_id:path}")
def get_aggregate(
    request: Request,
    target_type: str,
    target_id: str,
    currency: str | None = Query(None),
) -> dict[str, Any]:
    """Get aggregate valuation for a target (canonical_printing, commercial_variant, or sellable_sku)."""
    conn = _get_db(request)
    cur = conn.cursor()

    conditions = "target_type = ? AND target_id = ?"
    params: list[Any] = [target_type, target_id]
    if currency:
        conditions += " AND currency = ?"
        params.append(currency)

    cur.execute(
        f"""SELECT aggregate_id, target_type, target_id, currency, listing_type,
                   finish, median_price, low_price, high_price, mean_price,
                   observation_count, source_count, freshness_days,
                   confidence_label, confidence_score, confidence_reason,
                   computed_at
            FROM v11_price_aggregates
            WHERE {conditions}
            ORDER BY computed_at DESC""",
        params
    )
    cols = [d[0] for d in cur.description]
    aggregates = [dict(zip(cols, row)) for row in cur.fetchall()]

    return {"data": aggregates}


@v11_pricing_router.post("/refresh/{target_type}/{target_id:path}")
def refresh_evidence(
    request: Request,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    """Trigger a manual evidence refresh for a target.

    This endpoint fetches fresh pricing from the source adapter, normalises
    the results, and updates observations and aggregates.
    """
    conn = _get_db(request)
    cur = conn.cursor()

    # Record the refresh run — look up source by source_code
    cur.execute(
        "SELECT source_id FROM v11_price_sources WHERE source_code = 'tcgdex' AND is_enabled = 1 LIMIT 1"
    )
    source_row = cur.fetchone()
    if not source_row:
        return {
            "data": {
                "run_id": run_id,
                "status": "failed",
                "error": "Source 'tcgdex' not found or not enabled",
            }
        }
    source_id = source_row[0]

    cur.execute(
        """INSERT INTO v11_price_refresh_runs (source_id, target_type, target_id, status)
           VALUES (?, ?, ?, 'running')""",
        (source_id, target_type, target_id)
    )
    run_id = cur.lastrowid
    conn.commit()

    try:
        # Get the adapter
        adapter = _get_tcgdex()

        # Build a query for the matcher
        from pricing_sources.matcher import match_observation_to_identity
        from pricing_sources.base import PriceQuery

        # Parse target_id to extract set_code and collector_number
        # Expected format: cp-{set_code}-{collector_number}
        parts = target_id.split("-", 2)
        if len(parts) >= 3 and parts[0] == "cp":
            set_code = parts[1]
            collector_number = parts[2]
        else:
            set_code = None
            collector_number = None

        # Fetch from TCGdex
        # For now, we need the card name to search. Look it up from canonical printings.
        card_name = None
        if set_code and collector_number:
            cur.execute(
                "SELECT canonical_name FROM v10_canonical_printings WHERE set_code = ? AND collector_number = ? LIMIT 1",
                (set_code, collector_number)
            )
            row = cur.fetchone()
            if row:
                card_name = row[0]

        if not card_name:
            # Cannot fetch without a card name
            cur.execute(
                "UPDATE v11_price_refresh_runs SET status = 'failed', error_message = 'card_name_not_found', completed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE run_id = ?",
                (run_id,)
            )
            conn.commit()
            return {
                "data": {
                    "run_id": run_id,
                    "status": "failed",
                    "error": "Could not resolve card name for target_id",
                }
            }

        # Build query and fetch
        query = PriceQuery(
            target_type=target_type,
            target_id=target_id,
            set_code=set_code,
            collector_number=collector_number,
            card_name=card_name,
        )
        queries = adapter.build_queries(query)

        observations_created = 0
        cache_created = 0

        for q in queries:
            raw = adapter.fetch(q)
            if raw is None:
                continue

            # Cache raw response
            import json
            from datetime import datetime, timezone
            raw_json = json.dumps(raw, sort_keys=True, ensure_ascii=False)
            payload_hash = adapter.hash_raw(raw)
            fetched_at = datetime.now(timezone.utc).isoformat()

            cur.execute(
                """INSERT INTO v11_price_source_cache (source_id, source_record_id, fetched_at, raw_payload_json, payload_hash, http_status)
                   VALUES (?, ?, ?, ?, ?, 200)""",
                (source_id, f"{card_name}:{q.get('type', 'unknown')}", fetched_at, raw_json, payload_hash)
            )
            cache_created += 1

            # Normalise
            obs_candidates = adapter.normalise(raw, query)

            # Match
            matched = adapter.match_observations(obs_candidates, query)

            # Store observations
            for m in matched:
                obs = m.observation
                cur.execute(
                    """INSERT INTO v11_price_observations
                       (source_id, source_record_id, observed_at, currency, amount,
                        condition, finish, printing_label, marketplace, listing_type,
                        raw_title, observation_type, canonical_printing_id,
                        commercial_variant_id, sellable_sku_id, match_confidence,
                        match_reason, is_usable_for_aggregate)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (source_id, obs.source_record_id, obs.observed_at,
                     obs.currency, obs.amount, obs.condition, obs.finish,
                     obs.printing_label, obs.marketplace, obs.listing_type,
                     obs.raw_title, obs.observation_type,
                     m.target_id if m.target_type == "canonical_printing" else None,
                     m.target_id if m.target_type == "commercial_variant" else None,
                     m.target_id if m.target_type == "sellable_sku" else None,
                     m.match_confidence.value, m.match_reason)
                )
                obs_id = cur.lastrowid
                observations_created += 1

                # Store match
                cur.execute(
                    """INSERT INTO v11_price_observation_matches
                       (observation_id, target_type, target_id, match_confidence,
                        match_reason, match_method)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (obs_id, m.target_type, m.target_id, m.match_confidence.value,
                     m.match_reason, m.match_method)
                )

        conn.commit()

        # Update run status
        cur.execute(
            """UPDATE v11_price_refresh_runs
               SET status = 'completed', observations_created = ?, cache_rows_created = ?,
                   completed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE run_id = ?""",
            (observations_created, cache_created, run_id)
        )
        conn.commit()

        return {
            "data": {
                "run_id": run_id,
                "status": "completed",
                "observations_created": observations_created,
                "cache_rows_created": cache_created,
            }
        }

    except Exception as e:
        cur.execute(
            """UPDATE v11_price_refresh_runs
               SET status = 'failed', error_message = ?, completed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE run_id = ?""",
            (str(e), run_id)
        )
        conn.commit()
        return {
            "data": {
                "run_id": run_id,
                "status": "failed",
                "error": str(e),
            }
        }
