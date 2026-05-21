#!/usr/bin/env python3
"""List all recent alerts."""
from src.state import SqliteStateStore

store = SqliteStateStore("state.db")
conn = store._connect()

rows = conn.execute(
    "SELECT id, ts_utc, symbol, direction, score, trigger_close FROM alerts_log ORDER BY id DESC LIMIT 20"
).fetchall()

if not rows:
    print("No alerts in database")
else:
    print(f"\nAll recent alerts:")
    print("-" * 90)
    print(f"{'ID':<6} {'Timestamp':<20} {'Symbol':<8} {'Side':<6} {'Score':<6} {'Price':<10}")
    print("-" * 90)
    for row in rows:
        print(f"{row[0]:<6} {row[1]:<20} {row[2]:<8} {row[3]:<6} {row[4] or 'N/A':<6} {row[5] or 'N/A':<10}")
