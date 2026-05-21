#!/usr/bin/env python3
"""Deep analysis of what's going wrong with the alerts."""

import sqlite3
import requests
import os
from collections import Counter

# Load API key
with open('/opt/trade-app-v2/.env') as f:
    for line in f:
        if line.startswith('POLYGON_API_KEY='):
            API_KEY = line.strip().split('=', 1)[1]
            break

def get_current_price(symbol):
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={API_KEY}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('results') and len(data['results']) > 0:
            return float(data['results'][0]['c'])
    except:
        pass
    return None

conn = sqlite3.connect('/opt/trade-app-v2/state.db')
cur = conn.cursor()

cur.execute('''
    SELECT id, symbol, direction, score, trend_regime, vol_regime, 
           trigger_close, ts_utc
    FROM alerts_log WHERE id >= 71
''')
alerts = cur.fetchall()

# Compute P&L for each
results = []
for a in alerts:
    id, symbol, direction, score, trend, vol, entry, ts = a
    current = get_current_price(symbol)
    if current:
        if direction == 'LONG':
            pnl_pct = ((current - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current) / entry) * 100
        results.append({
            'id': id, 'symbol': symbol, 'score': score,
            'trend': trend, 'vol': vol, 'pnl': pnl_pct,
            'entry': entry, 'current': current, 'date': ts[:10]
        })

print("=" * 60)
print("PROBLEM #1: DUPLICATE SYMBOLS")
print("=" * 60)
symbols = [r['symbol'] for r in results]
dupes = [(s, c) for s, c in Counter(symbols).items() if c > 1]
for s, c in sorted(dupes, key=lambda x: -x[1]):
    trades = [r for r in results if r['symbol'] == s]
    total_pnl = sum(t['pnl'] for t in trades)
    print(f"\n{s}: {c} trades, total P&L: {total_pnl:+.2f}%")
    for t in trades:
        print(f"  ID {t['id']}: {t['trend']}/{t['vol']} score={t['score']} -> {t['pnl']:+.2f}%")

print("\n" + "=" * 60)
print("PROBLEM #2: AVG WIN vs AVG LOSS")
print("=" * 60)
wins = [r['pnl'] for r in results if r['pnl'] > 0]
losses = [r['pnl'] for r in results if r['pnl'] <= 0]
print(f"Avg Win:  {sum(wins)/len(wins):+.2f}% ({len(wins)} trades)")
print(f"Avg Loss: {sum(losses)/len(losses):+.2f}% ({len(losses)} trades)")
print(f"Win/Loss Ratio: {abs(sum(wins)/len(wins)) / abs(sum(losses)/len(losses)):.2f}")

print("\n" + "=" * 60)
print("PROBLEM #3: P&L BY REGIME")
print("=" * 60)
by_trend = {}
for r in results:
    t = r['trend'] or 'NONE'
    if t not in by_trend:
        by_trend[t] = []
    by_trend[t].append(r['pnl'])

for t, pnls in sorted(by_trend.items(), key=lambda x: sum(x[1])):
    avg = sum(pnls) / len(pnls)
    total = sum(pnls)
    wins = len([p for p in pnls if p > 0])
    print(f"{t}: {len(pnls)} trades, {wins} wins ({wins/len(pnls)*100:.0f}%), avg={avg:+.2f}%, total={total:+.2f}%")

print("\n" + "=" * 60)
print("PROBLEM #4: P&L BY VOLATILITY")
print("=" * 60)
by_vol = {}
for r in results:
    v = r['vol'] or 'NONE'
    if v not in by_vol:
        by_vol[v] = []
    by_vol[v].append(r['pnl'])

for v, pnls in sorted(by_vol.items(), key=lambda x: sum(x[1])):
    avg = sum(pnls) / len(pnls)
    total = sum(pnls)
    wins = len([p for p in pnls if p > 0])
    print(f"{v}: {len(pnls)} trades, {wins} wins ({wins/len(pnls)*100:.0f}%), avg={avg:+.2f}%, total={total:+.2f}%")

print("\n" + "=" * 60)
print("PROBLEM #5: P&L BY SCORE")
print("=" * 60)
by_score = {}
for r in results:
    s = r['score']
    if s not in by_score:
        by_score[s] = []
    by_score[s].append(r['pnl'])

for s, pnls in sorted(by_score.items()):
    avg = sum(pnls) / len(pnls)
    total = sum(pnls)
    wins = len([p for p in pnls if p > 0])
    print(f"Score {s}: {len(pnls)} trades, {wins} wins ({wins/len(pnls)*100:.0f}%), avg={avg:+.2f}%, total={total:+.2f}%")

print("\n" + "=" * 60)
print("RECOMMENDATIONS")
print("=" * 60)

# What if we only took score >= 80?
high_score = [r for r in results if r['score'] >= 80]
hs_pnl = sum(r['pnl'] for r in high_score)
print(f"If min_score=80: {len(high_score)} trades, P&L={hs_pnl:+.2f}%")

# What if we excluded HIGH vol?
normal_vol = [r for r in results if r['vol'] == 'NORMAL']
nv_pnl = sum(r['pnl'] for r in normal_vol)
print(f"If NORMAL vol only: {len(normal_vol)} trades, P&L={nv_pnl:+.2f}%")

# What if score >= 80 AND NORMAL vol?
strict = [r for r in results if r['score'] >= 80 and r['vol'] == 'NORMAL']
st_pnl = sum(r['pnl'] for r in strict)
print(f"If score>=80 AND NORMAL vol: {len(strict)} trades, P&L={st_pnl:+.2f}%")

# What if we blocked repeated symbols within 3 days?
print(f"\nIf blocked duplicate symbols (first trade only):")
seen = set()
unique_trades = []
for r in sorted(results, key=lambda x: x['id']):
    if r['symbol'] not in seen:
        seen.add(r['symbol'])
        unique_trades.append(r)
unique_pnl = sum(r['pnl'] for r in unique_trades)
print(f"  {len(unique_trades)} trades, P&L={unique_pnl:+.2f}%")
