"""
Volatility Squeeze Breakout Strategy
Strategy 3 from Brainstorming Session

Rules:
- Setup: Bollinger Band Width (BBW) drops below 20th percentile of its 100-bar lookback (Squeeze)
- Trigger: Price closes outside BB with volume spike (> 2× SMA)
- Direction: Long if close > upper BB AND EMA50 > EMA200
- Stop: Opposite BB band (Lower BB)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict

from .mean_reversion import (
    MeanReversionAlert, SetupResult, SetupStatus, calculate_invalidation
)
from .regimes import detect_volatility_regime, detect_trend_regime, detect_chop_regime

def evaluate_volatility_squeeze_setup(
    df: pd.DataFrame,
    rsi: pd.Series,
    atr: pd.Series,
    ema20: pd.Series,
    ema50: pd.Series,
    ema200: pd.Series,
    bb_lower: pd.Series,
    bb_middle: pd.Series,
    bb_upper: pd.Series,
    volume_sma: pd.Series,
    timeframe: str = "1h",
    rsi_threshold: float = 50,
    volume_multiplier: float = 2.5,
    base_score: int = 70,
) -> SetupResult:
    min_required = 150
    if len(df) < min_required:
        return SetupResult(SetupStatus.NOT_EVALUATED, "Insufficient bars")

    close = df['close']
    low = df['low']
    high = df['high']
    volume = df['volume']
    
    current_close = close.iloc[-1]
    current_ema20 = ema20.iloc[-1]
    current_ema50 = ema50.iloc[-1]
    current_ema200 = ema200.iloc[-1]
    current_volume = volume.iloc[-1]
    current_volume_sma = volume_sma.iloc[-1] if not pd.isna(volume_sma.iloc[-1]) else 0
    current_atr = atr.iloc[-1]

    # === Rule 1: Breakout & Trend (Long Only) ===
    # Entry: Close > upper BB AND EMA20 > EMA50 AND EMA50 > EMA200
    if current_ema50 <= current_ema200:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "EMA50 <= EMA200 (not uptrend)")
        
    if current_ema20 <= current_ema50:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "EMA20 <= EMA50 (weak short-term momentum)")
        
    if current_close <= bb_upper.iloc[-1]:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"Price {current_close:.2f} <= Upper BB {bb_upper.iloc[-1]:.2f}")

    # === Over-Extended Filter ===
    # Reject if price is way outside the Bollinger Bands (rubber band effect)
    if current_close > bb_upper.iloc[-1] + (1.0 * current_atr):
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"Price {current_close:.2f} over-extended (> 1 ATR above upper BB)")

    # === Rule 2: Volume Spike ===
    if current_volume <= current_volume_sma * volume_multiplier:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"Volume {current_volume} not {volume_multiplier}x SMA {current_volume_sma}")

    # === Rule 3: Previous Squeeze ===
    # Check if a squeeze occurred recently (in the last 5 bars)
    # BBW drops below 20th percentile of its 100-bar lookback
    bandwidth = (bb_upper - bb_lower) / bb_middle
    recent_bandwidths = bandwidth.iloc[-100-5:-5].dropna()
    if len(recent_bandwidths) < 50:
        return SetupResult(SetupStatus.NOT_EVALUATED, "Not enough bandwidth data")

    # Check last 5 bars for a squeeze
    has_squeeze = False
    squeeze_percentile = 100
    for i in range(-6, -1):
        bw = bandwidth.iloc[i]
        # Rank it against recent_bandwidths
        pct = (recent_bandwidths < bw).sum() / len(recent_bandwidths) * 100
        if pct <= 15:
            has_squeeze = True
            squeeze_percentile = pct
            break

    if not has_squeeze:
        return SetupResult(SetupStatus.EVALUATED_NO_SETUP, "No recent BB Squeeze (pct > 15)")

    # Detect Regimes
    vol_regime_result = detect_volatility_regime(atr, close)
    trend_regime_result = detect_trend_regime(close, ema200, atr)
    
    # === Setup Triggered ===
    score = base_score
    if rsi.iloc[-1] > 60: score += 10
    if current_volume > current_volume_sma * 3.0: score += 15
    
    score = min(score, 100)
    
    entry_zone_pct = 0.5
    entry_low = current_close * (1 - entry_zone_pct / 100)
    entry_high = current_close * (1 + entry_zone_pct / 100)
    
    # Stop: Opposite BB band
    invalidation = bb_lower.iloc[-1]

    alert = MeanReversionAlert(
        setup="VOLATILITY_SQUEEZE_BREAKOUT",
        timeframe=timeframe,
        direction="LONG",
        trigger_close=float(current_close),
        entry_zone=(float(entry_low), float(entry_high)),
        invalidation=float(invalidation),
        score=int(score),
        evidence=[
            f"BB Squeeze Breakout (Squeeze Pct: {squeeze_percentile:.1f}%)",
            f"Close > Upper BB (${bb_upper.iloc[-1]:.2f})",
            f"Volume Spike ({current_volume/current_volume_sma:.1f}x SMA)"
        ],
        rsi=float(rsi.iloc[-1]),
        atr=float(atr.iloc[-1]),
        ema200=float(ema200.iloc[-1]),
        vol_regime=vol_regime_result.regime.value if vol_regime_result else "UNKNOWN",
        trend_regime=trend_regime_result.regime.value if trend_regime_result else "UNKNOWN",
    )

    return SetupResult(SetupStatus.SETUP_TRIGGERED, alert=alert)
