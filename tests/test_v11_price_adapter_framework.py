"""Tests for the v11 price adapter framework.

Uses fake adapters and fixture data — no live source calls.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from pricing_sources.base import (
    ConfidenceLabel,
    ListingType,
    MatchConfidence,
    MatchedPriceObservation,
    PriceObservationCandidate,
    PriceQuery,
    PriceSourceAdapter,
    SourceHealthResult,
    compute_aggregate,
    determine_aggregate_confidence,
)


class FakeAdapter(PriceSourceAdapter):
    """A fake adapter for testing that returns canned responses."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None):
        self._responses = responses or {}
        self._fetch_count = 0

    @property
    def source_code(self) -> str:
        return "fake"

    @property
    def source_name(self) -> str:
        return "Fake Source"

    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_condition": False,
            "supports_finish": True,
            "supports_sold_prices": False,
            "supports_active_listings": True,
            "supports_market_prices": True,
            "currencies": ["USD", "EUR"],
            "update_frequency": "test",
        }

    def health_check(self) -> SourceHealthResult:
        return SourceHealthResult(source_code="fake", status="healthy")

    def build_queries(self, query: PriceQuery) -> list[dict[str, Any]]:
        return [{"card_name": query.card_name, "set_code": query.set_code}]

    def fetch(self, query: dict[str, Any]) -> dict[str, Any] | None:
        self._fetch_count += 1
        key = query.get("card_name", "unknown")
        return self._responses.get(key)

    def normalise(self, raw_response: dict[str, Any], query: PriceQuery) -> list[PriceObservationCandidate]:
        results = []
        for item in raw_response.get("prices", []):
            results.append(PriceObservationCandidate(
                source_record_id=item["id"],
                observed_at="2026-06-27T00:00:00Z",
                currency=item.get("currency", "USD"),
                amount=item["amount"],
                finish=item.get("finish", "unknown"),
                listing_type=ListingType(item.get("listing_type", "market_price")),
            ))
        return results

    def match_observations(
        self,
        observations: list[PriceObservationCandidate],
        query: PriceQuery,
    ) -> list[MatchedPriceObservation]:
        matched = []
        for obs in observations:
            matched.append(MatchedPriceObservation(
                observation=obs,
                target_type="canonical_printing",
                target_id=f"cp-{query.card_name or 'unknown'}",
                match_confidence=MatchConfidence.HIGH,
                match_reason="exact set+number match",
                match_method="set_code+collector_number",
            ))
        return matched


class TestConfidenceLabel:
    def test_values(self):
        assert ConfidenceLabel.HIGH == "HIGH"
        assert ConfidenceLabel.MEDIUM == "MEDIUM"
        assert ConfidenceLabel.LOW == "LOW"
        assert ConfidenceLabel.UNUSABLE == "UNUSABLE"


class TestListingType:
    def test_values(self):
        assert ListingType.MARKET_PRICE == "market_price"
        assert ListingType.ACTIVE_LISTING == "active_listing"
        assert ListingType.SOLD == "sold"


class TestPriceObservationCandidate:
    def test_defaults(self):
        obs = PriceObservationCandidate(
            source_record_id="card-1",
            observed_at="2026-06-27T00:00:00Z",
            currency="USD",
            amount=10.0,
        )
        assert obs.condition == "unknown"
        assert obs.finish == "unknown"
        assert obs.listing_type == ListingType.UNKNOWN
        assert obs.marketplace == "unknown"

    def test_with_finish(self):
        obs = PriceObservationCandidate(
            source_record_id="card-1",
            observed_at="2026-06-27T00:00:00Z",
            currency="USD",
            amount=25.0,
            finish="holo",
            listing_type=ListingType.MARKET_PRICE,
        )
        assert obs.finish == "holo"
        assert obs.listing_type == ListingType.MARKET_PRICE


class TestComputeAggregate:
    def test_empty_returns_none(self):
        assert compute_aggregate([]) is None

    def test_single_observation(self):
        obs = [PriceObservationCandidate("c1", "2026-06-27", "USD", 10.0)]
        result = compute_aggregate(obs)
        assert result is not None
        assert result["median_price"] == 10.0
        assert result["low_price"] == 10.0
        assert result["high_price"] == 10.0
        assert result["observation_count"] == 1

    def test_median_odd(self):
        obs = [
            PriceObservationCandidate("c1", "2026-06-27", "USD", 5.0),
            PriceObservationCandidate("c2", "2026-06-27", "USD", 10.0),
            PriceObservationCandidate("c3", "2026-06-27", "USD", 15.0),
        ]
        result = compute_aggregate(obs)
        assert result["median_price"] == 10.0
        assert result["low_price"] == 5.0
        assert result["high_price"] == 15.0
        assert result["observation_count"] == 3

    def test_median_even(self):
        obs = [
            PriceObservationCandidate("c1", "2026-06-27", "USD", 5.0),
            PriceObservationCandidate("c2", "2026-06-27", "USD", 10.0),
            PriceObservationCandidate("c3", "2026-06-27", "USD", 15.0),
            PriceObservationCandidate("c4", "2026-06-27", "USD", 20.0),
        ]
        result = compute_aggregate(obs)
        assert result["median_price"] == 12.5

    def test_mean(self):
        obs = [
            PriceObservationCandidate("c1", "2026-06-27", "USD", 10.0),
            PriceObservationCandidate("c2", "2026-06-27", "USD", 20.0),
        ]
        result = compute_aggregate(obs)
        assert result["mean_price"] == 15.0


class TestDetermineAggregateConfidence:
    def test_high_confidence(self):
        label, score, reason = determine_aggregate_confidence(
            observation_count=10, source_count=2, freshness_days=1.0, finish="holo"
        )
        assert label == ConfidenceLabel.HIGH
        assert score >= 0.85

    def test_low_single_observation(self):
        label, score, reason = determine_aggregate_confidence(
            observation_count=1, source_count=1, freshness_days=1.0, finish="holo"
        )
        assert label == ConfidenceLabel.LOW
        assert "thin evidence" in reason

    def test_stale_reduces_confidence(self):
        label, score, reason = determine_aggregate_confidence(
            observation_count=10, source_count=2, freshness_days=21.0, finish="holo"
        )
        assert label != ConfidenceLabel.HIGH
        assert "stale" in reason

    def test_unknown_finish_reduces(self):
        label, score, reason = determine_aggregate_confidence(
            observation_count=10, source_count=2, freshness_days=1.0, finish="unknown"
        )
        assert score < 0.85
        assert "finish ambiguous" in reason

    def test_mixed_currencies_reduces(self):
        label, score, reason = determine_aggregate_confidence(
            observation_count=10, source_count=2, freshness_days=1.0,
            finish="holo", currency_mixed=True
        )
        assert score < 0.9
        assert "mixed currencies" in reason

    def test_unusable_when_very_low(self):
        label, score, reason = determine_aggregate_confidence(
            observation_count=1, source_count=1, freshness_days=30.0,
            finish="unknown", currency_mixed=True
        )
        assert label == ConfidenceLabel.UNUSABLE


class TestFakeAdapter:
    def test_capabilities(self):
        adapter = FakeAdapter()
        caps = adapter.capabilities()
        assert caps["supports_finish"] is True
        assert caps["supports_sold_prices"] is False
        assert "USD" in caps["currencies"]

    def test_health_check(self):
        adapter = FakeAdapter()
        health = adapter.health_check()
        assert health.status == "healthy"
        assert health.source_code == "fake"

    def test_build_queries(self):
        adapter = FakeAdapter()
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test",
            card_name="Charizard",
            set_code="swsh3",
        )
        queries = adapter.build_queries(query)
        assert len(queries) == 1
        assert queries[0]["card_name"] == "Charizard"

    def test_fetch_returns_none_for_unknown(self):
        adapter = FakeAdapter()
        result = adapter.fetch({"card_name": "Unknown"})
        assert result is None

    def test_fetch_returns_canned_response(self):
        canned = {"prices": [{"id": "p1", "amount": 10.0, "currency": "USD"}]}
        adapter = FakeAdapter(responses={"Charizard": canned})
        result = adapter.fetch({"card_name": "Charizard"})
        assert result == canned

    def test_normalise_extracts_observations(self):
        raw = {
            "prices": [
                {"id": "p1", "amount": 10.0, "currency": "USD", "finish": "holo"},
                {"id": "p2", "amount": 5.0, "currency": "USD", "finish": "normal"},
            ]
        }
        adapter = FakeAdapter()
        obs_list = adapter.normalise(raw, PriceQuery("canonical_printing", "cp-test"))
        assert len(obs_list) == 2
        assert obs_list[0].amount == 10.0
        assert obs_list[0].finish == "holo"
        assert obs_list[1].amount == 5.0

    def test_match_observations(self):
        obs_list = [
            PriceObservationCandidate("p1", "2026-06-27", "USD", 10.0, finish="holo"),
        ]
        adapter = FakeAdapter()
        matched = adapter.match_observations(obs_list, PriceQuery("canonical_printing", "cp-test", card_name="Charizard"))
        assert len(matched) == 1
        assert matched[0].match_confidence == MatchConfidence.HIGH
        assert matched[0].target_type == "canonical_printing"


class TestAdapterAbstractMethods:
    """Verify that PriceSourceAdapter cannot be instantiated without all methods."""

    def test_cannot_instantiate_without_all_methods(self):
        class IncompleteAdapter:
            pass

        with pytest.raises(TypeError):
            # PriceSourceAdapter is ABC, cannot instantiate incomplete impl
            PriceSourceAdapter()

    def test_can_instantiate_complete_impl(self):
        adapter = FakeAdapter()
        assert adapter.source_code == "fake"
