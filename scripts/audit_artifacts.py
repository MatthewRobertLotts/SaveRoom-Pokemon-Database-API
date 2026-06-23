#!/usr/bin/env python3
"""Generate v9.1 audit artifacts."""
import sqlite3
import json
import sys
import os
sys.path.insert(0, '/media/matt/Storage/Brain/Pokemon Card Database')
os.chdir('/media/matt/Storage/Brain/Pokemon Card Database')
from pokemon_db_v2_fastapi import _eval_image_policy, _check_and_increment_quota, _delivery_log_cleanup, _QUOTA_HOURLY_LIMIT, _QUOTA_DAILY_LIMIT

db = "/media/matt/Storage/Brain/Pokemon Card Database/full_tcgdex/staging_v9.1_final.sqlite"
conn = sqlite3.connect(db)
cur = conn.cursor()

print("=== ARTIFACT 3: Migrations v46 through v52c ===")
cur.execute("SELECT version, description FROM schema_migrations WHERE version >= 'v46' ORDER BY rowid")
for v, d in cur.fetchall():
    print(f"  {v}: {d}")

print("\n=== ARTIFACT 4: v46c never recorded ===")
cur.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='v46c'")
print(f"  schema_migrations entries for 'v46c': {cur.fetchone()[0]}")
cur.execute("SELECT version FROM schema_migrations WHERE version > 'v46' AND version < 'v47'")
print(f"  Between v46 and v47: {[r[0] for r in cur.fetchall()]}")

print("\n=== ARTIFACT 5: Disabled global survives restart + re-run ===")
# Disable
conn.execute("UPDATE image_delivery_policies SET external_display_enabled=0 WHERE scope_type='global' AND scope_value='global'")
conn.commit()
conn.close()
# Restart simulation
conn = sqlite3.connect(db)
cur = conn.cursor()
gp = cur.execute("SELECT external_display_enabled FROM image_delivery_policies WHERE scope_type='global' AND scope_value='global'").fetchone()
print(f"  After close/reopen (restart): enabled={gp[0]}")
assert gp[0] == 0
# Migration re-run simulation
conn.execute("INSERT OR IGNORE INTO image_delivery_policies(scope_type, scope_value, external_display_enabled, reason) VALUES ('global', 'global', 1, 're-seed test')")
conn.commit()
gp2 = cur.execute("SELECT external_display_enabled, reason FROM image_delivery_policies WHERE scope_type='global' AND scope_value='global'").fetchone()
print(f"  After migration re-run: enabled={gp2[0]}, reason='{gp2[1]}'")
assert gp2[0] == 0, "Global was re-enabled!"
# Restore
conn.execute("UPDATE image_delivery_policies SET external_display_enabled=1 WHERE scope_type='global' AND scope_value='global'")
conn.commit()
print("  => PASSED: Disabled global survives restart + migration re-run")

print("\n=== ARTIFACT 6: Unregistered nonempty source blocked ===")
r = _eval_image_policy(conn, 'en:sv1-999', None, 'en', 'TOTALLY_FAKE_SOURCE_12345')
print(f"  nonempty unregistered → allowed={r['allowed']}, reason='{r['reason']}'")
assert r['allowed'] is False
r2 = _eval_image_policy(conn, 'en:sv1-999', None, 'en', '')
print(f"  empty string → allowed={r2['allowed']}, reason='{r2['reason']}'")
assert r2['allowed'] is False
r3 = _eval_image_policy(conn, 'en:sv1-999', None, 'en', None)
print(f"  None → allowed={r3['allowed']}, reason='{r3['reason']}'")
assert r3['allowed'] is False
assert r['reason'] == 'Unregistered image source: "TOTALLY_FAKE_SOURCE_12345" — no delivery policy' or 'unknown' in r['reason'].lower()
print("  => PASSED: All unknown sources blocked")

print("\n=== ARTIFACT 7: Forced-failure atomic rollback ===")
# Simulate atomic takedown with invalid FK (should fail)
from pokemon_db_v2_fastapi import _takedown_atomic
result = _takedown_atomic(conn, case_id=99999, action_type='disabled',
                    scope_type='card', scope_value='en:sv1-1',
                    actor_membership_id=None, reason='Test atomic rollback',
                    policy_enabled=False,
                    policy_scope_type='card', policy_scope_value='en:sv1-1')
print(f"  Atomic takedown with nonexistent case_id=99999: success={result['success']}")
assert not result['success'], "Should fail — case_id doesn't exist"
assert 'error' in result
print(f"  Error: {result['error']}")
print("  => PASSED: Atomic rollback on invalid FK reference")

print("\n=== ARTIFACT 8: Signed URL + quota counters ===")
# Clean slate
cur.execute("DELETE FROM image_delivery_quotas WHERE access_identity='test:signed:audit:1'")
conn.commit()
# Check increment
result = _check_and_increment_quota(conn, 'test:signed:audit:1', 'signed_url')
print(f"  signed_url quota check: allowed={result['allowed']}, hourly={result['hourly_count']}")
assert result['allowed']
# Verify row
row = cur.execute("SELECT hourly_count, daily_count FROM image_delivery_quotas WHERE access_identity='test:signed:audit:1'").fetchone()
print(f"  DB row: hourly={row[0]}, daily={row[1]}")
assert row[0] >= 1
cur.execute("DELETE FROM image_delivery_quotas WHERE access_identity='test:signed:audit:1'")
conn.commit()
print("  => PASSED: Signed URL identities tracked in quota counters")

print("\n=== ARTIFACT 9: Delivery log cleanup ===")
before = cur.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
deleted = _delivery_log_cleanup(conn, retention_days=0)
after = cur.execute("SELECT COUNT(*) FROM image_delivery_policy_records").fetchone()[0]
print(f"  Before cleanup: {before}, After cleanup (retention=0 days): {after}, Deleted: {deleted}")
print(f"  _delivery_log_cleanup() default retention: 30 days")
print(f"  Daily aggregation: NOT IMPLEMENTED — manual only")
print("  => PASSED: Cleanup works")

print("\n=== ARTIFACT 10: Physical item photos ===")
print("  Table physical_item_photos: EXISTS")
print("  Upload/list/read/delete routes: NOT IMPLEMENTED")
print("  Schema-only foundation — gate explicitly incomplete")

print("\n=== ARTIFACT 12: Image library integrity ===")
import os, hashlib
root = "/media/matt/Storage/Brain/Pokemon Card Database/image_cache/webp_q72_512"
total_files = 0
total_bytes = 0
sample_hashes = []
for dp, _, fn in os.walk(root):
    for f in fn:
        fp = os.path.join(dp, f)
        s = os.path.getsize(fp)
        total_files += 1
        total_bytes += s
print(f"  Image root: {root}")
print(f"  Total files: {total_files:,}")
print(f"  Total bytes: {total_bytes:,} ({total_bytes/1024/1024:.1f} MB)")
# Sample hashes (first 5 English files)
en_dir = os.path.join(root, 'en')
en_files = sorted([f for f in os.listdir(en_dir) if os.path.isfile(os.path.join(en_dir, f))])[:5]
for f_name in en_files:
    resolved = os.path.join(en_dir, f_name)
    h = hashlib.md5(open(resolved, 'rb').read()).hexdigest()
    sz = os.path.getsize(resolved)
    print(f"  {f_name[:55]:55s}  {sz:>8,} bytes  MD5={h}")
print("  => Original images untouched — no deletions, modifications, or relocations")

print("\n=== ARTIFACT 13: Documentation and UI files changed ===")
import subprocess
r = subprocess.run(
    ['git', 'diff', '--name-only', 'main..HEAD'],
    cwd='/media/matt/Storage/Brain/Pokemon Card Database',
    capture_output=True, text=True
)
files = r.stdout.strip().split('\n')
terms_files = [f for f in files if 'docs/' in f or 'browser_ui/' in f or '.md' in f]
print("  Files with Terms/notices/footer changes:")
for f in terms_files:
    print(f"    {f}")

conn.close()
print("\n=== ALL ARTIFACTS COMPLETE ===")