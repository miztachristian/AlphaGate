"""
ATR (Average True Range) Indicator
Used for volatility measurement and risk management.

Uses standard Wilder smoothing (not simple rolling mean) for proper ATR calculation.
"""

import pandas as pd
import numpy as np
from typing import Dict


def calculate_true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    Calculate True Range for each bar.
    
    True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of close prices
    
    Returns:
        Series with True Range values
    """
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, 
                  period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR) using Wilder smoothing.
    
    Wilder smoothing uses the update rule:
    ATR[t] = (ATR[t-1] * (period - 1) + TR[t]) / period
    
    This produces smoother, more stable ATR values compared to simple rolling mean.
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of close prices
        period: ATR period (default: 14)
    
    Returns:
        Series with ATR values. NaN for first `period` bars (warmup).
    """
    true_range = calculate_true_range(high, low, close)
    
    # Initialize ATR with NaN
    atr = pd.Series(np.nan, index=close.index)
    
    # First ATR is simple mean over first period
    if len(close) > period:
        atr.iloc[period] = true_range.iloc[1:period + 1].mean()
        
        # Wilder smoothing for remaining bars
        for i in range(period + 1, len(close)):
            atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + true_range.iloc[i]) / period
    
    return atr


def calculate_atr_vectorized(high: pd.Series, low: pd.Series, close: pd.Series, 
                             period: int = 14) -> pd.Series:
    """
    Calculate ATR using Wilder smoothing - vectorized version for performance.
    
    Uses pandas ewm with alpha = 1/period which is equivalent to Wilder smoothing.
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of close prices
        period: ATR period (default: 14)
    
    Returns:
        Series with ATR values. NaN for first `period` bars (warmup).
    """
    true_range = calculate_true_range(high, low, close)
    
    # Wilder smoothing is equivalent to EMA with alpha = 1/period
    alpha = 1.0 / period
    atr = true_range.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    
    # Mark warmup period as NaN
    atr.iloc[:period] = np.nan
    
    return atr


def calculate_atr_percent(atr: pd.Series, close: pd.Series) -> pd.Series:
    """
    Calculate ATR as a percentage of price.
    
    ATR% = ATR / close * 100
    
    Useful for comparing volatility across different price levels.
    
    Args:
        atr: Series of ATR values
        close: Series of close prices
    
    Returns:
        Series with ATR percentage values
    """
    return (atr / close) * 100


def calculate_stop_loss(entry_price: float, atr: float, position_type: str,
                        atr_multiplier: float = 1.5) -> float:
    """
    Calculate ATR-based stop loss.
    
    Strategy Rule: Stop loss = 1.5-2x ATR from entry
    
    Args:
        entry_price: Entry price
        atr: Current ATR value
        position_type: 'LONG' or 'SHORT'
        atr_multiplier: ATR multiplier (default: 1.5)
    
    Returns:
        Stop loss price
    """
    stop_distance = atr * atr_multiplier
    
    if position_type == 'LONG':
        return entry_price - stop_distance
    else:  # SHORT
        return entry_price + stop_distance


def calculate_take_profit(entry_price: float, atr: float, position_type: str,
                          atr_multiplier: float = 2.5) -> float:
    """
    Calculate ATR-based take profit.
    
    Strategy Rule: Take profit = 2-3x ATR from entry
    
    Args:
        entry_price: Entry price
        atr: Current ATR value
        position_type: 'LONG' or 'SHORT'
        atr_multiplier: ATR multiplier (default: 2.5)
    
    Returns:
        Take profit price
    """
    profit_distance = atr * atr_multiplier
    
    if position_type == 'LONG':
        return entry_price + profit_distance
    else:  # SHORT
        return entry_price - profit_distance


def check_volatility(atr_current: float, atr_sma: float) -> Dict[str, any]:
    """
    Check if market volatility is suitable for trading.
    
    Strategy Rule: Skip trades if ATR < its 20-bar average (market too quiet)
    
    Args:
        atr_current: Current ATR value
        atr_sma: 20-period SMA of ATR
    
    Returns:
        Dict with volatility info
    """
    result = {
        'is_tradeable': True,
        'relative_volatility': 0,
        'condition': ''
    }
    
    if atr_sma == 0:
        result['is_tradeable'] = False
        result['condition'] = 'Insufficient data'
        return result
    
    relative_vol = atr_current / atr_sma
    result['relative_volatility'] = relative_vol
    
    if relative_vol < 0.8:  # ATR below 80% of average
        result['is_tradeable'] = False
        result['condition'] = f'Low volatility ({relative_vol:.1%} of avg) - Market too quiet'
    elif relative_vol > 2.0:  # ATR above 200% of average
        result['is_tradeable'] = False
        result['condition'] = f'Extreme volatility ({relative_vol:.1%} of avg) - Too risky'
    else:
        result['condition'] = f'Normal volatility ({relative_vol:.1%} of avg)'
    
    return result


def calculate_position_size(account_balance: float, risk_percent: float,
                            entry_price: float, stop_loss: float) -> float:
    """
    Calculate position size based on risk management.
    
    Args:
        account_balance: Total account balance
        risk_percent: Risk per trade (e.g., 2.0 for 2%)
        entry_price: Entry price
        stop_loss: Stop loss price
    
    Returns:
        Position size (quantity)
    """
    risk_amount = account_balance * (risk_percent / 100)
    price_risk = abs(entry_price - stop_loss)
    
    if price_risk == 0:
        return 0
    
    position_size = risk_amount / price_risk
    return position_size
