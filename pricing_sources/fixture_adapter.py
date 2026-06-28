"""Fixture-only adapter skeleton for testing the provider adapter pipeline.

This adapter exercises the normalisation and matching path using approved
fixture payloads. It does NOT make external API calls and does NOT require
the access gate.

This is NOT a real provider adapter. It is a test harness.

Design: docs/V11_3_FIXTURE_ADAPTER_HARNESS.md
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pricing_sources.base import (
    ListingType,
    MatchedPriceObservation,
    MatchConfidence,
    PriceObservationCandidate,
    PriceQuery,
    PriceSourceAdapter,
    SourceHealthResult,
)


class FixtureOnlyAdapter(PriceSourceAdapter):
    """Adapter that loads fixture payloads instead of making live API calls.

    This is a test harness for exercising the adapter pipeline:
    - build_queries: returns fixture file references
    - fetch: loads fixture from disk
    - normalise: parses fixture records into observation candidates
    - match_observations: attaches observations to v10 identity targets

    This adapter NEVER makes external calls and NEVER requires the access gate.
    """

    def __init__(self, fixture_path: Path | None = None):
        self._fixture_path = fixture_path

    @property
    def source_code(self) -> str:
        return "internal_fixture"

    @property
    def source_name(self) -> str:
        return "Internal Fixture Harness"

    def requires_access_gate(self) -> bool:
        # Never makes live calls — no gate needed
        return False

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_condition": False,
            "supports_finish": True,
            "supports_sold_prices": False,
            "supports_active_listings": True,
            "supports_market_prices": True,
            "currencies": ["USD"],
            "update_frequency": "static fixture",
            "note": "Test harness only — not a real provider",
        }

    def health_check(self) -> SourceHealthResult:
        return SourceHealthResult(
            source_code=self.source_code,
            status="healthy",
            response_ms=0.0,
        )

    def build_queries(self, query: PriceQuery) -> list[dict[str, Any]]:
        """Return fixture file references as queries."""
        if self._fixture_path:
            return [{"fixture_path": str(self._fixture_path), "target": query.target_id}]
        return [{"fixture_path": None, "target": query.target_id}]

    def fetch(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Load fixture from disk. No network calls."""
        fixture_path = query.get("fixture_path")
        if not fixture_path:
            return None
        path = Path(fixture_path)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def normalise(self, raw_response: dict[str, Any], query: PriceQuery) -> list[PriceObservationCandidate]:
        """Parse fixture records into observation candidates."""
        candidates = []

        # Handle _metadata wrapper
        if "_metadata" in raw_response:
            payload = raw_response.get("payload", raw_response.get("response", {}))
        else:
            payload = raw_response

        # Handle different fixture shapes
        records = []
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            if "records" in payload:
                records = payload["records"]
            elif "data" in payload:
                records = payload["data"] if isinstance(payload["data"], list) else [payload["data"]]
            else:
                records = [payload]

        for rec in records:
            if not isinstance(rec, dict):
                continue
            candidates.append(PriceObservationCandidate(
                source_record_id=str(rec.get("id", rec.get("source_record_id", "fixture"))),
                observed_at=str(rec.get("observed_at", "2026-06-28T00:00:00Z")),
                currency=str(rec.get("currency", "USD")).upper(),
                amount=float(rec.get("amount", rec.get("price", 0))),
                condition=str(rec.get("condition", "unknown")),
                finish=str(rec.get("finish", "unknown")),
                marketplace=str(rec.get("marketplace", "unknown")),
                listing_type=self._parse_listing_type(rec.get("listing_type", "market_price")),
                raw_title=str(rec.get("name", rec.get("raw_title", ""))) or None,
                observation_type=str(rec.get("observation_type", "market_price")),
            ))

        return candidates

    def match_observations(
        self,
        observations: list[PriceObservationCandidate],
        query: PriceQuery,
    ) -> list[MatchedPriceObservation]:
        """Attach observations to the query target."""
        results = []
        for obs in observations:
            results.append(MatchedPriceObservation(
                observation=obs,
                target_type=query.target_type,
                target_id=query.target_id,
                match_confidence=MatchConfidence.HIGH,
                match_reason="fixture harness direct match",
                match_method="fixture",
            ))
        return results

    @staticmethod
    def _parse_listing_type(value: str) -> ListingType:
        """Parse listing type string to enum."""
        try:
            return ListingType(value)
        except ValueError:
            return ListingType.UNKNOWN
