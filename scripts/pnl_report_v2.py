#!/usr/bin/env python3
"""Calculate P&L for alerts from ID 71 onwards with $100 per trade."""

import sqlite3
import requests
import time
import os

# Load API key from .env file
env_path = '/opt/trade-app-v2/.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith('POLYGON_API_KEY='):
                API_KEY = line.strip().split('=', 1)[1]
                break
else:
    API_KEY = os.environ.get('POLYGON_API_KEY', '')

if not API_KEY:
    print("ERROR: No API key found!")
    exit(1)

print(f"API Key loaded: {API_KEY[:8]}...")

def get_current_price(symbol):
    """Fetch current price from Polygon.io."""
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={API_KEY}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('results') and len(data['results']) > 0:
            return float(data['results'][0]['c'])
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None

# Connect to database
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
    trend = alert['trend_regime'] or 'N/A'
    vol = alert['vol_regime'] or 'N/A'
    
    print(f"Fetching {symbol}...", end=" ", flush=True)
    current_price = get_current_price(symbol)
    
    if current_price is None:
        print("NO DATA")
        continue
    
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
    
    print(f"{status} {pnl_pct:+.2f}%")
        
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
    
    time.sleep(0.25)  # Rate limit

conn.close()

# Print results table
print()
print(f"{'ID':<4} {'Symbol':<6} {'Dir':<5} {'Entry':>8} {'Current':>8} {'P&L%':>7} {'P&L$':>7} {'Score':>5} {'Trend':<12} {'Vol':<8} {'Date':<10}")
print("-" * 105)

for r in results:
    print(f"{r['id']:<4} {r['symbol']:<6} {r['direction']:<5} ${r['entry']:>7.2f} ${r['current']:>7.2f} {r['pnl_pct']:>+6.2f}% ${r['pnl_dollar']:>+6.2f} {r['score']:>5} {r['trend']:<12} {r['vol']:<8} {r['date']:<10}")

print("-" * 105)
print()
print(f"=" * 80)
print(f"SUMMARY")
print(f"=" * 80)
if results:
    print(f"Total Trades: {len(results)}")
    print(f"Wins: {wins} ({wins/len(results)*100:.1f}%)")
    print(f"Losses: {losses} ({losses/len(results)*100:.1f}%)")
    print()
    print(f"Investment: ${len(results) * 100:.2f} ($100 x {len(results)} trades)")
    print(f"Total P&L: ${total_pnl:+.2f}")
    print(f"Return: {(total_pnl / (len(results) * 100)) * 100:+.2f}%")
else:
    print("No results to display")
