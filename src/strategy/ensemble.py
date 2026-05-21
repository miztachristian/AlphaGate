"""
Multi-Strategy Ensemble
Strategy 4 from Brainstorming Session

Rules:
- NORMAL vol + UPTREND -> Run Strategy 1 (Pullback) + Strategy 2 (Breakout)
- DEAD vol -> Run Strategy 3 (Squeeze)
- HIGH vol + UPTREND -> Run Strategy 2 only
- DOWNTREND -> No longs
- PANIC vol -> No trades
"""

import pandas as pd
from typing import Optional, Dict, List

from .regimes import detect_volatility_regime, detect_trend_regime
from .mean_reversion import SetupResult, SetupStatus
from .trend_pullback import evaluate_trend_pullback_setup
from .momentum_breakout import evaluate_momentum_breakout_setup
from .vol_squeeze import evaluate_volatility_squeeze_setup

def evaluate_multi_strategy_ensemble(
    df: pd.DataFrame,
    indicators: Dict[str, pd.Series],
    timeframe: str = "1h"
) -> List[SetupResult]:
    
    rsi = indicators['rsi_values']
    atr = indicators['atr']
    ema50 = indicators['ema_50']
    ema200 = indicators['ema_200']
    bb_lower = indicators['bb_lower']
    bb_middle = indicators['bb_middle']
    bb_upper = indicators['bb_upper']
    macd_histogram = indicators['macd_histogram']
    volume_sma = indicators['volume_sma']
    
    close = df['close']
    
    # Needs enough historical data
    if len(df) < 200:
        return [SetupResult(SetupStatus.NOT_EVALUATED, "Insufficient bars")]
        
    vol_regime = detect_volatility_regime(atr, close, panic_percentile=90, dead_percentile=20, lookback_bars=200)
    trend_regime = detect_trend_regime(close, ema200, atr)
    
    if not vol_regime or not trend_regime:
        return [SetupResult(SetupStatus.NOT_EVALUATED, "Could not compute regime")]
        
    v_regime_str = vol_regime.regime.value
    t_regime_str = trend_regime.regime.value
    
    results = []
    
    # Hard Blocks
    if v_regime_str == "PANIC":
        return [SetupResult(SetupStatus.EVALUATED_NO_SETUP, "Blocked: PANIC volatility")]
    if t_regime_str in ["DOWNTREND", "STRONG_DOWNTREND"]:
        return [SetupResult(SetupStatus.EVALUATED_NO_SETUP, "Blocked: Downtrend regime (Long Only)")]
        
    # Router
    run_strat_1 = False
    run_strat_2 = False
    run_strat_3 = False
    
    if v_regime_str == "DEAD":
        run_strat_3 = True
    elif v_regime_str == "HIGH" and t_regime_str in ["UPTREND", "STRONG_UPTREND", "NEUTRAL"]:
        run_strat_2 = True
    elif v_regime_str in ["NORMAL", "LOW"] and t_regime_str in ["UPTREND", "STRONG_UPTREND", "NEUTRAL"]:
        run_strat_1 = True
        run_strat_2 = True
    
    # Execute selected strategies
    if run_strat_1:
        res1 = evaluate_trend_pullback_setup(
            df, rsi, atr, ema50, ema200, bb_lower, bb_middle, bb_upper, volume_sma, timeframe
        )
        if res1.status == SetupStatus.SETUP_TRIGGERED:
            results.append(res1)
            
    if run_strat_2:
        res2 = evaluate_momentum_breakout_setup(
            df, rsi, atr, ema200, macd_histogram, volume_sma, timeframe
        )
        if res2.status == SetupStatus.SETUP_TRIGGERED:
            results.append(res2)
            
    if run_strat_3:
        res3 = evaluate_volatility_squeeze_setup(
            df, rsi, atr, indicators['ema_20'], ema50, ema200, bb_lower, bb_middle, bb_upper, volume_sma, timeframe
        )
        if res3.status == SetupStatus.SETUP_TRIGGERED:
            results.append(res3)

    if not results:
        results.append(SetupResult(SetupStatus.EVALUATED_NO_SETUP, f"No setup triggered in {v_regime_str} / {t_regime_str}"))

    return results
