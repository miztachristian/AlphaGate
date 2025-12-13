"""
ATR (Average True Range) Indicator
Used for volatility measurement and risk management.
"""

import pandas as pd
from typing import Dict


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, 
                  period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).
    
    Args:
        high: Series of high prices
        low: Series of low prices
        close: Series of close prices
        period: ATR period (default: 14)
    
    Returns:
        Series with ATR values
    """
    # True Range calculation
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    
    return atr


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
