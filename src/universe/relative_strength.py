"""
Relative Strength Pre-Screen
Strategy 5 from Brainstorming Session

Rules:
- Rank all stocks by momentum score (3-month return * volume weight).
- Only trade top 10% (strongest movers).
"""

import pandas as pd
import numpy as np
from typing import Dict, List

def calculate_momentum_score(df: pd.DataFrame, return_lookback_bars: int = 60) -> float:
    """
    Calculate momentum score for a single stock.
    return_lookback_bars: 60 bars (approx 3 months if daily)
    """
    if len(df) <= return_lookback_bars:
        return 0.0
    
    close = df['close']
    volume = df['volume']
    
    current_close = close.iloc[-1]
    past_close = close.iloc[-return_lookback_bars]
    
    if past_close == 0:
        return 0.0
        
    ret = (current_close - past_close) / past_close
    
    # Calculate average volume over the period as a simple weight proxy
    # We can normalize volume or just use log(volume) as weight
    avg_vol = volume.iloc[-return_lookback_bars:].mean()
    vol_weight = np.log1p(avg_vol) if avg_vol > 0 else 1.0
    
    return float(ret * vol_weight)

def rank_universe_by_relative_strength(
    stocks_data: Dict[str, pd.DataFrame], 
    return_lookback_bars: int = 60,
    top_percentile: float = 0.10
) -> List[str]:
    """
    Rank a dictionary of DataFrames by momentum score and return the top N%.
    
    Args:
        stocks_data: Dict[symbol, DataFrame]
        return_lookback_bars: Bars to lookback for return
        top_percentile: Top 10% = 0.10
        
    Returns:
        List of top symbols
    """
    scores = {}
    for symbol, df in stocks_data.items():
        score = calculate_momentum_score(df, return_lookback_bars)
        scores[symbol] = score
        
    if not scores:
        return []
        
    # Sort symbols by score descending
    sorted_symbols = sorted(scores.keys(), key=lambda s: scores[s], reverse=True)
    
    # Take top %
    top_n = max(1, int(len(sorted_symbols) * top_percentile))
    
    return sorted_symbols[:top_n]
