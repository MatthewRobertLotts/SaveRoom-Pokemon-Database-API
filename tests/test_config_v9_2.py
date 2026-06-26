#!/usr/bin/env python3
"""v9.2 runtime configuration boundary tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from pokemon_db_v3_config import PokemonDBSettings, settings_from_env, validate_settings


def _db(tmp_path: Path) -> Path:
    p = tmp_path / 'runtime.sqlite'
    p.write_bytes(b'SQLite format 3\x00')
    return p


def test_production_requires_explicit_database_path(tmp_path):
    settings = PokemonDBSettings(
        db=_db(tmp_path),
        ui_dir=tmp_path,
        reports_dir=tmp_path / 'reports',
        runtime_env='production',
        db_source='default',
        require_api_key=True,
        signed_url_secret='s' * 32,
    )

    with pytest.raises(ValueError, match='explicit database path'):
        validate_settings(settings, require_ui=False)


def test_production_rejects_placeholder_or_missing_secret(tmp_path):
    settings = PokemonDBSettings(
        db=_db(tmp_path),
        ui_dir=tmp_path,
        reports_dir=tmp_path / 'reports',
        runtime_env='production',
        db_source='env',
        require_api_key=True,
        signed_url_secret='replace-me',
    )

    with pytest.raises(ValueError, match='SIGNED_URL_SECRET'):
        validate_settings(settings, require_ui=False)


def test_production_requires_api_key_auth(tmp_path):
    settings = PokemonDBSettings(
        db=_db(tmp_path),
        ui_dir=tmp_path,
        reports_dir=tmp_path / 'reports',
        runtime_env='production',
        db_source='arg',
        require_api_key=False,
        signed_url_secret='s' * 32,
    )

    with pytest.raises(ValueError, match='REQUIRE_API_KEY'):
        validate_settings(settings, require_ui=False)


def test_development_keeps_convenient_local_defaults(tmp_path):
    settings = PokemonDBSettings(
        db=_db(tmp_path),
        ui_dir=tmp_path,
        reports_dir=tmp_path / 'reports',
        runtime_env='development',
        db_source='default',
        require_api_key=False,
        signed_url_secret=None,
    )

    assert validate_settings(settings, require_ui=False).runtime_env == 'development'


def test_env_loader_records_explicit_db_source(monkeypatch, tmp_path):
    db = _db(tmp_path)
    monkeypatch.setenv('POKEMON_DB_DB', str(db))
    monkeypatch.setenv('POKEMON_DB_ENV', 'production')
    monkeypatch.setenv('POKEMON_DB_REQUIRE_API_KEY', '1')
    monkeypatch.setenv('POKEMON_DB_SIGNED_URL_SECRET', 'x' * 32)

    settings = settings_from_env()

    assert settings.db == db.resolve()
    assert settings.db_source == 'env'
    assert settings.runtime_env == 'production'
    assert settings.require_api_key is True
