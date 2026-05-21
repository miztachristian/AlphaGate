#!/usr/bin/env python3
"""Calculate P&L for alerts from ID 71 onwards with $100 per trade."""

import sqlite3
import sys
import os

# Load API key from .env
with open('/opt/trade-app-v2/.env') as f:
    for line in f:
        if line.startswith('POLYGON_API_KEY='):
            os.environ['POLYGON_API_KEY'] = line.strip().split('=', 1)[1]
            break

sys.path.insert(0, '/opt/trade-app-v2')

from src.marketdata import fetch_stock_ohlcv

conn = sqlite3.connect('/opt/trade-app-v2/state.db')
cursor = conn.cursor()

# Get alerts from ID 71 onwards
cursor.execute('''
    SELECT id, symbol, timeframe, direction, setup, score, 
           trend_regime, vol_regime, news_risk,
           trigger_close, invalidation,
           ts_utc
    FROM alerts_log 
    WHERE id >= 71
    ORDER BY id
''')

alerts = cursor.fetchall()
columns = [desc[0] for desc in cursor.description]

print(f"=" * 80)
print(f"P&L REPORT - Alerts from ID 71 onwards")
print(f"=" * 80)
print(f"Total alerts: {len(alerts)}")
print()

# Calculate P&L for each alert
total_pnl = 0.0
wins = 0
losses = 0
results = []

for row in alerts:
    alert = dict(zip(columns, row))
    alert_id = alert['id']
    symbol = alert['symbol']
    entry_price = alert['trigger_close']
    direction = alert['direction']
    ts_utc = alert['ts_utc']
    score = alert['score']
    trend = alert['trend_regime']
    vol = alert['vol_regime']
    
    try:
        # Fetch current price
        df = fetch_stock_ohlcv(symbol, interval='1h', lookback_days=1)
        if df is None or df.empty:
            current_price = None
            pnl_pct = None
            status = "NO_DATA"
        else:
            current_price = float(df['close'].iloc[-1])
            
            if direction == 'LONG':
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
            else:  # SHORT
                pnl_pct = ((entry_price - current_price) / entry_price) * 100
            
            pnl_dollar = (pnl_pct / 100) * 100  # $100 per trade
            total_pnl += pnl_dollar
            
            if pnl_pct > 0:
                wins += 1
                status = "WIN"
            else:
                losses += 1
                status = "LOSS"
                
            results.append({
                'id': alert_id,
                'symbol': symbol,
                'direction': direction,
                'entry': entry_price,
                'current': current_price,
                'pnl_pct': pnl_pct,
                'pnl_dollar': pnl_dollar,
                'score': score,
                'trend': trend,
                'vol': vol,
                'status': status,
                'date': ts_utc[:10] if ts_utc else ''
            })
            
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        continue

# Print results table
print(f"{'ID':<4} {'Symbol':<6} {'Dir':<5} {'Entry':>8} {'Current':>8} {'P&L%':>7} {'P&L$':>7} {'Score':>5} {'Trend':<10} {'Vol':<6} {'Status':<5} {'Date':<10}")
print("-" * 100)

for r in results:
    print(f"{r['id']:<4} {r['symbol']:<6} {r['direction']:<5} ${r['entry']:>7.2f} ${r['current']:>7.2f} {r['pnl_pct']:>6.2f}% ${r['pnl_dollar']:>6.2f} {r['score']:>5} {r['trend']:<10} {r['vol']:<6} {r['status']:<5} {r['date']:<10}")

print("-" * 100)
print()
print(f"=" * 80)
print(f"SUMMARY")
print(f"=" * 80)
print(f"Total Trades: {len(results)}")
print(f"Wins: {wins} ({wins/len(results)*100:.1f}%)" if results else "Wins: 0")
print(f"Losses: {losses} ({losses/len(results)*100:.1f}%)" if results else "Losses: 0")
print()
print(f"Investment: ${len(results) * 100:.2f} ($100 x {len(results)} trades)")
print(f"Total P&L: ${total_pnl:.2f}")
print(f"Return: {total_pnl / (len(results) * 100) * 100:.2f}%" if results else "Return: 0%")
print(f"Current Value: ${len(results) * 100 + total_pnl:.2f}")
print(f"=" * 80)

conn.close()
