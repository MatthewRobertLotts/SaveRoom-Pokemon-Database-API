#!/usr/bin/env python3
"""Management command for delivery log maintenance.

Run daily via systemd timer or cron:
  python -m pokemon_db_v2_fastapi delivery-log-cleanup

Or schedule via the built-in scheduler:
  python -m pokemon_db_v2_fastapi delivery-log-cleanup --watch
"""
import argparse
import sys
import os


def cleanup(db_path: str, retention_days: int = 30, dry_run: bool = False) -> dict:
    """Aggregate and clean up expired delivery log entries."""
    import sqlite3
    from pathlib import Path

    db = Path(db_path)
    if not db.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return {"error": "database_not_found"}

    conn = sqlite3.connect(str(db), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    from pokemon_db_v2_fastapi import _delivery_log_cleanup

    if dry_run:
        # Just count what would be cleaned
        cur = conn.cursor()
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)).strftime('%Y-%m-%d')
        cur.execute("SELECT COUNT(*) FROM image_delivery_policy_records WHERE date(created_at) < ?", (cutoff,))
        raw_count = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT date(created_at) FROM image_delivery_policy_records WHERE date(created_at) < ?", (cutoff,))
        dates = [r[0] for r in cur.fetchall()]
        conn.close()
        return {
            "dry_run": True,
            "retention_days": retention_days,
            "expired_dates": dates,
            "raw_records_to_aggregate": raw_count,
        }

    result = _delivery_log_cleanup(conn, retention_days=retention_days)
    conn.commit()
    conn.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="Delivery log maintenance")
    parser.add_argument("command", choices=["delivery-log-cleanup"], help="Command to run")
    parser.add_argument("--db", default=None, help="Database path (default: from POKEMON_DB_DB env or default)")
    parser.add_argument("--retention-days", type=int, default=30, help="Retention period in days (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned without making changes")
    args = parser.parse_args()

    db_path = args.db or os.environ.get("POKEMON_DB_DB", "full_tcgdex/pokemon_tcg_set_knowledge_base.sqlite")

    if args.command == "delivery-log-cleanup":
        result = cleanup(db_path, args.retention_days, args.dry_run)
        if "error" in result:
            print(f"Error: {result['error']}", file=sys.stderr)
            sys.exit(1)

        if result.get("dry_run"):
            print(f"Dry run: {result['raw_records_to_aggregate']} raw records would be aggregated")
            print(f"Expired dates: {result['expired_dates']}")
        else:
            print(f"Aggregated: {result['rows_aggregated']} date-groups")
            print(f"Deleted: {result['rows_deleted']} raw records")
            print(f"Retention: {result['retention_days']} days")


if __name__ == "__main__":
    main()
