#!/usr/bin/env python3
"""Delivery log aggregation and cleanup CLI.

Usage:
    python scripts/delivery_log_cleanup.py [--retention-days 30] [--dry-run]

Designed for systemd timer, cron, or manual maintenance invocation.
Aggregates raw delivery log entries into daily summaries before deleting
expired raw records. Failed aggregation preserves raw records.
"""
import argparse
import os
import sys
import sqlite3
import datetime as dt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)


def main():
    parser = argparse.ArgumentParser(description='Aggregate and cleanup delivery logs')
    parser.add_argument('command', nargs='?', default='cleanup',
                        choices=['cleanup', 'dry-run'],
                        help='Command: cleanup or dry-run')
    parser.add_argument('--retention-days', type=int, default=30,
                        help='Days to retain raw delivery log entries (default: 30)')
    parser.add_argument('--db', type=str, default=None,
                        help='SQLite database path (default: from POKEMON_DB_DB env or config)')
    args = parser.parse_args()

    db_path = args.db or os.environ.get('POKEMON_DB_DB')
    if not db_path:
        from pokemon_db_v3_config import settings_from_env
        db_path = str(settings_from_env().db)

    if not os.path.exists(db_path):
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    # Import after path setup
    from pokemon_db_v2_fastapi import _delivery_log_cleanup

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    if args.command == 'dry-run':
        cur = conn.cursor()
        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=args.retention_days)).strftime('%Y-%m-%d')
        cur.execute(
            "SELECT DISTINCT date(created_at) FROM image_delivery_policy_records WHERE date(created_at) < ? ORDER BY date(created_at)",
            (cutoff,)
        )
        dates = [r[0] for r in cur.fetchall()]
        if dates:
            print(f"Dry run: Would aggregate and cleanup {len(dates)} date(s): {', '.join(dates)}")
        else:
            print("Dry run: No expired records to aggregate")
        conn.close()
        return

    result = _delivery_log_cleanup(conn, retention_days=args.retention_days)
    print(f"Aggregation complete: {result['rows_aggregated']} rows aggregated, "
          f"{result['rows_deleted']} raw rows deleted (retention: {result['retention_days']} days)")
    conn.close()


if __name__ == '__main__':
    main()
