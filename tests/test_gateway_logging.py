#!/usr/bin/env python3
"""Gateway delivery logging tests — use isolated fixture (v9.1)."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from test_gateway_fixture import gw as _gw_fixture

HEADERS_READER = {'X-API-Key': 'test-reader-key'}
ADMIN_KEY = 'test-gw-admin-key-12345'


def _secret(fd):
    return fd["secret"]


def _count_log_entries(db_path: str) -> int:
    conn = sqlite3.connect(db_path, timeout=10)
    count = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
    conn.close()
    return count


class TestGatewayDeliveryLogging:
    """Test that gateway requests are properly logged through the real endpoint."""

    def test_successful_image_request_logged(self, _gw_fixture):
        """An image delivery request is recorded in the delivery log."""
        client, fd = _gw_fixture
        db_path = str(fd["db_path"])

        # Ensure global policy is enabled
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
        conn.close()

        resp = client.get(f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=small',
                          headers=HEADERS_READER)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"

        after = _count_log_entries(db_path)
        assert after > before, f"Expected log entry, before={before}, after={after}"

    def test_log_entry_contains_identity(self, _gw_fixture):
        """The delivery log records the correct API key identity."""
        client, fd = _gw_fixture
        db_path = str(fd["db_path"])

        # Ensure global policy is enabled
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        before = _count_log_entries(db_path)
        conn.close()

        raw_key = 'test-logging-key-unique'
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("DELETE FROM developer_api_keys WHERE label='test-logging-key-unique'")
        conn.execute("INSERT INTO developer_api_keys(key_hash, label, scopes, is_active) VALUES (?, ?, ?, 1)",
                     (key_hash, 'test-logging-key-unique', json.dumps(['images:read', 'cards:read'])))
        conn.execute("UPDATE developer_api_keys SET membership_id=(SELECT membership_id FROM tenant_memberships WHERE tenant_id=1 AND role='admin' LIMIT 1) WHERE label='test-logging-key-unique'")
        cur = conn.execute("SELECT id FROM developer_api_keys WHERE label='test-logging-key-unique'")
        key_id = cur.fetchone()[0]
        conn.commit()
        conn.close()

        resp = client.get(f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=small',
                          headers={'X-API-Key': raw_key})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

        after = _count_log_entries(db_path)
        assert after > before, "No new log entry"

        # Verify the log has correct api_key_id
        conn = sqlite3.connect(db_path, timeout=10)
        latest = conn.execute(
            "SELECT api_key_id, image_id, response_status FROM image_delivery_policy_records ORDER BY record_id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert latest is not None
        assert int(latest[0]) == key_id, f"Expected key_id={key_id}, got {latest[0]}"
        assert int(latest[1]) == fd["img_a_id"], f"Expected image_id={fd['img_a_id']}, got {latest[1]}"
        assert int(latest[2]) == 200

    def test_policy_block_recorded(self, _gw_fixture):
        """A policy-blocked request is also logged."""
        client, fd = _gw_fixture
        db_path = str(fd["db_path"])

        before = _count_log_entries(db_path)

        # Disable global policy
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=0 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        conn.close()

        resp = client.get(f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=small',
                          headers=HEADERS_READER)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"

        after = _count_log_entries(db_path)
        assert after > before, f"Expected log for blocked request, before={before}, after={after}"

        # Verify blocked status in log
        conn = sqlite3.connect(db_path, timeout=10)
        latest = conn.execute(
            "SELECT response_status, response_outcome FROM image_delivery_policy_records ORDER BY record_id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert latest is not None
        assert int(latest[0]) == 403
        assert "policy_blocked" in latest[1]

        # Restore global policy
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
        conn.commit()
        conn.close()