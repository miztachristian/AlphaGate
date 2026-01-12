"""Run live monitoring for a universe of stocks.

Flow:
Universe CSV -> Scheduler -> Market Data -> News -> Strategy -> State -> Notify

Usage:
    python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60

Notes:
- News validation is enabled if NEWSAPI_KEY is set.
- Telegram/email notifications are enabled if corresponding env vars are set.
- Alerts are deduped with a cooldown window via SQLite (state.db).
"""

from __future__ import annotations

import argparse
import time
from typing import List, Tuple
import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from src.strategy.engine import StrategyEngine
from src.universe import load_universe_csv
from src.runner.live_runner import LiveRunConfig, run_live_universe
from src.state import SqliteStateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Live stock universe monitor")
    parser.add_argument("--universe", type=str, default="data/universe.csv", help="Path to universe CSV")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to strategy config")

    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        choices=["1m", "2m", "5m", "15m", "30m", "1h", "1d"],
        help="Candle interval (Yahoo Finance)",
    )
    parser.add_argument("--lookback-days", type=int, default=60, help="How many days to fetch")

    parser.add_argument("--interval", type=int, default=60, help="Scheduler loop interval seconds")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")

    parser.add_argument(
        "--min-confidence",
        type=str,
        default="MEDIUM",
        choices=["LOW", "MEDIUM", "HIGH"],
        help="Minimum signal confidence to alert",
    )
    parser.add_argument("--cooldown-minutes", type=int, default=120, help="Dedup cooldown per ticker/signal")

    parser.add_argument(
        "--news-query-mode",
        type=str,
        default="ticker",
        choices=["ticker", "name"],
        help="Use ticker or company name for news search",
    )
    parser.add_argument("--news-lookback-hours", type=int, default=24, help="How far back to search news")
    parser.add_argument(
        "--require-news-alignment",
        action="store_true",
        help="Only alert when news sentiment aligns with signal (LONG=positive/neutral, SHORT=negative/neutral)",
    )

    parser.add_argument("--state-db", type=str, default="state.db", help="SQLite state DB path")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Delay between API calls in seconds (free tier: 12.0 for 5 calls/min, paid: 0.5)",
    )
    parser.add_argument(
        "--skip-market-check",
        action="store_true",
        help="Skip market status check (scan regardless of market hours)",
    )
    parser.add_argument(
        "--no-extended-hours",
        action="store_true",
        help="Only scan during regular market hours (skip pre/post market)",
    )

    args = parser.parse_args()

    engine = StrategyEngine(args.config)
    state = SqliteStateStore(args.state_db)

    universe_items = load_universe_csv(args.universe)
    universe: List[Tuple[str, str | None]] = [(u.ticker, u.name) for u in universe_items]

    run_config = LiveRunConfig(
        timeframe=args.timeframe,
        interval_seconds=args.interval,
        lookback_days=args.lookback_days,
        min_confidence=args.min_confidence,
        cooldown_minutes=args.cooldown_minutes,
        news_query_mode=args.news_query_mode,
        news_lookback_hours=args.news_lookback_hours,
        news_required_alignment=bool(args.require_news_alignment),
        rate_limit_delay=args.rate_limit,
        check_market_status=not args.skip_market_check,
        allow_extended_hours=not args.no_extended_hours,
    )

    verbose = not args.quiet
    
    # Show rate limit info
    if verbose:
        stock_count = len(universe)
        time_per_cycle = stock_count * args.rate_limit
        calls_per_min = 60 / args.rate_limit if args.rate_limit > 0 else float('inf')
        print(f"📊 Monitoring {stock_count} stocks")
        print(f"⏱️  Rate limit: {args.rate_limit}s between calls ({calls_per_min:.0f} calls/min max)")
        print(f"⏳ Time per cycle: ~{time_per_cycle:.0f}s")
        if args.rate_limit < 12.0 and stock_count > 4:
            print(f"⚠️  Warning: Free tier is 5 calls/min. Use --rate-limit 12.0 or upgrade to paid plan.")
    
    cycle = 0
    while True:
        cycle += 1
        if verbose:
            from datetime import datetime
            print(f"\n{'='*60}")
            print(f"🔄 Cycle {cycle} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
        run_live_universe(universe=universe, engine=engine, config=run_config, state=state, verbose=verbose)
        if args.once:
            break
        if verbose:
            print(f"\n⏳ Sleeping {run_config.interval_seconds}s until next cycle...")
        time.sleep(run_config.interval_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
