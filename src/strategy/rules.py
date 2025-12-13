"""
Trading Strategy Rules
Implements the high-probability setup combinations.
"""

from typing import Dict, List


def evaluate_long_setup(indicators: Dict) -> Dict[str, any]:
    """
    Evaluate conditions for LONG entry based on strategy rules.
    
    High-probability LONG setups:
    1. RSI oversold bounce (RSI < 30 → cross up)
    2. Bullish EMA trend (50>200) + pullback to 20 EMA
    3. MACD bullish crossover + price above 20 EMA
    4. Volume confirmation (breakout + strong volume)
    5. Bollinger bounce from lower band
    6. Bullish divergence
    
    Args:
        indicators: Dict with all indicator signals
    
    Returns:
        Dict with long setup evaluation
    """
    conditions_met = []
    total_strength = 0.0
    
    # 1. RSI Signal
    if indicators.get('rsi', {}).get('signal') == 'LONG':
        conditions_met.append(indicators['rsi']['condition'])
        total_strength += indicators['rsi']['strength']
    
    # 2. EMA Trend + Pullback
    if indicators.get('ema_pullback', {}).get('signal') == 'LONG':
        conditions_met.append(indicators['ema_pullback']['condition'])
        total_strength += indicators['ema_pullback']['strength']
    
    # 3. MACD Crossover
    if indicators.get('macd', {}).get('signal') == 'LONG':
        conditions_met.append(indicators['macd']['condition'])
        total_strength += indicators['macd']['strength']
    
    # 4. Volume Confirmation
    if indicators.get('volume', {}).get('is_spike'):
        conditions_met.append('High volume confirmation')
        total_strength += 0.5
    
    # 5. Bollinger Band Signal
    if indicators.get('bollinger', {}).get('signal') == 'LONG':
        conditions_met.append(indicators['bollinger']['condition'])
        total_strength += indicators['bollinger']['strength']
    
    # 6. Divergence
    if indicators.get('rsi_divergence') == 'BULLISH':
        conditions_met.append('Bullish RSI divergence')
        total_strength += 0.6
    
    # Calculate average strength
    avg_strength = total_strength / len(conditions_met) if conditions_met else 0
    
    return {
        'signal': 'LONG' if len(conditions_met) >= 2 else 'NEUTRAL',
        'conditions_met': conditions_met,
        'num_conditions': len(conditions_met),
        'strength': avg_strength,
        'confidence': 'HIGH' if len(conditions_met) >= 3 else 'MEDIUM' if len(conditions_met) >= 2 else 'LOW'
    }


def evaluate_short_setup(indicators: Dict) -> Dict[str, any]:
    """
    Evaluate conditions for SHORT entry based on strategy rules.
    
    High-probability SHORT setups:
    1. RSI overbought reversal (RSI > 70 → cross down)
    2. Bearish EMA trend (50<200) + rally to 20 EMA
    3. MACD bearish crossover + price below 20 EMA
    4. Volume confirmation (breakdown + strong volume)
    5. Bollinger rejection from upper band
    6. Bearish divergence
    
    Args:
        indicators: Dict with all indicator signals
    
    Returns:
        Dict with short setup evaluation
    """
    conditions_met = []
    total_strength = 0.0
    
    # 1. RSI Signal
    if indicators.get('rsi', {}).get('signal') == 'SHORT':
        conditions_met.append(indicators['rsi']['condition'])
        total_strength += indicators['rsi']['strength']
    
    # 2. EMA Trend + Rally
    if indicators.get('ema_pullback', {}).get('signal') == 'SHORT':
        conditions_met.append(indicators['ema_pullback']['condition'])
        total_strength += indicators['ema_pullback']['strength']
    
    # 3. MACD Crossover
    if indicators.get('macd', {}).get('signal') == 'SHORT':
        conditions_met.append(indicators['macd']['condition'])
        total_strength += indicators['macd']['strength']
    
    # 4. Volume Confirmation
    if indicators.get('volume', {}).get('is_spike'):
        conditions_met.append('High volume confirmation')
        total_strength += 0.5
    
    # 5. Bollinger Band Signal
    if indicators.get('bollinger', {}).get('signal') == 'SHORT':
        conditions_met.append(indicators['bollinger']['condition'])
        total_strength += indicators['bollinger']['strength']
    
    # 6. Divergence
    if indicators.get('rsi_divergence') == 'BEARISH':
        conditions_met.append('Bearish RSI divergence')
        total_strength += 0.6
    
    # Calculate average strength
    avg_strength = total_strength / len(conditions_met) if conditions_met else 0
    
    return {
        'signal': 'SHORT' if len(conditions_met) >= 2 else 'NEUTRAL',
        'conditions_met': conditions_met,
        'num_conditions': len(conditions_met),
        'strength': avg_strength,
        'confidence': 'HIGH' if len(conditions_met) >= 3 else 'MEDIUM' if len(conditions_met) >= 2 else 'LOW'
    }


def combine_signals(long_setup: Dict, short_setup: Dict, 
                    min_conditions: int = 2) -> Dict[str, any]:
    """
    Combine long and short evaluations into final signal.
    
    Strategy Rule: Need at least 2 conditions to trade
    3+ conditions = high confidence signal
    
    Args:
        long_setup: Long setup evaluation
        short_setup: Short setup evaluation
        min_conditions: Minimum conditions required (default: 2)
    
    Returns:
        Dict with final trading signal
    """
    result = {
        'final_signal': 'NEUTRAL',
        'direction': None,
        'confidence': 'NONE',
        'strength': 0.0,
        'reason': '',
        'conditions': []
    }
    
    # Check if either setup meets minimum requirements
    long_valid = long_setup['num_conditions'] >= min_conditions
    short_valid = short_setup['num_conditions'] >= min_conditions
    
    # If both valid, choose stronger one
    if long_valid and short_valid:
        if long_setup['strength'] > short_setup['strength']:
            result['final_signal'] = 'LONG'
            result['direction'] = 'LONG'
            result['confidence'] = long_setup['confidence']
            result['strength'] = long_setup['strength']
            result['conditions'] = long_setup['conditions_met']
            result['reason'] = f"Long setup stronger ({long_setup['num_conditions']} conditions)"
        else:
            result['final_signal'] = 'SHORT'
            result['direction'] = 'SHORT'
            result['confidence'] = short_setup['confidence']
            result['strength'] = short_setup['strength']
            result['conditions'] = short_setup['conditions_met']
            result['reason'] = f"Short setup stronger ({short_setup['num_conditions']} conditions)"
    
    # Only long valid
    elif long_valid:
        result['final_signal'] = 'LONG'
        result['direction'] = 'LONG'
        result['confidence'] = long_setup['confidence']
        result['strength'] = long_setup['strength']
        result['conditions'] = long_setup['conditions_met']
        result['reason'] = f"Long setup: {long_setup['num_conditions']} conditions met"
    
    # Only short valid
    elif short_valid:
        result['final_signal'] = 'SHORT'
        result['direction'] = 'SHORT'
        result['confidence'] = short_setup['confidence']
        result['strength'] = short_setup['strength']
        result['conditions'] = short_setup['conditions_met']
        result['reason'] = f"Short setup: {short_setup['num_conditions']} conditions met"
    
    # Neither setup valid
    else:
        long_count = long_setup['num_conditions']
        short_count = short_setup['num_conditions']
        result['reason'] = f"No clear setup (Long: {long_count}, Short: {short_count} conditions)"
    
    return result


def check_risk_filters(indicators: Dict) -> Dict[str, any]:
    """
    Check risk management filters before trading.
    
    Strategy Rules:
    - Don't trade if volatility too low (ATR < avg)
    - Don't trade against strong trend
    - Don't trade on low volume breakouts
    
    Args:
        indicators: Dict with all indicator data
    
    Returns:
        Dict with risk filter results
    """
    filters_passed = []
    filters_failed = []
    
    # 1. Volatility Check
    volatility = indicators.get('volatility', {})
    if volatility.get('is_tradeable', True):
        filters_passed.append(f"Volatility OK: {volatility.get('condition', 'Normal')}")
    else:
        filters_failed.append(f"⚠️ {volatility.get('condition', 'Low volatility')}")
    
    # 2. Trend Alignment Check
    ema_trend = indicators.get('ema_trend', {}).get('trend')
    signal_direction = indicators.get('final_signal')
    
    if signal_direction == 'LONG' and ema_trend == 'BEARISH':
        filters_failed.append("⚠️ Long signal against bearish trend (risky)")
    elif signal_direction == 'SHORT' and ema_trend == 'BULLISH':
        filters_failed.append("⚠️ Short signal against bullish trend (risky)")
    else:
        filters_passed.append(f"Trend alignment: {ema_trend}")
    
    # 3. Volume Check
    volume = indicators.get('volume', {})
    if signal_direction in ['LONG', 'SHORT'] and not volume.get('is_spike'):
        filters_failed.append("⚠️ Low volume - weak confirmation")
    else:
        filters_passed.append(f"Volume: {volume.get('condition', 'N/A')}")
    
    return {
        'all_passed': len(filters_failed) == 0,
        'filters_passed': filters_passed,
        'filters_failed': filters_failed,
        'recommendation': 'TRADE' if len(filters_failed) == 0 else 'CAUTION' if len(filters_failed) == 1 else 'SKIP'
    }
