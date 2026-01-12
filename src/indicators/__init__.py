"""
Indicators Package
Contains all technical indicator calculations for the trading strategy.

v2: Now using Wilder smoothing for RSI and ATR (standard implementations).
"""

from .rsi import calculate_rsi, calculate_rsi_vectorized
from .ema import calculate_ema, check_ema_trend
from .macd import calculate_macd
from .volume import analyze_volume
from .atr import calculate_atr, calculate_atr_vectorized, calculate_true_range, calculate_atr_percent
from .bollinger import calculate_bollinger_bands

__all__ = [
    'calculate_rsi',
    'calculate_rsi_vectorized',
    'calculate_ema',
    'check_ema_trend',
    'calculate_macd',
    'analyze_volume',
    'calculate_atr',
    'calculate_atr_vectorized',
    'calculate_true_range',
    'calculate_atr_percent',
    'calculate_bollinger_bands'
]
