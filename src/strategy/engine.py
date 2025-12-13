"""
Strategy Engine
Main engine that orchestrates indicator analysis and signal generation.
"""

import pandas as pd
from typing import Dict, Optional
import yaml

from ..indicators import (
    calculate_rsi, calculate_ema, check_ema_trend, calculate_macd,
    analyze_volume, calculate_atr, calculate_bollinger_bands
)
from ..indicators.rsi import analyze_rsi_signal, detect_rsi_divergence
from ..indicators.ema import analyze_ema_pullback, detect_ema_crossover
from ..indicators.macd import analyze_macd_signal
from ..indicators.bollinger import analyze_bollinger_signal, detect_bollinger_squeeze
from ..indicators.atr import check_volatility, calculate_stop_loss, calculate_take_profit
from ..indicators.volume import calculate_volume_profile

from .rules import evaluate_long_setup, evaluate_short_setup, combine_signals, check_risk_filters


class StrategyEngine:
    """
    Main strategy engine for analyzing market data and generating signals.
    """
    
    def __init__(self, config_path: str = 'config.yaml'):
        """
        Initialize the strategy engine with configuration.
        
        Args:
            config_path: Path to configuration file
        """
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.indicators_config = self.config['indicators']
        self.risk_config = self.config['risk']
        self.volume_config = self.config['volume']
    
    def calculate_all_indicators(self, df: pd.DataFrame) -> Dict:
        """
        Calculate all technical indicators for the given data.
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
        
        Returns:
            Dict with all calculated indicators
        """
        indicators = {}
        
        # RSI
        rsi_period = self.indicators_config['rsi']['period']
        indicators['rsi_values'] = calculate_rsi(df['close'], rsi_period)
        
        # EMAs
        indicators['ema_20'] = calculate_ema(df['close'], self.indicators_config['ema']['short'])
        indicators['ema_50'] = calculate_ema(df['close'], self.indicators_config['ema']['medium'])
        indicators['ema_200'] = calculate_ema(df['close'], self.indicators_config['ema']['long'])
        
        # MACD
        macd_config = self.indicators_config['macd']
        macd_line, signal_line, histogram = calculate_macd(
            df['close'], 
            macd_config['fast'], 
            macd_config['slow'], 
            macd_config['signal']
        )
        indicators['macd_line'] = macd_line
        indicators['macd_signal'] = signal_line
        indicators['macd_histogram'] = histogram
        
        # Volume
        indicators['volume_sma'] = calculate_volume_profile(df['volume'])
        
        # ATR
        atr_period = self.indicators_config['atr']['period']
        indicators['atr'] = calculate_atr(df['high'], df['low'], df['close'], atr_period)
        indicators['atr_sma'] = indicators['atr'].rolling(window=20).mean()
        
        # Bollinger Bands
        bb_config = self.indicators_config['bollinger']
        upper, middle, lower = calculate_bollinger_bands(
            df['close'], 
            bb_config['period'], 
            bb_config['std_dev']
        )
        indicators['bb_upper'] = upper
        indicators['bb_middle'] = middle
        indicators['bb_lower'] = lower
        
        return indicators
    
    def analyze_current_market(self, df: pd.DataFrame) -> Dict:
        """
        Analyze current market conditions and generate trading signal.
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Dict with complete market analysis and trading signal
        """
        import numpy as np
        
        # Calculate all indicators
        indicators = self.calculate_all_indicators(df)
        
        # Helper to safely get value (returns 0.0 if NaN)
        def safe_val(series, idx=-1, default=0.0):
            try:
                val = series.iloc[idx]
                return default if pd.isna(val) else float(val)
            except (IndexError, KeyError):
                return default
        
        # Get current and previous values
        current_price = safe_val(df['close'], -1)
        previous_price = safe_val(df['close'], -2)
        
        rsi_current = safe_val(indicators['rsi_values'], -1, 50.0)
        rsi_previous = safe_val(indicators['rsi_values'], -2, 50.0)
        
        ema_20 = safe_val(indicators['ema_20'], -1, current_price)
        ema_50 = safe_val(indicators['ema_50'], -1, current_price)
        ema_50_prev = safe_val(indicators['ema_50'], -2, current_price)
        ema_200 = safe_val(indicators['ema_200'], -1, current_price)
        ema_200_prev = safe_val(indicators['ema_200'], -2, current_price)
        
        macd_current = safe_val(indicators['macd_line'], -1)
        macd_previous = safe_val(indicators['macd_line'], -2)
        signal_current = safe_val(indicators['macd_signal'], -1)
        signal_previous = safe_val(indicators['macd_signal'], -2)
        histogram_current = safe_val(indicators['macd_histogram'], -1)
        histogram_previous = safe_val(indicators['macd_histogram'], -2)
        
        atr_current = safe_val(indicators['atr'], -1, 1.0)
        atr_sma = safe_val(indicators['atr_sma'], -1, 1.0)
        
        bb_upper = safe_val(indicators['bb_upper'], -1, current_price * 1.02)
        bb_middle = safe_val(indicators['bb_middle'], -1, current_price)
        bb_lower = safe_val(indicators['bb_lower'], -1, current_price * 0.98)
        
        # Analyze each indicator
        analysis = {}
        
        # RSI Analysis
        analysis['rsi'] = analyze_rsi_signal(
            rsi_current, rsi_previous,
            self.indicators_config['rsi']['overbought'],
            self.indicators_config['rsi']['oversold']
        )
        analysis['rsi_divergence'] = detect_rsi_divergence(df['close'], indicators['rsi_values'])
        
        # EMA Analysis
        analysis['ema_trend'] = {
            'trend': check_ema_trend(ema_50, ema_200)
        }
        analysis['ema_pullback'] = analyze_ema_pullback(
            current_price, ema_20, ema_50, ema_200
        )
        analysis['ema_crossover'] = detect_ema_crossover(
            ema_50, ema_50_prev, ema_200, ema_200_prev
        )
        
        # MACD Analysis
        analysis['macd'] = analyze_macd_signal(
            macd_current, macd_previous,
            signal_current, signal_previous,
            histogram_current, histogram_previous,
            current_price, ema_20
        )
        
        # Volume Analysis
        analysis['volume'] = analyze_volume(
            df['volume'], 
            indicators['volume_sma'],
            self.volume_config['spike_multiplier']
        )
        
        # ATR/Volatility Analysis
        analysis['volatility'] = check_volatility(atr_current, atr_sma)
        
        # Bollinger Bands Analysis
        analysis['bollinger'] = analyze_bollinger_signal(
            current_price, bb_upper, bb_middle, bb_lower, previous_price
        )
        analysis['bollinger_squeeze'] = detect_bollinger_squeeze(
            indicators['bb_upper'], indicators['bb_lower'], indicators['bb_middle']
        )
        
        # Evaluate setups
        long_setup = evaluate_long_setup(analysis)
        short_setup = evaluate_short_setup(analysis)
        
        # Combine signals
        final_signal = combine_signals(
            long_setup, short_setup,
            self.config['signal_strength']['minimum_conditions']
        )
        
        # Check risk filters
        analysis['final_signal'] = final_signal['final_signal']
        risk_filters = check_risk_filters(analysis)
        
        # Calculate position sizing if signal present
        if final_signal['final_signal'] != 'NEUTRAL' and risk_filters['all_passed']:
            stop_loss = calculate_stop_loss(
                current_price, atr_current,
                final_signal['final_signal'],
                self.risk_config['stop_loss_atr_multiplier']
            )
            take_profit = calculate_take_profit(
                current_price, atr_current,
                final_signal['final_signal'],
                self.risk_config['take_profit_atr_multiplier']
            )
            
            final_signal['entry_price'] = current_price
            final_signal['stop_loss'] = stop_loss
            final_signal['take_profit'] = take_profit
            final_signal['risk_reward'] = abs(take_profit - current_price) / abs(current_price - stop_loss)
        
        return {
            'price': current_price,
            'timestamp': df.index[-1],
            'indicators': analysis,
            'long_setup': long_setup,
            'short_setup': short_setup,
            'signal': final_signal,
            'risk_filters': risk_filters
        }
    
    def format_analysis_report(self, analysis: Dict) -> str:
        """
        Format analysis into human-readable report.
        
        Args:
            analysis: Analysis dict from analyze_current_market
        
        Returns:
            Formatted string report
        """
        lines = []
        lines.append("=" * 70)
        lines.append(f"TRADING SIGNAL ANALYSIS - {analysis['timestamp']}")
        lines.append("=" * 70)
        lines.append(f"Current Price: ${analysis['price']:.2f}")
        lines.append("")
        
        # Signal
        signal = analysis['signal']
        lines.append(f"🎯 SIGNAL: {signal['final_signal']} ({signal['confidence']} confidence)")
        lines.append(f"   Strength: {signal['strength']:.2f}")
        lines.append(f"   Reason: {signal['reason']}")
        lines.append("")
        
        # Conditions
        if signal['conditions']:
            lines.append("✅ Conditions Met:")
            for i, condition in enumerate(signal['conditions'], 1):
                lines.append(f"   {i}. {condition}")
            lines.append("")
        
        # Entry/Exit Levels
        if 'entry_price' in signal:
            lines.append("📊 Trade Levels:")
            lines.append(f"   Entry: ${signal['entry_price']:.2f}")
            lines.append(f"   Stop Loss: ${signal['stop_loss']:.2f}")
            lines.append(f"   Take Profit: ${signal['take_profit']:.2f}")
            lines.append(f"   Risk/Reward: 1:{signal['risk_reward']:.2f}")
            lines.append("")
        
        # Risk Filters
        filters = analysis['risk_filters']
        lines.append(f"⚡ Risk Assessment: {filters['recommendation']}")
        if filters['filters_failed']:
            lines.append("   Warnings:")
            for warning in filters['filters_failed']:
                lines.append(f"   {warning}")
        lines.append("")
        
        # Market Context
        lines.append("📈 Market Context:")
        lines.append(f"   Trend: {analysis['indicators']['ema_trend']['trend']}")
        lines.append(f"   RSI: {analysis['indicators']['rsi']['condition']}")
        lines.append(f"   MACD: {analysis['indicators']['macd']['condition']}")
        lines.append(f"   Volume: {analysis['indicators']['volume']['condition']}")
        lines.append(f"   Volatility: {analysis['indicators']['volatility']['condition']}")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
