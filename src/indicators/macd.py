"""
MACD (Moving Average Convergence Divergence) Indicator
Identifies momentum shifts and trend changes.
"""

import pandas as pd
from typing import Dict, Tuple


def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, 
                   signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD indicator.
    
    Args:
        prices: Series of closing prices
        fast: Fast EMA period (default: 12)
        slow: Slow EMA period (default: 26)
        signal: Signal line period (default: 9)
    
    Returns:
        Tuple of (macd_line, signal_line, histogram)
    """
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def analyze_macd_signal(macd_current: float, macd_previous: float,
                        signal_current: float, signal_previous: float,
                        histogram_current: float, histogram_previous: float,
                        price: float, ema_20: float) -> Dict[str, any]:
    """
    Analyze MACD for trading signals.
    
    Strategy Rules:
    - Long: MACD crosses above signal + price above 20 EMA
    - Short: MACD crosses below signal + price below 20 EMA
    - Stronger when cross happens near zero line
    
    Args:
        macd_current: Current MACD line value
        macd_previous: Previous MACD line value
        signal_current: Current signal line value
        signal_previous: Previous signal line value
        histogram_current: Current histogram value
        histogram_previous: Previous histogram value
        price: Current price
        ema_20: 20 EMA value
    
    Returns:
        Dict with signal info
    """
    result = {
        'signal': 'NEUTRAL',
        'condition': '',
        'strength': 0.0,
        'crossover': None
    }
    
    # Bullish crossover: MACD crosses above signal
    if macd_previous <= signal_previous and macd_current > signal_current:
        result['crossover'] = 'BULLISH'
        
        # Confirm with price position relative to 20 EMA
        if price > ema_20:
            result['signal'] = 'LONG'
            result['condition'] = 'MACD bullish crossover + price above 20 EMA'
            
            # Stronger if near zero line
            if abs(macd_current) < 0.5:
                result['strength'] = 0.8
            else:
                result['strength'] = 0.6
        else:
            result['condition'] = 'MACD bullish crossover (waiting for price confirmation)'
            result['strength'] = 0.3
    
    # Bearish crossover: MACD crosses below signal
    elif macd_previous >= signal_previous and macd_current < signal_current:
        result['crossover'] = 'BEARISH'
        
        if price < ema_20:
            result['signal'] = 'SHORT'
            result['condition'] = 'MACD bearish crossover + price below 20 EMA'
            
            if abs(macd_current) < 0.5:
                result['strength'] = 0.8
            else:
                result['strength'] = 0.6
        else:
            result['condition'] = 'MACD bearish crossover (waiting for price confirmation)'
            result['strength'] = 0.3
    
    # Momentum slowing (histogram shrinking toward zero)
    elif abs(histogram_previous) > 0 and abs(histogram_current) < abs(histogram_previous) * 0.5:
        result['condition'] = 'MACD momentum slowing (histogram shrinking toward zero)'
        result['strength'] = 0.2
    
    return result


def check_macd_divergence(prices: pd.Series, macd: pd.Series, 
                          lookback: int = 14) -> str:
    """
    Detect divergence between price and MACD.
    
    Args:
        prices: Series of closing prices
        macd: Series of MACD values
        lookback: Periods to analyze
    
    Returns:
        'BULLISH', 'BEARISH', or None
    """
    if len(prices) < lookback or len(macd) < lookback:
        return None
    
    recent_prices = prices.tail(lookback)
    recent_macd = macd.tail(lookback)
    
    # Bullish: Price lower low, MACD higher low
    price_min = recent_prices.min()
    macd_min = recent_macd.min()
    
    if recent_prices.iloc[-1] < price_min and recent_macd.iloc[-1] > macd_min:
        return 'BULLISH'
    
    # Bearish: Price higher high, MACD lower high
    price_max = recent_prices.max()
    macd_max = recent_macd.max()
    
    if recent_prices.iloc[-1] > price_max and recent_macd.iloc[-1] < macd_max:
        return 'BEARISH'
    
    return None
