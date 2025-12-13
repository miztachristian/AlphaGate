"""
Bollinger Bands Indicator
Identifies volatility extremes and mean reversion opportunities.
"""

import pandas as pd
from typing import Dict, Tuple


def calculate_bollinger_bands(prices: pd.Series, period: int = 20, 
                              std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.
    
    Args:
        prices: Series of closing prices
        period: SMA period (default: 20)
        std_dev: Standard deviation multiplier (default: 2.0)
    
    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    middle_band = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    
    upper_band = middle_band + (std * std_dev)
    lower_band = middle_band - (std * std_dev)
    
    return upper_band, middle_band, lower_band


def analyze_bollinger_signal(price: float, upper_band: float, 
                             middle_band: float, lower_band: float,
                             price_previous: float) -> Dict[str, any]:
    """
    Analyze Bollinger Bands for trading signals.
    
    Strategy Rules:
    - Short: Close above upper band (overbought) → wait for reversal candle
    - Long: Close below lower band (oversold) → wait for reversal candle
    - Band squeeze: Narrow bands signal imminent breakout
    
    Args:
        price: Current closing price
        upper_band: Upper Bollinger Band
        middle_band: Middle Bollinger Band (SMA)
        lower_band: Lower Bollinger Band
        price_previous: Previous closing price
    
    Returns:
        Dict with signal info
    """
    result = {
        'signal': 'NEUTRAL',
        'condition': '',
        'strength': 0.0,
        'band_position': ''
    }
    
    # Calculate band width (for squeeze detection)
    band_width = (upper_band - lower_band) / middle_band * 100
    
    # Overbought: Price above upper band
    if price > upper_band:
        result['band_position'] = 'ABOVE_UPPER'
        
        # Look for reversal (price coming back inside)
        if price_previous > upper_band and price < price_previous:
            result['signal'] = 'SHORT'
            result['condition'] = 'Price rejecting upper band (overbought reversal)'
            result['strength'] = 0.7
        else:
            result['condition'] = 'Price above upper band (wait for reversal)'
            result['strength'] = 0.4
    
    # Oversold: Price below lower band
    elif price < lower_band:
        result['band_position'] = 'BELOW_LOWER'
        
        # Look for reversal (price coming back inside)
        if price_previous < lower_band and price > price_previous:
            result['signal'] = 'LONG'
            result['condition'] = 'Price bouncing off lower band (oversold bounce)'
            result['strength'] = 0.7
        else:
            result['condition'] = 'Price below lower band (wait for reversal)'
            result['strength'] = 0.4
    
    # Near middle band (mean reversion zone)
    elif abs(price - middle_band) / middle_band < 0.01:  # Within 1%
        result['band_position'] = 'MIDDLE'
        result['condition'] = f'Price at middle band (neutral, band width: {band_width:.1f}%)'
    
    # Inside bands
    else:
        if price > middle_band:
            result['band_position'] = 'UPPER_HALF'
        else:
            result['band_position'] = 'LOWER_HALF'
        
        result['condition'] = f'Price inside bands (band width: {band_width:.1f}%)'
    
    return result


def detect_bollinger_squeeze(upper_band: pd.Series, lower_band: pd.Series,
                             middle_band: pd.Series, lookback: int = 20) -> Dict[str, any]:
    """
    Detect Bollinger Band squeeze pattern.
    
    Strategy Rule: Narrow bands → imminent big move
    Wait for breakout + volume, then trade direction
    
    Args:
        upper_band: Series of upper bands
        lower_band: Series of lower bands
        middle_band: Series of middle bands
        lookback: Periods to analyze
    
    Returns:
        Dict with squeeze info
    """
    if len(upper_band) < lookback:
        return {'is_squeeze': False, 'condition': 'Insufficient data'}
    
    # Calculate recent band widths
    recent_widths = ((upper_band - lower_band) / middle_band * 100).tail(lookback)
    
    current_width = recent_widths.iloc[-1]
    avg_width = recent_widths.mean()
    min_width = recent_widths.min()
    
    result = {
        'is_squeeze': False,
        'current_width': current_width,
        'avg_width': avg_width,
        'condition': ''
    }
    
    # Squeeze detected: current width near minimum and below average
    if current_width <= min_width * 1.1 and current_width < avg_width * 0.7:
        result['is_squeeze'] = True
        result['condition'] = f'Bollinger squeeze detected ({current_width:.1f}% vs avg {avg_width:.1f}%) - Big move imminent'
    else:
        result['condition'] = f'Normal band width ({current_width:.1f}%)'
    
    return result


def calculate_bollinger_percent_b(price: float, upper_band: float, 
                                  lower_band: float) -> float:
    """
    Calculate %B indicator (price position within bands).
    
    %B = (price - lower_band) / (upper_band - lower_band)
    
    Values:
    - > 1: Above upper band
    - 0.5: At middle band
    - < 0: Below lower band
    
    Args:
        price: Current price
        upper_band: Upper band value
        lower_band: Lower band value
    
    Returns:
        %B value
    """
    if upper_band == lower_band:
        return 0.5
    
    return (price - lower_band) / (upper_band - lower_band)
