#!/usr/bin/env python3
"""Delivery log aggregation and cleanup CLI.

Usage:
    python scripts/delivery_log_cleanup.py [--retention-days 30] [--dry-run]

Designed for systemd timer, cron, or manual maintenance invocation.
"""
import argparse
import os
import sys
import sqlite3
import datetime as dt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)


def _aggregate_delivery_log(conn, *, target_date=None):
    """Aggregate one day's delivery records into daily summary (inline copy)."""
    cur = conn.cursor()
    if target_date is None:
        target_date = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).strftime('%Y-%m-%d')
    rows = cur.execute(
        "SELECT COUNT(*) FROM image_delivery_policy_records WHERE date(created_at) = ?",
        (target_date,)
    ).fetchone()[0]
    if rows == 0:
        return {'rows_aggregated': 0, 'rows_deleted': 0, 'target_date': target_date}
    groups = cur.execute("""
        SELECT date(created_at), COALESCE(tenant_id, 0), COALESCE(api_key_id, 0),
               COALESCE(card_key, ''), policy_decision, COUNT(*)
        FROM image_delivery_policy_records
        WHERE date(created_at) = ?
        GROUP BY date(created_at), COALESCE(tenant_id, 0), COALESCE(api_key_id, 0),
                 COALESCE(card_key, ''), policy_decision
    """, (target_date,)).fetchall()
    rows_aggregated = 0
    for g in groups:
        agg_date, tenant_id, api_key_id, card_key, policy_decision, new_count = g
        cur.execute("""
            INSERT INTO image_delivery_daily_aggregation
                (agg_date, tenant_id, api_key_id, card_key, policy_decision, count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(agg_date, tenant_id, api_key_id, card_key, policy_decision)
            DO UPDATE SET count = count + excluded.count
        """, (agg_date, tenant_id, api_key_id, card_key, policy_decision, new_count))
        rows_aggregated += 1
    conn.commit()
    cur.execute(
        "DELETE FROM image_delivery_policy_records WHERE date(created_at) = ?",
        (target_date,)
    )
    rows_deleted = cur.rowcount
    conn.commit()
    return {'rows_aggregated': rows_aggregated, 'rows_deleted': rows_deleted, 'target_date': target_date}


def _delivery_log_cleanup(conn, *, retention_days=30):
    """Aggregate and clean up expired delivery log entries."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=retention_days)
    target_dates = set()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT date(created_at) FROM image_delivery_policy_records WHERE date(created_at) < ?",
        (cutoff.strftime('%Y-%m-%d'),)
    )
    for row in cur.fetchall():
        target_dates.add(row[0])
    total_agg = 0
    total_del = 0
    for d in sorted(target_dates):
        result = _aggregate_delivery_log(conn, target_date=d)
        total_agg += result['rows_aggregated']
        total_del += result['rows_deleted']
    return {'rows_aggregated': total_agg, 'rows_deleted': total_del, 'retention_days': retention_days}


def main():
    parser = argparse.ArgumentParser(description='Aggregate and cleanup delivery logs')
    parser.add_argument('command', nargs='?', default='cleanup',
                        choices=['cleanup', 'dry-run'],
                        help='Command: cleanup or dry-run')
    parser.add_argument('--retention-days', type=int, default=30,
                        help='Days to retain raw delivery log entries (default: 30)')
    parser.add_argument('--db', type=str, default=None,
                        help='SQLite database path (default: from POKEMON_DB_DB env)')
    args = parser.parse_args()

    db_path = args.db or os.environ.get('POKEMON_DB_DB')
    if not db_path:
        # Fallback: relative to project directory
        db_path = os.path.join(PROJECT_DIR, 'full_tcgdex', 'pokemon_tcg_set_knowledge_base.sqlite')

    if not os.path.exists(db_path):
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

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
