"""
Regime Detection Module

Detects market regimes for filtering trading setups:
- Volatility regime (ATR%): PANIC, NORMAL, DEAD
- Trend regime (EMA200): STRONG_DOWNTREND, DOWNTREND, NEUTRAL, UPTREND, STRONG_UPTREND
- Chop regime (BB bandwidth): CHOP, TRENDING
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd
import numpy as np


class VolatilityRegime(Enum):
    """Volatility regime based on ATR%."""
    PANIC = "PANIC"       # ATR% >= 90th percentile - dangerous
    HIGH = "HIGH"         # ATR% 70-90th percentile
    NORMAL = "NORMAL"     # ATR% 20-70th percentile
    LOW = "LOW"           # ATR% 10-20th percentile
    DEAD = "DEAD"         # ATR% <= 10th percentile - no volatility


class TrendRegime(Enum):
    """Trend regime based on EMA200 slope and price position."""
    STRONG_DOWNTREND = "STRONG_DOWNTREND"  # Slope down AND price > 1 ATR below EMA200
    DOWNTREND = "DOWNTREND"                 # Slope down OR price below EMA200
    NEUTRAL = "NEUTRAL"                     # Slope flat, price near EMA200
    UPTREND = "UPTREND"                     # Slope up OR price above EMA200
    STRONG_UPTREND = "STRONG_UPTREND"       # Slope up AND price > 1 ATR above EMA200


class ChopRegime(Enum):
    """Chop regime based on Bollinger Band bandwidth compression."""
    CHOP = "CHOP"           # BB bandwidth compressed (range-bound, mean reverting)
    TRENDING = "TRENDING"   # BB bandwidth expanded (trending market)


@dataclass
class VolatilityRegimeResult:
    """Result of volatility regime detection."""
    regime: VolatilityRegime
    atr_pct: float          # Current ATR as % of price
    percentile: float       # Percentile rank of current ATR%
    is_panic: bool          # Convenience flag
    
    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "atr_pct": self.atr_pct,
            "percentile": self.percentile,
            "is_panic": self.is_panic,
        }


@dataclass
class TrendRegimeResult:
    """Result of trend regime detection."""
    regime: TrendRegime
    ema200: float           # Current EMA200 value
    ema200_slope: float     # EMA200 change over slope period
    price_vs_ema200: float  # (price - EMA200) / ATR
    is_strong_downtrend: bool  # Convenience flag
    
    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "ema200": self.ema200,
            "ema200_slope": self.ema200_slope,
            "price_vs_ema200": self.price_vs_ema200,
            "is_strong_downtrend": self.is_strong_downtrend,
        }


def calculate_atr_percent(atr: pd.Series, close: pd.Series) -> pd.Series:
    """
    Calculate ATR as percentage of price.
    
    ATR% = (ATR / close) * 100
    """
    return (atr / close) * 100


def detect_volatility_regime(
    atr: pd.Series,
    close: pd.Series,
    panic_percentile: float = 90,
    dead_percentile: float = 20,
    lookback_bars: int = 200,
) -> Optional[VolatilityRegimeResult]:
    """
    Detect current volatility regime based on ATR%.
    
    Args:
        atr: Series of ATR values
        close: Series of close prices
        panic_percentile: Percentile threshold for PANIC regime
        dead_percentile: Percentile threshold for DEAD regime
        lookback_bars: Number of bars for percentile calculation
    
    Returns:
        VolatilityRegimeResult or None if insufficient data
    """
    if len(atr) < lookback_bars or atr.iloc[-1] is None or pd.isna(atr.iloc[-1]):
        return None
    
    atr_pct = calculate_atr_percent(atr, close)
    current_atr_pct = atr_pct.iloc[-1]
    
    if pd.isna(current_atr_pct):
        return None
    
    # Calculate percentile of current ATR% vs recent history
    recent_atr_pct = atr_pct.tail(lookback_bars).dropna()
    if len(recent_atr_pct) < lookback_bars // 2:
        return None
    
    percentile = (recent_atr_pct < current_atr_pct).sum() / len(recent_atr_pct) * 100
    
    # Determine regime
    if percentile >= panic_percentile:
        regime = VolatilityRegime.PANIC
    elif percentile >= 70:
        regime = VolatilityRegime.HIGH
    elif percentile <= 10:
        regime = VolatilityRegime.DEAD
    elif percentile <= dead_percentile:
        regime = VolatilityRegime.LOW
    else:
        regime = VolatilityRegime.NORMAL
    
    return VolatilityRegimeResult(
        regime=regime,
        atr_pct=float(current_atr_pct),
        percentile=float(percentile),
        is_panic=(regime == VolatilityRegime.PANIC),
    )


def detect_trend_regime(
    close: pd.Series,
    ema200: pd.Series,
    atr: pd.Series,
    slope_lookback: int = 20,
    strong_trend_atr_threshold: float = 1.0,
) -> Optional[TrendRegimeResult]:
    """
    Detect current trend regime based on EMA200 slope and price position.
    
    Args:
        close: Series of close prices
        ema200: Series of EMA200 values
        atr: Series of ATR values
        slope_lookback: Number of bars to measure EMA200 slope
        strong_trend_atr_threshold: ATR distance for strong trend classification
    
    Returns:
        TrendRegimeResult or None if insufficient data
    """
    if len(ema200) < slope_lookback + 1:
        return None
    
    current_close = close.iloc[-1]
    current_ema200 = ema200.iloc[-1]
    current_atr = atr.iloc[-1]
    
    if any(pd.isna(v) for v in [current_close, current_ema200, current_atr]):
        return None
    
    if current_atr <= 0:
        return None
    
    # Calculate EMA200 slope
    ema200_prev = ema200.iloc[-slope_lookback - 1]
    if pd.isna(ema200_prev):
        return None
    
    ema200_slope = current_ema200 - ema200_prev
    slope_normalized = ema200_slope / current_atr  # Normalize by ATR
    
    # Calculate price distance from EMA200 in ATR units
    price_vs_ema200 = (current_close - current_ema200) / current_atr
    
    # Determine regime
    slope_down = slope_normalized < -0.5  # Slope down by more than 0.5 ATR over period
    slope_up = slope_normalized > 0.5
    price_far_below = price_vs_ema200 < -strong_trend_atr_threshold
    price_far_above = price_vs_ema200 > strong_trend_atr_threshold
    price_below = current_close < current_ema200
    price_above = current_close > current_ema200
    
    if slope_down and price_far_below:
        regime = TrendRegime.STRONG_DOWNTREND
    elif slope_up and price_far_above:
        regime = TrendRegime.STRONG_UPTREND
    elif slope_down or price_below:
        regime = TrendRegime.DOWNTREND
    elif slope_up or price_above:
        regime = TrendRegime.UPTREND
    else:
        regime = TrendRegime.NEUTRAL
    
    return TrendRegimeResult(
        regime=regime,
        ema200=float(current_ema200),
        ema200_slope=float(ema200_slope),
        price_vs_ema200=float(price_vs_ema200),
        is_strong_downtrend=(regime == TrendRegime.STRONG_DOWNTREND),
    )


@dataclass
class ChopRegimeResult:
    """Result of chop regime detection."""
    regime: ChopRegime
    bb_bandwidth: float      # Current BB bandwidth (upper - lower) / middle
    percentile: float        # Percentile rank of current bandwidth
    is_chop: bool            # Convenience flag
    
    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "bb_bandwidth": self.bb_bandwidth,
            "percentile": self.percentile,
            "is_chop": self.is_chop,
        }


def detect_chop_regime(
    bb_upper: pd.Series,
    bb_lower: pd.Series,
    bb_middle: pd.Series,
    chop_percentile: float = 25,
    lookback_bars: int = 100,
) -> Optional[ChopRegimeResult]:
    """
    Detect chop regime based on Bollinger Band bandwidth compression.
    
    Chop = narrow BB bandwidth (compression indicates range-bound market)
    Trending = wide BB bandwidth (expansion indicates directional move)
    
    Args:
        bb_upper: Series of BB upper band values
        bb_lower: Series of BB lower band values
        bb_middle: Series of BB middle band (SMA) values
        chop_percentile: Percentile threshold below which we consider CHOP
        lookback_bars: Number of bars for percentile calculation
    
    Returns:
        ChopRegimeResult or None if insufficient data
    """
    if len(bb_upper) < lookback_bars:
        return None
    
    current_upper = bb_upper.iloc[-1]
    current_lower = bb_lower.iloc[-1]
    current_middle = bb_middle.iloc[-1]
    
    if any(pd.isna(v) for v in [current_upper, current_lower, current_middle]):
        return None
    
    if current_middle <= 0:
        return None
    
    # Calculate BB bandwidth: (upper - lower) / middle
    # Also compute historical bandwidth for percentile ranking
    bandwidth = (bb_upper - bb_lower) / bb_middle
    current_bandwidth = bandwidth.iloc[-1]
    
    if pd.isna(current_bandwidth):
        return None
    
    # Calculate percentile of current bandwidth vs recent history
    recent_bandwidth = bandwidth.tail(lookback_bars).dropna()
    if len(recent_bandwidth) < lookback_bars // 2:
        return None
    
    percentile = (recent_bandwidth < current_bandwidth).sum() / len(recent_bandwidth) * 100
    
    # Chop when bandwidth is in the lower percentiles (compressed)
    if percentile <= chop_percentile:
        regime = ChopRegime.CHOP
    else:
        regime = ChopRegime.TRENDING
    
    return ChopRegimeResult(
        regime=regime,
        bb_bandwidth=float(current_bandwidth),
        percentile=float(percentile),
        is_chop=(regime == ChopRegime.CHOP),
    )
