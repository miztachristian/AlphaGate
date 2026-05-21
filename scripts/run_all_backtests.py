"""
Thorough Backtesting Runner
============================
Runs all 4 strategies across the ENTIRE cached universe (133 symbols),
computes production-grade metrics, and generates a full comparison report.

Usage:
  .venv\\Scripts\\python.exe -u scripts/run_all_backtests.py
  .venv\\Scripts\\python.exe -u scripts/run_all_backtests.py --symbols AAPL,MSFT,NVDA
  .venv\\Scripts\\python.exe -u scripts/run_all_backtests.py --max-symbols 20
"""

import os
import sys
import glob
import time
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.backtest.engine import BacktestEngine, Trade, compute_metrics, format_metrics_report
from src.strategy.engine import StrategyEngine
from src.strategy.trend_pullback import evaluate_trend_pullback_setup
from src.strategy.momentum_breakout import evaluate_momentum_breakout_setup
from src.strategy.vol_squeeze import evaluate_volatility_squeeze_setup
from src.strategy.ensemble import evaluate_multi_strategy_ensemble


# ──────────────────────────────────────────────────────────────────────────
# Strategy wrappers
# ──────────────────────────────────────────────────────────────────────────
def make_strat1_wrapper(timeframe):
    def fn(df_slice, ind_slice):
        return evaluate_trend_pullback_setup(
            df=df_slice, rsi=ind_slice['rsi_values'], atr=ind_slice['atr'],
            ema50=ind_slice['ema_50'], ema200=ind_slice['ema_200'],
            bb_lower=ind_slice['bb_lower'], bb_middle=ind_slice['bb_middle'],
            bb_upper=ind_slice['bb_upper'], volume_sma=ind_slice['volume_sma'],
            timeframe=timeframe,
        )
    return fn


def make_strat2_wrapper(timeframe):
    def fn(df_slice, ind_slice):
        return evaluate_momentum_breakout_setup(
            df=df_slice, rsi=ind_slice['rsi_values'], atr=ind_slice['atr'],
            ema200=ind_slice['ema_200'], macd_histogram=ind_slice['macd_histogram'],
            volume_sma=ind_slice['volume_sma'], timeframe=timeframe,
        )
    return fn


def make_strat3_wrapper(timeframe):
    def fn(df_slice, ind_slice):
        return evaluate_volatility_squeeze_setup(
            df=df_slice, rsi=ind_slice['rsi_values'], atr=ind_slice['atr'],
            ema50=ind_slice['ema_50'], ema200=ind_slice['ema_200'],
            bb_lower=ind_slice['bb_lower'], bb_middle=ind_slice['bb_middle'],
            bb_upper=ind_slice['bb_upper'], volume_sma=ind_slice['volume_sma'],
            timeframe=timeframe,
        )
    return fn


def make_strat4_wrapper(timeframe):
    def fn(df_slice, ind_slice):
        results = evaluate_multi_strategy_ensemble(df_slice, ind_slice, timeframe)
        for r in results:
            if getattr(r, 'status', None) and r.status.value == "SETUP_TRIGGERED":
                return r
        return results[0] if results else None
    return fn


STRATEGIES = {
    1: ("Trend Pullback", make_strat1_wrapper),
    2: ("Momentum Breakout", make_strat2_wrapper),
    3: ("Volatility Squeeze", make_strat3_wrapper),
    4: ("Multi-Strategy Ensemble", make_strat4_wrapper),
}


# ──────────────────────────────────────────────────────────────────────────
# Data loader
# ──────────────────────────────────────────────────────────────────────────
def load_parquet(file_path: str) -> pd.DataFrame:
    """Load a parquet file and ensure it has a proper DatetimeIndex."""
    df = pd.read_parquet(file_path)

    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ['timestamp', 'date', 'time', 'datetime']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
                df.set_index(col, inplace=True)
                break

    df = df.sort_index()

    # Ensure required columns exist
    required = {'open', 'high', 'low', 'close', 'volume'}
    if not required.issubset(set(df.columns)):
        return None
    return df


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Thorough multi-strategy backtester")
    parser.add_argument("--cache-dir", type=str, default="cache/parquet",
                        help="Directory with parquet files")
    parser.add_argument("--timeframe", type=str, default="1h",
                        help="Timeframe suffix to look for (default: 1h)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols to test (default: all)")
    parser.add_argument("--max-symbols", type=int, default=None,
                        help="Max number of symbols to test")
    parser.add_argument("--capital", type=float, default=10000.0,
                        help="Initial capital per strategy")
    parser.add_argument("--fee-bps", type=float, default=15.0,
                        help="One-way fee in basis points")
    parser.add_argument("--max-hold", type=int, default=30,
                        help="Max bars to hold a trade")
    parser.add_argument("--trail-atr", type=float, default=1.5,
                        help="Trailing stop ATR multiplier")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--strategies", type=str, default="1,2,3,4",
                        help="Comma-separated strategy IDs to test")

    args = parser.parse_args()

    # Discover files
    pattern = os.path.join(args.cache_dir, f"*_{args.timeframe}.parquet")
    files = sorted(glob.glob(pattern))

    if args.symbols:
        wanted = set(args.symbols.upper().split(","))
        files = [f for f in files if os.path.basename(f).split('_')[0] in wanted]

    if args.max_symbols:
        files = files[:args.max_symbols]

    if not files:
        print(f"No parquet files found matching {pattern}")
        return

    strat_ids = [int(x) for x in args.strategies.split(",")]

    print("=" * 60)
    print("  THOROUGH BACKTEST ENGINE")
    print("=" * 60)
    print(f"  Symbols:       {len(files)}")
    print(f"  Timeframe:     {args.timeframe}")
    print(f"  Strategies:    {[STRATEGIES[s][0] for s in strat_ids]}")
    print(f"  Capital:       ${args.capital:,.0f}")
    print(f"  Fee:           {args.fee_bps} bps (one-way)")
    print(f"  Max Hold:      {args.max_hold} bars")
    print(f"  Trailing ATR:  {args.trail_atr}x")
    print("=" * 60)
    print()

    # Initialise strategy engine for indicator calculation
    se = StrategyEngine(args.config)

    # Aggregate trades per strategy
    all_trades = {sid: [] for sid in strat_ids}
    all_equity = {sid: [] for sid in strat_ids}
    per_symbol_metrics = {sid: {} for sid in strat_ids}

    total_start = time.time()

    for file_idx, file_path in enumerate(files):
        symbol = os.path.basename(file_path).split('_')[0]
        print(f"[{file_idx + 1}/{len(files)}] {symbol}", flush=True)

        df = load_parquet(file_path)
        if df is None or len(df) < 300:
            print(f"  Skipped (insufficient data: {len(df) if df is not None else 0} bars)")
            continue

        # Pre-compute indicators once per symbol
        indicators = se.calculate_all_indicators(df)

        for sid in strat_ids:
            strat_name, wrapper_factory = STRATEGIES[sid]
            eval_fn = wrapper_factory(args.timeframe)

            bt = BacktestEngine(
                initial_capital=args.capital,
                fee_bps=args.fee_bps,
                trailing_stop_atr=args.trail_atr,
                max_hold_bars=args.max_hold,
            )

            eq_curve = bt.run(
                df=df,
                strategy_eval_func=eval_fn,
                indicators=indicators,
                symbol=symbol,
                min_bars=200,
                silent=True,
            )

            # Collect trades
            all_trades[sid].extend(bt.trades)

            # Collect equity curve
            if len(eq_curve) > 0:
                eq_curve['symbol'] = symbol
                all_equity[sid].append(eq_curve)

            # Per-symbol metrics
            m = bt.get_metrics(eq_curve)
            if m.get("total_trades", 0) > 0:
                per_symbol_metrics[sid][symbol] = m

    elapsed = time.time() - total_start
    print(f"\nBacktest complete in {elapsed:.1f}s\n")

    # ── Generate reports ──
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    comparison_rows = []

    for sid in strat_ids:
        strat_name = STRATEGIES[sid][0]
        trades = all_trades[sid]

        # Combine equity curves
        if all_equity[sid]:
            combined_eq = pd.concat(all_equity[sid], ignore_index=True)
            # Create aggregate equity by averaging drawdowns
            agg_eq = combined_eq.groupby('time').agg({'equity': 'mean', 'drawdown_pct': 'mean'}).reset_index()
        else:
            agg_eq = pd.DataFrame(columns=['time', 'equity', 'drawdown_pct'])

        # Overall metrics
        overall = compute_metrics(trades, agg_eq, args.capital)
        overall['strategy'] = strat_name

        # Print
        print(format_metrics_report(f"Strategy {sid}: {strat_name}", overall))

        comparison_rows.append({
            "Strategy": f"S{sid}: {strat_name}",
            "Trades": overall.get("total_trades", 0),
            "WinRate%": overall.get("win_rate", 0),
            "AvgWin%": overall.get("avg_win_pct", 0),
            "AvgLoss%": overall.get("avg_loss_pct", 0),
            "R:R": overall.get("risk_reward", 0),
            "ProfitFactor": overall.get("profit_factor", 0),
            "Expectancy%": overall.get("expectancy_pct", 0),
            "TotalReturn%": overall.get("total_return_pct", 0),
            "Sharpe": overall.get("sharpe", 0),
            "Sortino": overall.get("sortino", 0),
            "MaxDD%": overall.get("max_drawdown_pct", 0),
            "AvgMFE%": overall.get("avg_mfe_pct", 0),
            "AvgMAE%": overall.get("avg_mae_pct", 0),
            "AvgBarsHeld": overall.get("avg_bars_held", 0),
        })

        # Save per-strategy trade log
        trades_df = pd.DataFrame([t.to_dict() for t in trades if t.status == "CLOSED"])
        if len(trades_df) > 0:
            trades_file = f"reports/bt_trades_strat{sid}_{timestamp}.csv"
            trades_df.to_csv(trades_file, index=False)

        # Save per-symbol breakdown
        if per_symbol_metrics[sid]:
            sym_rows = []
            for sym, m in per_symbol_metrics[sid].items():
                sym_rows.append({
                    "Symbol": sym,
                    "Trades": m["total_trades"],
                    "WinRate%": m["win_rate"],
                    "AvgWin%": m["avg_win_pct"],
                    "AvgLoss%": m["avg_loss_pct"],
                    "R:R": m["risk_reward"],
                    "TotalReturn%": m["total_return_pct"],
                    "ProfitFactor": m["profit_factor"],
                    "Sharpe": m["sharpe"],
                    "MaxDD%": m["max_drawdown_pct"],
                })
            sym_df = pd.DataFrame(sym_rows).sort_values("TotalReturn%", ascending=False)
            sym_file = f"reports/bt_by_symbol_strat{sid}_{timestamp}.csv"
            sym_df.to_csv(sym_file, index=False)

    # Overall comparison
    comp_df = pd.DataFrame(comparison_rows)
    comp_file = f"reports/bt_comparison_{timestamp}.csv"
    comp_df.to_csv(comp_file, index=False)

    print("\n" + "=" * 60)
    print("  STRATEGY COMPARISON")
    print("=" * 60)
    print(comp_df.to_string(index=False))
    print("=" * 60)
    print(f"\nAll reports saved to reports/ directory")
    print(f"  Comparison:   {comp_file}")
    for sid in strat_ids:
        print(f"  Strat {sid} trades: reports/bt_trades_strat{sid}_{timestamp}.csv")
        print(f"  Strat {sid} by sym: reports/bt_by_symbol_strat{sid}_{timestamp}.csv")


if __name__ == "__main__":
    main()
