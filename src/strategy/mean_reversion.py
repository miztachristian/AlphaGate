"""
Mean Reversion Setup Module

Implements the MEAN_REVERSION_BB_RECLAIM setup:
- Primary trigger: Bollinger Band reclaim (price overshoots below lower band, then reclaims)
- Confirmations: RSI cross up, volatility not panic, trend not strong downtrend
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

from .regimes import (
    VolatilityRegime, TrendRegime,
    VolatilityRegimeResult, TrendRegimeResult,
    detect_volatility_regime, detect_trend_regime,
)


class SetupStatus(Enum):
    """Status of setup evaluation."""
    NOT_EVALUATED = "NOT_EVALUATED"    # Missing data / warmup
    EVALUATED_NO_SETUP = "EVALUATED_NO_SETUP"  # Data ok, no setup triggered
    SETUP_TRIGGERED = "SETUP_TRIGGERED"  # Alert!


@dataclass
class MeanReversionAlert:
    """Alert payload for MEAN_REVERSION_BB_RECLAIM setup."""
    setup: str = "MEAN_REVERSION_BB_RECLAIM"
    timeframe: str = ""
    direction: str = "LONG"
    
    # Price levels
    trigger_close: float = 0.0
    entry_zone: tuple = (0.0, 0.0)  # (low, high)
    invalidation: float = 0.0
    hold_window: str = ""
    
    # Score
    score: int = 0
    
    # Evidence
    evidence: List[str] = field(default_factory=list)
    
    # Indicator values (for logging/calibration)
    rsi: float = 0.0
    rsi_prev: float = 0.0
    atr: float = 0.0
    atr_pct: float = 0.0
    ema200: float = 0.0
    ema200_slope: float = 0.0
    bb_lower: float = 0.0
    bb_middle: float = 0.0
    bb_upper: float = 0.0
    
    # Regimes
    vol_regime: str = ""
    trend_regime: str = ""
    
    # News risk (filled in by caller)
    news_risk: str = "LOW"
    news_reasons: List[str] = field(default_factory=list)
    
    # Cooldown
    cooldown_active: bool = False
    last_alert_ago: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "setup": self.setup,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "trigger_close": self.trigger_close,
            "entry_zone": list(self.entry_zone),
            "invalidation": self.invalidation,
            "hold_window": self.hold_window,
            "score": self.score,
            "evidence": self.evidence,
            "rsi": self.rsi,
            "rsi_prev": self.rsi_prev,
            "atr": self.atr,
            "atr_pct": self.atr_pct,
            "ema200": self.ema200,
            "ema200_slope": self.ema200_slope,
            "bb_lower": self.bb_lower,
            "bb_middle": self.bb_middle,
            "bb_upper": self.bb_upper,
            "vol_regime": self.vol_regime,
            "trend_regime": self.trend_regime,
            "news_risk": self.news_risk,
            "news_reasons": self.news_reasons,
            "cooldown_active": self.cooldown_active,
            "last_alert_ago": self.last_alert_ago,
        }


@dataclass
class SetupResult:
    """Result of setup evaluation."""
    status: SetupStatus
    reason: Optional[str] = None
    alert: Optional[MeanReversionAlert] = None
    
    def __str__(self) -> str:
        if self.status == SetupStatus.SETUP_TRIGGERED:
            return f"SETUP_TRIGGERED: {self.alert.setup} score={self.alert.score}"
        return f"{self.status.value}: {self.reason}"


def check_bb_reclaim(
    close: pd.Series,
    bb_lower: pd.Series,
    lookback_overshoot: int = 5,
) -> tuple[bool, bool, Optional[int]]:
    """
    Check for Bollinger Band lower band reclaim.
    
    Overshoot: close < lower_band within last lookback bars
    Reclaim: current close >= lower_band AND previous close < lower_band
    
    Args:
        close: Series of close prices
        bb_lower: Series of lower Bollinger Band values
        lookback_overshoot: Number of bars to look for overshoot
    
    Returns:
        Tuple of (has_overshoot, is_reclaim, overshoot_bars_ago)
    """
    if len(close) < lookback_overshoot + 1:
        return False, False, None
    
    current_close = close.iloc[-1]
    prev_close = close.iloc[-2]
    current_bb_lower = bb_lower.iloc[-1]
    prev_bb_lower = bb_lower.iloc[-2]
    
    if any(pd.isna(v) for v in [current_close, prev_close, current_bb_lower, prev_bb_lower]):
        return False, False, None
    
    # Check for overshoot in recent history
    has_overshoot = False
    overshoot_bars_ago = None
    
    for i in range(1, lookback_overshoot + 1):
        idx = -i - 1  # -2, -3, -4, etc.
        if abs(idx) > len(close):
            break
        
        bar_close = close.iloc[idx]
        bar_bb_lower = bb_lower.iloc[idx]
        
        if pd.isna(bar_close) or pd.isna(bar_bb_lower):
            continue
        
        if bar_close < bar_bb_lower:
            has_overshoot = True
            overshoot_bars_ago = i
            break
    
    # Also check if current or previous bar was overshoot
    if prev_close < prev_bb_lower:
        has_overshoot = True
        overshoot_bars_ago = 1
    
    # Check for reclaim: was below, now inside
    is_reclaim = (prev_close < prev_bb_lower) and (current_close >= current_bb_lower)
    
    return has_overshoot, is_reclaim, overshoot_bars_ago


def check_rsi_cross_up(
    rsi: pd.Series,
    threshold: float = 35,
) -> tuple[bool, float, float]:
    """
    Check if RSI crosses up through threshold.
    
    Cross up: RSI_prev < threshold AND RSI_current >= threshold
    
    Args:
        rsi: Series of RSI values
        threshold: RSI threshold to cross
    
    Returns:
        Tuple of (is_cross_up, rsi_current, rsi_prev)
    """
    if len(rsi) < 2:
        return False, np.nan, np.nan
    
    rsi_current = rsi.iloc[-1]
    rsi_prev = rsi.iloc[-2]
    
    if pd.isna(rsi_current) or pd.isna(rsi_prev):
        return False, np.nan, np.nan
    
    is_cross_up = (rsi_prev < threshold) and (rsi_current >= threshold)
    
    return is_cross_up, float(rsi_current), float(rsi_prev)


def calculate_invalidation(
    low: pd.Series,
    atr: float,
    lookback: int = 10,
    buffer_multiplier: float = 0.5,
) -> float:
    """
    Calculate invalidation level (stop loss zone).
    
    Invalidation = recent swing low - (buffer * ATR)
    
    Args:
        low: Series of low prices
        atr: Current ATR value
        lookback: Bars to look for swing low
        buffer_multiplier: ATR multiplier for buffer
    
    Returns:
        Invalidation price level
    """
    recent_lows = low.tail(lookback)
    swing_low = recent_lows.min()
    
    if pd.isna(swing_low) or pd.isna(atr):
        return np.nan
    
    return float(swing_low - (buffer_multiplier * atr))


def evaluate_mean_reversion_setup(
    df: pd.DataFrame,
    rsi: pd.Series,
    atr: pd.Series,
    ema200: pd.Series,
    bb_lower: pd.Series,
    bb_middle: pd.Series,
    bb_upper: pd.Series,
    volume_sma: pd.Series,
    timeframe: str = "1h",
    # Config parameters
    rsi_threshold: float = 35,
    lookback_overshoot: int = 5,
    panic_percentile: float = 90,
    vol_lookback: int = 200,
    slope_lookback: int = 20,
    strong_downtrend_atr: float = 1.0,
    entry_zone_pct: float = 0.5,
    # Scoring
    base_score: int = 60,
    strong_rsi_bonus: int = 15,
    low_vol_bonus: int = 10,
    good_trend_bonus: int = 10,
    low_volume_penalty: int = 15,
    # Hold windows
    hold_windows: Optional[Dict[str, str]] = None,
) -> SetupResult:
    """
    Evaluate the MEAN_REVERSION_BB_RECLAIM setup.
    
    Returns NOT_EVALUATED if data quality issues prevent evaluation.
    Returns EVALUATED_NO_SETUP if conditions not met.
    Returns SETUP_TRIGGERED with alert if setup fires.
    """
    if hold_windows is None:
        hold_windows = {"1h": "6-24h", "4h": "1-3d", "1d": "3-7d"}
    
    # Validate minimum data
    min_required = max(vol_lookback, slope_lookback, 50)
    if len(df) < min_required:
        return SetupResult(
            status=SetupStatus.NOT_EVALUATED,
            reason=f"Insufficient bars: {len(df)} < {min_required}"
        )
    
    # Check for NaN in critical values
    critical_indices = [-1, -2]
    for idx in critical_indices:
        if any(pd.isna(s.iloc[idx]) for s in [rsi, atr, ema200, bb_lower, bb_middle, bb_upper] if len(s) > abs(idx)):
            return SetupResult(
                status=SetupStatus.NOT_EVALUATED,
                reason="Critical indicator values are NaN (warmup incomplete)"
            )
    
    close = df['close']
    low = df['low']
    volume = df['volume']
    
    # Get current values
    current_close = close.iloc[-1]
    current_atr = atr.iloc[-1]
    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    current_bb_lower = bb_lower.iloc[-1]
    current_bb_middle = bb_middle.iloc[-1]
    current_bb_upper = bb_upper.iloc[-1]
    current_ema200 = ema200.iloc[-1]
    current_volume = volume.iloc[-1]
    current_volume_sma = volume_sma.iloc[-1] if len(volume_sma) > 0 else np.nan
    
    # Calculate ATR%
    atr_pct = (current_atr / current_close) * 100 if current_close > 0 else np.nan
    
    # Detect regimes
    vol_regime_result = detect_volatility_regime(
        atr, close, panic_percentile=panic_percentile, lookback_bars=vol_lookback
    )
    trend_regime_result = detect_trend_regime(
        close, ema200, atr, slope_lookback=slope_lookback, 
        strong_trend_atr_threshold=strong_downtrend_atr
    )
    
    if vol_regime_result is None or trend_regime_result is None:
        return SetupResult(
            status=SetupStatus.NOT_EVALUATED,
            reason="Could not compute regime (insufficient data)"
        )
    
    # === PRIMARY TRIGGER: BB Reclaim ===
    has_overshoot, is_reclaim, overshoot_bars_ago = check_bb_reclaim(
        close, bb_lower, lookback_overshoot
    )
    
    if not has_overshoot:
        return SetupResult(
            status=SetupStatus.EVALUATED_NO_SETUP,
            reason="No BB overshoot in lookback period"
        )
    
    if not is_reclaim:
        return SetupResult(
            status=SetupStatus.EVALUATED_NO_SETUP,
            reason="BB overshoot exists but no reclaim yet"
        )
    
    # === CONFIRMATION 1: RSI Cross Up ===
    rsi_cross, rsi_now, rsi_prev_val = check_rsi_cross_up(rsi, rsi_threshold)
    
    # RSI cross is a soft confirmation - we proceed even without it
    # but it affects scoring
    
    # === CONFIRMATION 2: Volatility not PANIC ===
    if vol_regime_result.is_panic:
        return SetupResult(
            status=SetupStatus.EVALUATED_NO_SETUP,
            reason=f"Volatility regime is PANIC (ATR% at {vol_regime_result.percentile:.0f}th percentile)"
        )
    
    # === CONFIRMATION 3: Trend not STRONG_DOWNTREND ===
    if trend_regime_result.is_strong_downtrend:
        return SetupResult(
            status=SetupStatus.EVALUATED_NO_SETUP,
            reason=f"Trend regime is STRONG_DOWNTREND (price {trend_regime_result.price_vs_ema200:.1f} ATR below EMA200)"
        )
    
    # === SETUP TRIGGERED - Build Alert ===
    
    # Calculate score
    score = base_score
    evidence = []
    
    # Primary trigger evidence
    evidence.append(f"BB reclaim: prior close below lower band, now closed back inside")
    
    # RSI bonus
    if rsi_cross:
        evidence.append(f"RSI cross up: {rsi_prev_val:.1f} -> {rsi_now:.1f} above {rsi_threshold}")
        if rsi_now >= rsi_threshold + 5:
            score += strong_rsi_bonus
    else:
        # Still in oversold territory even without cross
        if rsi_now < 40:
            evidence.append(f"RSI oversold at {rsi_now:.1f}")
    
    # Volatility bonus
    if vol_regime_result.percentile < 70:
        score += low_vol_bonus
        evidence.append(f"Vol regime: {vol_regime_result.regime.value} ({vol_regime_result.percentile:.0f}th pctl)")
    else:
        evidence.append(f"Vol regime: {vol_regime_result.regime.value}")
    
    # Trend bonus
    if not trend_regime_result.is_strong_downtrend:
        if trend_regime_result.price_vs_ema200 >= -0.5:
            score += good_trend_bonus
        evidence.append(f"Trend regime: {trend_regime_result.regime.value}")
    
    # Volume penalty (soft - doesn't block)
    if not pd.isna(current_volume_sma) and current_volume_sma > 0:
        vol_ratio = current_volume / current_volume_sma
        if vol_ratio < 0.7:
            score -= low_volume_penalty
    
    # Clamp score
    score = max(0, min(100, score))
    
    # Trim evidence to max 3
    evidence = evidence[:3]
    
    # Calculate entry zone and invalidation
    entry_low = current_close * (1 - entry_zone_pct / 100)
    entry_high = current_close * (1 + entry_zone_pct / 100)
    invalidation = calculate_invalidation(low, current_atr)
    
    # Get hold window
    hold_window = hold_windows.get(timeframe, "6-24h")
    
    # Build alert
    alert = MeanReversionAlert(
        setup="MEAN_REVERSION_BB_RECLAIM",
        timeframe=timeframe,
        direction="LONG",
        trigger_close=float(current_close),
        entry_zone=(float(entry_low), float(entry_high)),
        invalidation=float(invalidation) if not pd.isna(invalidation) else 0.0,
        hold_window=hold_window,
        score=score,
        evidence=evidence,
        rsi=float(rsi_now),
        rsi_prev=float(rsi_prev_val),
        atr=float(current_atr),
        atr_pct=float(atr_pct) if not pd.isna(atr_pct) else 0.0,
        ema200=float(current_ema200),
        ema200_slope=float(trend_regime_result.ema200_slope),
        bb_lower=float(current_bb_lower),
        bb_middle=float(current_bb_middle),
        bb_upper=float(current_bb_upper),
        vol_regime=vol_regime_result.regime.value,
        trend_regime=trend_regime_result.regime.value,
    )
    
    return SetupResult(
        status=SetupStatus.SETUP_TRIGGERED,
        alert=alert
    )
