#!/usr/bin/env python3
"""
Volatility Squeeze Alert Performance Report
============================================
Analyses all VOLATILITY_SQUEEZE_BREAKOUT alerts from ID 233 onwards.
For each alert, fetches current price and calculates:
  - P&L if $100 was invested at trigger_close
  - Whether the trade hit target (1x ATR) or stop (0.7x ATR)
  - Overall success/failure rate
"""
import json
import os
import sys
import time
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
CAPITAL_PER_TRADE = 100.0


def get_current_price(symbol: str) -> float | None:
    """Fetch current/latest price from Polygon."""
    import urllib.request
    import json as _json

    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
            if data.get("results"):
                return data["results"][0]["c"]  # close price
    except Exception as e:
        print(f"  ⚠ Error fetching {symbol}: {e}")
    return None


def get_price_history_after_alert(symbol: str, alert_ts: str, atr: float, direction: str) -> dict:
    """Fetch price bars after alert to check if target/stop was hit."""
    import urllib.request
    import json as _json

    alert_date = alert_ts[:10]
    end_date = "2026-03-17"  # today

    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/hour/{alert_date}/{end_date}"
        f"?adjusted=true&sort=asc&limit=500&apiKey={POLYGON_API_KEY}"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
            return data
    except Exception as e:
        return {}


def main():
    # Load alerts
    conn = sqlite3.connect("remote_state.db")
    rows = conn.execute("""
        SELECT id, ts_utc, symbol, direction, score, trigger_close,
               entry_zone_low, entry_zone_high, invalidation,
               trend_regime, vol_regime, atr, atr_pct
        FROM alerts_log
        WHERE id >= 233
          AND setup = 'VOLATILITY_SQUEEZE_BREAKOUT'
        ORDER BY id
    """).fetchall()
    conn.close()

    print(f"\n{'='*80}")
    print(f"  VOLATILITY SQUEEZE BREAKOUT — PERFORMANCE REPORT")
    print(f"  Alerts #{rows[0][0]} to #{rows[-1][0]}  |  {len(rows)} total alerts")
    print(f"  Period: {rows[0][1][:10]} to {rows[-1][1][:10]}")
    print(f"  Capital per trade: ${CAPITAL_PER_TRADE:.0f}")
    print(f"{'='*80}\n")

    # Get unique symbols and their latest alert entry price
    symbols = sorted(set(r[2] for r in rows))
    print(f"Fetching current prices for {len(symbols)} symbols...")

    current_prices = {}
    for i, sym in enumerate(symbols):
        price = get_current_price(sym)
        current_prices[sym] = price
        if price:
            print(f"  ✓ {sym}: ${price:.2f}")
        else:
            print(f"  ✗ {sym}: UNAVAILABLE")
        # Rate limit: polygon starter = 5 req/sec
        if (i + 1) % 5 == 0:
            time.sleep(1.2)

    print(f"\n{'='*80}")
    print(f"  INDIVIDUAL TRADE RESULTS ($100 per alert)")
    print(f"{'='*80}\n")

    total_invested = 0
    total_current_value = 0
    wins = 0
    losses = 0
    breakeven = 0
    skipped = 0

    results = []

    for r in rows:
        alert_id = r[0]
        ts = r[1]
        symbol = r[2]
        direction = r[3]
        score = r[4]
        entry_price = r[5]
        entry_low = r[6]
        entry_high = r[7]
        invalidation = r[8]
        trend = r[9]
        vol = r[10]
        atr = r[11]
        atr_pct = r[12]

        cur_price = current_prices.get(symbol)
        if cur_price is None:
            skipped += 1
            results.append({
                "id": alert_id, "symbol": symbol, "entry": entry_price,
                "current": None, "pnl_pct": None, "pnl_usd": None,
                "status": "SKIPPED", "score": score, "ts": ts
            })
            continue

        # Calculate P&L
        if direction == "LONG":
            pnl_pct = ((cur_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - cur_price) / entry_price) * 100

        pnl_usd = CAPITAL_PER_TRADE * (pnl_pct / 100)
        current_value = CAPITAL_PER_TRADE + pnl_usd

        total_invested += CAPITAL_PER_TRADE
        total_current_value += current_value

        # Determine win/loss using target (1x ATR) and stop (0.7x ATR)
        if atr and atr > 0:
            target_price = entry_price + (1.0 * atr) if direction == "LONG" else entry_price - (1.0 * atr)
            stop_price = entry_price - (0.7 * atr) if direction == "LONG" else entry_price + (0.7 * atr)

            if direction == "LONG":
                if cur_price >= target_price:
                    status = "WIN"
                    wins += 1
                elif cur_price <= stop_price:
                    status = "LOSS"
                    losses += 1
                else:
                    status = "OPEN"
                    breakeven += 1
            else:
                if cur_price <= target_price:
                    status = "WIN"
                    wins += 1
                elif cur_price >= stop_price:
                    status = "LOSS"
                    losses += 1
                else:
                    status = "OPEN"
                    breakeven += 1
        else:
            # No ATR data — judge by P&L
            if pnl_pct > 1:
                status = "WIN"
                wins += 1
            elif pnl_pct < -1:
                status = "LOSS"
                losses += 1
            else:
                status = "OPEN"
                breakeven += 1

        results.append({
            "id": alert_id, "symbol": symbol, "entry": entry_price,
            "current": cur_price, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
            "status": status, "score": score, "ts": ts,
            "current_value": current_value
        })

    # Print individual results
    print(f"{'ID':<5} {'Date':<12} {'Symbol':<7} {'Score':<6} {'Entry':>9} {'Current':>9} {'P&L %':>8} {'P&L $':>8} {'Value':>8} {'Status':<6}")
    print("-" * 90)

    for res in results:
        if res["status"] == "SKIPPED":
            print(f"{res['id']:<5} {res['ts'][:10]:<12} {res['symbol']:<7} {res['score']:<6} ${res['entry']:>7.2f}   {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>8} SKIP")
            continue

        status_icon = "✅" if res["status"] == "WIN" else "❌" if res["status"] == "LOSS" else "⏳"
        pnl_sign = "+" if res["pnl_pct"] >= 0 else ""

        print(
            f"{res['id']:<5} {res['ts'][:10]:<12} {res['symbol']:<7} {res['score']:<6} "
            f"${res['entry']:>7.2f}  ${res['current']:>7.2f}  "
            f"{pnl_sign}{res['pnl_pct']:>6.2f}%  {pnl_sign}${res['pnl_usd']:>6.2f}  "
            f"${res.get('current_value', 0):>6.2f}  {status_icon} {res['status']}"
        )

    # ===== SUMMARY =====
    evaluated = wins + losses + breakeven
    total_pnl = total_current_value - total_invested

    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    print(f"  Total Alerts Analysed:   {len(rows)}")
    print(f"  Evaluated (price avail): {evaluated}")
    print(f"  Skipped (no price):      {skipped}")
    print()
    print(f"  ✅ Wins (hit target):    {wins}  ({(wins/evaluated*100):.1f}%)" if evaluated else "")
    print(f"  ❌ Losses (hit stop):    {losses}  ({(losses/evaluated*100):.1f}%)" if evaluated else "")
    print(f"  ⏳ Still Open:           {breakeven}  ({(breakeven/evaluated*100):.1f}%)" if evaluated else "")
    print()
    print(f"  💰 Total Invested:       ${total_invested:,.2f}")
    print(f"  💵 Current Value:        ${total_current_value:,.2f}")
    print(f"  📊 Total P&L:            {'+'if total_pnl>=0 else ''}${total_pnl:,.2f} ({'+'if total_pnl>=0 else ''}{(total_pnl/total_invested*100) if total_invested else 0:.2f}%)")

    # Win rate excluding open trades
    closed = wins + losses
    if closed > 0:
        print(f"\n  📈 Win Rate (closed):     {wins}/{closed} = {(wins/closed*100):.1f}%")
        print(f"  📉 Failure Rate (closed): {losses}/{closed} = {(losses/closed*100):.1f}%")

    # By score tier
    print(f"\n{'='*80}")
    print(f"  BREAKDOWN BY SCORE")
    print(f"{'='*80}")

    score_buckets = {}
    for res in results:
        if res["status"] == "SKIPPED":
            continue
        score = res["score"]
        bucket = f"{(score // 10) * 10}-{(score // 10) * 10 + 9}"
        if bucket not in score_buckets:
            score_buckets[bucket] = {"wins": 0, "losses": 0, "open": 0, "total_pnl": 0}
        if res["status"] == "WIN":
            score_buckets[bucket]["wins"] += 1
        elif res["status"] == "LOSS":
            score_buckets[bucket]["losses"] += 1
        else:
            score_buckets[bucket]["open"] += 1
        score_buckets[bucket]["total_pnl"] += res["pnl_usd"]

    print(f"  {'Score':>7}  {'Wins':>5}  {'Losses':>6}  {'Open':>5}  {'Win%':>6}  {'Total P&L':>10}")
    print(f"  {'-'*50}")
    for bucket in sorted(score_buckets.keys()):
        b = score_buckets[bucket]
        closed_b = b["wins"] + b["losses"]
        win_pct = (b["wins"] / closed_b * 100) if closed_b > 0 else 0
        pnl_sign = "+" if b["total_pnl"] >= 0 else ""
        print(f"  {bucket:>7}  {b['wins']:>5}  {b['losses']:>6}  {b['open']:>5}  {win_pct:>5.1f}%  {pnl_sign}${b['total_pnl']:>8.2f}")

    # By symbol (top performers)
    print(f"\n{'='*80}")
    print(f"  TOP PERFORMERS BY SYMBOL")
    print(f"{'='*80}")

    sym_pnl = {}
    for res in results:
        if res["status"] == "SKIPPED" or res["pnl_usd"] is None:
            continue
        sym = res["symbol"]
        if sym not in sym_pnl:
            sym_pnl[sym] = {"pnl": 0, "count": 0, "wins": 0, "losses": 0}
        sym_pnl[sym]["pnl"] += res["pnl_usd"]
        sym_pnl[sym]["count"] += 1
        if res["status"] == "WIN":
            sym_pnl[sym]["wins"] += 1
        elif res["status"] == "LOSS":
            sym_pnl[sym]["losses"] += 1

    sorted_syms = sorted(sym_pnl.items(), key=lambda x: x[1]["pnl"], reverse=True)

    print(f"  {'Symbol':<7}  {'Alerts':>6}  {'Wins':>5}  {'Losses':>6}  {'Total P&L':>10}")
    print(f"  {'-'*45}")
    for sym, data in sorted_syms[:15]:
        pnl_sign = "+" if data["pnl"] >= 0 else ""
        print(f"  {sym:<7}  {data['count']:>6}  {data['wins']:>5}  {data['losses']:>6}  {pnl_sign}${data['pnl']:>8.2f}")

    print(f"\n  ... (showing top 15 of {len(sym_pnl)} symbols)")

    # Worst performers
    print(f"\n{'='*80}")
    print(f"  WORST PERFORMERS BY SYMBOL")
    print(f"{'='*80}")
    print(f"  {'Symbol':<7}  {'Alerts':>6}  {'Wins':>5}  {'Losses':>6}  {'Total P&L':>10}")
    print(f"  {'-'*45}")
    for sym, data in sorted_syms[-10:]:
        pnl_sign = "+" if data["pnl"] >= 0 else ""
        print(f"  {sym:<7}  {data['count']:>6}  {data['wins']:>5}  {data['losses']:>6}  {pnl_sign}${data['pnl']:>8.2f}")

    # Export JSON for artifact
    report_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "period": {
            "start_alert": rows[0][0],
            "end_alert": rows[-1][0],
            "start_date": rows[0][1][:10],
            "end_date": rows[-1][1][:10],
        },
        "summary": {
            "total_alerts": len(rows),
            "evaluated": evaluated,
            "skipped": skipped,
            "wins": wins,
            "losses": losses,
            "open": breakeven,
            "win_rate_closed": (wins / closed * 100) if closed > 0 else 0,
            "failure_rate_closed": (losses / closed * 100) if closed > 0 else 0,
            "total_invested": total_invested,
            "current_value": total_current_value,
            "total_pnl_usd": total_pnl,
            "total_pnl_pct": (total_pnl / total_invested * 100) if total_invested else 0,
        },
        "results": results,
        "score_breakdown": score_buckets,
        "symbol_breakdown": {s: d for s, d in sorted_syms},
    }

    with open("vol_squeeze_report.json", "w") as f:
        json.dump(report_data, f, indent=2, default=str)

    print(f"\n✅ Full report data exported to vol_squeeze_report.json")


if __name__ == "__main__":
    main()
