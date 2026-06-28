"""Tests for v11.3 fixture-only adapter harness.

Uses synthetic fixtures only. No external calls. No real secrets.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pricing_sources.base import PriceQuery
from pricing_sources.fixture_adapter import FixtureOnlyAdapter


REPO = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = REPO / "tests" / "fixtures" / "pricing_sources"
SYNTHTETIC_FIXTURE = FIXTURES_ROOT / "internal_synthetic" / "synthetic_pokemon_cards_2026.json"


class TestFixtureAdapterNoGate:
    def test_does_not_require_access_gate(self):
        adapter = FixtureOnlyAdapter()
        assert adapter.requires_access_gate() is False

    def test_live_calls_always_enabled(self):
        adapter = FixtureOnlyAdapter()
        assert adapter.live_calls_enabled({}) is True
        assert adapter.live_calls_enabled(None) is True

    def test_require_live_access_noop(self):
        adapter = FixtureOnlyAdapter()
        adapter.require_live_access(None)  # should not raise


class TestFixtureAdapterProperties:
    def test_source_code(self):
        adapter = FixtureOnlyAdapter()
        assert adapter.source_code == "internal_fixture"

    def test_source_name(self):
        adapter = FixtureOnlyAdapter()
        assert "Fixture" in adapter.source_name

    def test_capabilities(self):
        adapter = FixtureOnlyAdapter()
        caps = adapter.capabilities()
        assert caps["supports_market_prices"] is True
        assert "Test harness" in caps["note"]

    def test_health_check(self):
        adapter = FixtureOnlyAdapter()
        hc = adapter.health_check()
        assert hc.status == "healthy"


class TestFixtureAdapterPipeline:
    def test_loads_synthetic_fixture(self):
        adapter = FixtureOnlyAdapter(fixture_path=SYNTHTETIC_FIXTURE)
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test-001",
        )
        queries = adapter.build_queries(query)
        assert len(queries) == 1

        raw = adapter.fetch(queries[0])
        assert raw is not None
        assert isinstance(raw, dict)

    def test_normalizes_synthetic_records(self):
        adapter = FixtureOnlyAdapter(fixture_path=SYNTHTETIC_FIXTURE)
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test-001",
        )
        raw = adapter.fetch(adapter.build_queries(query)[0])
        candidates = adapter.normalise(raw, query)
        assert len(candidates) == 3
        assert candidates[0].currency == "USD"
        assert candidates[0].amount > 0

    def test_matches_observations(self):
        adapter = FixtureOnlyAdapter(fixture_path=SYNTHTETIC_FIXTURE)
        query = PriceQuery(
            target_type="canonical_printing",
            target_id="cp-test-001",
        )
        raw = adapter.fetch(adapter.build_queries(query)[0])
        candidates = adapter.normalise(raw, query)
        matched = adapter.match_observations(candidates, query)
        assert len(matched) == 3
        for m in matched:
            assert m.target_id == "cp-test-001"

    def test_handles_empty_fixture_safely(self, tmp_path):
        empty_fixture = tmp_path / "empty.json"
        empty_fixture.write_text(json.dumps({
            "_metadata": {
                "provider_code": "internal_synthetic",
                "fixture_name": "empty",
                "permission_basis": "test",
                "allowed_for_unit_tests": True,
            },
            "payload": []
        }))
        adapter = FixtureOnlyAdapter(fixture_path=empty_fixture)
        query = PriceQuery(target_type="canonical_printing", target_id="cp-empty")
        raw = adapter.fetch(adapter.build_queries(query)[0])
        candidates = adapter.normalise(raw, query)
        assert candidates == []

    def test_handles_missing_fixture(self):
        adapter = FixtureOnlyAdapter(fixture_path=Path("/nonexistent/path.json"))
        query = PriceQuery(target_type="canonical_printing", target_id="cp-missing")
        raw = adapter.fetch(adapter.build_queries(query)[0])
        assert raw is None


class TestFixtureAdapterProvenance:
    def test_output_contains_source_fields(self):
        adapter = FixtureOnlyAdapter(fixture_path=SYNTHTETIC_FIXTURE)
        query = PriceQuery(target_type="canonical_printing", target_id="cp-test")
        raw = adapter.fetch(adapter.build_queries(query)[0])
        candidates = adapter.normalise(raw, query)
        for c in candidates:
            assert c.source_record_id != ""
            assert c.observed_at != ""

    def test_does_not_mention_real_providers_as_implemented(self):
        """The fixture adapter must not claim to be a real provider."""
        adapter = FixtureOnlyAdapter()
        assert adapter.source_code != "justtcg"
        assert adapter.source_code != "pokewallet"
        assert adapter.source_code != "cardmarket"
        assert adapter.source_code != "ebay"
        caps = adapter.capabilities()
        # Note should clarify this is NOT a real provider
        assert "not a real provider" in caps["note"].lower() or "test harness" in caps["note"].lower()


class TestNoNetworkCalls:
    def test_adapter_never_imports_requests(self):
        """Verify the fixture adapter has no network library imports."""
        import pricing_sources.fixture_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "import aiohttp" not in source
        assert "urllib" not in source
