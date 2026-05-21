#!/usr/bin/env python3
"""
Volatility Squeeze Alert Performance Report — CORRECTED
=========================================================
The BACKTEST uses:
  - Target: entry + 3.0 * ATR  (not 1.0 ATR like my first report!)
  - Stop:   alert.invalidation level
  - Trailing stop: 1.5 * ATR (ratchets up)
  - Max hold: 50 bars (50 hours on 1H timeframe)

The first report used 1.0x ATR target / 0.7x ATR stop which was WRONG —
that's the outcome_eval hit rule, not the backtest trade management.

This corrected version:
  1. Uses the ACTUAL backtest parameters (3x ATR target, invalidation stop)
  2. Fetches hourly bars AFTER each alert to check if target/stop was hit
  3. Respects 50-bar max hold
"""
import json
import os
import sys
import time
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
import urllib.request

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
CAPITAL_PER_TRADE = 100.0
MAX_HOLD_BARS = 50  # 50 bars = 50 hours  on 1H timeframe


def fetch_bars(symbol: str, from_date: str, to_date: str = "2026-03-17") -> list:
    """Fetch 1H bars from Polygon."""
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/hour/{from_date}/{to_date}"
        f"?adjusted=true&sort=asc&limit=5000&apiKey={POLYGON_API_KEY}"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("results", [])
    except Exception as e:
        print(f"  ! Error fetching {symbol}: {e}")
        return []


def evaluate_trade(entry_price, stop_price, target_price, bars_after_entry, direction="LONG"):
    """
    Simulate the backtest exit logic:
      1. Stop loss hit (bar low <= stop for LONG)
      2. Target hit (bar high >= target for LONG)
      3. Max hold exceeded -> close at market
    
    Returns: (exit_price, exit_reason, bars_held, max_favorable, max_adverse)
    """
    mfe = 0.0  # max favorable excursion %
    mae = 0.0  # max adverse excursion %
    
    for i, bar in enumerate(bars_after_entry):
        if i >= MAX_HOLD_BARS:
            # Max hold: close at this bar's close
            exit_price = bar["c"]
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if direction == "LONG" else (entry_price - exit_price) / entry_price * 100
            return exit_price, "MAX_HOLD", i, mfe, mae
        
        bar_high = bar["h"]
        bar_low = bar["l"]
        bar_close = bar["c"]
        
        # Track MFE/MAE
        if direction == "LONG":
            fav = (bar_high - entry_price) / entry_price * 100
            adv = (entry_price - bar_low) / entry_price * 100
        else:
            fav = (entry_price - bar_low) / entry_price * 100
            adv = (bar_high - entry_price) / entry_price * 100
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        
        # Check stop first (worse case in same bar)
        if direction == "LONG":
            if bar_low <= stop_price:
                return stop_price, "STOP_LOSS", i + 1, mfe, mae
            if bar_high >= target_price:
                return target_price, "TARGET_HIT", i + 1, mfe, mae
        else:
            if bar_high >= stop_price:
                return stop_price, "STOP_LOSS", i + 1, mfe, mae
            if bar_low <= target_price:
                return target_price, "TARGET_HIT", i + 1, mfe, mae
    
    # Not enough bars yet - trade still open
    if bars_after_entry:
        last_close = bars_after_entry[-1]["c"]
        return last_close, "STILL_OPEN", len(bars_after_entry), mfe, mae
    return entry_price, "NO_DATA", 0, 0, 0


def main():
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
    print(f"  VOLATILITY SQUEEZE — CORRECTED PERFORMANCE REPORT")
    print(f"  Using ACTUAL backtest parameters:")
    print(f"    Target: entry + 3.0 * ATR")  
    print(f"    Stop:   invalidation level from alert")
    print(f"    Max Hold: {MAX_HOLD_BARS} bars (hours)")
    print(f"  Alerts #{rows[0][0]} to #{rows[-1][0]}  |  {len(rows)} total alerts")
    print(f"  Capital per trade: ${CAPITAL_PER_TRADE:.0f}")
    print(f"{'='*80}\n")

    # Group alerts by symbol to batch API calls
    alerts_by_symbol = {}
    for r in rows:
        sym = r[2]
        if sym not in alerts_by_symbol:
            alerts_by_symbol[sym] = []
        alerts_by_symbol[sym].append(r)

    symbols = sorted(alerts_by_symbol.keys())
    print(f"Fetching hourly bars for {len(symbols)} symbols...")

    symbol_bars = {}
    for i, sym in enumerate(symbols):
        # Fetch all bars from first alert date
        first_alert_date = alerts_by_symbol[sym][0][1][:10]
        bars = fetch_bars(sym, first_alert_date)
        symbol_bars[sym] = bars
        n = len(bars)
        print(f"  [{i+1}/{len(symbols)}] {sym}: {n} bars fetched")
        # Rate limit
        if (i + 1) % 4 == 0:
            time.sleep(1.5)

    print(f"\n{'='*80}")
    print(f"  TRADE-BY-TRADE RESULTS (Backtest Parameters)")
    print(f"{'='*80}\n")

    results = []
    wins = 0
    losses = 0
    still_open = 0
    max_hold = 0
    target_hits = 0
    stop_hits = 0
    
    total_invested = 0
    total_value = 0

    print(f"{'ID':<5} {'Date':<12} {'Sym':<7} {'Scr':<4} {'Entry':>8} {'Stop':>8} {'Target':>8} {'Exit':>8} {'P&L%':>7} {'Reason':<12} {'Bars':<5}")
    print("-" * 100)

    for r in rows:
        alert_id = r[0]
        ts = r[1]
        symbol = r[2]
        direction = r[3]
        score = r[4]
        entry_price = r[5]  # trigger_close
        invalidation = r[8]
        atr = r[11]

        # Compute target and stop using BACKTEST PARAMETERS
        if atr and atr > 0:
            target_price = entry_price + 3.0 * atr if direction == "LONG" else entry_price - 3.0 * atr
        else:
            target_price = entry_price * 1.06  # fallback 6%

        stop_price = invalidation if invalidation and invalidation > 0 else entry_price - 1.5 * (atr or entry_price * 0.02)
        if direction == "SHORT":
            stop_price = entry_price + abs(entry_price - stop_price)

        # Find bars AFTER the alert timestamp
        alert_ts_ms = None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            alert_ts_ms = int(dt.timestamp() * 1000)
        except:
            pass

        bars = symbol_bars.get(symbol, [])
        
        # Find bars after entry
        bars_after = []
        if alert_ts_ms and bars:
            for b in bars:
                if b["t"] > alert_ts_ms:
                    bars_after.append(b)
        elif bars:
            # Fallback: skip first bar (entry bar), use rest
            bars_after = bars[1:]

        # Evaluate trade
        exit_price, exit_reason, bars_held, mfe, mae = evaluate_trade(
            entry_price, stop_price, target_price, bars_after, direction
        )

        # Calculate P&L
        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100

        pnl_usd = CAPITAL_PER_TRADE * (pnl_pct / 100)
        current_value = CAPITAL_PER_TRADE + pnl_usd
        total_invested += CAPITAL_PER_TRADE
        total_value += current_value

        if exit_reason == "TARGET_HIT":
            wins += 1
            target_hits += 1
            status = "WIN"
        elif exit_reason == "STOP_LOSS":
            losses += 1
            stop_hits += 1
            status = "LOSS"
        elif exit_reason == "MAX_HOLD":
            max_hold += 1
            status = "WIN" if pnl_pct > 0 else "LOSS"
            if pnl_pct > 0:
                wins += 1
            else:
                losses += 1
        elif exit_reason == "STILL_OPEN":
            still_open += 1
            status = "OPEN"
        else:
            still_open += 1
            status = "NO_DATA"

        icon = "+" if pnl_pct >= 0 else ""
        reason_icon = "  T" if exit_reason == "TARGET_HIT" else " SL" if exit_reason == "STOP_LOSS" else " MH" if exit_reason == "MAX_HOLD" else "..."
        print(
            f"{alert_id:<5} {ts[:10]:<12} {symbol:<7} {score:<4} "
            f"${entry_price:>7.2f} ${stop_price:>7.2f} ${target_price:>7.2f} "
            f"${exit_price:>7.2f} {icon}{pnl_pct:>5.1f}% "
            f"{reason_icon} {exit_reason:<12} {bars_held:<5}"
        )

        results.append({
            "id": alert_id, "symbol": symbol, "entry": entry_price,
            "stop": stop_price, "target": target_price,
            "exit": exit_price, "exit_reason": exit_reason,
            "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
            "status": status, "score": score, "ts": ts,
            "bars_held": bars_held, "mfe": mfe, "mae": mae,
            "atr": atr, "direction": direction,
        })

    # ===== SUMMARY =====
    closed = wins + losses
    total_pnl = total_value - total_invested

    print(f"\n{'='*80}")
    print(f"  SUMMARY (Using Actual Backtest Parameters)")
    print(f"{'='*80}")
    print(f"  Total Alerts:            {len(rows)}")
    print(f"  Closed Trades:           {closed}")
    print(f"  Still Open:              {still_open}")
    print()
    print(f"  TARGET_HIT (wins):       {target_hits}")
    print(f"  STOP_LOSS (losses):      {stop_hits}")
    print(f"  MAX_HOLD (time exit):    {max_hold}")
    print()
    
    if closed > 0:
        print(f"  WIN RATE (closed):       {wins}/{closed} = {wins/closed*100:.1f}%")
        print(f"  LOSS RATE (closed):      {losses}/{closed} = {losses/closed*100:.1f}%")
    
    print()
    print(f"  Total Invested:          ${total_invested:,.2f}")
    print(f"  Current Value:           ${total_value:,.2f}")
    pnl_sign = "+" if total_pnl >= 0 else ""
    print(f"  Net P&L:                 {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pnl/total_invested*100:.2f}%)")
    
    # Average win/loss
    win_pnls = [r["pnl_pct"] for r in results if r["status"] == "WIN"]
    loss_pnls = [r["pnl_pct"] for r in results if r["status"] == "LOSS"]
    if win_pnls:
        print(f"\n  Avg Win:                 +{sum(win_pnls)/len(win_pnls):.2f}%")
    if loss_pnls:
        print(f"  Avg Loss:                {sum(loss_pnls)/len(loss_pnls):.2f}%")
    if win_pnls and loss_pnls:
        avg_w = sum(win_pnls)/len(win_pnls)
        avg_l = abs(sum(loss_pnls)/len(loss_pnls))
        print(f"  Risk/Reward:             1:{avg_w/avg_l:.2f}")

    # By score
    print(f"\n{'='*80}")
    print(f"  BREAKDOWN BY SCORE")
    print(f"{'='*80}")
    score_buckets = {}
    for res in results:
        if res["status"] == "OPEN" or res["status"] == "NO_DATA":
            continue
        score = res["score"]
        bucket = f"{(score // 10) * 10}-{(score // 10) * 10 + 9}"
        if bucket not in score_buckets:
            score_buckets[bucket] = {"wins": 0, "losses": 0, "total_pnl": 0}
        if res["status"] == "WIN":
            score_buckets[bucket]["wins"] += 1
        else:
            score_buckets[bucket]["losses"] += 1
        score_buckets[bucket]["total_pnl"] += res["pnl_usd"]

    print(f"  {'Score':>7}  {'Wins':>5}  {'Losses':>6}  {'Win%':>6}  {'Total P&L':>10}")
    print(f"  {'-'*45}")
    for bucket in sorted(score_buckets.keys()):
        b = score_buckets[bucket]
        total_b = b["wins"] + b["losses"]
        win_pct = (b["wins"] / total_b * 100) if total_b > 0 else 0
        pnl_sign = "+" if b["total_pnl"] >= 0 else ""
        print(f"  {bucket:>7}  {b['wins']:>5}  {b['losses']:>6}  {win_pct:>5.1f}%  {pnl_sign}${b['total_pnl']:>8.2f}")

    # Export
    report = {
        "methodology": "Backtest parameters: target=3xATR, stop=invalidation, max_hold=50bars",
        "total_alerts": len(rows),
        "closed": closed,
        "still_open": still_open,
        "wins": wins,
        "losses": losses,
        "target_hits": target_hits,
        "stop_hits": stop_hits,
        "max_hold_exits": max_hold,
        "win_rate": wins / closed * 100 if closed > 0 else 0,
        "total_invested": total_invested,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "results": results,
    }
    with open("vol_squeeze_report_corrected.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Exported to vol_squeeze_report_corrected.json")


if __name__ == "__main__":
    main()
