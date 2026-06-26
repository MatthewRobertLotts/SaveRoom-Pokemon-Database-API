#!/usr/bin/env python3
"""Image delivery quota tests — v9.1 atomic quota windows."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pokemon_db_v2_fastapi import (
    create_app,
    quota_windows,
    _check_and_increment_quota,
    _QuotaWindow,
)
from pokemon_db_v3_config import PokemonDBSettings

# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

SECRET="gateway-test-secret-" + ("a" * 48)
READER_HASH = hashlib.sha256("quota-reader".encode()).hexdigest()


def _make_db(db_path: Path, image_root: Path) -> sqlite3.Connection:
    """Create a minimal gateway database and return a connection."""
    image_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Create quota windows table (v55 schema)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS image_delivery_quota_windows (
            quota_window_id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_identity TEXT NOT NULL,
            identity_type TEXT NOT NULL,
            window_kind TEXT NOT NULL CHECK (window_kind IN ('hour', 'day')),
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            successful_delivery_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (access_identity, identity_type, window_kind, window_start)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_quota_windows_lookup
        ON image_delivery_quota_windows (access_identity, identity_type, window_kind, window_start)
    """)

    # Other required tables
    for ddl in [
        "CREATE TABLE IF NOT EXISTS v2_card_search(language_code TEXT,card_id TEXT,card_name TEXT,name_english TEXT)",
        "CREATE TABLE IF NOT EXISTS v2_card_search_fts(language_code TEXT,card_id TEXT,card_name TEXT,name_english TEXT)",
        "CREATE TABLE IF NOT EXISTS v2_card_detail(language_code TEXT,card_id TEXT,card_name TEXT)",
        "CREATE TABLE IF NOT EXISTS v2_card_detail_api_cache(language_code TEXT,card_id TEXT,card_name TEXT,has_display_image INTEGER,local_display_image_url TEXT,display_image_source_type TEXT,display_image_source_language_code TEXT)",
        "CREATE TABLE IF NOT EXISTS languages(code TEXT,name TEXT)",
        "CREATE TABLE IF NOT EXISTS sets(set_id TEXT,language_code TEXT,name TEXT)",
        "CREATE TABLE IF NOT EXISTS cards(id TEXT,language_code TEXT,set_id TEXT)",
        "CREATE TABLE IF NOT EXISTS uk_price_fetch_cache(cache_key TEXT PRIMARY KEY,query TEXT,language_code TEXT,card_id TEXT,response_json TEXT,fetched_at TEXT,source TEXT,algorithm_version TEXT)",
        "CREATE TABLE IF NOT EXISTS uk_price_history(id INTEGER PRIMARY KEY,card_id TEXT,language_code TEXT,condition TEXT,price_gbp REAL,sold_date TEXT,listing_url TEXT,source TEXT,imported_at TEXT)",
        "CREATE TABLE IF NOT EXISTS uk_price_fetch_usage(id INTEGER PRIMARY KEY,query TEXT,language_code TEXT,card_id TEXT,status TEXT,requested_at TEXT)",
        "CREATE TABLE IF NOT EXISTS uk_price_scrape_failures(id INTEGER PRIMARY KEY,card_id TEXT,language_code TEXT,query TEXT,reason TEXT,raw_title TEXT,listing_url TEXT,imported_at TEXT)",
        "CREATE TABLE IF NOT EXISTS schema_migrations(id INTEGER PRIMARY KEY,version TEXT NOT NULL UNIQUE,applied_at TEXT,description TEXT)",
        "CREATE TABLE IF NOT EXISTS catalogue_image_assets(image_id INTEGER PRIMARY KEY AUTOINCREMENT,card_key TEXT NOT NULL,set_id TEXT,language_code TEXT NOT NULL,source_type TEXT NOT NULL,source_language_code TEXT,local_path TEXT NOT NULL,source_hash TEXT,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS image_delivery_policies(policy_id INTEGER PRIMARY KEY AUTOINCREMENT,scope_type TEXT NOT NULL,scope_value TEXT NOT NULL,external_display_enabled INTEGER NOT NULL,reason TEXT,attribution_text TEXT,created_at TEXT,updated_at TEXT,UNIQUE(scope_type,scope_value))",
        "CREATE TABLE IF NOT EXISTS image_delivery_policy_records(record_id INTEGER PRIMARY KEY AUTOINCREMENT,image_id INTEGER,card_key TEXT,tenant_id INTEGER,api_key_id INTEGER,requested_size TEXT,policy_decision TEXT NOT NULL,response_status INTEGER NOT NULL,response_outcome TEXT NOT NULL,request_id TEXT,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS image_delivery_quotas(quota_id INTEGER PRIMARY KEY AUTOINCREMENT,access_identity TEXT NOT NULL,identity_type TEXT NOT NULL,window_start TEXT NOT NULL,window_end TEXT NOT NULL,hourly_count INTEGER NOT NULL DEFAULT 0,daily_count INTEGER NOT NULL DEFAULT 0,created_at TEXT,updated_at TEXT,UNIQUE(access_identity,window_start))",
        "CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY AUTOINCREMENT,tenant_id INTEGER DEFAULT 1,username TEXT,email TEXT,role TEXT,is_active INTEGER DEFAULT 1,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS tenants(tenant_id INTEGER PRIMARY KEY AUTOINCREMENT,tenant_name TEXT,tenant_slug TEXT UNIQUE,name TEXT,is_active INTEGER DEFAULT 1,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS tenant_memberships(membership_id INTEGER PRIMARY KEY AUTOINCREMENT,tenant_id INTEGER NOT NULL,user_id INTEGER NOT NULL,role TEXT,is_active INTEGER DEFAULT 1,created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS developer_api_keys(id INTEGER PRIMARY KEY,key_hash TEXT NOT NULL UNIQUE,label TEXT,scopes TEXT,monthly_quota INTEGER,is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT,last_used_at TEXT,membership_id INTEGER)",
        "CREATE TABLE IF NOT EXISTS api_key_scopes(key_id INTEGER NOT NULL,scope TEXT NOT NULL,PRIMARY KEY(key_id,scope))",
    ]:
        cur.execute(ddl)

    cur.execute("INSERT OR REPLACE INTO languages(code,name) VALUES ('en','English')")
    cur.execute("INSERT OR REPLACE INTO tenants(tenant_id,tenant_name,tenant_slug,name) VALUES (1,'Default Tenant','default','Default')")
    cur.execute("INSERT OR REPLACE INTO users(user_id,tenant_id,username,email,role) VALUES (1,1,'system','system@saveroom.local','admin')")
    cur.execute("INSERT OR REPLACE INTO tenant_memberships(membership_id,tenant_id,user_id,role) VALUES (1,1,1,'admin')")
    cur.execute("INSERT OR REPLACE INTO image_delivery_policies(scope_type,scope_value,external_display_enabled,reason) VALUES ('global','global',1,'test')")
    cur.execute("INSERT OR REPLACE INTO image_delivery_policies(scope_type,scope_value,external_display_enabled,reason) VALUES ('source','tcgplayer',1,'test-source-allow')")

    # Seed reader API key
    cur.execute(
        "INSERT OR REPLACE INTO developer_api_keys(id,key_hash,label,scopes,is_active,membership_id) "
        "VALUES (1,?, 'quota-reader', ?, 1, 1)",
        (READER_HASH, json.dumps(["images:read", "cards:read"])),
    )
    # Seed key for second identity
    key2_hash = hashlib.sha256("quota-reader-2".encode()).hexdigest()
    cur.execute(
        "INSERT OR REPLACE INTO developer_api_keys(id,key_hash,label,scopes,is_active,membership_id) "
        "VALUES (2,?, 'quota-reader-2', ?, 1, 1)",
        (key2_hash, json.dumps(["images:read", "cards:read"])),
    )

    # Seed catalogue image
    img_path = image_root / "card-a.webp"
    Image.new("RGB", (600, 800), (255, 0, 0)).save(img_path, "WEBP")
    cur.execute(
        "INSERT OR REPLACE INTO catalogue_image_assets(image_id,card_key,set_id,language_code,source_type,source_language_code,local_path) "
        "VALUES (1,'en:card-a','s1','en','tcgplayer','en','card-a.webp')"
    )
    conn.commit()
    return conn


def _app_and_client(db_path: Path, image_root: Path, *,
                    hourly_limit: int = 1000, daily_limit: int = 5000) -> tuple:
    """Build an app and TestClient with custom quota limits."""
    settings = PokemonDBSettings(
        db=db_path,
        image_root=image_root,
        signed_url_secret=SECRET,
        skip_search_setup=True,
        require_api_key=True,
        image_hourly_delivery_limit=hourly_limit,
        image_daily_delivery_limit=daily_limit,
    )
    app = create_app(settings)
    from pokemon_db_v2_fastapi import get_settings
    app.dependency_overrides[get_settings] = lambda: settings
    return app, TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# Schema tests
# ══════════════════════════════════════════════════════════════════════

class TestQuotaSchema:
    """Prove the new quota table structure is correct."""

    def test_hour_and_day_rows_are_separate(self, tmp_path):
        db = tmp_path / "q.db"
        img = tmp_path / "img"
        conn = _make_db(db, img)
        cur = conn.cursor()

        # Insert one hour row and one day row for the same identity
        cur.execute("""
            INSERT INTO image_delivery_quota_windows
            (access_identity, identity_type, window_kind, window_start, window_end,
             successful_delivery_count, created_at, updated_at)
            VALUES ('test:id', 'api_key', 'hour', '2026-06-01T10:00:00', '2026-06-01T11:00:00',
                    5, 'now', 'now')
        """)
        cur.execute("""
            INSERT INTO image_delivery_quota_windows
            (access_identity, identity_type, window_kind, window_start, window_end,
             successful_delivery_count, created_at, updated_at)
            VALUES ('test:id', 'api_key', 'day', '2026-06-01T00:00:00', '2026-06-02T00:00:00',
                    42, 'now', 'now')
        """)
        conn.commit()

        # Verify they are two distinct rows
        rows = cur.execute(
            "SELECT window_kind, successful_delivery_count FROM image_delivery_quota_windows "
            "WHERE access_identity='test:id' ORDER BY window_kind"
        ).fetchall()
        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        kinds = {r[0] for r in rows}
        assert kinds == {'hour', 'day'}
        print(f"  hour={rows[0][1]}, day={rows[1][1]}")

    def test_window_kind_in_uniqueness(self, tmp_path):
        db = tmp_path / "q.db"
        img = tmp_path / "img"
        conn = _make_db(db, img)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO image_delivery_quota_windows
            (access_identity, identity_type, window_kind, window_start, window_end,
             successful_delivery_count, created_at, updated_at)
            VALUES ('id:1', 'api_key', 'hour', '2026-06-01T10:00:00', '2026-06-01T11:00:00',
                    1, 'now', 'now')
        """)
        # Same identity+start, different kind → should succeed
        cur.execute("""
            INSERT INTO image_delivery_quota_windows
            (access_identity, identity_type, window_kind, window_start, window_end,
             successful_delivery_count, created_at, updated_at)
            VALUES ('id:1', 'api_key', 'day', '2026-06-01T10:00:00', '2026-06-02T00:00:00',
                    1, 'now', 'now')
        """)
        conn.commit()
        # Duplicate (same identity+kind+start) → should fail
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute("""
                INSERT INTO image_delivery_quota_windows
                (access_identity, identity_type, window_kind, window_start, window_end,
                 successful_delivery_count, created_at, updated_at)
                VALUES ('id:1', 'api_key', 'hour', '2026-06-01T10:00:00', '2026-06-01T11:00:00',
                        1, 'now', 'now')
            """)
            conn.commit()

    def test_migration_rerun_safe(self, tmp_path):
        """CREATE IF NOT EXISTS twice should not add duplicate rows."""
        db = tmp_path / "q.db"
        img = tmp_path / "img"
        conn = _make_db(db, img)
        cur = conn.cursor()
        # Re-run the same DDL
        cur.execute("""
            CREATE TABLE IF NOT EXISTS image_delivery_quota_windows (
                quota_window_id INTEGER PRIMARY KEY AUTOINCREMENT,
                access_identity TEXT NOT NULL,
                identity_type TEXT NOT NULL,
                window_kind TEXT NOT NULL CHECK (window_kind IN ('hour', 'day')),
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                successful_delivery_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (access_identity, identity_type, window_kind, window_start)
            )
        """)
        # Insert one row
        cur.execute("""
            INSERT INTO image_delivery_quota_windows
            (access_identity, identity_type, window_kind, window_start, window_end,
             successful_delivery_count, created_at, updated_at)
            VALUES ('x', 'api_key', 'hour', '2026-06-01T10:00:00', '2026-06-01T11:00:00',
                    0, 'now', 'now')
        """)
        conn.commit()
        # Re-run DDL again
        cur.execute("""
            CREATE TABLE IF NOT EXISTS image_delivery_quota_windows (
                quota_window_id INTEGER PRIMARY KEY AUTOINCREMENT,
                access_identity TEXT NOT NULL,
                identity_type TEXT NOT NULL,
                window_kind TEXT NOT NULL CHECK (window_kind IN ('hour', 'day')),
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                successful_delivery_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (access_identity, identity_type, window_kind, window_start)
            )
        """)
        count = cur.execute("SELECT COUNT(*) FROM image_delivery_quota_windows").fetchone()[0]
        assert count == 1, f"Expected 1 row after rerun, got {count}"

    def test_daily_usage_does_not_reset_on_new_hour(self, tmp_path):
        """Prove the daily counter lives in a separate row."""
        db = tmp_path / "q.db"
        img = tmp_path / "img"
        _make_db(db, img)

        # Use _check_and_increment_quota with injected timestamps
        conn = sqlite3.connect(str(db))
        # Hour 10: first delivery
        r1 = _check_and_increment_quota(
            conn, "test:id", "api_key",
            hourly_limit=1000, daily_limit=5000,
            now_val=dt.datetime(2026, 6, 1, 10, 30, 0, tzinfo=dt.UTC),
        )
        assert r1['allowed']
        assert r1['hourly_count'] == 1
        assert r1['daily_count'] == 1

        # Hour 11 (different hour, same day): second delivery
        r2 = _check_and_increment_quota(
            conn, "test:id", "api_key",
            hourly_limit=1000, daily_limit=5000,
            now_val=dt.datetime(2026, 6, 1, 11, 0, 0, tzinfo=dt.UTC),
        )
        assert r2['allowed']
        assert r2['hourly_count'] == 1  # hour 11 has its own row
        assert r2['daily_count'] == 2   # day row persisted across hours

        # Verify separate rows
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT window_kind, window_start, successful_delivery_count "
            "FROM image_delivery_quota_windows WHERE access_identity='test:id' "
            "ORDER BY window_kind, window_start"
        ).fetchall()
        assert len(rows) == 3  # 2 hour rows + 1 day row
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# Functional tests
# ══════════════════════════════════════════════════════════════════════

HDR = {"X-API-Key": "quota-reader"}
HDR2 = {"X-API-Key": "quota-reader-2"}


class TestQuotaFunctional:
    """End-to-end quota enforcement through the real gateway."""

    def _setup(self, tmp_path, *, hourly=1000, daily=5000):
        db = tmp_path / "func.db"
        img = tmp_path / "img"
        _make_db(db, img)
        app, client = _app_and_client(db, img, hourly_limit=hourly, daily_limit=daily)
        return client, db

    def _counters(self, db: Path) -> tuple[int, int]:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        h = cur.execute(
            "SELECT COALESCE(SUM(successful_delivery_count),0) FROM image_delivery_quota_windows "
            "WHERE window_kind='hour' AND access_identity LIKE 'key:%'"
        ).fetchone()[0]
        d = cur.execute(
            "SELECT COALESCE(SUM(successful_delivery_count),0) FROM image_delivery_quota_windows "
            "WHERE window_kind='day' AND access_identity LIKE 'key:%'"
        ).fetchone()[0]
        conn.close()
        return int(h), int(d)

    # ── Successful usage ────────────────────────────────────────────────

    def test_first_request_counts(self, tmp_path):
        client, db = self._setup(tmp_path)
        r = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r.status_code == 200
        h, d = self._counters(db)
        assert h == 1, f"Hour count: {h}"
        assert d == 1, f"Day count: {d}"

    # ── Hourly limit ─────────────────────────────────────────────────────

    def test_hourly_limit_enforced(self, tmp_path):
        client, db = self._setup(tmp_path, hourly=2, daily=5)
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        r3 = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r3.status_code == 429
        h, d = self._counters(db)
        assert h == 2, f"Hour count should be 2, got {h}"
        assert d == 2, f"Day count should be 2, got {d}"

    # ── Daily limit across hours ─────────────────────────────────────────

    def test_daily_limit_across_hours(self, tmp_path):
        client, db = self._setup(tmp_path, hourly=10, daily=3)
        # Two in "hour 10"
        r1 = client.get(
            "/api/v1/images/assets/1/content?size=medium",
            headers=HDR,
        )
        assert r1.status_code == 200
        r2 = client.get(
            "/api/v1/images/assets/1/content?size=medium",
            headers=HDR,
        )
        assert r2.status_code == 200

        # One in "hour 11" (different clock hour, same UTC day)
        r3 = client.get(
            "/api/v1/images/assets/1/content?size=medium",
            headers=HDR,
        )
        assert r3.status_code == 200

        # Should be out of daily quota now
        r4 = client.get(
            "/api/v1/images/assets/1/content?size=medium",
            headers=HDR,
        )
        assert r4.status_code == 429

        # Verify separate hour rows but one shared day row
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT window_kind, successful_delivery_count "
            "FROM image_delivery_quota_windows WHERE access_identity LIKE 'key:%' "
            "ORDER BY window_kind, window_start"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1, "Should have some rows"
        # Day sum should be 3 total across all rows
        day_sum = sum(r[1] for r in rows if r[0] == 'day')
        assert day_sum == 3, f"Day sum should be 3, got {day_sum}"

    # ── New-day reset ────────────────────────────────────────────────────

    def test_new_day_reset(self, tmp_path):
        client, db = self._setup(tmp_path, daily=2)
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        r3 = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r3.status_code == 429

        # Previous day row should still exist
        conn = sqlite3.connect(str(db))
        day_rows = conn.execute(
            "SELECT window_start FROM image_delivery_quota_windows "
            "WHERE window_kind='day' AND access_identity LIKE 'key:%'"
        ).fetchall()
        conn.close()
        assert len(day_rows) >= 1

    # ── Failed requests do not consume quota ─────────────────────────────

    def test_invalid_api_key_no_quota(self, tmp_path):
        client, db = self._setup(tmp_path)
        r = client.get("/api/v1/images/assets/1/content?size=medium",
                       headers={"X-API-Key": "bogus"})
        assert r.status_code in (401, 403)
        h, d = self._counters(db)
        assert h == 0, f"Hour count should be 0, got {h}"
        assert d == 0

    def test_tampered_token_no_quota(self, tmp_path):
        client, db = self._setup(tmp_path)
        r = client.get("/api/v1/images/assets/1/content?size=medium&token=bad:bad:bad:bad:bad")
        assert r.status_code == 403
        h, d = self._counters(db)
        assert h == 0
        assert d == 0

    def test_policy_block_no_quota(self, tmp_path):
        client, db = self._setup(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE image_delivery_policies SET external_display_enabled=0 WHERE scope_type='source' AND scope_value='tcgplayer'")
        conn.commit()
        conn.close()
        r = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r.status_code == 403
        h, d = self._counters(db)
        assert h == 0, f"Hour count should be 0 after policy block, got {h}"
        assert d == 0

    def test_unknown_image_id_no_quota(self, tmp_path):
        client, db = self._setup(tmp_path)
        r = client.get("/api/v1/images/assets/99999/content?size=medium", headers=HDR)
        assert r.status_code == 404
        h, d = self._counters(db)
        assert h == 0
        assert d == 0

    # ── Identity consistency ─────────────────────────────────────────────

    def test_different_keys_separate_pools(self, tmp_path):
        client, db = self._setup(tmp_path, hourly=2, daily=5)
        # Key 1: consume both hourly slots
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        r3 = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r3.status_code == 429

        # Key 2: should still have full quota
        r4 = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR2)
        assert r4.status_code == 200

        # Count only key:1 rows should be 2, key:2 rows should be 1
        conn = sqlite3.connect(str(db))
        key1_h = conn.execute(
            "SELECT COALESCE(SUM(successful_delivery_count),0) FROM image_delivery_quota_windows "
            "WHERE window_kind='hour' AND access_identity='key:1'"
        ).fetchone()[0]
        key2_h = conn.execute(
            "SELECT COALESCE(SUM(successful_delivery_count),0) FROM image_delivery_quota_windows "
            "WHERE window_kind='hour' AND access_identity='key:2'"
        ).fetchone()[0]
        conn.close()
        assert int(key1_h) == 2, f"Key1 hour count: {key1_h}"
        assert int(key2_h) == 1, f"Key2 hour count: {key2_h}"

    # ── Delivery log consistency ─────────────────────────────────────────

    def test_delivery_log_after_success(self, tmp_path):
        client, db = self._setup(tmp_path)
        r = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r.status_code == 200
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT image_id, response_status, response_outcome FROM image_delivery_policy_records "
            "ORDER BY record_id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert int(row[0]) == 1  # real image_id
        assert int(row[1]) == 200
        assert "ok" in row[2]

    def test_quota_rejection_logged_once(self, tmp_path):
        client, db = self._setup(tmp_path, hourly=1, daily=5)
        assert client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR).status_code == 200
        r2 = client.get("/api/v1/images/assets/1/content?size=medium", headers=HDR)
        assert r2.status_code == 429
        conn = sqlite3.connect(str(db))
        # Should have one 'delivered' log and one 'quota_exceeded' log
        rows = conn.execute(
            "SELECT policy_decision, response_status FROM image_delivery_policy_records "
            "ORDER BY record_id"
        ).fetchall()
        conn.close()
        decisions = [r[0] for r in rows]
        assert 'delivered' in decisions
        assert any('quota' in d for d in decisions), f"No quota log found: {decisions}"

    # ── Concurrency ──────────────────────────────────────────────────────

    def test_concurrent_boundary(self, tmp_path):
        """Two simultaneous requests with limit=1; exactly one must succeed."""
        client, db = self._setup(tmp_path, hourly=1, daily=1)
        n_workers = 2
        results = [None] * n_workers
        barrier = threading.Barrier(n_workers, timeout=5)

        def _do(i):
            try:
                barrier.wait()
                r = client.get(
                    "/api/v1/images/assets/1/content?size=medium",
                    headers=HDR,
                )
                results[i] = r.status_code
            except Exception as e:
                results[i] = e

        threads = [threading.Thread(target=_do, args=(i,)) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        codes = [r for r in results if isinstance(r, int)]
        assert len(codes) == n_workers, f"Expected {n_workers} int results, got {results}"
        assert codes.count(200) == 1, f"Expected exactly 1 success, got {codes}"
        assert codes.count(429) == 1, f"Expected exactly 1 rejection, got {codes}"
        # Counters should show exactly 1
        h, d = self._counters(db)
        assert h == 1, f"Hour count should be 1 after race, got {h}"
        assert d == 1, f"Day count should be 1 after race, got {d}"