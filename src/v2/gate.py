"""
V2 Gate Module - Go/No-Go decision logic for trade setups.

The gate provides a secondary filter after a setup is triggered, checking:
- Price/liquidity minimums (penny stock, illiquid)
- Regime combinations (panic vol, falling knife, etc.)
- Produces GO, NO_GO, or NOT_EVALUATED decisions

This module is ONLY used when engine.mode is "v2" or "shadow".
V1 mode skips the gate entirely for backward compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np


class GateStatus(Enum):
    """Result status of gate evaluation."""
    GO = "GO"                    # Setup passes gate, proceed with alert
    NO_GO = "NO_GO"              # Setup fails gate, suppress alert
    NOT_EVALUATED = "NOT_EVALUATED"  # Missing required features, cannot decide


class ScrutinyLevel(Enum):
    """Scrutiny level for passed setups."""
    NORMAL = "NORMAL"  # Standard confidence
    HIGH = "HIGH"      # Elevated scrutiny (e.g., weak downtrend + chop)


@dataclass
class GateResult:
    """Result of gate evaluation."""
    status: GateStatus
    reasons: List[str] = field(default_factory=list)
    scrutiny_level: ScrutinyLevel = ScrutinyLevel.NORMAL
    tags: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "reasons": self.reasons,
            "scrutiny_level": self.scrutiny_level.value,
            "tags": self.tags,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class GateFeatures:
    """Features required for gate evaluation."""
    last_price: Optional[float] = None
    avg_dollar_volume_20d: Optional[float] = None
    trend_regime: Optional[str] = None
    vol_regime: Optional[str] = None
    chop_regime: Optional[str] = None
    news_risk: Optional[str] = None
    score: Optional[int] = None          # Setup score (0-100)
    atr_pct: Optional[float] = None       # ATR as % of price
    
    def is_complete(self) -> bool:
        """Check if all required features are present."""
        # Note: chop_regime is optional - we don't use it for blocking decisions
        required = [
            self.last_price,
            self.avg_dollar_volume_20d,
            self.trend_regime,
            self.vol_regime,
        ]
        return all(f is not None for f in required)
    
    def missing_features(self) -> List[str]:
        """Return list of missing required features."""
        # Note: chop_regime is optional - we don't use it for blocking decisions
        missing = []
        if self.last_price is None:
            missing.append("last_price")
        if self.avg_dollar_volume_20d is None:
            missing.append("avg_dollar_volume_20d")
        if self.trend_regime is None:
            missing.append("trend_regime")
        if self.vol_regime is None:
            missing.append("vol_regime")
        return missing


@dataclass 
class GateConfig:
    """Configuration for gate evaluation."""
    # Hard filters
    min_price: float = 5.0
    min_avg_dollar_volume_20d: float = 20_000_000
    # Score filters
    min_score: int = 70                   # Minimum score to pass gate
    downtrend_min_score: int = 80         # Higher bar for downtrend trades (replaces min_score_downtrend)
    # Volatility filters
    max_atr_pct: float = 5.0              # Max ATR% (filter extremely volatile)
    # Toxic regime block (V2.1 key improvement)
    block_downtrend_high_vol: bool = True # NO_GO on DOWNTREND + HIGH volatility
    # Regime allowances
    allow_weak_downtrend: bool = True     # Allow GO with HIGH scrutiny in weak downtrend
    # Event risk
    strict_earnings_block: bool = False   # Placeholder for earnings calendar
    block_high_news_risk: bool = False    # NO_GO on HIGH news risk (disabled by default)


def compute_gate_features(
    df: pd.DataFrame,
    trend_regime: Optional[str] = None,
    vol_regime: Optional[str] = None,
    chop_regime: Optional[str] = None,
    news_risk: Optional[str] = None,
) -> GateFeatures:
    """
    Compute gate features from OHLCV DataFrame.
    
    Args:
        df: DataFrame with OHLCV data (must have close, volume columns)
        trend_regime: Pre-computed trend regime (from existing analysis)
        vol_regime: Pre-computed volatility regime (from existing analysis)
        chop_regime: Pre-computed chop regime (from existing analysis)
        news_risk: News risk level if available
    
    Returns:
        GateFeatures dataclass with computed values
    """
    features = GateFeatures(
        trend_regime=trend_regime,
        vol_regime=vol_regime,
        chop_regime=chop_regime,
        news_risk=news_risk,
    )
    
    if df is None or df.empty:
        return features
    
    # Last price
    if 'close' in df.columns and len(df) > 0:
        features.last_price = float(df['close'].iloc[-1])
    
    # Average dollar volume (20 trading days)
    if 'close' in df.columns and 'volume' in df.columns:
        try:
            features.avg_dollar_volume_20d = _compute_avg_dollar_volume_20d(df)
        except Exception:
            pass
    
    return features


def _compute_avg_dollar_volume_20d(df: pd.DataFrame) -> Optional[float]:
    """
    Compute average daily dollar volume over last 20 trading days.
    
    Resamples intraday data to daily, then computes:
    daily_dollar_volume = daily_close * daily_volume
    
    Returns average over last 20 trading days.
    """
    if df is None or df.empty:
        return None
    
    if 'close' not in df.columns or 'volume' not in df.columns:
        return None
    
    # Ensure we have a datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    
    # Resample to daily
    try:
        daily = df.resample('1D').agg({
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        if len(daily) < 5:  # Need at least 5 days
            return None
        
        # Compute daily dollar volume
        daily['dollar_volume'] = daily['close'] * daily['volume']
        
        # Take last 20 days (or fewer if not available)
        recent_days = min(20, len(daily))
        avg_dollar_volume = daily['dollar_volume'].tail(recent_days).mean()
        
        if pd.isna(avg_dollar_volume):
            return None
            
        return float(avg_dollar_volume)
        
    except Exception:
        return None


def evaluate_gate(
    symbol: str,
    timeframe: str,
    setup_name: str,
    direction: str,
    features: GateFeatures,
    gate_config: GateConfig,
) -> GateResult:
    """
    Evaluate the V2 gate for a triggered setup.
    
    Rules applied in order (fail-closed design):
    1. Missing features -> NOT_EVALUATED (MISSING_FEATURES)
    2. Penny stock (price < min_price) -> NO_GO (PENNY_STOCK)
    3. Illiquid (dollar volume < threshold) -> NO_GO (ILLIQUID)
    4. PANIC volatility -> NO_GO (PANIC_VOL)
    5. Falling knife (STRONG_DOWN + HIGH/PANIC vol) -> NO_GO (FALLING_KNIFE_REGIME)
    6. Score too low (< min_score) -> NO_GO (LOW_SCORE)
    7. Toxic regime (DOWNTREND + HIGH vol) -> NO_GO (DOWNTREND_HIGH_VOL_BLOCK)
    8. High ATR% (> max_atr_pct) -> NO_GO (HIGH_ATR)
    9. HIGH news risk (if enabled) -> NO_GO (HIGH_NEWS_RISK)
    10. Downtrend requires higher score -> NO_GO (DOWNTREND_SCORE_TOO_LOW) or GO w/ HIGH scrutiny
    11. Allowed baseline regimes -> GO (REGIME_ALLOWED)
    12. Default -> NO_GO (REGIME_BLOCK)
    
    Args:
        symbol: Stock ticker
        timeframe: Timeframe being analyzed
        setup_name: Name of the triggered setup
        direction: Trade direction (LONG/SHORT)
        features: GateFeatures with computed values
        gate_config: GateConfig with thresholds
    
    Returns:
        GateResult with status, reasons, and scrutiny level
    """
    # Build tags for logging (always include regimes and score)
    tags = {
        "trend_regime": features.trend_regime,
        "vol_regime": features.vol_regime,
        "chop_regime": features.chop_regime,
    }
    if features.news_risk:
        tags["news_risk"] = features.news_risk
    if features.score is not None:
        tags["score"] = features.score
    if features.atr_pct is not None:
        tags["atr_pct"] = round(features.atr_pct, 2)
    
    # Normalize regimes for comparison
    trend_regime = (features.trend_regime or "").upper()
    vol_regime = (features.vol_regime or "").upper()
    chop_regime = (features.chop_regime or "").upper()
    
    # Regime classification helpers
    downtrend_regimes = {"DOWNTREND", "WEAK_DOWNTREND", "WEAK_DOWN", "STRONG_DOWNTREND", "STRONG_DOWN"}
    strong_down_regimes = {"STRONG_DOWNTREND", "STRONG_DOWN"}
    weak_down_regimes = {"DOWNTREND", "WEAK_DOWNTREND", "WEAK_DOWN"}
    good_trends = {"NEUTRAL", "WEAK_UP", "UPTREND", "STRONG_UPTREND", "WEAK_UPTREND"}
    
    is_downtrend = trend_regime in downtrend_regimes
    is_strong_down = trend_regime in strong_down_regimes
    is_weak_down = trend_regime in weak_down_regimes
    
    # =========================================================================
    # RULE 1: Missing features -> NOT_EVALUATED
    # =========================================================================
    if not features.is_complete():
        missing = features.missing_features()
        return GateResult(
            status=GateStatus.NOT_EVALUATED,
            reasons=[f"MISSING_FEATURES: {', '.join(missing)}"],
            tags=tags,
        )
    
    # Also check for score (required for V2)
    if features.score is None:
        return GateResult(
            status=GateStatus.NOT_EVALUATED,
            reasons=["MISSING_FEATURES: score"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 2: Penny stock filter
    # =========================================================================
    if features.last_price < gate_config.min_price:
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=[f"PENNY_STOCK: price ${features.last_price:.2f} < ${gate_config.min_price:.2f}"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 3: Liquidity filter
    # =========================================================================
    if features.avg_dollar_volume_20d < gate_config.min_avg_dollar_volume_20d:
        vol_millions = features.avg_dollar_volume_20d / 1_000_000
        threshold_millions = gate_config.min_avg_dollar_volume_20d / 1_000_000
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=[f"ILLIQUID: avg dollar vol ${vol_millions:.1f}M < ${threshold_millions:.1f}M"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 4: PANIC volatility -> NO_GO
    # =========================================================================
    if vol_regime == "PANIC":
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=["PANIC_VOL: volatility in PANIC regime"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 5: Falling knife (STRONG_DOWN + HIGH/PANIC vol) -> NO_GO
    # =========================================================================
    is_high_vol = vol_regime in ("HIGH", "PANIC")
    if is_strong_down and is_high_vol:
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=[f"FALLING_KNIFE_REGIME: {trend_regime} + {vol_regime}"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 6: Minimum score filter (applies to all)
    # =========================================================================
    min_required_score = gate_config.min_score
    if setup_name == "VOLATILITY_SQUEEZE_BREAKOUT":
        min_required_score = 80
        
    if features.score < min_required_score:
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=[f"LOW_SCORE: {features.score} < {min_required_score} minimum"],
            tags=tags,
        )
        
    # =========================================================================
    # RULE 6.5: Volatility Squeeze CHOP block
    # =========================================================================
    if setup_name == "VOLATILITY_SQUEEZE_BREAKOUT" and chop_regime == "CHOP":
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=["CHOP_REGIME_BLOCK: Volatility Squeeze blocked in CHOP regime"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 7: Toxic regime block (DOWNTREND + HIGH vol) - KEY V2.1 RULE
    # =========================================================================
    if gate_config.block_downtrend_high_vol:
        if is_downtrend and vol_regime == "HIGH":
            return GateResult(
                status=GateStatus.NO_GO,
                reasons=[f"DOWNTREND_HIGH_VOL_BLOCK: {trend_regime} + HIGH vol is toxic for mean reversion"],
                tags=tags,
            )
    
    # =========================================================================
    # RULE 8: High ATR% filter (too volatile for mean reversion)
    # =========================================================================
    if features.atr_pct is not None and features.atr_pct > gate_config.max_atr_pct:
        return GateResult(
            status=GateStatus.NO_GO,
            reasons=[f"HIGH_ATR: ATR {features.atr_pct:.2f}% > {gate_config.max_atr_pct:.1f}% max"],
            tags=tags,
        )
    
    # =========================================================================
    # RULE 9: HIGH news risk filter (if enabled)
    # =========================================================================
    if gate_config.block_high_news_risk and features.news_risk:
        if features.news_risk.upper() == "HIGH":
            return GateResult(
                status=GateStatus.NO_GO,
                reasons=["HIGH_NEWS_RISK: elevated event risk"],
                tags=tags,
            )
    
    # =========================================================================
    # RULE 10: Downtrend stricter threshold (non-toxic downtrends only)
    # For weak downtrends with NORMAL vol: require higher score
    # =========================================================================
    if is_weak_down and vol_regime == "NORMAL":
        if features.score < gate_config.downtrend_min_score:
            return GateResult(
                status=GateStatus.NO_GO,
                reasons=[f"DOWNTREND_SCORE_TOO_LOW: {features.score} < {gate_config.downtrend_min_score} required in downtrend"],
                tags=tags,
            )
        
        # Downtrend with sufficient score - check for squeeze (chop)
        is_chop = chop_regime == "CHOP"
        if is_chop:
            # Avoid mean reversion during squeeze in downtrend
            return GateResult(
                status=GateStatus.NO_GO,
                reasons=[f"REGIME_BLOCK: {trend_regime} + CHOP (squeeze risk)"],
                tags=tags,
            )
        
        # Downtrend + NORMAL vol + good score + no squeeze -> GO with HIGH scrutiny
        if gate_config.allow_weak_downtrend:
            return GateResult(
                status=GateStatus.GO,
                reasons=[f"WEAK_DOWNTREND_ALLOWED: {trend_regime} + {vol_regime} + score {features.score}"],
                scrutiny_level=ScrutinyLevel.HIGH,
                tags=tags,
            )
    
    # =========================================================================
    # RULE 11: Allowed baseline regimes
    # GO if trend in {NEUTRAL, UPTREND, WEAK_UP, STRONG_UPTREND} AND vol in {NORMAL, HIGH, LOW}
    # If vol == HIGH, return GO with scrutiny_level=HIGH
    # =========================================================================
    allowed_vol = {"NORMAL", "HIGH", "LOW", "DEAD"}
    
    if trend_regime in good_trends and vol_regime in allowed_vol:
        scrutiny = ScrutinyLevel.HIGH if vol_regime == "HIGH" else ScrutinyLevel.NORMAL
        return GateResult(
            status=GateStatus.GO,
            reasons=[f"REGIME_ALLOWED: {trend_regime} + {vol_regime}"],
            scrutiny_level=scrutiny,
            tags=tags,
        )
    
    # =========================================================================
    # RULE 12: Default -> NO_GO (fail-closed)
    # =========================================================================
    return GateResult(
        status=GateStatus.NO_GO,
        reasons=[f"REGIME_BLOCK: {trend_regime} + {vol_regime} not allowed"],
        tags=tags,
    )
