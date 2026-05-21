#!/usr/bin/env python3
"""Extract all volatility squeeze alerts from ID 233 onwards."""
import sqlite3
import json

conn = sqlite3.connect("remote_state.db")

rows = conn.execute("""
    SELECT id, ts_utc, symbol, direction, score, trigger_close, 
           entry_zone_low, entry_zone_high, invalidation,
           trend_regime, vol_regime, bb_lower, bb_middle, bb_upper
    FROM alerts_log 
    WHERE id >= 233 
      AND setup = 'VOLATILITY_SQUEEZE_BREAKOUT'
    ORDER BY id
""").fetchall()

print(f"Total VOLATILITY_SQUEEZE_BREAKOUT alerts since ID 233: {len(rows)}")
print()

# Get unique symbols
symbols = sorted(set(r[2] for r in rows))
print(f"Unique symbols ({len(symbols)}): {', '.join(symbols)}")
print()

# Print all alerts
print("ID | Timestamp | Symbol | Dir | Score | Entry Price | Entry Low | Entry High | Invalidation | Trend | Vol")
print("-" * 140)
for r in rows:
    print(f"{r[0]} | {r[1][:16]} | {r[2]:6s} | {r[3]:5s} | {r[4]:3d}   | {r[5]:10.2f} | {r[6]:10.4f} | {r[7]:10.4f} | {r[8]:10.4f}     | {r[9] or 'N/A':12s} | {r[10] or 'N/A'}")

# Export as JSON for the report script
data = []
for r in rows:
    data.append({
        "id": r[0],
        "ts_utc": r[1],
        "symbol": r[2],
        "direction": r[3],
        "score": r[4],
        "trigger_close": r[5],
        "entry_zone_low": r[6],
        "entry_zone_high": r[7],
        "invalidation": r[8],
        "trend_regime": r[9],
        "vol_regime": r[10],
        "bb_lower": r[11],
        "bb_middle": r[12],
        "bb_upper": r[13],
    })

with open("vol_squeeze_alerts.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"\nExported {len(data)} alerts to vol_squeeze_alerts.json")

conn.close()
