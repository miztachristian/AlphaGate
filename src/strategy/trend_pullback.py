"""
Trend Continuation Pullback Strategy
Strategy 1 from Brainstorming Session

Rules:
- Prerequisite: Price > EMA200 AND EMA50 > EMA200 (confirmed uptrend)
- Entry: BB lower band reclaim + RSI cross up from < 35
- Exit: Price reaches BB middle band OR 1.5 ATR trailing stop
- Block: No trade if DOWNTREND or HIGH/PANIC volatility
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict

from .mean_reversion import (
    MeanReversionAlert, SetupResult, SetupStatus,
    check_bb_reclaim, check_rsi_cross_up, calculate_invalidation
)
from .regimes import detect_volatility_regime, detect_trend_regime

def evaluate_trend_pullback_setup(
    df: pd.DataFrame,
    rsi: pd.Series,
    atr: pd.Series,
    ema50: pd.Series,
    ema200: pd.Series,
    bb_lower: pd.Series,
    bb_middle: pd.Series,
    bb_upper: pd.Series,
    volume_sma: pd.Series,
    timeframe: str = "1h",
    rsi_threshold: float = 35,
    lookback_overshoot: int = 5,
    panic_percentile: float = 70, # HIGH/PANIC block (percentile > 70 blocked)
    vol_lookback: int = 200,
    base_score: int = 70,
    entry_zone_pct: float = 0.5,
) -> SetupResult:
    """Evaluate Trend Pullback Setup."""
    min_required = 200
    if len(df) < min_required:
        return SetupResult(SetupStatus.NOT_EVALUATED, "Insufficient bars")

    # Critical values check
    for s in [rsi, atr, ema50, ema200, bb_lower]:
        if pd.isna(s.iloc[-1]) or pd.isna(s.iloc[-2]):
            return SetupResult(SetupStatus.NOT_EVALUATED, "Indicators warming up")

    close = df['close']
    low = df['low']
    high = df['high']
    
    current_close = close.iloc[-1]
    current_ema50 = ema50.iloc[-1]
    current_ema200 = ema200.iloc[-1]
    
    # === Rule 1: Prerequisite Filter ===
    # Price > EMA200 AND EMA50 > EMA200
    if current_close <= current_ema200 or current_ema50 <= current_ema200:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "Trend prerequisite not met (Price or EMA50 below EMA200)")

    # Detect Regimes
    vol_regime_result = detect_volatility_regime(atr, close, panic_percentile=90, lookback_bars=vol_lookback)
    trend_regime_result = detect_trend_regime(close, ema200, atr)
    
    if not vol_regime_result or not trend_regime_result:
        return SetupResult(SetupStatus.NOT_EVALUATED, "Could not compute regime")

    # === Rule 4: Block Downtrend or High Volatility ===
    if trend_regime_result.regime.value in ["DOWNTREND", "STRONG_DOWNTREND"]:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "Blocked: Downtrend regime")
        
    if vol_regime_result.percentile >= panic_percentile:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"Blocked: High volatility ({vol_regime_result.percentile:.0f}th pctl)")

    # === Rule 2: Entry Trigger ===
    has_overshoot, is_reclaim, _ = check_bb_reclaim(close, bb_lower, lookback_overshoot)
    if not has_overshoot or not is_reclaim:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "No BB lower reclaim")

    rsi_cross, rsi_now, rsi_prev = check_rsi_cross_up(rsi, rsi_threshold)
    if not rsi_cross and rsi_now >= rsi_threshold:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "RSI did not cross up from below threshold")

    # === Setup Triggered ===
    score = base_score
    if rsi_cross: score += 15
    if vol_regime_result.percentile < 30: score += 15

    score = min(score, 100)
    
    entry_low = current_close * (1 - entry_zone_pct / 100)
    entry_high = current_close * (1 + entry_zone_pct / 100)
    invalidation = calculate_invalidation(low, atr.iloc[-1])

    alert = MeanReversionAlert(
        setup="TREND_CONTINUATION_PULLBACK",
        timeframe=timeframe,
        direction="LONG",
        trigger_close=float(current_close),
        entry_zone=(float(entry_low), float(entry_high)),
        invalidation=float(invalidation) if not pd.isna(invalidation) else 0.0,
        score=int(score),
        evidence=["Price/EMA50 > EMA200", "BB Lower Reclaim", f"RSI crossed {rsi_threshold}"],
        rsi=float(rsi_now),
        rsi_prev=float(rsi_prev),
        atr=float(atr.iloc[-1]),
        ema200=float(current_ema200),
        bb_lower=float(bb_lower.iloc[-1]),
        bb_middle=float(bb_middle.iloc[-1]),
        bb_upper=float(bb_upper.iloc[-1]),
        vol_regime=vol_regime_result.regime.value,
        trend_regime=trend_regime_result.regime.value,
    )

    return SetupResult(SetupStatus.SETUP_TRIGGERED, alert=alert)
