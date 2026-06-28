"""Tests for v11.3 fixture loader.

Uses synthetic fixtures only. No external calls. No real secrets.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pricing_sources.fixtures import (
    FixtureError,
    load_fixture,
    load_all_fixtures,
    list_fixtures,
)


REPO = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = REPO / "tests" / "fixtures" / "pricing_sources"
SYNTHTETIC_FIXTURE = FIXTURES_ROOT / "internal_synthetic" / "synthetic_pokemon_cards_2026.json"


class TestLoadValidFixture:
    def test_loads_synthetic_fixture(self):
        result = load_fixture(SYNTHTETIC_FIXTURE)
        assert result.metadata.provider_code == "internal_synthetic"
        assert result.metadata.allowed_for_unit_tests is True
        assert isinstance(result.payload, list)
        assert len(result.payload) == 3

    def test_metadata_fields_populated(self):
        result = load_fixture(SYNTHTETIC_FIXTURE)
        assert result.metadata.permission_basis != ""
        assert result.metadata.fixture_name == "synthetic_pokemon_cards_2026"

    def test_redaction_count_zero_for_clean_fixture(self):
        result = load_fixture(SYNTHTETIC_FIXTURE)
        assert result.redaction_count == 0


class TestRejectInvalidFixture:
    def test_rejects_missing_metadata(self, tmp_path):
        fixture_file = tmp_path / "bad.json"
        fixture_file.write_text(json.dumps({"data": []}))
        with pytest.raises(FixtureError, match="No metadata found"):
            load_fixture(fixture_file, fixtures_root=tmp_path.parent)

    def test_rejects_allowed_for_unit_tests_false(self, tmp_path):
        provider_dir = tmp_path / "badprovider"
        provider_dir.mkdir()
        fixture_file = provider_dir / "test.json"
        fixture_file.write_text(json.dumps({
            "_metadata": {
                "provider_code": "badprovider",
                "fixture_name": "test",
                "permission_basis": "test",
                "allowed_for_unit_tests": False,
            },
            "payload": []
        }))
        with pytest.raises(FixtureError, match="allowed_for_unit_tests must be true"):
            load_fixture(fixture_file, fixtures_root=tmp_path)

    def test_rejects_empty_permission_basis(self, tmp_path):
        provider_dir = tmp_path / "badprovider"
        provider_dir.mkdir()
        fixture_file = provider_dir / "test.json"
        fixture_file.write_text(json.dumps({
            "_metadata": {
                "provider_code": "badprovider",
                "fixture_name": "test",
                "permission_basis": "",
                "allowed_for_unit_tests": True,
            },
            "payload": []
        }))
        with pytest.raises(FixtureError, match="permission_basis must be non-empty"):
            load_fixture(fixture_file, fixtures_root=tmp_path)

    def test_rejects_provider_folder_mismatch(self, tmp_path):
        provider_dir = tmp_path / "folder_a"
        provider_dir.mkdir()
        fixture_file = provider_dir / "test.json"
        fixture_file.write_text(json.dumps({
            "_metadata": {
                "provider_code": "different_provider",
                "fixture_name": "test",
                "permission_basis": "test",
                "allowed_for_unit_tests": True,
            },
            "payload": []
        }))
        with pytest.raises(FixtureError, match="Provider code mismatch"):
            load_fixture(fixture_file, fixtures_root=tmp_path)

    def test_rejects_non_json_payload(self, tmp_path):
        provider_dir = tmp_path / "badprovider"
        provider_dir.mkdir()
        fixture_file = provider_dir / "test.json"
        fixture_file.write_text("not valid json {{{")
        with pytest.raises(FixtureError, match="Invalid JSON"):
            load_fixture(fixture_file, fixtures_root=tmp_path)

    def test_rejects_obvious_secret_strings(self, tmp_path):
        """Fixtures containing apparent API keys should be redacted."""
        provider_dir = tmp_path / "testprovider"
        provider_dir.mkdir()
        fixture_file = provider_dir / "test.json"
        fixture_file.write_text(json.dumps({
            "_metadata": {
                "provider_code": "testprovider",
                "fixture_name": "test",
                "permission_basis": "test data",
                "allowed_for_unit_tests": True,
            },
            "payload": {"key": "tcg_live_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"}
        }))
        result = load_fixture(fixture_file, fixtures_root=tmp_path)
        payload_text = json.dumps(result.payload)
        assert "[REDACTED]" in payload_text
        assert "tcg_live_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in payload_text
        assert result.redaction_count > 0


class TestListFixtures:
    def test_lists_synthetic_fixtures(self):
        fixtures = list_fixtures("internal_synthetic")
        assert len(fixtures) >= 1

    def test_returns_empty_for_unknown_provider(self):
        fixtures = list_fixtures("nonexistent_provider")
        assert fixtures == []


class TestLoadAllFixtures:
    def test_loads_all_synthetic(self):
        results = load_all_fixtures("internal_synthetic")
        assert len(results) >= 1
        for r in results:
            assert r.metadata.allowed_for_unit_tests


class TestNoNetworkCalls:
    def test_fixture_loader_never_imports_requests(self):
        """Verify the fixtures module has no network library imports."""
        import pricing_sources.fixtures as mod
        import inspect
        source = inspect.getsource(mod)
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "import aiohttp" not in source
        assert "urllib.request" not in source
