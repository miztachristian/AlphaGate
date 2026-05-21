#!/usr/bin/env python3
"""Explore the remote state.db to understand alert data."""
import sqlite3

conn = sqlite3.connect("remote_state.db")

# List all tables
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:")
for t in tables:
    name = t[0]
    count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
    print(f"  {name}: {count} rows")

# Check alerts_log schema 
print("\n--- alerts_log schema ---")
for col in conn.execute("PRAGMA table_info(alerts_log)").fetchall():
    print(f"  {col}")

# Check total alerts and setups
print("\n--- Distinct setups ---")
for row in conn.execute("SELECT DISTINCT setup FROM alerts_log").fetchall():
    print(f"  {row}")

# Get alert 233 and surrounding context
print("\n--- Alert 233 and nearby ---")
rows = conn.execute(
    "SELECT id, ts_utc, symbol, setup, direction, score, trigger_close FROM alerts_log WHERE id >= 233 LIMIT 5"
).fetchall()
for r in rows:
    print(f"  {r}")

# Count alerts >= 233 with vol_squeeze setup
print("\n--- Vol squeeze alerts since ID 233 ---")
for pattern in ['vol_squeeze', 'volatile_squeeze', 'volatility_squeeze', 'vol_sq', 'squeeze']:
    count = conn.execute(
        "SELECT COUNT(*) FROM alerts_log WHERE id >= 233 AND LOWER(setup) LIKE ?",
        (f"%{pattern}%",)
    ).fetchone()[0]
    print(f"  Pattern '{pattern}': {count} matching alerts")

# Show all distinct setups with counts
print("\n--- Setup distribution (all alerts) ---")
for row in conn.execute(
    "SELECT setup, COUNT(*) as cnt FROM alerts_log GROUP BY setup ORDER BY cnt DESC"
).fetchall():
    print(f"  {row}")

# Show first few vol squeeze alerts from 233
print("\n--- First 10 vol_squeeze alerts since 233 ---")
rows = conn.execute(
    "SELECT id, ts_utc, symbol, direction, score, trigger_close, entry_zone_low, entry_zone_high, invalidation FROM alerts_log WHERE id >= 233 AND LOWER(setup) LIKE '%squeeze%' ORDER BY id LIMIT 10"
).fetchall()
for r in rows:
    print(f"  {r}")

# Also check if there's a different naming
print("\n--- All column names ---")
for col in conn.execute("PRAGMA table_info(alerts_log)").fetchall():
    print(f"  {col[1]} ({col[2]})")

conn.close()
