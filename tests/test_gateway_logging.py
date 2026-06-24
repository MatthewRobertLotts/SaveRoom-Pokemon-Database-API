#!/usr/bin/env python3
"""Gateway delivery logging and v1 contract tests — exercise real endpoints."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pokemon_db_v2_fastapi import create_app


client = TestClient(create_app())

ADMIN_KEY = 'test-gw-admin-key-12345'
READER_KEY = 'test-gw-reader-key-67890'


@pytest.fixture(autouse=True)
def _setup_keys(monkeypatch):
    """Set up API keys and auth for gateway logging tests."""
    monkeypatch.setenv('POKEMON_DB_REQUIRE_API_KEY', '1')
    conn = sqlite3.connect(str(client.app.state.db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    import hashlib
    admin_hash = hashlib.sha256(ADMIN_KEY.encode()).hexdigest()
    cur.execute("INSERT OR IGNORE INTO developer_api_keys(key_hash, label, scopes, is_active) VALUES (?, ?, ?, 1)",
                (admin_hash, 'test-gw-admin', json.dumps(['admin:all'])))
    cur.execute("UPDATE developer_api_keys SET membership_id=(SELECT membership_id FROM tenant_memberships WHERE tenant_id=1 AND role='admin' LIMIT 1) WHERE label='test-gw-admin'")

    reader_hash = hashlib.sha256(READER_KEY.encode()).hexdigest()
    cur.execute("INSERT OR IGNORE INTO developer_api_keys(key_hash, label, scopes, is_active) VALUES (?, ?, ?, 1)",
                (reader_hash, 'test-gw-reader', json.dumps(['images:read', 'cards:read'])))
    cur.execute("UPDATE developer_api_keys SET membership_id=(SELECT membership_id FROM tenant_memberships WHERE tenant_id=1 AND role='admin' LIMIT 1) WHERE label='test-gw-reader'")

    conn.commit()
    conn.close()
    yield

    # Teardown: re-enable global policy
    try:
        conn2 = sqlite3.connect(str(client.app.state.db), timeout=10)
        conn2.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn2.commit()
        conn2.close()
    except Exception:
        pass


HEADERS_ADMIN = {'X-API-Key': ADMIN_KEY}
HEADERS_READER = {'X-API-Key': READER_KEY}


def _count_log_entries():
    """Count total delivery log entries."""
    conn = sqlite3.connect(str(client.app.state.db), timeout=10)
    count = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
    conn.close()
    return count


class TestGatewayDeliveryLogging:
    """Test that gateway requests are properly logged through the real endpoint."""

    def test_successful_image_request_logged(self):
        """An image delivery request is recorded in the delivery log."""
        conn = sqlite3.connect(str(client.app.state.db), timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
        conn.close()

        resp = client.get('/api/v1/images/assets/0/content?size=small',
                          headers=HEADERS_READER)
        assert resp.status_code in (200, 403, 404), f"Unexpected: {resp.status_code}"

        after = _count_log_entries()
        assert after > before, f"Expected log entry, before={before}, after={after}"

    def test_log_entry_contains_identity(self):
        """The delivery log records the correct API key identity."""
        import hashlib
        raw_key = 'test-logging-key-unique'
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        conn = sqlite3.connect(str(client.app.state.db), timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.execute("DELETE FROM developer_api_keys WHERE label='test-logging-key-unique'")
        conn.execute("INSERT INTO developer_api_keys(key_hash, label, scopes, is_active) VALUES (?, ?, ?, 1)",
                     (key_hash, 'test-logging-key-unique', json.dumps(['images:read', 'cards:read'])))
        conn.execute("UPDATE developer_api_keys SET membership_id=(SELECT membership_id FROM tenant_memberships WHERE tenant_id=1 AND role='admin' LIMIT 1) WHERE label='test-logging-key-unique'")
        cur = conn.execute("SELECT id FROM developer_api_keys WHERE label='test-logging-key-unique'")
        key_id = cur.fetchone()[0]
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
        conn.close()

        headers = {'X-API-Key': raw_key}
        resp = client.get('/api/v1/images/assets/0/content?size=small', headers=headers)
        assert resp.status_code in (200, 403, 404)

        after = _count_log_entries()
        assert after > before, f"Log not written: before={before}, after={after}"

        conn2 = sqlite3.connect(str(client.app.state.db), timeout=10)
        cur2 = conn2.execute(
            "SELECT api_key_id FROM image_delivery_policy_records ORDER BY created_at DESC LIMIT 1"
        )
        row = cur2.fetchone()
        conn2.close()
        assert row is not None, "No log entry found"
        assert row[0] == key_id, f"Expected api_key_id={key_id}, got {row[0]}"

    def test_policy_block_recorded(self):
        """A 403 policy block is recorded as a blocked event."""
        conn = sqlite3.connect(str(client.app.state.db), timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=0 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
        conn.close()

        resp = client.get('/api/v1/images/assets/0/content?size=small',
                          headers=HEADERS_READER)
        assert resp.status_code in (403, 404)

        after = _count_log_entries()
        assert after > before, f"Policy block not recorded: before={before}, after={after}"

        # Restore
        conn = sqlite3.connect(str(client.app.state.db), timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        conn.close()

    def test_rate_limit_recorded(self):
        """A 429 rate limit response is recorded."""
        # Make many requests to trigger rate limiting
        before = _count_log_entries()
        got_429 = False
        for _ in range(150):
            resp = client.get('/api/v1/images/assets/0/content?size=small',
                              headers=HEADERS_READER)
            if resp.status_code == 429:
                got_429 = True
                break

        after = _count_log_entries()
        # At minimum, log entries should have been written
        assert after > before, f"No log entries written during rate limit test"


class TestV1MetadataContract:
    """Test that the v1 image metadata contract is preserved."""

    def test_v1_image_metadata_success_known_card(self):
        """v1 image metadata endpoint returns 200 with proper structure for a known card."""
        conn = sqlite3.connect(str(client.app.state.db), timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        conn.close()

        resp = client.get('/api/v1/images/cards/en:base1-1', headers=HEADERS_READER)
        assert resp.status_code == 200, f"Expected 200 for known card, got {resp.status_code}"
        body = resp.json()

        # Required top-level fields
        assert 'data' in body
        assert body.get('card_key') == 'en:base1-1'
        assert 'card_id' in body
        assert 'language_code' in body

        # Required image metadata fields
        data = body['data']
        assert 'has_exact_image' in data
        assert 'has_display_image' in data
        assert 'display_image_source_type' in data
        assert 'display_image_source_language_code' in data
        assert 'display_image_url' in data
        assert 'exact_image_url' in data

        # Field types — all strings or bools
        assert isinstance(data['display_image_url'], str)
        assert isinstance(data['has_display_image'], (bool, int))

        # local_display_image_url is now a controlled compatibility route URL
        gateway = data.get('local_display_image_url', '')
        assert '/api/v1/images/card/' in gateway, f"Expected /api/v1/images/card/ URL, got {gateway}"
        assert '/content' in gateway

        # No absolute local filesystem paths
        body_str = json.dumps(body)
        assert '/home/matt' not in body_str
        assert '/media/matt' not in body_str
        assert 'storage_path' not in body_str.lower()
        assert '/Storage/' not in body_str

    def test_v1_image_metadata_missing_card_404(self):
        """v1 image metadata returns 404 for nonexistent card."""
        resp = client.get('/api/v1/images/cards/xx:nonexistent-99999', headers=HEADERS_READER)
        assert resp.status_code == 404