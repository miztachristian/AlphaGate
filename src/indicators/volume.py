"""
Volume Analysis
Confirms breakouts and detects exhaustion patterns.
"""

import pandas as pd
from typing import Dict


def analyze_volume(volumes: pd.Series, volume_sma: pd.Series, 
                   spike_multiplier: float = 1.5) -> Dict[str, any]:
    """
    Analyze volume for trading confirmation.
    
    Strategy Rules:
    - High volume breakout (1.5x avg) = real move, trade it
    - Low volume breakout = weak move, fade or skip
    - Volume spike after long run = exhaustion (reversal)
    
    Args:
        volumes: Series of volume data
        volume_sma: Simple moving average of volume
        spike_multiplier: Threshold for volume spike (default: 1.5x)
    
    Returns:
        Dict with volume analysis
    """
    if len(volumes) == 0 or len(volume_sma) == 0:
        return {
            'is_spike': False,
            'relative_volume': 0,
            'condition': 'No volume data'
        }
    
    current_volume = volumes.iloc[-1]
    avg_volume = volume_sma.iloc[-1]
    
    relative_volume = current_volume / avg_volume if avg_volume > 0 else 0
    
    result = {
        'is_spike': relative_volume >= spike_multiplier,
        'relative_volume': relative_volume,
        'condition': ''
    }
    
    if relative_volume >= spike_multiplier:
        result['condition'] = f'High volume ({relative_volume:.1f}x avg) - Strong confirmation'
    elif relative_volume >= 1.0:
        result['condition'] = f'Normal volume ({relative_volume:.1f}x avg)'
    else:
        result['condition'] = f'Low volume ({relative_volume:.1f}x avg) - Weak move'
    
    return result


def detect_volume_exhaustion(volumes: pd.Series, prices: pd.Series, 
                             lookback: int = 10) -> bool:
    """
    Detect volume exhaustion pattern.
    Volume spike after extended move often signals reversal.
    
    Args:
        volumes: Series of volume data
        prices: Series of prices
        lookback: Number of periods to analyze
    
    Returns:
        True if exhaustion pattern detected
    """
    if len(volumes) < lookback or len(prices) < lookback:
        return False
    
    recent_volumes = volumes.tail(lookback)
    recent_prices = prices.tail(lookback)
    
    # Check if price has been trending
    price_change = (recent_prices.iloc[-1] - recent_prices.iloc[0]) / recent_prices.iloc[0]
    
    # Strong trend: >5% move
    strong_trend = abs(price_change) > 0.05
    
    if not strong_trend:
        return False
    
    # Check if current volume is significantly higher than recent average
    avg_volume = recent_volumes.iloc[:-1].mean()
    current_volume = recent_volumes.iloc[-1]
    
    volume_spike = current_volume > (avg_volume * 2.0)  # 2x average
    
    return volume_spike


def calculate_volume_profile(volumes: pd.Series, period: int = 20) -> pd.Series:
    """
    Calculate rolling volume moving average.
    
    Args:
        volumes: Series of volume data
        period: SMA period (default: 20)
    
    Returns:
        Series with volume SMA
    """
    return volumes.rolling(window=period).mean()
