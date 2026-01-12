#!/usr/bin/env python3
"""
Analyze Single Ticker Script

Integration test / CLI tool to analyze a single ticker and print either:
- NOT_EVALUATED with reason
- Full structured alert object

Usage:
    python analyze_single.py AAPL
    python analyze_single.py AAPL --timeframe 4h
    python analyze_single.py AAPL --timeframe 1h --verbose
    python analyze_single.py AAPL --json

Environment:
    POLYGON_API_KEY: Required for fetching market data
    NEWSAPI_KEY: Optional for news risk labeling
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.marketdata import fetch_stock_ohlcv
from src.news import fetch_company_news, assess_news_risk
from src.strategy.engine import StrategyEngine, EvaluationStatus
from src.strategy.mean_reversion import SetupStatus
from src.state import SqliteStateStore


def analyze_ticker(
    symbol: str,
    timeframe: str = "1h",
    lookback_days: int = 90,
    verbose: bool = False,
    output_json: bool = False,
    log_alerts: bool = True,
) -> dict:
    """
    Analyze a single ticker for mean reversion setup.
    
    Args:
        symbol: Ticker symbol (e.g., 'AAPL')
        timeframe: Candle timeframe (e.g., '1h', '4h')
        lookback_days: Days of historical data to fetch
        verbose: Print detailed progress
        output_json: Return JSON-formatted output
        log_alerts: Log triggered alerts to SQLite
    
    Returns:
        Analysis result dict
    """
    result = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "NOT_EVALUATED",
        "reason": None,
        "alert": None,
    }
    
    # Check API key
    if not os.getenv("POLYGON_API_KEY"):
        result["reason"] = "POLYGON_API_KEY environment variable not set"
        return result
    
    if verbose:
        print(f"[{symbol}] Fetching {timeframe} data ({lookback_days} days)...")
    
    # Fetch market data
    try:
        df = fetch_stock_ohlcv(
            ticker=symbol,
            interval=timeframe,
            lookback_days=lookback_days,
        )
    except Exception as e:
        result["reason"] = f"Data fetch error: {str(e)}"
        return result
    
    if df is None or df.empty:
        result["reason"] = "No data returned from API"
        return result
    
    if verbose:
        print(f"[{symbol}] Fetched {len(df)} bars")
    
    # Initialize strategy engine
    try:
        engine = StrategyEngine(config_path="config.yaml")
    except Exception as e:
        result["reason"] = f"Config error: {str(e)}"
        return result
    
    # Run analysis
    if verbose:
        print(f"[{symbol}] Running mean reversion analysis...")
    
    analysis = engine.analyze_with_mean_reversion(df, interval=timeframe)
    
    # Check evaluation status
    if analysis["status"] == EvaluationStatus.NOT_EVALUATED:
        result["reason"] = analysis.get("reason", "Unknown")
        result["data_quality"] = analysis.get("data_quality")
        return result
    
    # Get setup result
    setup_result = analysis.get("setup_result")
    if setup_result is None:
        result["reason"] = "No setup result"
        return result
    
    if setup_result.status == SetupStatus.NOT_EVALUATED:
        result["reason"] = setup_result.reason
        return result
    
    if setup_result.status == SetupStatus.EVALUATED_NO_SETUP:
        result["status"] = "EVALUATED_NO_SETUP"
        result["reason"] = setup_result.reason
        result["price"] = analysis.get("price")
        result["indicators"] = analysis.get("indicators")
        return result
    
    # SETUP_TRIGGERED - fetch news and build full alert
    result["status"] = "SETUP_TRIGGERED"
    alert = setup_result.alert
    
    # Fetch news risk
    if verbose:
        print(f"[{symbol}] Fetching news for risk assessment...")
    
    try:
        news_items = fetch_company_news(symbol, lookback_hours=24, max_items=10)
        news_risk = assess_news_risk(news_items)
        alert.news_risk = news_risk.risk_level
        alert.news_reasons = news_risk.reasons
    except Exception as e:
        if verbose:
            print(f"[{symbol}] News fetch error: {e}")
        alert.news_risk = "UNKNOWN"
        alert.news_reasons = [f"Could not fetch news: {str(e)}"]
    
    # Check cooldown
    state = SqliteStateStore()
    last_alert_time = state.get_last_alert_time(symbol, timeframe, "LONG")
    if last_alert_time:
        cooldown_minutes = engine.config.get("alerts", {}).get("cooldown_minutes", 60)
        minutes_ago = (datetime.utcnow() - last_alert_time).total_seconds() / 60
        if minutes_ago < cooldown_minutes:
            alert.cooldown_active = True
            alert.last_alert_ago = f"{int(minutes_ago)} minutes"
    
    # Log alert for calibration
    if log_alerts and not alert.cooldown_active:
        try:
            state.log_alert_for_calibration(
                symbol=symbol,
                timeframe=timeframe,
                setup=alert.setup,
                direction=alert.direction,
                score=alert.score,
                trigger_close=alert.trigger_close,
                rsi=alert.rsi,
                rsi_prev=alert.rsi_prev,
                atr=alert.atr,
                atr_pct=alert.atr_pct,
                ema200=alert.ema200,
                ema200_slope=alert.ema200_slope,
                trend_regime=alert.trend_regime,
                vol_regime=alert.vol_regime,
                bb_lower=alert.bb_lower,
                bb_middle=alert.bb_middle,
                bb_upper=alert.bb_upper,
                entry_zone_low=alert.entry_zone[0],
                entry_zone_high=alert.entry_zone[1],
                invalidation=alert.invalidation,
                news_risk=alert.news_risk,
                news_reasons=alert.news_reasons,
                alert_payload=alert.to_dict(),
            )
            if verbose:
                print(f"[{symbol}] Alert logged for calibration")
        except Exception as e:
            if verbose:
                print(f"[{symbol}] Failed to log alert: {e}")
    
    result["alert"] = alert.to_dict()
    result["price"] = analysis.get("price")
    result["indicators"] = analysis.get("indicators")
    
    return result


def format_result(result: dict, verbose: bool = False) -> str:
    """Format result for human-readable output."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"ANALYSIS: {result['symbol']} ({result['timeframe']})")
    lines.append(f"Timestamp: {result['timestamp']}")
    lines.append("=" * 70)
    
    status = result["status"]
    
    if status == "NOT_EVALUATED":
        lines.append(f"⚠️  Status: NOT_EVALUATED")
        lines.append(f"   Reason: {result.get('reason', 'Unknown')}")
        
        dq = result.get("data_quality")
        if dq and dq.get("warnings"):
            lines.append(f"   Data Quality Warnings:")
            for w in dq["warnings"]:
                lines.append(f"     - {w}")
    
    elif status == "EVALUATED_NO_SETUP":
        lines.append(f"📊 Status: EVALUATED_NO_SETUP")
        lines.append(f"   Price: ${result.get('price', 0):.2f}")
        lines.append(f"   Reason: {result.get('reason', 'Unknown')}")
        
        if verbose and result.get("indicators"):
            ind = result["indicators"]
            lines.append("")
            lines.append("   Indicators:")
            lines.append(f"     RSI: {ind.get('rsi', 'N/A'):.1f}")
            lines.append(f"     ATR: ${ind.get('atr', 'N/A'):.2f} ({ind.get('atr_pct', 'N/A'):.2f}%)")
            lines.append(f"     EMA200: ${ind.get('ema200', 'N/A'):.2f}")
    
    elif status == "SETUP_TRIGGERED":
        alert = result.get("alert", {})
        
        lines.append(f"🚨 Status: SETUP_TRIGGERED")
        lines.append("")
        lines.append(f"   Setup: {alert.get('setup')}")
        lines.append(f"   Direction: {alert.get('direction')}")
        lines.append(f"   Score: {alert.get('score')}/100")
        lines.append("")
        
        lines.append("   📊 Price Levels:")
        lines.append(f"      Trigger: ${alert.get('trigger_close', 0):.2f}")
        entry = alert.get('entry_zone', [0, 0])
        lines.append(f"      Entry Zone: ${entry[0]:.2f} - ${entry[1]:.2f}")
        lines.append(f"      Invalidation: ${alert.get('invalidation', 0):.2f}")
        lines.append(f"      Hold Window: {alert.get('hold_window')}")
        lines.append("")
        
        lines.append("   ✅ Evidence:")
        for i, ev in enumerate(alert.get("evidence", []), 1):
            lines.append(f"      {i}. {ev}")
        lines.append("")
        
        lines.append("   🎯 Regimes:")
        lines.append(f"      Volatility: {alert.get('vol_regime')}")
        lines.append(f"      Trend: {alert.get('trend_regime')}")
        lines.append("")
        
        lines.append(f"   📰 News Risk: {alert.get('news_risk')}")
        for reason in alert.get("news_reasons", []):
            lines.append(f"      - {reason}")
        
        if alert.get("cooldown_active"):
            lines.append("")
            lines.append(f"   ⏰ Cooldown Active (last: {alert.get('last_alert_ago')})")
        
        if verbose:
            lines.append("")
            lines.append("   📈 Indicator Values:")
            lines.append(f"      RSI: {alert.get('rsi_prev', 0):.1f} -> {alert.get('rsi', 0):.1f}")
            lines.append(f"      ATR: ${alert.get('atr', 0):.2f} ({alert.get('atr_pct', 0):.2f}%)")
            lines.append(f"      EMA200: ${alert.get('ema200', 0):.2f} (slope: {alert.get('ema200_slope', 0):.2f})")
            lines.append(f"      BB: ${alert.get('bb_lower', 0):.2f} / ${alert.get('bb_middle', 0):.2f} / ${alert.get('bb_upper', 0):.2f}")
    
    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a single ticker for mean reversion setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python analyze_single.py AAPL
    python analyze_single.py MSFT --timeframe 4h
    python analyze_single.py TSLA --verbose
    python analyze_single.py NVDA --json

Environment Variables:
    POLYGON_API_KEY  - Required for market data
    NEWSAPI_KEY      - Optional for news risk assessment
        """
    )
    
    parser.add_argument("symbol", help="Stock ticker symbol (e.g., AAPL)")
    parser.add_argument("--timeframe", "-t", default="1h", 
                       choices=["1h", "4h", "1d"],
                       help="Candle timeframe (default: 1h)")
    parser.add_argument("--lookback", "-l", type=int, default=90,
                       help="Days of historical data (default: 90)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed output")
    parser.add_argument("--json", "-j", action="store_true",
                       help="Output as JSON")
    parser.add_argument("--no-log", action="store_true",
                       help="Don't log alerts to database")
    
    args = parser.parse_args()
    
    result = analyze_ticker(
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback_days=args.lookback,
        verbose=args.verbose,
        output_json=args.json,
        log_alerts=not args.no_log,
    )
    
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_result(result, verbose=args.verbose))


if __name__ == "__main__":
    main()
