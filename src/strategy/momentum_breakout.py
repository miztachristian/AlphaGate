"""
Momentum Breakout Strategy
Strategy 2 from Brainstorming Session

Rules:
- Setup: Price closes above the 20-period high with volume > 1.5× SMA(20)
- Confirmation: RSI > 50 (momentum aligned), MACD histogram positive
- Entry: Close of breakout candle
- Stop: Below the breakout candle low OR 2× ATR
- Block: DOWNTREND regime
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict

from .mean_reversion import (
    MeanReversionAlert, SetupResult, SetupStatus, calculate_invalidation
)
from .regimes import detect_volatility_regime, detect_trend_regime

def evaluate_momentum_breakout_setup(
    df: pd.DataFrame,
    rsi: pd.Series,
    atr: pd.Series,
    ema200: pd.Series,
    macd_histogram: pd.Series,
    volume_sma: pd.Series,
    timeframe: str = "4h",
    lookback_period: int = 20,
    volume_multiplier: float = 1.5,
    base_score: int = 75,
) -> SetupResult:
    min_required = 50
    if len(df) < min_required:
        return SetupResult(SetupStatus.NOT_EVALUATED, "Insufficient bars")

    # Check for NaN in critical values
    if any(pd.isna(s.iloc[-1]) for s in [rsi, atr, ema200, macd_histogram]):
        return SetupResult(SetupStatus.NOT_EVALUATED, "Indicators warming up")

    close = df['close']
    low = df['low']
    high = df['high']
    volume = df['volume']
    
    current_close = close.iloc[-1]
    current_high = high.iloc[-1]
    current_low = low.iloc[-1]
    current_volume = volume.iloc[-1]
    current_volume_sma = volume_sma.iloc[-1] if not pd.isna(volume_sma.iloc[-1]) else 0

    # === Rule 1: Setup - Price closes above 20-period high ===
    # We find the rolling 20-period high BEFORE the current candle.
    # df['high'].iloc[-21:-1].max()
    historical_high = high.iloc[-lookback_period-1:-1].max()
    if pd.isna(historical_high):
        return SetupResult(SetupStatus.NOT_EVALUATED, "Not enough historical high data")
        
    if current_close <= historical_high:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"Price {current_close:.2f} not above {lookback_period}-period high {historical_high:.2f}")

    # === Rule 2: Volume > 1.5x SMA ===
    if current_volume <= current_volume_sma * volume_multiplier:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"Volume {current_volume} not {volume_multiplier}x SMA {current_volume_sma}")

    # === Rule 3: Confirmations ===
    rsi_now = rsi.iloc[-1]
    if rsi_now <= 50:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"RSI {rsi_now:.1f} <= 50")
        
    macd_hist_now = macd_histogram.iloc[-1]
    if macd_hist_now <= 0:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"MACD Histogram {macd_hist_now:.2f} <= 0")

    # Detect Regimes
    vol_regime_result = detect_volatility_regime(atr, close)
    trend_regime_result = detect_trend_regime(close, ema200, atr)
    
    # === Rule 4: Block Downtrend ===
    if trend_regime_result and trend_regime_result.regime.value in ["DOWNTREND", "STRONG_DOWNTREND"]:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "Blocked: Downtrend regime")

    # === Setup Triggered ===
    score = base_score
    if rsi_now > 60: score += 10
    if current_volume > current_volume_sma * 2.0: score += 15
    
    score = min(score, 100)
    
    entry_zone_pct = 0.5
    entry_low = current_close * (1 - entry_zone_pct / 100)
    entry_high = current_close * (1 + entry_zone_pct / 100)
    
    # Stop loss: below breakout candle low OR 2x ATR (whichever is closer to price to be safe, or just 2x ATR)
    stop_atr = current_close - (2.0 * atr.iloc[-1])
    invalidation = max(current_low, stop_atr)

    alert = MeanReversionAlert(
        setup="MOMENTUM_BREAKOUT",
        timeframe=timeframe,
        direction="LONG",
        trigger_close=float(current_close),
        entry_zone=(float(entry_low), float(entry_high)),
        invalidation=float(invalidation),
        score=int(score),
        evidence=[
            f"Breakout above {historical_high:.2f}",
            f"Volume {current_volume/current_volume_sma:.1f}x SMA",
            f"RSI {rsi_now:.1f} > 50 & MACD Hist > 0"
        ],
        rsi=float(rsi_now),
        atr=float(atr.iloc[-1]),
        ema200=float(ema200.iloc[-1]),
        vol_regime=vol_regime_result.regime.value if vol_regime_result else "UNKNOWN",
        trend_regime=trend_regime_result.regime.value if trend_regime_result else "UNKNOWN",
    )

    return SetupResult(SetupStatus.SETUP_TRIGGERED, alert=alert)
