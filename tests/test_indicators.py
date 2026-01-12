"""
Unit Tests for Indicators
Test indicator calculations with known values.
"""

import unittest
import pandas as pd
import numpy as np

from src.indicators.rsi import calculate_rsi, analyze_rsi_signal
from src.indicators.ema import calculate_ema, check_ema_trend
from src.indicators.macd import calculate_macd


class TestIndicators(unittest.TestCase):
    """Test cases for technical indicators."""
    
    def setUp(self):
        """Set up test data."""
        # Create sample price data
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=100, freq='1h')
        
        # Generate trending price data
        base = 50000
        trend = np.linspace(0, 2000, 100)
        noise = np.random.normal(0, 200, 100)
        
        self.prices = pd.Series(base + trend + noise, index=dates)
    
    def test_rsi_calculation(self):
        """Test RSI calculation."""
        rsi = calculate_rsi(self.prices, period=14)
        
        # Drop NaN warmup values before checking range
        rsi_valid = rsi.dropna()
        
        # RSI should be between 0 and 100 for valid (non-NaN) values
        self.assertTrue((rsi_valid >= 0).all())
        self.assertTrue((rsi_valid <= 100).all())
        
        # Should have NaN values for warmup period
        self.assertTrue(rsi.iloc[:14].isna().any())
    
    def test_rsi_signal_analysis(self):
        """Test RSI signal analysis."""
        # Oversold scenario
        signal = analyze_rsi_signal(35, 25, overbought=70, oversold=30)
        self.assertEqual(signal['signal'], 'LONG')
        
        # Overbought scenario
        signal = analyze_rsi_signal(65, 75, overbought=70, oversold=30)
        self.assertEqual(signal['signal'], 'SHORT')
        
        # Neutral scenario
        signal = analyze_rsi_signal(50, 50, overbought=70, oversold=30)
        self.assertEqual(signal['signal'], 'NEUTRAL')
    
    def test_ema_calculation(self):
        """Test EMA calculation."""
        ema_20 = calculate_ema(self.prices, period=20)
        
        # EMA should smooth prices
        self.assertEqual(len(ema_20), len(self.prices))
        
        # EMA should be less volatile than price
        price_std = self.prices.std()
        ema_std = ema_20.std()
        self.assertLess(ema_std, price_std)
    
    def test_ema_trend(self):
        """Test EMA trend detection."""
        # Bullish trend
        trend = check_ema_trend(ema_50=52000, ema_200=50000)
        self.assertEqual(trend, 'BULLISH')
        
        # Bearish trend
        trend = check_ema_trend(ema_50=48000, ema_200=50000)
        self.assertEqual(trend, 'BEARISH')
    
    def test_macd_calculation(self):
        """Test MACD calculation."""
        macd_line, signal_line, histogram = calculate_macd(self.prices)
        
        # All outputs should have same length as input
        self.assertEqual(len(macd_line), len(self.prices))
        self.assertEqual(len(signal_line), len(self.prices))
        self.assertEqual(len(histogram), len(self.prices))
        
        # Histogram should be macd - signal
        np.testing.assert_array_almost_equal(
            histogram.dropna(),
            (macd_line - signal_line).dropna(),
            decimal=5
        )


class TestStrategy(unittest.TestCase):
    """Test cases for strategy rules."""
    
    def test_long_setup_evaluation(self):
        """Test long setup evaluation."""
        from src.strategy.rules import evaluate_long_setup
        
        # Strong long setup
        indicators = {
            'rsi': {'signal': 'LONG', 'condition': 'RSI oversold', 'strength': 0.8},
            'ema_pullback': {'signal': 'LONG', 'condition': 'Pullback to EMA', 'strength': 0.7},
            'macd': {'signal': 'LONG', 'condition': 'MACD cross', 'strength': 0.6},
            'volume': {'is_spike': True}
        }
        
        result = evaluate_long_setup(indicators)
        self.assertEqual(result['signal'], 'LONG')
        self.assertGreaterEqual(result['num_conditions'], 2)
    
    def test_short_setup_evaluation(self):
        """Test short setup evaluation."""
        from src.strategy.rules import evaluate_short_setup
        
        # Strong short setup
        indicators = {
            'rsi': {'signal': 'SHORT', 'condition': 'RSI overbought', 'strength': 0.8},
            'ema_pullback': {'signal': 'SHORT', 'condition': 'Rally to EMA', 'strength': 0.7},
            'macd': {'signal': 'SHORT', 'condition': 'MACD cross', 'strength': 0.6}
        }
        
        result = evaluate_short_setup(indicators)
        self.assertEqual(result['signal'], 'SHORT')
        self.assertGreaterEqual(result['num_conditions'], 2)


if __name__ == '__main__':
    unittest.main()
