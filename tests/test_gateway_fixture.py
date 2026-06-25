#!/usr/bin/env python3
"""
Test gateway fixture — v9.1 refactored.

Architecture change (v9.1):
  Previously this fixture used fragile source-patching.  Now it:
  1. Builds a temporary SQLite database with known seed data
  2. Constructs a PokemonDBSettings pointing to that DB, with test image_root
     and signed_url_secret
  3. Calls create_app(settings) directly — no env-var pollution needed
  4. Overrides the get_settings dependency via app.dependency_overrides
  5. Helper functions accept settings parameters, so env vars are only a fallback
  6. Yields a TestClient + fixture_data with image IDs and bytes
  7. Cleans up dependency overrides and temp files afterwards

  The module-scoped fixture `gw` provides the same contract that
  test_signed_urls.py and similar test files expect.

Key wins:
  - Zero source-patching (no setattr, no mock.patch, no importlib)
  - Tests can use any database path / image root / secret without env vars
  - ensure_search_support is skipped via settings.skip_search_setup=True
  - FTS rebuild never runs during test collection
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pokemon_db_v2_fastapi import create_app
from pokemon_db_v3_config import PokemonDBSettings

SECRET="gateway-test-secret-" + ("a" * 48)
READER_KEY = "test-reader-key"

DETAIL_COLUMNS = [
    "language_code", "language_name", "card_id", "raw_set_id", "resolved_set_id",
    "core_set_id", "core_set_name", "local_id", "local_id_sort", "card_name",
    "resolved_set_name", "resolved_series_name", "resolved_release_date",
    "category", "hp", "types", "rarity", "stage", "illustrator",
    "regulation_mark", "variants", "legal", "exact_image_url", "display_image_url",
    "local_display_image_url", "local_display_image_cache_profile",
    "local_display_image_bytes", "display_image_source_type", "display_image_source_language_code",
    "has_exact_image", "has_display_image", "attacks", "weaknesses", "resistances",
    "retreat", "description", "provenance_record_count", "legacy_provenance_count",
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _create_detail_cache(cur):
    column_defs = []
    integer_cols = {
        "local_display_image_bytes", "has_exact_image", "has_display_image",
        "provenance_record_count", "legacy_provenance_count",
    }
    for name in DETAIL_COLUMNS:
        column_type = "INTEGER" if name in integer_cols else "TEXT"
        column_defs.append(f"{name} {column_type}")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS v2_card_detail_api_cache ("
        + ", ".join(column_defs)
        + ", PRIMARY KEY(language_code, card_id))"
    )


def _insert_card(cur, *, card_id, name, filename, set_id="base1"):
    values = {column: "" for column in DETAIL_COLUMNS}
    values.update({
        "language_code": "en",
        "language_name": "English",
        "card_id": card_id,
        "raw_set_id": set_id,
        "resolved_set_id": set_id,
        "core_set_id": set_id,
        "core_set_name": "Base Set",
        "local_id": card_id.rsplit("-", 1)[-1],
        "local_id_sort": "1",
        "card_name": name,
        "resolved_set_name": "Base Set",
        "resolved_series_name": "Base",
        "resolved_release_date": "1999-01-09",
        "category": "Pokemon",
        "hp": "60",
        "types": json.dumps(["Colorless"]),
        "rarity": "Common",
        "variants": json.dumps({}),
        "legal": json.dumps({}),
        "exact_image_url": filename,
        "display_image_url": filename,
        "local_display_image_url": filename,
        "local_display_image_cache_profile": "test",
        "local_display_image_bytes": len(filename),
        "display_image_source_type": "tcgplayer",
        "display_image_source_language_code": "en",
        "has_exact_image": 1,
        "has_display_image": 1,
        "attacks": json.dumps([]),
        "weaknesses": json.dumps([]),
        "resistances": json.dumps([]),
        "retreat": json.dumps([]),
        "description": "",
        "provenance_record_count": 1,
        "legacy_provenance_count": 0,
    })
    placeholders = ", ".join("?" for _ in DETAIL_COLUMNS)
    cur.execute(
        f"INSERT OR REPLACE INTO v2_card_detail_api_cache ({', '.join(DETAIL_COLUMNS)}) VALUES ({placeholders})",
        [values[column] for column in DETAIL_COLUMNS],
    )
    cur.execute(
        "INSERT OR REPLACE INTO v2_card_search(language_code, card_id, card_name, name_english) VALUES (?, ?, ?, ?)",
        ("en", card_id, name, name),
    )
    cur.execute(
        "INSERT OR REPLACE INTO v2_card_search_fts(language_code, card_id, card_name, name_english) VALUES (?, ?, ?, ?)",
        ("en", card_id, name, name),
    )
    cur.execute(
        "INSERT OR REPLACE INTO v2_card_detail(language_code, card_id, card_name) VALUES (?, ?, ?)",
        ("en", card_id, name),
    )
    cur.execute(
        "INSERT OR IGNORE INTO catalogue_image_assets "
        "(card_key, set_id, language_code, source_type, source_language_code, local_path) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (f"en:{card_id}", set_id, "en", "tcgplayer", "en", filename),
    )


def _seed_database(db_path: Path, image_root: Path):
    """Create and seed a temporary SQLite database for gateway tests.

    Every table is created exactly once.  Schema assertions are run
    after all tables are created to catch mismatches early.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── Core card search tables ──────────────────────────────────────────
    cur.execute("CREATE TABLE IF NOT EXISTS cards(id TEXT, language_code TEXT, set_id TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sets(set_id TEXT PRIMARY KEY, language_code TEXT, name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS languages(code TEXT PRIMARY KEY, name TEXT, set_count INTEGER, card_count INTEGER)")
    cur.execute("INSERT OR REPLACE INTO languages(code, name, set_count, card_count) VALUES ('en', 'English', 1, 2)")
    cur.execute("INSERT OR REPLACE INTO sets(set_id, language_code, name) VALUES ('base1', 'en', 'Base Set')")

    cur.execute("CREATE TABLE IF NOT EXISTS v2_card_search(language_code TEXT, card_id TEXT, card_name TEXT, name_english TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS v2_card_search_fts(language_code TEXT, card_id TEXT, card_name TEXT, name_english TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS v2_card_detail(language_code TEXT, card_id TEXT, card_name TEXT)")
    _create_detail_cache(cur)

    # ── Price tables (required by startup code even when skip_search_setup) ─
    cur.execute("CREATE TABLE IF NOT EXISTS uk_price_fetch_cache(cache_key TEXT PRIMARY KEY, query TEXT, language_code TEXT, card_id TEXT, response_json TEXT, fetched_at TEXT, source TEXT, algorithm_version TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS uk_price_history(id INTEGER PRIMARY KEY, card_id TEXT, language_code TEXT, condition TEXT, price_gbp REAL, sold_date TEXT, listing_url TEXT, source TEXT, imported_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS uk_price_fetch_usage(id INTEGER PRIMARY KEY, query TEXT, language_code TEXT, card_id TEXT, status TEXT, requested_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS uk_price_scrape_failures(id INTEGER PRIMARY KEY, card_id TEXT, language_code TEXT, query TEXT, reason TEXT, raw_title TEXT, listing_url TEXT, imported_at TEXT)")

    # ── Schema migrations ────────────────────────────────────────────────
    cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations(id INTEGER PRIMARY KEY, version TEXT NOT NULL UNIQUE, applied_at TEXT DEFAULT CURRENT_TIMESTAMP, description TEXT)")

    # ── Catalogue image assets (stable PK, not rowid) ──────────────────
    cur.execute(
        "CREATE TABLE IF NOT EXISTS catalogue_image_assets("
        "image_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "card_key TEXT NOT NULL, set_id TEXT, language_code TEXT NOT NULL, "
        "source_type TEXT NOT NULL, source_language_code TEXT, local_path TEXT NOT NULL, "
        "source_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(card_key, source_type, local_path))"
    )

    # ── Image delivery policy tables ─────────────────────────────────────
    cur.execute(
        "CREATE TABLE IF NOT EXISTS image_delivery_policies("
        "policy_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "scope_type TEXT NOT NULL, scope_value TEXT NOT NULL, "
        "external_display_enabled INTEGER NOT NULL, reason TEXT, attribution_text TEXT, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(scope_type, scope_value))"
    )
    cur.execute(
        "INSERT OR REPLACE INTO image_delivery_policies"
        "(scope_type, scope_value, external_display_enabled, reason) "
        "VALUES ('global', 'global', 1, 'test-default-enable')"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS image_delivery_policy_records("
        "record_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "image_id INTEGER, card_key TEXT, tenant_id INTEGER, api_key_id INTEGER, "
        "requested_size TEXT, policy_decision TEXT NOT NULL, "
        "response_status INTEGER NOT NULL, response_outcome TEXT NOT NULL, "
        "request_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS derivative_cache("
        "cache_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "source_image_id INTEGER, source_hash TEXT, size TEXT, "
        "cache_version INTEGER DEFAULT 1, local_path TEXT, "
        "file_bytes INTEGER DEFAULT 0, mime_type TEXT DEFAULT 'image/webp', "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS image_delivery_quotas("
        "quota_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "access_identity TEXT NOT NULL, identity_type TEXT NOT NULL, "
        "window_start TEXT NOT NULL, window_end TEXT NOT NULL, "
        "hourly_count INTEGER NOT NULL DEFAULT 0, daily_count INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(access_identity, window_start))"
    )

    # ── Real WebP images ─────────────────────────────────────────────────
    from PIL import Image
    image_a_path = image_root / "card-a.webp"
    image_b_path = image_root / "card-b.webp"
    Image.new("RGB", (600, 800), (255, 0, 0)).save(image_a_path, "WEBP")
    Image.new("RGB", (600, 800), (0, 0, 255)).save(image_b_path, "WEBP")
    with Image.open(image_a_path) as decoded_a:
        decoded_a.verify()
    with Image.open(image_b_path) as decoded_b:
        decoded_b.verify()
    img_a_bytes = image_a_path.read_bytes()
    img_b_bytes = image_b_path.read_bytes()
    assert img_a_bytes
    assert img_b_bytes
    assert img_a_bytes != img_b_bytes

    # ── Seed card data ───────────────────────────────────────────────────
    _insert_card(cur, card_id="card-a", name="Test Card A", filename="card-a.webp")
    _insert_card(cur, card_id="card-b", name="Test Card B", filename="card-b.webp")

    # ── Multi-tenancy tables ─────────────────────────────────────────────
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users("
        "user_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "tenant_id INTEGER DEFAULT 1, username TEXT, email TEXT, "
        "role TEXT DEFAULT 'viewer', is_active INTEGER DEFAULT 1, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS tenants("
        "tenant_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "tenant_name TEXT, tenant_slug TEXT UNIQUE, name TEXT, "
        "is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS tenant_memberships("
        "membership_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "tenant_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
        "role TEXT, is_active INTEGER DEFAULT 1, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO tenants(tenant_id, tenant_name, tenant_slug, name) "
        "VALUES (1, 'Default Tenant', 'default', 'Default')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO users(user_id, username, email) "
        "VALUES (1, 'test', 'test@example.com')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO tenant_memberships(membership_id, tenant_id, user_id, role) "
        "VALUES (1, 1, 1, 'owner')"
    )

    # ── API keys ─────────────────────────────────────────────────────────
    cur.execute(
        "CREATE TABLE IF NOT EXISTS developer_api_keys("
        "id INTEGER PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, label TEXT, "
        "scopes TEXT, monthly_quota INTEGER, is_active INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_used_at TEXT, "
        "membership_id INTEGER)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS api_key_scopes("
        "key_id INTEGER NOT NULL, scope TEXT NOT NULL, "
        "PRIMARY KEY(key_id, scope))"
    )
    reader_hash = hashlib.sha256(READER_KEY.encode()).hexdigest()
    reader_scopes = json.dumps(["images:read", "cards:read"])
    cur.execute(
        "INSERT OR REPLACE INTO developer_api_keys"
        "(id, key_hash, label, scopes, monthly_quota, is_active, membership_id) "
        "VALUES (1, ?, 'test-reader', ?, 100000, 1, 1)",
        (reader_hash, reader_scopes),
    )
    cur.execute("INSERT OR IGNORE INTO api_key_scopes(key_id, scope) VALUES (1, 'images:read')")
    cur.execute("INSERT OR IGNORE INTO api_key_scopes(key_id, scope) VALUES (1, 'cards:read')")

    # ── Preseed schema migrations ────────────────────────────────────────
    versions = [f"v{idx}" for idx in range(1, 55)]
    versions += [
        "v18b", "v20b", "v28b", "v29b", "v30b", "v30c", "v30d", "v30e", "v30f",
        "v31b", "v32b", "v32c", "v32d", "v32e", "v33b", "v33c", "v34b", "v34c",
        "v35b", "v36b", "v36c", "v36d", "v37b", "v44b", "v45b", "v46b", "v48b",
        "v48c", "v49b", "v49c", "v49d", "v50b", "v51b", "v51c", "v52b", "v52c",
        "v53b", "v54b",
    ]
    for version in versions:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, description) "
            "VALUES (?, 'test preseed')",
            (version,),
        )

    conn.commit()

    # ── Schema assertions ────────────────────────────────────────────
    cat_cols = _table_columns(conn, "catalogue_image_assets")
    assert "image_id" in cat_cols, f"catalogue_image_assets missing image_id: {cat_cols}"
    assert "card_key" in cat_cols, f"catalogue_image_assets missing card_key: {cat_cols}"
    assert "local_path" in cat_cols, f"catalogue_image_assets missing local_path: {cat_cols}"
    assert "source_type" in cat_cols

    pol_cols = _table_columns(conn, "image_delivery_policies")
    assert "scope_type" in pol_cols
    assert "scope_value" in pol_cols
    assert "external_display_enabled" in pol_cols

    log_cols = _table_columns(conn, "image_delivery_policy_records")
    assert "image_id" in log_cols

    quota_cols = _table_columns(conn, "image_delivery_quotas")
    assert "access_identity" in quota_cols
    assert "hourly_count" in quota_cols
    assert "daily_count" in quota_cols

    # ── Stable image identity ────────────────────────────────────────────
    row_a = cur.execute(
        "SELECT image_id FROM catalogue_image_assets WHERE card_key='en:card-a'"
    ).fetchone()
    row_b = cur.execute(
        "SELECT image_id FROM catalogue_image_assets WHERE card_key='en:card-b'"
    ).fetchone()
    conn.close()

    image_a_id = int(row_a["image_id"])
    image_b_id = int(row_b["image_id"])
    assert image_a_id > 0
    assert image_b_id > 0
    assert image_a_id != image_b_id

    return image_a_id, image_b_id, img_a_bytes, img_b_bytes


def _get_settings(db_path: Path, image_root: Path) -> PokemonDBSettings:
    """
    Build a PokemonDBSettings pointing to the test database, with
    skip_search_setup=True so that expensive FTS rebuilds never run.
    """
    return PokemonDBSettings(
        db=db_path,
        ui_dir=db_path.parent,
        image_cache_dir=None,
        reports_dir=db_path.parent / "reports",
        host="127.0.0.1",
        port=0,
        cors_origins=(),
        image_root=image_root,
        signed_url_secret=SECRET,
        skip_search_setup=True,
        require_api_key=True,
    )


@pytest.fixture(scope="module")
def gw(tmp_path_factory):
    """
    Module-scoped fixture with test DB, real WebP images, and NO source-patching.

    Builds a fresh PokemonDBSettings, calls create_app(settings),
    seeds the test database with known cards and images, and returns
    (TestClient, fixture_data) for use by test functions.

    No env vars are modified — all config is passed through the settings
    object. No module globals are patched.
    """
    temp_dir = tmp_path_factory.mktemp("test_gateway")
    db_path = temp_dir / "test.db"
    image_root = temp_dir / "images"
    image_root.mkdir()

    img_a_id, img_b_id, img_a_bytes, img_b_bytes = _seed_database(db_path, image_root)

    # Build settings pointing to the test DB
    settings = _get_settings(db_path, image_root)

    # Create app with test settings — ensure_search_support is skipped
    # because skip_search_setup=True
    app = create_app(settings)

    # Override the get_settings dependency so future endpoints that use
    # Depends(get_settings) get test settings
    from pokemon_db_v2_fastapi import get_settings
    app.dependency_overrides[get_settings] = lambda: settings

    # Use TestClient as a context manager for proper lifecycle
    with TestClient(app) as client:
        fixture_data = {
            "image_id": img_a_id,
            "img_a_id": img_a_id,
            "img_b_id": img_b_id,
            "img_a_bytes": img_a_bytes,
            "img_b_bytes": img_b_bytes,
            "image_root": str(image_root),
            "db_path": str(db_path),
            "secret": SECRET,
        }
        assert img_a_id > 0
        assert img_b_id > 0

        yield client, fixture_data

    # Cleanup dependency override
    app.dependency_overrides.pop(get_settings, None)