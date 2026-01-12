"""
Strategy Engine
Main engine that orchestrates indicator analysis and signal generation.

v2: Hardened version with:
- Wilder-smoothed RSI and ATR
- Data quality gate (no partial candles, gap detection)
- NOT_EVALUATED status for missing/invalid data
- Mean reversion setup (MEAN_REVERSION_BB_RECLAIM)
- Regime detection (volatility, trend)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import yaml

from ..indicators import (
    calculate_rsi, calculate_ema, check_ema_trend, calculate_macd,
    analyze_volume, calculate_atr, calculate_bollinger_bands
)
from ..indicators.rsi import analyze_rsi_signal, detect_rsi_divergence
from ..indicators.ema import analyze_ema_pullback, detect_ema_crossover
from ..indicators.macd import analyze_macd_signal
from ..indicators.bollinger import analyze_bollinger_signal, detect_bollinger_squeeze
from ..indicators.atr import check_volatility, calculate_stop_loss, calculate_take_profit, calculate_atr_percent
from ..indicators.volume import calculate_volume_profile

from ..data_quality import (
    validate_data_quality, DataQualityStatus, DataQualityResult,
    validate_ohlcv_columns, check_indicator_warmup
)

from .rules import evaluate_long_setup, evaluate_short_setup, combine_signals, check_risk_filters
from .regimes import (
    detect_volatility_regime, detect_trend_regime,
    VolatilityRegime, TrendRegime
)
from .mean_reversion import (
    evaluate_mean_reversion_setup, SetupStatus, SetupResult, MeanReversionAlert
)


class EvaluationStatus:
    """Status of strategy evaluation."""
    NOT_EVALUATED = "NOT_EVALUATED"
    EVALUATED = "EVALUATED"


class StrategyEngine:
    """
    Main strategy engine for analyzing market data and generating signals.
    
    v2 features:
    - Data quality validation before analysis
    - NOT_EVALUATED status for insufficient/invalid data
    - Mean reversion setup with regime filters
    - No more safe defaults that hide data issues
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
        
        # New v2 configs
        self.data_quality_config = self.config.get('data_quality', {})
        self.mean_reversion_config = self.config.get('mean_reversion', {})
    
    def validate_data(self, df: pd.DataFrame, interval: str) -> DataQualityResult:
        """
        Validate data quality before analysis.
        
        Args:
            df: DataFrame with OHLCV data
            interval: Timeframe interval (e.g., "1h", "4h")
        
        Returns:
            DataQualityResult with status and cleaned DataFrame
        """
        # Check OHLCV columns
        is_valid, error = validate_ohlcv_columns(df)
        if not is_valid:
            return DataQualityResult(
                status=DataQualityStatus.NO_DATA,
                df=None,
                reason=error
            )
        
        # Get min bars for this timeframe
        min_bars_config = self.data_quality_config.get('min_bars', {})
        min_bars = min_bars_config.get(interval, 250)
        
        # Run data quality validation
        return validate_data_quality(
            df=df,
            interval=interval,
            min_bars=min_bars,
            max_gaps=self.data_quality_config.get('max_gaps_in_lookback', 2),
            gap_lookback_bars=self.data_quality_config.get('gap_lookback_bars', 200),
            max_single_gap_multiplier=self.data_quality_config.get('max_single_gap_multiplier', 3.0),
            drop_partial=self.data_quality_config.get('drop_partial_candles', True),
        )
    
    def calculate_all_indicators(self, df: pd.DataFrame) -> Dict:
        """
        Calculate all technical indicators for the given data.
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
        
        Returns:
            Dict with all calculated indicators (may contain NaN for warmup periods)
        """
        indicators = {}
        
        # RSI (Wilder smoothing)
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
        
        # ATR (Wilder smoothing)
        atr_period = self.indicators_config['atr']['period']
        indicators['atr'] = calculate_atr(df['high'], df['low'], df['close'], atr_period)
        indicators['atr_sma'] = indicators['atr'].rolling(window=20).mean()
        indicators['atr_pct'] = calculate_atr_percent(indicators['atr'], df['close'])
        
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
    
    def check_indicator_warmup(self, indicators: Dict, required_indicators: list = None) -> Tuple[bool, str]:
        """
        Check if all required indicators have warmed up.
        
        Args:
            indicators: Dict of indicator series
            required_indicators: List of indicator names to check
        
        Returns:
            Tuple of (all_warmed_up, reason_if_not)
        """
        if required_indicators is None:
            required_indicators = ['rsi_values', 'atr', 'ema_200', 'bb_lower', 'bb_middle', 'bb_upper']
        
        warmup_periods = {
            'rsi_values': self.indicators_config['rsi']['period'],
            'atr': self.indicators_config['atr']['period'],
            'ema_20': self.indicators_config['ema']['short'],
            'ema_50': self.indicators_config['ema']['medium'],
            'ema_200': self.indicators_config['ema']['long'],
            'bb_lower': self.indicators_config['bollinger']['period'],
            'bb_middle': self.indicators_config['bollinger']['period'],
            'bb_upper': self.indicators_config['bollinger']['period'],
        }
        
        for ind_name in required_indicators:
            if ind_name not in indicators:
                return False, f"Missing indicator: {ind_name}"
            
            series = indicators[ind_name]
            warmup = warmup_periods.get(ind_name, 14)
            
            if not check_indicator_warmup(series, warmup):
                return False, f"Indicator {ind_name} not warmed up (need {warmup} bars)"
        
        return True, ""
    
    def evaluate_mean_reversion(
        self, 
        df: pd.DataFrame, 
        indicators: Dict,
        interval: str = "1h"
    ) -> SetupResult:
        """
        Evaluate the mean reversion setup (MEAN_REVERSION_BB_RECLAIM).
        
        Args:
            df: DataFrame with OHLCV data
            indicators: Pre-calculated indicators
            interval: Timeframe interval
        
        Returns:
            SetupResult with status and optional alert
        """
        mr_config = self.mean_reversion_config
        
        if not mr_config.get('enabled', True):
            return SetupResult(
                status=SetupStatus.NOT_EVALUATED,
                reason="Mean reversion setup disabled in config"
            )
        
        # Get config values
        vol_config = mr_config.get('vol_regime', {})
        trend_config = mr_config.get('trend_regime', {})
        scoring_config = mr_config.get('scoring', {})
        hold_windows = mr_config.get('hold_window', {})
        
        return evaluate_mean_reversion_setup(
            df=df,
            rsi=indicators['rsi_values'],
            atr=indicators['atr'],
            ema200=indicators['ema_200'],
            bb_lower=indicators['bb_lower'],
            bb_middle=indicators['bb_middle'],
            bb_upper=indicators['bb_upper'],
            volume_sma=indicators['volume_sma'],
            timeframe=interval,
            rsi_threshold=mr_config.get('rsi_cross_threshold', 35),
            lookback_overshoot=mr_config.get('lookback_overshoot', 5),
            panic_percentile=vol_config.get('panic_percentile', 90),
            vol_lookback=vol_config.get('lookback_bars', 200),
            slope_lookback=trend_config.get('ema_slope_lookback', 20),
            strong_downtrend_atr=trend_config.get('strong_downtrend_atr_threshold', 1.0),
            entry_zone_pct=mr_config.get('entry_zone_pct', 0.5),
            base_score=scoring_config.get('base_score', 60),
            strong_rsi_bonus=scoring_config.get('strong_rsi_bonus', 15),
            low_vol_bonus=scoring_config.get('low_vol_bonus', 10),
            good_trend_bonus=scoring_config.get('good_trend_bonus', 10),
            low_volume_penalty=scoring_config.get('low_volume_penalty', 15),
            hold_windows=hold_windows,
        )
    
    def analyze_with_mean_reversion(
        self, 
        df: pd.DataFrame, 
        interval: str = "1h"
    ) -> Dict:
        """
        Main analysis entry point using the mean reversion setup.
        
        This is the recommended v2 analysis method that:
        1. Validates data quality
        2. Calculates indicators
        3. Checks warmup
        4. Evaluates mean reversion setup
        
        Args:
            df: DataFrame with OHLCV data
            interval: Timeframe interval
        
        Returns:
            Dict with analysis results including status, setup result, etc.
        """
        result = {
            'status': EvaluationStatus.NOT_EVALUATED,
            'reason': None,
            'setup_result': None,
            'data_quality': None,
            'indicators': None,
            'timestamp': None,
            'price': None,
        }
        
        # Step 1: Validate data quality
        dq_result = self.validate_data(df, interval)
        result['data_quality'] = {
            'status': dq_result.status.value,
            'reason': dq_result.reason,
            'warnings': dq_result.warnings,
        }
        
        if not dq_result.is_ok:
            result['reason'] = f"Data quality: {dq_result.reason}"
            return result
        
        cleaned_df = dq_result.df
        
        # Step 2: Calculate indicators
        indicators = self.calculate_all_indicators(cleaned_df)
        
        # Step 3: Check warmup
        warmed_up, warmup_reason = self.check_indicator_warmup(indicators)
        if not warmed_up:
            result['reason'] = f"Warmup: {warmup_reason}"
            return result
        
        # Step 4: Evaluate mean reversion setup
        setup_result = self.evaluate_mean_reversion(cleaned_df, indicators, interval)
        
        result['status'] = EvaluationStatus.EVALUATED
        result['setup_result'] = setup_result
        result['timestamp'] = cleaned_df.index[-1]
        result['price'] = float(cleaned_df['close'].iloc[-1])
        
        # Store key indicator values (not NaN)
        result['indicators'] = {
            'rsi': float(indicators['rsi_values'].iloc[-1]),
            'atr': float(indicators['atr'].iloc[-1]),
            'atr_pct': float(indicators['atr_pct'].iloc[-1]),
            'ema200': float(indicators['ema_200'].iloc[-1]),
            'bb_lower': float(indicators['bb_lower'].iloc[-1]),
            'bb_middle': float(indicators['bb_middle'].iloc[-1]),
            'bb_upper': float(indicators['bb_upper'].iloc[-1]),
        }
        
        return result
    
    def analyze_current_market(self, df: pd.DataFrame) -> Dict:
        """
        Analyze current market conditions and generate trading signal.
        
        LEGACY METHOD - kept for backward compatibility.
        For new code, use analyze_with_mean_reversion() instead.
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Dict with complete market analysis and trading signal
        """
        # Calculate all indicators
        indicators = self.calculate_all_indicators(df)
        
        # Check if we have enough valid data
        def get_val(series, idx=-1):
            """Get value, return None if NaN."""
            try:
                val = series.iloc[idx]
                return None if pd.isna(val) else float(val)
            except (IndexError, KeyError):
                return None
        
        # Get current and previous values
        current_price = get_val(df['close'], -1)
        previous_price = get_val(df['close'], -2)
        
        if current_price is None:
            return {
                'status': 'NOT_EVALUATED',
                'reason': 'No valid price data',
                'signal': {'final_signal': 'NEUTRAL', 'confidence': 'NONE', 'reason': 'No data'}
            }
        
        rsi_current = get_val(indicators['rsi_values'], -1)
        rsi_previous = get_val(indicators['rsi_values'], -2)
        
        # If critical indicators are NaN, return NOT_EVALUATED
        if rsi_current is None or rsi_previous is None:
            return {
                'status': 'NOT_EVALUATED',
                'reason': 'RSI not warmed up',
                'price': current_price,
                'timestamp': df.index[-1],
                'signal': {'final_signal': 'NEUTRAL', 'confidence': 'NONE', 'reason': 'Indicators warming up'}
            }
        
        ema_20 = get_val(indicators['ema_20'], -1) or current_price
        ema_50 = get_val(indicators['ema_50'], -1) or current_price
        ema_50_prev = get_val(indicators['ema_50'], -2) or current_price
        ema_200 = get_val(indicators['ema_200'], -1) or current_price
        ema_200_prev = get_val(indicators['ema_200'], -2) or current_price
        
        macd_current = get_val(indicators['macd_line'], -1) or 0
        macd_previous = get_val(indicators['macd_line'], -2) or 0
        signal_current = get_val(indicators['macd_signal'], -1) or 0
        signal_previous = get_val(indicators['macd_signal'], -2) or 0
        histogram_current = get_val(indicators['macd_histogram'], -1) or 0
        histogram_previous = get_val(indicators['macd_histogram'], -2) or 0
        
        atr_current = get_val(indicators['atr'], -1)
        atr_sma = get_val(indicators['atr_sma'], -1)
        
        if atr_current is None:
            return {
                'status': 'NOT_EVALUATED',
                'reason': 'ATR not warmed up',
                'price': current_price,
                'timestamp': df.index[-1],
                'signal': {'final_signal': 'NEUTRAL', 'confidence': 'NONE', 'reason': 'Indicators warming up'}
            }
        
        bb_upper = get_val(indicators['bb_upper'], -1) or current_price * 1.02
        bb_middle = get_val(indicators['bb_middle'], -1) or current_price
        bb_lower = get_val(indicators['bb_lower'], -1) or current_price * 0.98
        
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
        analysis['volatility'] = check_volatility(atr_current, atr_sma or atr_current)
        
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
            final_signal['risk_reward'] = abs(take_profit - current_price) / abs(current_price - stop_loss) if abs(current_price - stop_loss) > 0 else 0
        
        return {
            'status': 'EVALUATED',
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
        lines.append(f"TRADING SIGNAL ANALYSIS - {analysis.get('timestamp', 'N/A')}")
        lines.append("=" * 70)
        
        if analysis.get('status') == 'NOT_EVALUATED':
            lines.append(f"⚠️  NOT EVALUATED: {analysis.get('reason', 'Unknown')}")
            lines.append("=" * 70)
            return "\n".join(lines)
        
        lines.append(f"Current Price: ${analysis.get('price', 0):.2f}")
        lines.append("")
        
        # Signal
        signal = analysis.get('signal', {})
        lines.append(f"🎯 SIGNAL: {signal.get('final_signal', 'N/A')} ({signal.get('confidence', 'N/A')} confidence)")
        lines.append(f"   Strength: {signal.get('strength', 0):.2f}")
        lines.append(f"   Reason: {signal.get('reason', 'N/A')}")
        lines.append("")
        
        # Conditions
        conditions = signal.get('conditions', [])
        if conditions:
            lines.append("✅ Conditions Met:")
            for i, condition in enumerate(conditions, 1):
                lines.append(f"   {i}. {condition}")
            lines.append("")
        
        # Entry/Exit Levels
        if 'entry_price' in signal:
            lines.append("📊 Trade Levels:")
            lines.append(f"   Entry: ${signal['entry_price']:.2f}")
            lines.append(f"   Stop Loss: ${signal.get('stop_loss', 0):.2f}")
            lines.append(f"   Take Profit: ${signal.get('take_profit', 0):.2f}")
            lines.append(f"   Risk/Reward: 1:{signal.get('risk_reward', 0):.2f}")
            lines.append("")
        
        # Risk Filters
        filters = analysis.get('risk_filters', {})
        lines.append(f"⚡ Risk Assessment: {filters.get('recommendation', 'N/A')}")
        failed = filters.get('filters_failed', [])
        if failed:
            lines.append("   Warnings:")
            for warning in failed:
                lines.append(f"   {warning}")
        lines.append("")
        
        # Market Context
        indicators = analysis.get('indicators', {})
        lines.append("📈 Market Context:")
        lines.append(f"   Trend: {indicators.get('ema_trend', {}).get('trend', 'N/A')}")
        lines.append(f"   RSI: {indicators.get('rsi', {}).get('condition', 'N/A')}")
        lines.append(f"   MACD: {indicators.get('macd', {}).get('condition', 'N/A')}")
        lines.append(f"   Volume: {indicators.get('volume', {}).get('condition', 'N/A')}")
        lines.append(f"   Volatility: {indicators.get('volatility', {}).get('condition', 'N/A')}")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def format_mean_reversion_alert(self, result: Dict, symbol: str = "") -> str:
        """
        Format mean reversion analysis into a structured alert.
        
        Args:
            result: Result from analyze_with_mean_reversion
            symbol: Ticker symbol
        
        Returns:
            Formatted string alert
        """
        lines = []
        lines.append("=" * 70)
        
        if result['status'] == EvaluationStatus.NOT_EVALUATED:
            lines.append(f"⚠️  NOT_EVALUATED: {symbol}")
            lines.append(f"   Reason: {result.get('reason', 'Unknown')}")
            if result.get('data_quality', {}).get('warnings'):
                lines.append(f"   Warnings: {result['data_quality']['warnings']}")
            lines.append("=" * 70)
            return "\n".join(lines)
        
        setup_result = result.get('setup_result')
        if setup_result is None:
            lines.append(f"⚠️  NO SETUP RESULT: {symbol}")
            lines.append("=" * 70)
            return "\n".join(lines)
        
        if setup_result.status == SetupStatus.NOT_EVALUATED:
            lines.append(f"⚠️  NOT_EVALUATED: {symbol}")
            lines.append(f"   Reason: {setup_result.reason}")
            lines.append("=" * 70)
            return "\n".join(lines)
        
        if setup_result.status == SetupStatus.EVALUATED_NO_SETUP:
            lines.append(f"📊 NO SETUP: {symbol}")
            lines.append(f"   Price: ${result.get('price', 0):.2f}")
            lines.append(f"   Reason: {setup_result.reason}")
            lines.append("=" * 70)
            return "\n".join(lines)
        
        # SETUP_TRIGGERED
        alert = setup_result.alert
        lines.append(f"🚨 ALERT: {alert.setup}")
        lines.append("=" * 70)
        lines.append(f"Symbol: {symbol}")
        lines.append(f"Timeframe: {alert.timeframe}")
        lines.append(f"Direction: {alert.direction}")
        lines.append(f"Score: {alert.score}/100")
        lines.append("")
        
        lines.append("📊 Price Levels:")
        lines.append(f"   Trigger Close: ${alert.trigger_close:.2f}")
        lines.append(f"   Entry Zone: ${alert.entry_zone[0]:.2f} - ${alert.entry_zone[1]:.2f}")
        lines.append(f"   Invalidation: ${alert.invalidation:.2f}")
        lines.append(f"   Hold Window: {alert.hold_window}")
        lines.append("")
        
        lines.append("✅ Evidence:")
        for i, ev in enumerate(alert.evidence, 1):
            lines.append(f"   {i}. {ev}")
        lines.append("")
        
        lines.append("📈 Indicators:")
        lines.append(f"   RSI: {alert.rsi_prev:.1f} -> {alert.rsi:.1f}")
        lines.append(f"   ATR: ${alert.atr:.2f} ({alert.atr_pct:.2f}%)")
        lines.append(f"   EMA200: ${alert.ema200:.2f}")
        lines.append(f"   BB: ${alert.bb_lower:.2f} / ${alert.bb_middle:.2f} / ${alert.bb_upper:.2f}")
        lines.append("")
        
        lines.append("🎯 Regimes:")
        lines.append(f"   Volatility: {alert.vol_regime}")
        lines.append(f"   Trend: {alert.trend_regime}")
        lines.append("")
        
        lines.append(f"📰 News Risk: {alert.news_risk}")
        if alert.news_reasons:
            for reason in alert.news_reasons:
                lines.append(f"   - {reason}")
        
        if alert.cooldown_active:
            lines.append("")
            lines.append(f"⏰ Cooldown: Active (last alert: {alert.last_alert_ago})")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
