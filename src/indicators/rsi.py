"""
RSI (Relative Strength Index) Indicator
Measures momentum strength and overbought/oversold conditions.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate RSI (Relative Strength Index).
    
    Args:
        prices: Series of closing prices
        period: RSI period (default: 14)
    
    Returns:
        Series with RSI values (0-100)
    """
    delta = prices.diff()
    
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def analyze_rsi_signal(rsi_current: float, rsi_previous: float, 
                       overbought: float = 70, oversold: float = 30) -> Dict[str, any]:
    """
    Analyze RSI for trading signals.
    
    Strategy Rules:
    - Long: RSI crosses above 30 from oversold
    - Short: RSI crosses below 70 from overbought
    - Neutral: RSI in 40-60 range
    
    Args:
        rsi_current: Current RSI value
        rsi_previous: Previous RSI value
        overbought: Overbought threshold (default: 70)
        oversold: Oversold threshold (default: 30)
    
    Returns:
        Dict with signal info: {
            'signal': 'LONG' | 'SHORT' | 'NEUTRAL',
            'condition': str,
            'strength': float (0-1)
        }
    """
    signal = {
        'signal': 'NEUTRAL',
        'condition': '',
        'strength': 0.0
    }
    
    # Long signal: RSI crosses above 30 from oversold
    if rsi_previous < oversold and rsi_current >= oversold:
        signal['signal'] = 'LONG'
        signal['condition'] = f'RSI oversold bounce ({rsi_current:.1f} crossing above {oversold})'
        signal['strength'] = min((oversold - rsi_previous) / 10, 1.0)  # Strength based on how oversold
        
    # Short signal: RSI crosses below 70 from overbought
    elif rsi_previous > overbought and rsi_current <= overbought:
        signal['signal'] = 'SHORT'
        signal['condition'] = f'RSI overbought reversal ({rsi_current:.1f} crossing below {overbought})'
        signal['strength'] = min((rsi_previous - overbought) / 10, 1.0)
    
    # Extremely oversold (strong long potential)
    elif rsi_current < 20:
        signal['signal'] = 'LONG'
        signal['condition'] = f'RSI extremely oversold ({rsi_current:.1f})'
        signal['strength'] = 0.8
    
    # Extremely overbought (strong short potential)
    elif rsi_current > 80:
        signal['signal'] = 'SHORT'
        signal['condition'] = f'RSI extremely overbought ({rsi_current:.1f})'
        signal['strength'] = 0.8
    
    # Neutral zone
    elif 40 <= rsi_current <= 60:
        signal['condition'] = f'RSI neutral zone ({rsi_current:.1f})'
        signal['strength'] = 0.0
    
    return signal


def detect_rsi_divergence(prices: pd.Series, rsi: pd.Series, lookback: int = 14) -> Optional[str]:
    """
    Detect bullish or bearish divergence between price and RSI.
    
    Divergence Rules:
    - Bullish: Price makes lower low, RSI makes higher low
    - Bearish: Price makes higher high, RSI makes lower high
    
    Args:
        prices: Series of closing prices
        rsi: Series of RSI values
        lookback: Number of periods to look back
    
    Returns:
        'BULLISH', 'BEARISH', or None
    """
    if len(prices) < lookback or len(rsi) < lookback:
        return None
    
    recent_prices = prices.tail(lookback).reset_index(drop=True)
    recent_rsi = rsi.tail(lookback).reset_index(drop=True)
    
    # Find local extreme positions (integer indices)
    price_min_pos = int(recent_prices.idxmin())
    price_max_pos = int(recent_prices.idxmax())
    rsi_min_pos = int(recent_rsi.idxmin())
    rsi_max_pos = int(recent_rsi.idxmax())
    
    # Bullish divergence: price lower low, RSI higher low
    # Check that the min isn't too recent (last 3 bars)
    if price_min_pos < len(recent_prices) - 3 and price_min_pos > 0:
        prev_price_low = recent_prices.iloc[:price_min_pos].min()
        curr_price_low = recent_prices.iloc[-1]
        
        if rsi_min_pos > 0:
            prev_rsi_low = recent_rsi.iloc[:rsi_min_pos].min()
        else:
            prev_rsi_low = recent_rsi.iloc[0]
        curr_rsi_low = recent_rsi.iloc[-1]
        
        if curr_price_low < prev_price_low and curr_rsi_low > prev_rsi_low:
            return 'BULLISH'
    
    # Bearish divergence: price higher high, RSI lower high
    if price_max_pos < len(recent_prices) - 3 and price_max_pos > 0:
        prev_price_high = recent_prices.iloc[:price_max_pos].max()
        curr_price_high = recent_prices.iloc[-1]
        
        if rsi_max_pos > 0:
            prev_rsi_high = recent_rsi.iloc[:rsi_max_pos].max()
        else:
            prev_rsi_high = recent_rsi.iloc[0]
        curr_rsi_high = recent_rsi.iloc[-1]
        
        if curr_price_high > prev_price_high and curr_rsi_high < prev_rsi_high:
            return 'BEARISH'
    
    return None
