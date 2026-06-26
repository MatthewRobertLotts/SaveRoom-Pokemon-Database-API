#!/usr/bin/env python3
"""Signed URL tests — isolated gateway fixture (v9.1)."""
import hashlib, hmac, io, json, os, sqlite3, time, tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image

# Re-use the module-scoped gateway fixture
from test_gateway_fixture import gw as _gw_fixture

H = {"X-API-Key": "test-reader-key"}


def _assert_image_response(actual: bytes, expected_size: tuple[int, int]) -> None:
    """Validate that the response is a valid WebP image.

    The derivative pipeline preserves aspect ratio, so the output height
    may be smaller than the target. We verify the width matches exactly
    and height is within tolerance.
    """
    img = Image.open(io.BytesIO(actual))
    img.verify()
    img = Image.open(io.BytesIO(actual))
    assert img.format == 'WEBP', f'Expected WEBP, got {img.format}'
    w, h = img.size
    assert w == expected_size[0], f'Width mismatch: got {w}, expected {expected_size[0]}'
    assert abs(h - expected_size[1]) <= 30, f'Height mismatch: got {h}, expected {expected_size[1]}'

def _secret(fd):
    """Return the gateway fixture's signed URL secret."""
    return fd["secret"]


def _token(secret, image_id, size="medium", api_key_id=None, expires_in=3600):
    from pokemon_db_v2_fastapi import _generate_signed_url
    t, _ = _generate_signed_url(image_id, size, secret, expires_in=expires_in, api_key_id=api_key_id)
    return t


def test_fixture_creates_data(_gw_fixture):
    """The fixture provides valid gateway test data."""
    client, fd = _gw_fixture
    assert fd["img_a_id"] > 0
    assert fd["img_b_id"] > 0
    assert len(fd["img_a_bytes"]) > 0
    assert len(fd["img_b_bytes"]) > 0
    assert fd["img_a_id"] != fd["img_b_id"]


def test_image_a_api_key_200(_gw_fixture):
    """API key request for image A returns 200 with correct bytes."""
    client, fd = _gw_fixture
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:200]}"
    assert resp.headers["content-type"] == "image/webp"
    _assert_image_response(resp.content, (350, 489))


def test_image_b_api_key_200(_gw_fixture):
    """API key request for image B returns 200 with correct bytes."""
    client, fd = _gw_fixture
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_b_id"]}/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 200
    _assert_image_response(resp.content, (350, 489))


def test_image_id_zero_404(_gw_fixture):
    """image_id=0 is rejected."""
    client, fd = _gw_fixture
    resp = client.get(
        '/api/v1/images/assets/0/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 404


def test_image_id_negative_404(_gw_fixture):
    """Negative image_id is rejected."""
    client, fd = _gw_fixture
    resp = client.get(
        '/api/v1/images/assets/-1/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 404


def test_unknown_image_id_404(_gw_fixture):
    """Unknown positive image_id returns 404."""
    client, fd = _gw_fixture
    resp = client.get(
        '/api/v1/images/assets/99999/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 404


def test_signed_url_image_a_200(_gw_fixture):
    """Signed URL for image A returns 200 with correct bytes, no API key header."""
    client, fd = _gw_fixture
    t = _token(_secret(fd), fd["img_a_id"])
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium&token={t}',
    )
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:200]}"
    _assert_image_response(resp.content, (350, 489))


def test_token_image_a_for_b_403(_gw_fixture):
    """Token for image A cannot request image B."""
    client, fd = _gw_fixture
    t = _token(_secret(fd), fd["img_a_id"])
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_b_id"]}/content?size=medium&token={t}',
    )
    assert resp.status_code == 403


def test_tampered_sig_403(_gw_fixture):
    """Tampered signature rejected."""
    client, fd = _gw_fixture
    t = _token(_secret(fd), fd["img_a_id"])
    p = t.split(":")
    p[1] = "deadbeef" * 8
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium&token={":".join(p)}',
    )
    assert resp.status_code == 403


def test_tampered_image_id_403(_gw_fixture):
    """Tampered image_id in token rejected."""
    client, fd = _gw_fixture
    t = _token(_secret(fd), fd["img_a_id"])
    p = t.split(":")
    p[2] = str(fd["img_b_id"])
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium&token={":".join(p)}',
    )
    assert resp.status_code == 403


def test_tampered_expiry_403(_gw_fixture):
    """Tampered expiry rejected."""
    client, fd = _gw_fixture
    t = _token(_secret(fd), fd["img_a_id"])
    p = t.split(":")
    p[0] = str(int(time.time()) + 999999)
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium&token={":".join(p)}',
    )
    assert resp.status_code == 403


def test_expired_token_403(_gw_fixture):
    """Expired token rejected."""
    client, fd = _gw_fixture
    t = _token(_secret(fd), fd["img_a_id"], expires_in=1)
    time.sleep(2)
    resp = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium&token={t}',
    )
    assert resp.status_code == 403


def test_global_disable_blocks(_gw_fixture):
    """Global disable blocks image access."""
    client, fd = _gw_fixture
    # Prove it works first
    r1 = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert r1.status_code == 200

    # Disable global
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    conn.execute("UPDATE image_delivery_policies SET external_display_enabled=0 WHERE scope_type='global' AND scope_value='global'")
    conn.commit()
    conn.close()

    r2 = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert r2.status_code == 403

    # Restore
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
    conn.commit()
    conn.close()

    r3 = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert r3.status_code == 200


def test_card_level_disable_blocks(_gw_fixture):
    """Card-level disable overrides global enable."""
    client, fd = _gw_fixture
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    conn.execute("INSERT OR REPLACE INTO image_delivery_policies(scope_type,scope_value,external_display_enabled,reason,created_at,updated_at) VALUES ('card','en:card-a',0,'test',datetime('now'),datetime('now'))")
    conn.commit()
    conn.close()

    r = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert r.status_code == 403

    # Image B still works
    r2 = client.get(
        f'/api/v1/images/assets/{fd["img_b_id"]}/content?size=medium',
        headers=H,
    )
    assert r2.status_code == 200

    # Restore
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    conn.execute("DELETE FROM image_delivery_policies WHERE scope_type='card' AND scope_value='en:card-a'")
    conn.commit()
    conn.close()


def test_image_level_disable_blocks(_gw_fixture):
    """Image-level disable overrides everything."""
    client, fd = _gw_fixture
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    conn.execute("INSERT OR REPLACE INTO image_delivery_policies(scope_type,scope_value,external_display_enabled,reason,created_at,updated_at) VALUES ('image',?,0,'test',datetime('now'),datetime('now'))", (str(fd["img_a_id"]),))
    conn.commit()
    conn.close()

    r = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert r.status_code == 403

    # Restore
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    conn.execute("DELETE FROM image_delivery_policies WHERE scope_type='image' AND scope_value=?", (str(fd["img_a_id"]),))
    conn.commit()
    conn.close()


def test_delivery_log_recorded(_gw_fixture):
    """Successful delivery creates a log entry."""
    client, fd = _gw_fixture
    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    before = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
    conn.close()

    r = client.get(
        f'/api/v1/images/assets/{fd["img_a_id"]}/content?size=medium',
        headers=H,
    )
    assert r.status_code == 200

    conn = sqlite3.connect(str(fd["db_path"]), timeout=10)
    after = conn.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
    rec = conn.execute(
        "SELECT image_id, card_key, response_status, response_outcome FROM image_delivery_policy_records ORDER BY record_id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert after > before
    assert rec[0] == fd["img_a_id"]  # real image_id recorded
    assert rec[2] == 200
    assert "ok" in rec[3]


def test_token_format(_gw_fixture):
    """Token has expected 5-part format with real image_id."""
    from pokemon_db_v2_fastapi import _generate_signed_url
    client, fd = _gw_fixture
    secret = _secret(fd)
    t, exp = _generate_signed_url(fd["img_a_id"], "medium", secret, expires_in=3600)
    p = t.split(":")
    assert len(p) == 5
    assert int(p[0]) > 0  # expires
    assert len(p[1]) == 64  # full HMAC
    assert int(p[2]) == fd["img_a_id"]  # real image_id
    assert p[3] == "medium"
    assert p[4] == "0"  # kid when no api_key


def test_signing_rejects_nonexistent_image(_gw_fixture):
    """Signing a nonexistent image_id fails."""
    client, fd = _gw_fixture
    resp = client.post(
        '/api/v1/images/assets/signed-url?image_id=99999&size=medium',
        headers=H,
    )
    assert resp.status_code == 404


def test_card_compatibility_route(_gw_fixture):
    """The card content route resolves and delivers the real image."""
    client, fd = _gw_fixture
    resp = client.get(
        '/api/v1/images/card/en:card-a/content?size=medium',
        headers=H,
    )
    assert resp.status_code == 200
    _assert_image_response(resp.content, (350, 489))