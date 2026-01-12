"""Live runner for the universe.

Flow:
Universe CSV -> Scheduler loop -> Fetch market data -> Compute strategy -> 
    (if SETUP_TRIGGERED) -> Fetch news -> Attach risk label -> State store -> Notify

v3: News is now fetched ONLY after a setup triggers, using Polygon.io News API.
v4: Cache-backed OHLCV fetching with metrics for performance optimization.
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from ..marketdata import (
    fetch_stock_ohlcv,
    fetch_stock_ohlcv_cached,
    CACHE_AVAILABLE,
    should_scan_market,
    format_market_status_message,
)
from ..marketdata.scan_metrics import (
    start_scan_metrics,
    get_current_metrics,
    finish_scan_metrics,
)
from ..news import (
    fetch_ticker_news,
    assess_news_risk,
    create_unknown_risk_result,
    get_lookback_hours_for_timeframe,
    NewsRiskResult,
)
from ..state import SqliteStateStore
from ..strategy.engine import StrategyEngine, EvaluationStatus
from ..strategy.mean_reversion import SetupStatus
from ..notify import MultiNotifier, TelegramNotifier, EmailNotifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveRunConfig:
    timeframe: str
    interval_seconds: int
    lookback_days: int
    min_confidence: str
    cooldown_minutes: int
    news_query_mode: str  # "ticker" | "name" (kept for compatibility, ticker recommended)
    news_lookback_hours: int
    news_required_alignment: bool  # Deprecated - news no longer vetoes, only labels
    rate_limit_delay: float = 1.0  # Delay between API calls in seconds
    use_cache: bool = True  # Use cache-backed fetching (v4)
    max_workers: int = 32  # Concurrent fetch threads
    check_market_status: bool = True  # Check if market is open before scanning
    allow_extended_hours: bool = True  # Allow scanning during pre/post market


def _get_min_bars_for_timeframe(timeframe: str) -> int:
    """Get minimum bars required for a timeframe from config.yaml."""
    import yaml
    from pathlib import Path
    
    # Default fallbacks
    defaults = {"1h": 350, "4h": 250, "1d": 200}
    
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    if not config_path.exists():
        return defaults.get(timeframe, 220)
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        min_bars_config = config.get("data_quality", {}).get("min_bars", {})
        return min_bars_config.get(timeframe, defaults.get(timeframe, 220))
    except Exception:
        return defaults.get(timeframe, 220)


def _confidence_rank(conf: str) -> int:
    order = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    return order.get((conf or "").upper(), 0)


def _build_notifier() -> MultiNotifier:
    notifiers = []
    tel = TelegramNotifier()
    if tel.enabled():
        notifiers.append(tel)
    email = EmailNotifier()
    if email.enabled():
        notifiers.append(email)
    return MultiNotifier(notifiers=notifiers)


def _fetch_news_risk(ticker: str, timeframe: str, lookback_hours: Optional[int] = None) -> NewsRiskResult:
    """
    Fetch news and compute risk label for a ticker.
    
    Only called AFTER a setup triggers.
    
    Args:
        ticker: Stock ticker symbol
        timeframe: Candle timeframe for determining default lookback
        lookback_hours: Override lookback hours (optional)
    
    Returns:
        NewsRiskResult with risk level and reasons
    """
    if lookback_hours is None:
        lookback_hours = get_lookback_hours_for_timeframe(timeframe)
    
    try:
        news_items = fetch_ticker_news(ticker, lookback_hours=lookback_hours, limit=20)
        risk_result = assess_news_risk(news_items)
        return risk_result
    except Exception as e:
        logger.warning(f"News fetch failed for {ticker}: {e}")
        return create_unknown_risk_result(f"news_fetch_error: {str(e)[:50]}")


def _format_alert_message(
    ticker: str,
    analysis: dict,
    news_risk: NewsRiskResult,
    timeframe: str,
) -> tuple[str, str]:
    """
    Format alert title and message.
    
    Returns:
        Tuple of (title, message)
    """
    setup_result = analysis.get('setup_result')
    alert = setup_result.alert if setup_result else None
    
    if alert:
        title = f"🔔 {alert.direction} {ticker} | Score: {alert.score} | {alert.setup}"
        
        parts = [
            f"⏱️  Timeframe: {timeframe}",
            f"💰 Trigger Price: ${alert.trigger_close:.2f}",
            f"📍 Entry Zone: ${alert.entry_zone[0]:.2f} - ${alert.entry_zone[1]:.2f}",
            f"🛑 Invalidation: ${alert.invalidation:.2f}",
            f"⏳ Hold Window: {alert.hold_window}",
            "",
            "📊 Evidence:",
        ]
        for ev in alert.evidence[:5]:  # Max 5 evidence bullets
            parts.append(f"  • {ev}")
        
        parts.extend([
            "",
            f"📰 News Risk: {news_risk.risk_level}",
        ])
        
        if news_risk.reasons:
            parts.append(f"   Reasons: {', '.join(news_risk.reasons[:2])}")
        
        if news_risk.top_headline:
            parts.append(f"   Top: {news_risk.top_headline[:80]}...")
            if news_risk.top_headline_source:
                parts.append(f"   Source: {news_risk.top_headline_source} ({news_risk.top_headline_time})")
        
        parts.extend([
            "",
            f"📈 Indicators:",
            f"   RSI: {alert.rsi:.1f} (prev: {alert.rsi_prev:.1f})",
            f"   ATR%: {alert.atr_pct:.2f}%",
            f"   Vol Regime: {alert.vol_regime}",
            f"   Trend Regime: {alert.trend_regime}",
        ])
        
        message = "\n".join(parts)
    else:
        # Fallback for legacy analysis format
        title = f"ALERT {ticker}"
        message = f"Analysis: {analysis}"
    
    return title, message


def run_live_universe_v2(
    universe: Iterable[tuple[str, str | None]],
    engine: StrategyEngine,
    config: LiveRunConfig,
    state: SqliteStateStore,
    verbose: bool = True,
) -> bool:
    """
    Run live monitoring using v2 mean reversion analysis.
    
    News is fetched ONLY after a setup triggers (downstream-only).
    v4: Cache-backed OHLCV fetching with concurrent requests.
    v5: Market status check - skips scan when market is closed.
    
    Args:
        universe: Iterable of (ticker, company_name) tuples
        engine: StrategyEngine instance
        config: LiveRunConfig settings
        state: SqliteStateStore for cooldown tracking
        verbose: Print verbose output
    
    Returns:
        bool: True if scan was executed, False if skipped (market closed)
    """
    # Check market status before scanning
    if config.check_market_status:
        should_scan, market_status = should_scan_market(
            allow_extended_hours=config.allow_extended_hours,
            fallback_on_error=True,  # If API fails, proceed with scan
        )
        
        if market_status and verbose:
            print(format_market_status_message(market_status))
            print()
        
        if not should_scan:
            if verbose:
                print("⏸️  Market is closed. Skipping scan cycle.")
                if market_status:
                    print(f"   Next scan will check again in {config.interval_seconds}s")
            logger.info(f"Scan skipped: market={market_status.market if market_status else 'unknown'}")
            return False
    
    notifier = _build_notifier()
    
    # Convert universe to list for batch processing
    universe_list = list(universe)
    
    # Decide on caching strategy
    use_cache = config.use_cache and CACHE_AVAILABLE
    
    if use_cache and verbose:
        print(f"📦 Cache-backed fetching enabled ({len(universe_list)} tickers)")
    elif verbose:
        print(f"⚠️  Cache not available, using direct API calls")
    
    # Start scan metrics for the entire scan cycle
    metrics = start_scan_metrics(total_tickers=len(universe_list))
    
    # Fetch data for all tickers (batch or sequential)
    ohlcv_data = {}
    
    if use_cache:
        try:
            from ..marketdata import fetch_stock_ohlcv_batch
            
            if verbose:
                print(f"🚀 Starting batch fetch...")
            
            tickers = [t for t, _ in universe_list]
            ohlcv_data = fetch_stock_ohlcv_batch(
                tickers=tickers,
                interval=config.timeframe,
                lookback_days=config.lookback_days,
                max_workers=config.max_workers,
            )
            
            if verbose:
                # Print interim metrics
                current = get_current_metrics()
                if current:
                    print(f"\n📊 Fetch Summary:")
                    print(f"   Cache hits: {current.cache_hits}")
                    print(f"   REST calls: {current.rest_calls}")
                    print(f"   Errors: {current.rest_errors}")
                    print(f"   Duration so far: {current.duration_seconds:.1f}s")
                    print()
        except Exception as e:
            logger.error(f"Batch fetch failed: {e}")
            use_cache = False  # Fall back to sequential
    
    # Get min_bars from config for this timeframe
    min_bars = _get_min_bars_for_timeframe(config.timeframe)
    
    # Process tickers
    for ticker, name in universe_list:
        try:
            # Get data (from batch or fetch directly)
            if ticker in ohlcv_data:
                df = ohlcv_data[ticker]
            elif use_cache:
                # Fetch single ticker with cache
                df = fetch_stock_ohlcv_cached(
                    ticker=ticker,
                    interval=config.timeframe,
                    lookback_days=config.lookback_days,
                )
            else:
                # Fall back to direct API (no cache)
                df = fetch_stock_ohlcv(
                    ticker=ticker,
                    interval=config.timeframe,
                    lookback_days=config.lookback_days,
                )
                time.sleep(config.rate_limit_delay)
                
        except Exception as e:
            if verbose:
                print(f"[{ticker}] ❌ Data fetch error: {e}")
            continue

        # Need sufficient bars for indicators (from config.yaml)
        if df is None or df.empty or len(df) < min_bars:
            if verbose:
                print(f"[{ticker}] ⏭️  Skipped (only {len(df) if df is not None else 0}/{min_bars} bars)")
            current = get_current_metrics()
            if current:
                current.record_not_evaluated("insufficient_bars")
            continue
        
        # Track ticker scanned
        current = get_current_metrics()
        if current:
            current.record_ticker_scanned()

        # Run v2 analysis (mean reversion)
        analysis = engine.analyze_with_mean_reversion(df, interval=config.timeframe)
        
        # Check evaluation status
        if analysis['status'] == EvaluationStatus.NOT_EVALUATED:
            if verbose:
                print(f"[{ticker}] ⏭️  NOT_EVALUATED: {analysis.get('reason', 'unknown')}")
            continue
        
        setup_result = analysis.get('setup_result')
        if not setup_result:
            if verbose:
                print(f"[{ticker}] ⏭️  No setup result")
            continue
        
        # Check setup status
        if setup_result.status == SetupStatus.NOT_EVALUATED:
            if verbose:
                print(f"[{ticker}] ⏭️  Setup NOT_EVALUATED: {setup_result.reason}")
            continue
        
        if setup_result.status == SetupStatus.EVALUATED_NO_SETUP:
            if verbose:
                price = analysis.get('price', 0)
                print(f"[{ticker}] ${price:.2f} | No setup")
            continue
        
        # SETUP_TRIGGERED - now we fetch news
        alert = setup_result.alert
        if not alert:
            continue
        
        if verbose:
            print(f"[{ticker}] 🎯 SETUP TRIGGERED: {alert.setup} Score={alert.score}")
        
        # Check cooldown
        if state.recently_alerted(ticker, config.timeframe, alert.direction, 
                                   cooldown_minutes=config.cooldown_minutes):
            if verbose:
                print(f"[{ticker}] ⏭️  Skipped (alerted recently)")
            continue
        
        # NOW fetch news (only for triggered setups)
        news_risk = _fetch_news_risk(ticker, config.timeframe, config.news_lookback_hours)
        
        # Update alert with news risk
        alert.news_risk = news_risk.risk_level
        alert.news_reasons = news_risk.reasons
        
        # Format message
        title, message = _format_alert_message(ticker, analysis, news_risk, config.timeframe)
        
        # Print to console
        if verbose:
            print(f"\n{'='*60}")
            print(f"🚨 {title}")
            print(f"{'='*60}")
            print(message)
            print(f"{'='*60}\n")
        
        # Send notification
        if notifier.notifiers:
            notifier.send(title, message)
        elif verbose:
            print(f"[{ticker}] ℹ️  No notifiers configured")
        
        # Record alert
        state.record_alert(ticker, config.timeframe, alert.direction, str(alert.score))
        
        # Track alert sent in metrics
        current = get_current_metrics()
        if current:
            current.record_alert_sent()
        
        # Log for calibration if enabled
        try:
            state.log_alert_for_calibration(
                ticker=ticker,
                timeframe=config.timeframe,
                setup_name=alert.setup,
                direction=alert.direction,
                score=alert.score,
                trigger_price=alert.trigger_close,
                invalidation=alert.invalidation,
                evidence=alert.evidence,
                news_risk=news_risk.risk_level,
                news_reasons=news_risk.reasons,
            )
        except Exception as e:
            logger.warning(f"Failed to log alert for calibration: {e}")
    
    # Finish scan metrics and log summary
    final_metrics = finish_scan_metrics()
    if final_metrics and verbose:
        final_metrics.print_summary()
    
    if final_metrics:
        logger.info(f"Scan completed: {final_metrics.to_dict()}")
    
    return True  # Scan was executed


# Keep legacy function for backward compatibility
def run_live_universe(
    universe: Iterable[tuple[str, str | None]],
    engine: StrategyEngine,
    config: LiveRunConfig,
    state: SqliteStateStore,
    verbose: bool = True,
) -> bool:
    """
    Legacy live runner - redirects to v2 implementation.
    """
    return run_live_universe_v2(universe, engine, config, state, verbose)
