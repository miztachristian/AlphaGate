"""Live runner for the universe.

Flow:
Universe CSV -> Scheduler loop -> Fetch market data -> Compute strategy -> 
    (if SETUP_TRIGGERED) -> Fetch news -> Attach risk label -> State store -> Notify

v3: News is now fetched ONLY after a setup triggers, using Polygon.io News API.
v4: Cache-backed OHLCV fetching with metrics for performance optimization.
v5: V2 engine mode with gate logic (shadow / v2 modes).
"""

from __future__ import annotations

import os
import time
import logging
import yaml
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Dict, Any

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
from ..strategy.regimes import detect_chop_regime
from ..notify import MultiNotifier, TelegramNotifier, EmailNotifier
from ..v2 import (
    GateStatus,
    ScrutinyLevel,
    GateResult,
    GateFeatures,
    GateConfig,
    evaluate_gate,
    compute_gate_features,
)

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
    engine_mode: Optional[str] = None  # Engine mode: v1, v2, or shadow (None=use config.yaml)
    max_concurrent_trades: int = 3  # Maximum concurrent open positions (risk governor)


def _get_engine_config() -> Dict[str, Any]:
    """Load engine configuration from config.yaml."""
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    
    defaults = {
        "mode": "v2",
        "v2_gate": {
            "min_price": 5.0,
            "min_avg_dollar_volume_20d": 20_000_000,
            # Score filters
            "min_score": 70,
            "downtrend_min_score": 80,
            # Volatility filters
            "max_atr_pct": 5.0,
            "block_downtrend_high_vol": True,
            # Regime allowances
            "allow_weak_downtrend": True,
            # Event risk
            "strict_earnings_block": False,
            "block_high_news_risk": False,
        },
        "calibration_logging": {
            "enabled": False,
            "hold_hours_by_timeframe": {"1h": 24, "4h": 72, "1d": 168},
        }
    }
    
    if not config_path.exists():
        return defaults
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        result = {
            "mode": config.get("engine", {}).get("mode", "v2"),
            "strategy": config.get("engine", {}).get("strategy", "multi_strategy"),
            "v2_gate": {**defaults["v2_gate"], **config.get("v2_gate", {})},
            "calibration_logging": {**defaults["calibration_logging"], **config.get("calibration_logging", {})},
        }
        return result
    except Exception as e:
        logger.warning(f"Failed to load engine config: {e}, using defaults")
        return defaults


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


def _compute_chop_regime(analysis: dict) -> Optional[str]:
    """
    Compute chop regime from analysis data.
    
    Uses Bollinger Band bandwidth to determine if market is in chop.
    Returns "CHOP" or "TRENDING" (or None if insufficient data).
    """
    try:
        bb_data = analysis.get('bb', {})
        bb_upper = bb_data.get('upper_series')
        bb_lower = bb_data.get('lower_series')
        bb_middle = bb_data.get('middle_series')
        
        if bb_upper is None or bb_lower is None or bb_middle is None:
            return None
        
        result = detect_chop_regime(
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            bb_middle=bb_middle,
        )
        
        return result.regime.value if result else None
    except Exception as e:
        logger.debug(f"Chop regime detection error: {e}")
        return None


def _evaluate_v2_gate(
    symbol: str,
    df,
    analysis: dict,
    alert,
    gate_config: GateConfig,
    news_risk: Optional[NewsRiskResult] = None,
) -> GateResult:
    """
    Evaluate V2 gate for a triggered setup.
    
    Args:
        symbol: Stock ticker
        df: OHLCV DataFrame
        analysis: Analysis results from strategy engine
        alert: SetupAlert with setup details
        gate_config: GateConfig with thresholds
        news_risk: Optional news risk result
    
    Returns:
        GateResult with gate decision
    """
    try:
        # Get regime data from the alert (not analysis dict)
        vol_regime = alert.vol_regime if hasattr(alert, 'vol_regime') else None
        trend_regime = alert.trend_regime if hasattr(alert, 'trend_regime') else None
        
        # Compute chop regime from BB data
        chop_regime = _compute_chop_regime(analysis)
        
        # Extract score and atr_pct from alert for new gate filters
        score = alert.score if hasattr(alert, 'score') else None
        atr_pct = alert.atr_pct if hasattr(alert, 'atr_pct') else None
        
        # Compute gate features
        features = compute_gate_features(
            df=df,
            trend_regime=trend_regime,
            vol_regime=vol_regime,
            chop_regime=chop_regime,
            news_risk=news_risk.risk_level if news_risk else None,
        )
        
        # Add score and atr_pct for new refinement filters
        features.score = score
        features.atr_pct = atr_pct
        
        # Evaluate gate
        return evaluate_gate(
            symbol=symbol,
            timeframe=alert.timeframe if hasattr(alert, 'timeframe') else '',
            setup_name=alert.setup,
            direction=alert.direction,
            features=features,
            gate_config=gate_config,
        )
    except Exception as e:
        logger.error(f"Gate evaluation error for {symbol}: {e}")
        return GateResult(
            status=GateStatus.NOT_EVALUATED,
            reasons=[f"GATE_ERROR: {str(e)[:100]}"],
        )


def _format_alert_message(
    ticker: str,
    analysis: dict,
    news_risk: NewsRiskResult,
    timeframe: str,
    alert_log_id: int | None = None,
    company_name: str | None = None,
) -> tuple[str, str]:
    """
    Format alert title and message.
    
    Returns:
        Tuple of (title, message)
    """
    setup_result = analysis.get('setup_result')
    alert = setup_result.alert if setup_result else None
    
    if alert:
        # Build title with optional company name
        ticker_display = f"{ticker} ({company_name})" if company_name else ticker
        title = f"🔔 {alert.direction} ALERT: {ticker_display} | Score: {alert.score} | {alert.setup}"
        
        parts = []
        
        # Add Alert Log ID at the top if available
        if alert_log_id:
            parts.append(f"🆔 Alert ID: {alert_log_id}")
            parts.append("")
        
        parts.extend([
            f"⏱️  Timeframe: {timeframe}",
            f"💰 Trigger Price: ${alert.trigger_close:.2f}",
            f"📍 Entry Zone: ${alert.entry_zone[0]:.2f} - ${alert.entry_zone[1]:.2f}",
            f"🛑 StopLoss: ${alert.invalidation:.2f}",
            f"⏳ Hold Window: {alert.hold_window}",
            "",
            "📊 Evidence:",
        ])
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

        # Run analysis based on engine strategy mode
        engine_config = _get_engine_config()
        strategy_mode = engine_config.get("strategy", "vol_squeeze_only")
        
        if strategy_mode == "vol_squeeze_only":
            # Volatility Squeeze ONLY (no ensemble fallback)
            analysis = engine.analyze_with_vol_squeeze_only(df, interval=config.timeframe)
        elif strategy_mode == "multi_strategy":
            # Multi-strategy: Volatility Squeeze primary + Ensemble secondary
            analysis = engine.analyze_with_multi_strategy(df, interval=config.timeframe)
        else:
            # Legacy: Mean reversion only
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
        
        # ============ V2 Engine Mode Gate ============
        # Get engine config
        engine_config = _get_engine_config()
        engine_mode = config.engine_mode or engine_config.get("mode", "v2")
        
        # Build GateConfig from config.yaml (V2.1 with toxic regime blocking)
        v2_gate_cfg = engine_config.get("v2_gate", {})
        gate_config = GateConfig(
            # Hard filters
            min_price=v2_gate_cfg.get("min_price", 5.0),
            min_avg_dollar_volume_20d=v2_gate_cfg.get("min_avg_dollar_volume_20d", 20_000_000),
            # Score filters
            min_score=v2_gate_cfg.get("min_score", 70),
            downtrend_min_score=v2_gate_cfg.get("downtrend_min_score", 80),
            # Volatility filters
            max_atr_pct=v2_gate_cfg.get("max_atr_pct", 5.0),
            block_downtrend_high_vol=v2_gate_cfg.get("block_downtrend_high_vol", True),
            # Regime allowances
            allow_weak_downtrend=v2_gate_cfg.get("allow_weak_downtrend", True),
            # Event risk
            strict_earnings_block=v2_gate_cfg.get("strict_earnings_block", False),
            block_high_news_risk=v2_gate_cfg.get("block_high_news_risk", False),
        )
        
        # Gate evaluation variables
        gate_result: Optional[GateResult] = None
        gate_decision_id: Optional[int] = None
        should_send_alert = True  # Default: send alert (v1 behavior)
        
        # Only evaluate gate in shadow or v2 mode
        if engine_mode in ("shadow", "v2"):
            gate_result = _evaluate_v2_gate(
                symbol=ticker,
                df=df,
                analysis=analysis,
                alert=alert,
                gate_config=gate_config,
                news_risk=news_risk,
            )
            
            if verbose:
                status_emoji = "✅" if gate_result.status == GateStatus.GO else "❌" if gate_result.status == GateStatus.NO_GO else "⚠️"
                scrutiny_str = f" ({gate_result.scrutiny_level.value})" if gate_result.status == GateStatus.GO else ""
                print(f"[{ticker}] 🚦 Gate: {status_emoji} {gate_result.status.value}{scrutiny_str} - {', '.join(gate_result.reasons)}")
            
            # Log gate decision to database
            try:
                gate_decision_id = state.log_gate_decision(
                    symbol=ticker,
                    timeframe=config.timeframe,
                    setup=alert.setup,
                    direction=alert.direction,
                    gate_status=gate_result.status.value,
                    gate_reasons=gate_result.reasons,
                    scrutiny_level=gate_result.scrutiny_level.value,
                    gate_tags=gate_result.tags,
                )
            except Exception as e:
                logger.warning(f"Failed to log gate decision: {e}")
            
            # Determine if we should send alert
            if engine_mode == "v2":
                # V2 mode: gate enforced - only send if GO
                should_send_alert = (gate_result.status == GateStatus.GO)
                if not should_send_alert and verbose:
                    print(f"[{ticker}] 🚫 Alert suppressed by V2 gate")
            # shadow mode: always send alert (gate is logged but not enforced)
        
        # ============ End V2 Engine Mode Gate ============
        
        # Skip if gate blocked (v2 mode only)
        if not should_send_alert:
            continue
        
        # ============ Position Limit Check (Risk Governor) ============
        # Check if we're at max concurrent positions
        calibration_logging = engine_config.get("calibration_logging", {})
        hold_hours_by_timeframe = calibration_logging.get("hold_hours_by_timeframe", {"1h": 24, "4h": 48})
        
        try:
            active_trades = state.count_active_trades(hold_hours_by_timeframe=hold_hours_by_timeframe)
            if active_trades >= config.max_concurrent_trades:
                if verbose:
                    print(f"[{ticker}] 🛑 Position limit reached: {active_trades}/{config.max_concurrent_trades} active trades")
                current = get_current_metrics()
                if current:
                    current.record_not_evaluated("MAX_POSITION_LIMIT")
                continue
        except Exception as e:
            logger.warning(f"Failed to check position limit: {e}, proceeding with alert")
        
        # ============ End Position Limit Check ============
        
        # Log alert FIRST to get the alert_log_id for the message
        alert_log_id = None
        calibration_logging = engine_config.get("calibration_logging", {})
        if calibration_logging.get("enabled", False):
            try:
                alert_log_id = state.log_alert_for_calibration(
                    symbol=ticker,
                    timeframe=config.timeframe,
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
                    news_risk=news_risk.risk_level,
                    news_reasons=news_risk.reasons,
                    alert_payload=alert.to_dict(),
                )
            except Exception as e:
                logger.warning(f"Failed to log alert for calibration: {e}")
        
        # Format message (now includes alert_log_id if available)
        title, message = _format_alert_message(ticker, analysis, news_risk, config.timeframe, alert_log_id, name)
        
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
        
        # If in v2 mode and gate passed, log v2 alert
        if alert_log_id and engine_mode == "v2" and gate_result and gate_result.status == GateStatus.GO:
            try:
                state.log_v2_alert(
                    symbol=ticker,
                    timeframe=config.timeframe,
                    setup=alert.setup,
                    direction=alert.direction,
                    score=alert.score,
                    trigger_close=alert.trigger_close,
                    scrutiny_level=gate_result.scrutiny_level.value,
                    gate_decision_id=gate_decision_id or 0,
                    alert_log_id=alert_log_id,
                )
            except Exception as e:
                logger.warning(f"Failed to log v2 alert: {e}")
    
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
