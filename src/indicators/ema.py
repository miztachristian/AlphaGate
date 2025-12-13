"""
EMA (Exponential Moving Average) Indicator
Used for trend identification and pullback entries.
"""

import pandas as pd
from typing import Dict, Tuple


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average.
    
    Args:
        prices: Series of closing prices
        period: EMA period
    
    Returns:
        Series with EMA values
    """
    return prices.ewm(span=period, adjust=False).mean()


def check_ema_trend(ema_50: float, ema_200: float) -> str:
    """
    Determine market trend based on EMA crossover.
    
    Strategy Rules:
    - Bullish: 50 EMA > 200 EMA
    - Bearish: 50 EMA < 200 EMA
    
    Args:
        ema_50: Current 50 EMA value
        ema_200: Current 200 EMA value
    
    Returns:
        'BULLISH' or 'BEARISH'
    """
    return 'BULLISH' if ema_50 > ema_200 else 'BEARISH'


def analyze_ema_pullback(price: float, ema_20: float, ema_50: float, 
                         ema_200: float) -> Dict[str, any]:
    """
    Analyze EMA for pullback entry signals.
    
    Strategy Rules:
    - Long: 50>200 (bullish trend) + price near 20 EMA on pullback
    - Short: 50<200 (bearish trend) + price near 20 EMA on rally
    - Avoid: Price too far from 50 EMA (overextended)
    
    Args:
        price: Current price
        ema_20: 20 EMA value
        ema_50: 50 EMA value
        ema_200: 200 EMA value
    
    Returns:
        Dict with signal info
    """
    trend = check_ema_trend(ema_50, ema_200)
    
    # Calculate distances
    distance_to_20ema = abs(price - ema_20) / price * 100
    distance_to_50ema = abs(price - ema_50) / price * 100
    
    signal = {
        'signal': 'NEUTRAL',
        'trend': trend,
        'condition': '',
        'strength': 0.0
    }
    
    # Check if price is overextended (too far from 50 EMA)
    if distance_to_50ema > 5:  # More than 5% away
        if price > ema_50:
            signal['condition'] = f'Price overextended above 50 EMA ({distance_to_50ema:.1f}%)'
        else:
            signal['condition'] = f'Price overextended below 50 EMA ({distance_to_50ema:.1f}%)'
        return signal
    
    # Bullish trend + pullback to 20 EMA
    if trend == 'BULLISH' and distance_to_20ema < 2:  # Within 2% of 20 EMA
        if price >= ema_20:  # Bouncing off support
            signal['signal'] = 'LONG'
            signal['condition'] = f'Bullish trend + pullback to 20 EMA (trend support)'
            signal['strength'] = 0.7
    
    # Bearish trend + rally to 20 EMA
    elif trend == 'BEARISH' and distance_to_20ema < 2:
        if price <= ema_20:  # Rejecting from resistance
            signal['signal'] = 'SHORT'
            signal['condition'] = f'Bearish trend + rally to 20 EMA (trend resistance)'
            signal['strength'] = 0.7
    
    return signal


def detect_ema_crossover(ema_50_current: float, ema_50_previous: float,
                         ema_200_current: float, ema_200_previous: float) -> Dict[str, any]:
    """
    Detect golden cross (bullish) or death cross (bearish).
    
    Args:
        ema_50_current: Current 50 EMA
        ema_50_previous: Previous 50 EMA
        ema_200_current: Current 200 EMA
        ema_200_previous: Previous 200 EMA
    
    Returns:
        Dict with crossover info
    """
    result = {
        'crossover': None,
        'signal': 'NEUTRAL',
        'strength': 0.0
    }
    
    # Golden Cross: 50 EMA crosses above 200 EMA
    if ema_50_previous <= ema_200_previous and ema_50_current > ema_200_current:
        result['crossover'] = 'GOLDEN_CROSS'
        result['signal'] = 'LONG'
        result['strength'] = 0.9
    
    # Death Cross: 50 EMA crosses below 200 EMA
    elif ema_50_previous >= ema_200_previous and ema_50_current < ema_200_current:
        result['crossover'] = 'DEATH_CROSS'
        result['signal'] = 'SHORT'
        result['strength'] = 0.9
    
    return result
