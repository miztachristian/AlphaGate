#!/usr/bin/env python3
"""
Alert Performance Report — from alert 288 onwards.
Simulates $100 invested per alert, tracks success/failure using invalidation as stop loss
and bb_upper / entry_zone_high as target.
"""
import sqlite3
import json
from datetime import datetime

import yfinance as yf
import pandas as pd

DB_PATH = "remote_state.db"
INVESTMENT = 100.0  # $100 per alert
FROM_ALERT_ID = 288


def load_alerts(db_path, from_id):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT id, ts_utc, symbol, direction, score, trigger_close,
                  setup, trend_regime, vol_regime,
                  invalidation, entry_zone_low, entry_zone_high,
                  bb_upper, bb_middle, alert_payload_json
           FROM alerts_log
           WHERE id >= ?
           ORDER BY id ASC""",
        (from_id,),
    ).fetchall()
    conn.close()
    
    alerts = []
    for r in rows:
        payload = {}
        if r[14]:
            try:
                payload = json.loads(r[14])
            except Exception:
                pass
        alerts.append({
            "id": r[0],
            "ts_utc": r[1],
            "symbol": r[2],
            "direction": r[3],
            "score": r[4],
            "entry_price": r[5],
            "setup": r[6],
            "trend_regime": r[7],
            "vol_regime": r[8],
            "invalidation": r[9],
            "entry_zone_low": r[10],
            "entry_zone_high": r[11],
            "bb_upper": r[12],
            "bb_middle": r[13],
            "payload": payload,
        })
    return alerts


def fetch_current_prices(symbols):
    """Fetch current prices for all symbols using yfinance."""
    print(f"Fetching current prices for {len(symbols)} symbols...")
    prices = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                t = tickers.tickers[sym]
                info = t.fast_info
                prices[sym] = info.get("lastPrice") or info.get("last_price") or info.get("regularMarketPrice")
                if prices[sym] is None:
                    hist = t.history(period="1d")
                    if not hist.empty:
                        prices[sym] = hist["Close"].iloc[-1]
            except Exception as e:
                print(f"  Warning: Could not fetch price for {sym}: {e}")
    except Exception as e:
        print(f"  Bulk fetch error, trying one-by-one: {e}")
        for sym in symbols:
            try:
                t = yf.Ticker(sym)
                hist = t.history(period="1d")
                if not hist.empty:
                    prices[sym] = hist["Close"].iloc[-1]
            except Exception as e2:
                print(f"  Warning: {sym} failed: {e2}")
    return prices


def evaluate_alert(alert, current_price):
    """
    Evaluate an alert's performance.
    
    Logic for LONG alerts:
      - If current_price <= invalidation => LOSS (stopped out)
      - If current_price >= entry_price  => WIN (in profit)
      - If current_price < entry_price but > invalidation => UNREALIZED LOSS (still active)
    
    Returns dict with outcome info.
    """
    entry = alert["entry_price"]
    inv = alert["invalidation"]
    
    if entry is None or entry == 0:
        return {"outcome": "NO_DATA", "pnl_pct": 0, "pnl_dollar": 0}
    
    if current_price is None:
        return {"outcome": "NO_PRICE", "pnl_pct": 0, "pnl_dollar": 0}
    
    pnl_pct = ((current_price - entry) / entry) * 100
    pnl_dollar = INVESTMENT * (pnl_pct / 100)
    
    # Determine outcome
    if inv and inv > 0 and current_price <= inv:
        # Stopped out — cap loss at invalidation level
        stop_loss_pct = ((inv - entry) / entry) * 100
        stop_loss_dollar = INVESTMENT * (stop_loss_pct / 100)
        return {
            "outcome": "STOPPED_OUT",
            "pnl_pct": stop_loss_pct,
            "pnl_dollar": stop_loss_dollar,
        }
    elif current_price >= entry:
        return {
            "outcome": "WIN",
            "pnl_pct": pnl_pct,
            "pnl_dollar": pnl_dollar,
        }
    else:
        return {
            "outcome": "UNDERWATER",
            "pnl_pct": pnl_pct,
            "pnl_dollar": pnl_dollar,
        }


def main():
    print("=" * 80)
    print("  ALERT PERFORMANCE REPORT")
    print(f"  From Alert #{FROM_ALERT_ID} | ${INVESTMENT} per alert | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    print()

    # Load alerts
    alerts = load_alerts(DB_PATH, FROM_ALERT_ID)
    print(f"Total alerts loaded: {len(alerts)}")
    
    if not alerts:
        print("No alerts found!")
        return

    first_date = alerts[0]["ts_utc"][:10]
    last_date = alerts[-1]["ts_utc"][:10]
    print(f"Date range: {first_date} to {last_date}")
    print()

    # Get unique symbols and fetch prices
    symbols = list(set(a["symbol"] for a in alerts))
    current_prices = fetch_current_prices(symbols)
    
    print(f"Prices fetched for {len(current_prices)}/{len(symbols)} symbols")
    print()

    # Evaluate each alert
    results = []
    for a in alerts:
        cp = current_prices.get(a["symbol"])
        eval_result = evaluate_alert(a, cp)
        results.append({**a, **eval_result, "current_price": cp})

    # ── Summary Statistics ──────────────────────────────────────
    wins = [r for r in results if r["outcome"] == "WIN"]
    stopped = [r for r in results if r["outcome"] == "STOPPED_OUT"]
    underwater = [r for r in results if r["outcome"] == "UNDERWATER"]
    no_data = [r for r in results if r["outcome"] in ("NO_DATA", "NO_PRICE")]

    total_evaluated = len(wins) + len(stopped) + len(underwater)
    
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Total Alerts:        {len(results)}")
    print(f"  Evaluated:           {total_evaluated}")
    print(f"  No Data:             {len(no_data)}")
    print()
    
    if total_evaluated > 0:
        win_rate = len(wins) / total_evaluated * 100
        loss_rate = (len(stopped) + len(underwater)) / total_evaluated * 100
        stopped_rate = len(stopped) / total_evaluated * 100
        underwater_rate = len(underwater) / total_evaluated * 100
        
        print(f"  ✅ WINNERS:          {len(wins):>4}  ({win_rate:.1f}%)")
        print(f"  ❌ STOPPED OUT:      {len(stopped):>4}  ({stopped_rate:.1f}%)")
        print(f"  ⚠️  UNDERWATER:       {len(underwater):>4}  ({underwater_rate:.1f}%)")
        print()
        
        # P&L
        total_invested = total_evaluated * INVESTMENT
        total_pnl = sum(r["pnl_dollar"] for r in results)
        total_pnl_pct = (total_pnl / total_invested) * 100 if total_invested else 0
        
        win_pnl = sum(r["pnl_dollar"] for r in wins)
        loss_pnl = sum(r["pnl_dollar"] for r in stopped + underwater)
        
        print(f"  💰 Total Invested:   ${total_invested:,.2f}")
        print(f"  📈 Total P&L:        ${total_pnl:,.2f} ({total_pnl_pct:+.2f}%)")
        print(f"  📈 Winners P&L:      ${win_pnl:,.2f}")
        print(f"  📉 Losers P&L:       ${loss_pnl:,.2f}")
        print()
        
        if wins:
            avg_win = sum(r["pnl_pct"] for r in wins) / len(wins)
            best_win = max(wins, key=lambda r: r["pnl_pct"])
            print(f"  Avg Win:             {avg_win:+.2f}%")
            print(f"  Best Win:            {best_win['symbol']} #{best_win['id']} → {best_win['pnl_pct']:+.2f}% (${best_win['pnl_dollar']:+.2f})")
        
        if stopped or underwater:
            losers = stopped + underwater
            avg_loss = sum(r["pnl_pct"] for r in losers) / len(losers)
            worst = min(losers, key=lambda r: r["pnl_pct"])
            print(f"  Avg Loss:            {avg_loss:+.2f}%")
            print(f"  Worst Loss:          {worst['symbol']} #{worst['id']} → {worst['pnl_pct']:+.2f}% (${worst['pnl_dollar']:+.2f})")
        print()
        
        # Portfolio value if $100 per alert
        portfolio_value = total_invested + total_pnl
        print(f"  🏦 Portfolio Value:   ${portfolio_value:,.2f} (started at ${total_invested:,.2f})")
    
    # ── Detailed Table ──────────────────────────────────────────
    print()
    print("=" * 80)
    print("  DETAILED RESULTS")
    print("=" * 80)
    print(f"{'ID':<5} {'Date':<12} {'Symbol':<7} {'Score':<6} {'Entry':>9} {'Current':>9} {'P&L%':>8} {'P&L$':>9} {'Status':<12} {'Trend':<14} {'Vol':<8}")
    print("-" * 110)
    
    for r in results:
        date_str = r["ts_utc"][:10] if r["ts_utc"] else "N/A"
        entry_str = f"${r['entry_price']:.2f}" if r["entry_price"] else "N/A"
        curr_str = f"${r['current_price']:.2f}" if r["current_price"] else "N/A"
        pnl_pct_str = f"{r['pnl_pct']:+.2f}%" if r["pnl_pct"] else "N/A"
        pnl_dollar_str = f"${r['pnl_dollar']:+.2f}" if r["pnl_dollar"] else "N/A"
        
        # Color indicator
        status_icon = {
            "WIN": "✅ WIN",
            "STOPPED_OUT": "❌ STOP",
            "UNDERWATER": "⚠️  DOWN",
            "NO_DATA": "— N/A",
            "NO_PRICE": "— N/A",
        }.get(r["outcome"], r["outcome"])
        
        print(f"{r['id']:<5} {date_str:<12} {r['symbol']:<7} {r['score'] or 'N/A':<6} {entry_str:>9} {curr_str:>9} {pnl_pct_str:>8} {pnl_dollar_str:>9} {status_icon:<12} {r['trend_regime'] or 'N/A':<14} {r['vol_regime'] or 'N/A':<8}")

    # ── Score Analysis ──────────────────────────────────────────
    print()
    print("=" * 80)
    print("  WIN RATE BY SCORE")
    print("=" * 80)
    
    score_groups = {}
    for r in results:
        if r["outcome"] in ("NO_DATA", "NO_PRICE"):
            continue
        s = r["score"] or 0
        score_groups.setdefault(s, []).append(r)
    
    for score in sorted(score_groups.keys()):
        group = score_groups[score]
        w = sum(1 for r in group if r["outcome"] == "WIN")
        total = len(group)
        wr = w / total * 100 if total else 0
        avg_pnl = sum(r["pnl_pct"] for r in group) / total
        print(f"  Score {score:>3}: {w}/{total} wins ({wr:.0f}%)  |  Avg P&L: {avg_pnl:+.2f}%")

    # ── By Symbol Analysis ──────────────────────────────────────
    print()
    print("=" * 80)
    print("  PERFORMANCE BY SYMBOL")
    print("=" * 80)
    
    sym_groups = {}
    for r in results:
        if r["outcome"] in ("NO_DATA", "NO_PRICE"):
            continue
        sym_groups.setdefault(r["symbol"], []).append(r)
    
    sym_data = []
    for sym in sorted(sym_groups.keys()):
        group = sym_groups[sym]
        w = sum(1 for r in group if r["outcome"] == "WIN")
        total = len(group)
        wr = w / total * 100 if total else 0
        total_pnl = sum(r["pnl_dollar"] for r in group)
        sym_data.append((sym, total, w, wr, total_pnl))
    
    # Sort by total P&L
    sym_data.sort(key=lambda x: x[4], reverse=True)
    
    print(f"  {'Symbol':<8} {'Alerts':>7} {'Wins':>6} {'WinRate':>8} {'Total P&L':>12}")
    print("  " + "-" * 50)
    for sym, cnt, w, wr, pnl in sym_data:
        print(f"  {sym:<8} {cnt:>7} {w:>6} {wr:>7.0f}% ${pnl:>10.2f}")
    
    print()
    print("=" * 80)
    print("  END OF REPORT")
    print("=" * 80)


if __name__ == "__main__":
    main()
