#!/usr/bin/env python3
"""Signing secret policy tests.

This replaces an ignored scratch test that had a syntax error. The behavior is
commercially important: production must not silently mint browser image URLs
with a missing or placeholder signing secret, while development may still use a
clearly ephemeral local secret.
"""
from __future__ import annotations

import re

import pytest

from pokemon_db_v2_fastapi import _get_signed_url_secret


def test_production_missing_signed_url_secret_rejected(monkeypatch):
    monkeypatch.setenv('POKEMON_DB_ENV', 'production')
    monkeypatch.delenv('POKEMON_DB_SIGNED_URL_SECRET', raising=False)

    with pytest.raises(RuntimeError, match='POKEMON_DB_SIGNED_URL_SECRET must be set'):
        _get_signed_url_secret()


def test_production_short_signed_url_secret_rejected(monkeypatch):
    monkeypatch.setenv('POKEMON_DB_ENV', 'production')
    monkeypatch.setenv('POKEMON_DB_SIGNED_URL_SECRET', 'too-short')

    with pytest.raises(RuntimeError, match='too short'):
        _get_signed_url_secret()


def test_development_missing_signed_url_secret_uses_ephemeral(monkeypatch):
    monkeypatch.setenv('POKEMON_DB_ENV', 'development')
    monkeypatch.delenv('POKEMON_DB_SIGNED_URL_SECRET', raising=False)

    secret = _get_signed_url_secret()

    assert len(secret) == 64
    assert re.fullmatch(r'[0-9a-f]{64}', secret)


def test_explicit_custom_secret_wins(monkeypatch):
    monkeypatch.setenv('POKEMON_DB_ENV', 'production')
    monkeypatch.delenv('POKEMON_DB_SIGNED_URL_SECRET', raising=False)

    assert _get_signed_url_secret('x' * 32) == 'x' * 32
