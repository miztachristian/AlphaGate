"""
Backtest Script
Run historical backtests on different strategies.
"""

import sys
import os
import argparse
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.engine import BacktestEngine
from src.strategy.engine import StrategyEngine
from src.strategy.trend_pullback import evaluate_trend_pullback_setup
from src.strategy.momentum_breakout import evaluate_momentum_breakout_setup
from src.strategy.vol_squeeze import evaluate_volatility_squeeze_setup
from src.strategy.ensemble import evaluate_multi_strategy_ensemble
from src.marketdata.stocks import fetch_stock_ohlcv

def main():
    parser = argparse.ArgumentParser(description="Run backtest on a specific strategy.")
    parser.add_argument("--symbol", type=str, default="AAPL", help="Stock ticker symbol")
    parser.add_argument("--timeframe", type=str, default="1h", choices=["15m", "1h", "4h", "1d"])
    parser.add_argument("--days", type=int, default=365, help="Days of historical data")
    parser.add_argument("--strategy", type=int, default=1, choices=[1, 2, 3, 4], help="Strategy to re-test")
    parser.add_argument("--config", type=str, default="config.yaml")
    
    args = parser.parse_args()
    
    print(f"Fetching data for {args.symbol} ({args.timeframe}) over last {args.days} days...")
    df = fetch_stock_ohlcv(args.symbol, interval=args.timeframe, lookback_days=args.days)
    
    if df is None or len(df) == 0:
        print("Failed to fetch data.")
        return
        
    print(f"Data fetched: {len(df)} bars.")
    
    # Initialize strategy engine to calculate indicators
    se = StrategyEngine(args.config)
    indicators = se.calculate_all_indicators(df)
    
    bt = BacktestEngine(initial_capital=10000.0, fee_bps=15.0)
    
    print(f"Running strategy {args.strategy} backtest...")
    
    if args.strategy == 1:
        # Trend Pullback
        def eval_wrapper(df_slice, ind_slice):
            return evaluate_trend_pullback_setup(
                df=df_slice,
                rsi=ind_slice['rsi_values'],
                atr=ind_slice['atr'],
                ema50=ind_slice['ema_50'],
                ema200=ind_slice['ema_200'],
                bb_lower=ind_slice['bb_lower'],
                bb_middle=ind_slice['bb_middle'],
                bb_upper=ind_slice['bb_upper'],
                volume_sma=ind_slice['volume_sma'],
                timeframe=args.timeframe
            )
    elif args.strategy == 2:
        # Momentum Breakout
        def eval_wrapper(df_slice, ind_slice):
            return evaluate_momentum_breakout_setup(
                df=df_slice,
                rsi=ind_slice['rsi_values'],
                atr=ind_slice['atr'],
                ema200=ind_slice['ema_200'],
                macd_histogram=ind_slice['macd_histogram'],
                volume_sma=ind_slice['volume_sma'],
                timeframe=args.timeframe
            )
    elif args.strategy == 3:
        # Volatility Squeeze
        def eval_wrapper(df_slice, ind_slice):
            return evaluate_volatility_squeeze_setup(
                df=df_slice,
                rsi=ind_slice['rsi_values'],
                atr=ind_slice['atr'],
                ema50=ind_slice['ema_50'],
                ema200=ind_slice['ema_200'],
                bb_lower=ind_slice['bb_lower'],
                bb_middle=ind_slice['bb_middle'],
                bb_upper=ind_slice['bb_upper'],
                volume_sma=ind_slice['volume_sma'],
                timeframe=args.timeframe
            )
    elif args.strategy == 4:
        # Multi-Strategy Ensemble
        def eval_wrapper(df_slice, ind_slice):
            # Evaluate using ensemble
            results = evaluate_multi_strategy_ensemble(df_slice, ind_slice, args.timeframe)
            # Pick first triggered
            for r in results:
                if getattr(r, 'status', None) and r.status.value == "SETUP_TRIGGERED":
                    return r
            return results[0] if results else None

    equity_curve = bt.run(df, eval_wrapper, indicators, min_bars=200)
    
    bt.print_summary()
    
    # Output to CSV
    os.makedirs('reports', exist_ok=True)
    report_file = f"reports/backtest_{args.symbol}_{args.timeframe}_strat{args.strategy}.csv"
    if bt.trades:
        trades_df = pd.DataFrame([{
            "Setup": t.setup,
            "EntryTime": t.entry_time,
            "ExitTime": t.exit_time,
            "EntryPrice": t.entry_price,
            "ExitPrice": t.exit_price,
            "PnL": t.pnl,
            "PnLPct": t.pnl_pct * 100,
            "Reason": t.reason
        } for t in bt.trades])
        trades_df.to_csv(report_file, index=False)
        print(f"Detailed trades saved to {report_file}")

if __name__ == "__main__":
    main()
