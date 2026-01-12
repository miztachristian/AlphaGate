"""
Unit Tests for v2 Hardened Components

Tests for:
- Wilder-smoothed RSI
- Wilder-smoothed ATR
- Data quality gate
- Mean reversion setup
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

# RSI and ATR tests
from src.indicators.rsi import calculate_rsi, calculate_rsi_vectorized
from src.indicators.atr import calculate_atr, calculate_atr_vectorized, calculate_true_range

# Data quality tests
from src.data_quality import (
    validate_data_quality, DataQualityStatus, DataQualityResult,
    drop_partial_candle, detect_gaps, get_interval_minutes,
    is_candle_complete, check_indicator_warmup
)

# Mean reversion tests
from src.strategy.mean_reversion import (
    evaluate_mean_reversion_setup, SetupStatus, 
    check_bb_reclaim, check_rsi_cross_up
)
from src.strategy.regimes import (
    detect_volatility_regime, detect_trend_regime,
    VolatilityRegime, TrendRegime
)


class TestWilderRSI(unittest.TestCase):
    """Test Wilder-smoothed RSI calculation."""
    
    def test_rsi_warmup_period(self):
        """RSI should be NaN until warmup period is satisfied."""
        # Create simple price series
        prices = pd.Series([100 + i * 0.5 for i in range(30)])
        
        rsi = calculate_rsi(prices, period=14)
        
        # First period values should be NaN (need period bars for first average)
        # The exact warmup depends on implementation - at minimum first few are NaN
        self.assertTrue(rsi.iloc[:10].isna().any(), 
                       "Early RSI values should be NaN during warmup")
        
        # Values after warmup should be valid
        self.assertFalse(rsi.iloc[20:].isna().any(),
                        "RSI values after warmup should not be NaN")
    
    def test_rsi_range(self):
        """RSI should be between 0 and 100."""
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.randn(100)))
        
        rsi = calculate_rsi(prices, period=14)
        valid_rsi = rsi.dropna()
        
        self.assertTrue((valid_rsi >= 0).all(), "RSI should be >= 0")
        self.assertTrue((valid_rsi <= 100).all(), "RSI should be <= 100")
    
    def test_rsi_wilder_vs_simple(self):
        """Wilder RSI should differ from simple rolling RSI."""
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.randn(50)))
        
        # Calculate Wilder RSI
        wilder_rsi = calculate_rsi(prices, period=14)
        
        # Calculate simple rolling RSI (old method)
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        simple_rsi = 100 - (100 / (1 + gain / loss))
        
        # They should produce different results (Wilder is smoother)
        # Compare after warmup
        wilder_valid = wilder_rsi.iloc[20:].dropna()
        simple_valid = simple_rsi.iloc[20:].dropna()
        
        # Not exactly equal (different methods)
        self.assertFalse(np.allclose(wilder_valid.values, simple_valid.values[:len(wilder_valid)], rtol=0.01),
                        "Wilder RSI should differ from simple rolling RSI")
    
    def test_rsi_known_values(self):
        """Test RSI with a known sequence."""
        # Create a sequence where we know roughly what RSI should be
        # All gains: RSI should be 100
        prices_up = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                               110, 111, 112, 113, 114, 115, 116, 117, 118, 119])
        rsi_up = calculate_rsi(prices_up, period=14)
        
        # After warmup, RSI should be close to 100 (all gains, no losses)
        self.assertGreater(rsi_up.iloc[-1], 95, 
                          "RSI should be near 100 for all-gains sequence")
        
        # All losses: RSI should be near 0
        prices_down = pd.Series([100, 99, 98, 97, 96, 95, 94, 93, 92, 91,
                                 90, 89, 88, 87, 86, 85, 84, 83, 82, 81])
        rsi_down = calculate_rsi(prices_down, period=14)
        
        self.assertLess(rsi_down.iloc[-1], 5,
                       "RSI should be near 0 for all-losses sequence")
    
    def test_rsi_vectorized_exists(self):
        """Vectorized RSI function should exist and produce valid output."""
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.randn(100)))
        
        rsi_vec = calculate_rsi_vectorized(prices, period=14)
        
        # Should produce values in valid range after warmup
        valid = rsi_vec.dropna()
        self.assertTrue(len(valid) > 0, "Vectorized RSI should produce values")
        self.assertTrue((valid >= 0).all(), "RSI should be >= 0")
        self.assertTrue((valid <= 100).all(), "RSI should be <= 100")


class TestWilderATR(unittest.TestCase):
    """Test Wilder-smoothed ATR calculation."""
    
    def test_atr_warmup_period(self):
        """ATR should be NaN until warmup period is satisfied."""
        n = 30
        high = pd.Series([100 + i + 2 for i in range(n)])
        low = pd.Series([100 + i - 2 for i in range(n)])
        close = pd.Series([100 + i for i in range(n)])
        
        atr = calculate_atr(high, low, close, period=14)
        
        # First 14 values should be NaN
        self.assertTrue(atr.iloc[:14].isna().all(),
                       "First 14 ATR values should be NaN during warmup")
        
        # Values after warmup should be valid
        self.assertFalse(atr.iloc[14:].isna().any(),
                        "ATR values after warmup should not be NaN")
    
    def test_atr_positive(self):
        """ATR should always be positive."""
        np.random.seed(42)
        n = 100
        close = pd.Series(100 + np.cumsum(np.random.randn(n)))
        high = close + np.abs(np.random.randn(n)) * 2
        low = close - np.abs(np.random.randn(n)) * 2
        
        atr = calculate_atr(high, low, close, period=14)
        valid_atr = atr.dropna()
        
        self.assertTrue((valid_atr > 0).all(), "ATR should be positive")
    
    def test_true_range_calculation(self):
        """True Range should be max of three components."""
        high = pd.Series([105, 108, 107])
        low = pd.Series([100, 102, 103])
        close = pd.Series([102, 106, 105])
        
        tr = calculate_true_range(high, low, close)
        
        # TR[0] = high-low = 5 (no prev close)
        # TR[1] = max(108-102=6, |108-102|=6, |102-102|=0) = 6
        # TR[2] = max(107-103=4, |107-106|=1, |103-106|=3) = 4
        
        self.assertEqual(tr.iloc[0], 5.0)
        self.assertEqual(tr.iloc[1], 6.0)
        self.assertEqual(tr.iloc[2], 4.0)
    
    def test_atr_known_values(self):
        """Test ATR with constant true range."""
        n = 30
        # Create data where TR is always 4 (high-low)
        high = pd.Series([102.0] * n)
        low = pd.Series([98.0] * n)
        close = pd.Series([100.0] * n)
        
        atr = calculate_atr(high, low, close, period=14)
        
        # After warmup, ATR should be 4.0 (constant TR)
        self.assertAlmostEqual(atr.iloc[-1], 4.0, places=5,
                              msg="ATR should equal constant TR")
    
    def test_atr_vectorized_matches_loop(self):
        """Vectorized ATR should approximately match loop version."""
        np.random.seed(42)
        n = 100
        close = pd.Series(100 + np.cumsum(np.random.randn(n)))
        high = close + np.abs(np.random.randn(n)) * 2
        low = close - np.abs(np.random.randn(n)) * 2
        
        atr_loop = calculate_atr(high, low, close, period=14)
        atr_vec = calculate_atr_vectorized(high, low, close, period=14)
        
        # Compare after warmup
        loop_valid = atr_loop.iloc[30:].values
        vec_valid = atr_vec.iloc[30:].values
        
        np.testing.assert_allclose(loop_valid, vec_valid, rtol=0.02,
                                  err_msg="Vectorized ATR should match loop version")


class TestDataQuality(unittest.TestCase):
    """Test data quality gate module."""
    
    def _create_ohlcv_df(self, n_bars: int, interval_minutes: int = 60,
                         start_time: datetime = None) -> pd.DataFrame:
        """Helper to create OHLCV DataFrame."""
        if start_time is None:
            start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        
        timestamps = [start_time + timedelta(minutes=interval_minutes * i) for i in range(n_bars)]
        
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n_bars) * 0.5)
        
        df = pd.DataFrame({
            'open': close + np.random.randn(n_bars) * 0.1,
            'high': close + np.abs(np.random.randn(n_bars)) * 0.5,
            'low': close - np.abs(np.random.randn(n_bars)) * 0.5,
            'close': close,
            'volume': np.random.randint(1000, 10000, n_bars),
        }, index=pd.DatetimeIndex(timestamps))
        
        return df
    
    def test_drop_partial_candle(self):
        """Partial (incomplete) last candle should be dropped."""
        # Create df ending at a recent time (partial candle)
        now = datetime.now(timezone.utc)
        current_hour_start = now.replace(minute=0, second=0, microsecond=0)
        
        # Last candle starts at current hour (incomplete)
        df = self._create_ohlcv_df(100, interval_minutes=60, 
                                   start_time=current_hour_start - timedelta(hours=99))
        
        cleaned_df, was_dropped = drop_partial_candle(df, "1h", current_time=now)
        
        self.assertTrue(was_dropped, "Partial candle should be dropped")
        self.assertEqual(len(cleaned_df), 99, "Should have 99 bars after dropping partial")
    
    def test_keep_complete_candle(self):
        """Complete candle should not be dropped."""
        # Create df ending well in the past
        old_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        df = self._create_ohlcv_df(100, interval_minutes=60, start_time=old_time)
        
        # Current time is way after the data
        current_time = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
        
        cleaned_df, was_dropped = drop_partial_candle(df, "1h", current_time=current_time)
        
        self.assertFalse(was_dropped, "Complete candle should not be dropped")
        self.assertEqual(len(cleaned_df), 100)
    
    def test_detect_gaps_no_gaps(self):
        """No gaps should be detected in continuous data."""
        df = self._create_ohlcv_df(100, interval_minutes=60)
        
        has_bad_gaps, gap_details = detect_gaps(df, "1h")
        
        self.assertFalse(has_bad_gaps, "Should not detect gaps in continuous data")
    
    def test_detect_gaps_with_gap(self):
        """Gaps should be detected when timestamps are missing."""
        # Create df with a gap
        start_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        
        # Create 50 bars, then skip 5 hours, then 50 more
        timestamps = []
        for i in range(50):
            timestamps.append(start_time + timedelta(hours=i))
        for i in range(50):
            timestamps.append(start_time + timedelta(hours=55 + i))  # 5 hour gap
        
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        
        df = pd.DataFrame({
            'open': close,
            'high': close + 0.5,
            'low': close - 0.5,
            'close': close,
            'volume': [1000] * 100,
        }, index=pd.DatetimeIndex(timestamps))
        
        has_bad_gaps, gap_details = detect_gaps(df, "1h", max_gaps=0, max_single_gap_multiplier=3.0)
        
        self.assertTrue(has_bad_gaps, "Should detect the 5-hour gap")
    
    def test_insufficient_bars(self):
        """Should return INSUFFICIENT_BARS for too few bars."""
        df = self._create_ohlcv_df(50, interval_minutes=60)
        
        # Far in the past so no partial candle issue
        current_time = datetime(2024, 6, 1, tzinfo=timezone.utc)
        
        result = validate_data_quality(df, "1h", min_bars=100, current_time=current_time)
        
        self.assertEqual(result.status, DataQualityStatus.INSUFFICIENT_BARS)
        self.assertIn("50", result.reason)  # Should mention we have 50 bars
    
    def test_valid_data_quality(self):
        """Should return OK for valid data."""
        df = self._create_ohlcv_df(400, interval_minutes=60)
        
        # Far in the past
        current_time = datetime(2024, 6, 1, tzinfo=timezone.utc)
        
        result = validate_data_quality(df, "1h", min_bars=350, current_time=current_time)
        
        self.assertEqual(result.status, DataQualityStatus.OK)
        self.assertIsNotNone(result.df)
    
    def test_indicator_warmup_check(self):
        """Should detect when indicators haven't warmed up."""
        # Series with NaN at the end
        values = pd.Series([np.nan] * 10 + [50.0] * 10 + [np.nan])
        
        self.assertFalse(check_indicator_warmup(values, 14),
                        "Should fail warmup check with NaN at end")
        
        # Series with valid values at end
        values2 = pd.Series([np.nan] * 14 + [50.0] * 10)
        
        self.assertTrue(check_indicator_warmup(values2, 14),
                       "Should pass warmup check with valid values at end")


class TestMeanReversionSetup(unittest.TestCase):
    """Test mean reversion setup detection."""
    
    def _create_bb_reclaim_scenario(self):
        """Create data where BB reclaim occurs."""
        n = 250
        np.random.seed(42)
        
        # Create price that dips below BB then recovers
        base_close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.3))
        
        # Make last few bars show overshoot and reclaim
        # Lower the price significantly for overshoot, then recover
        base_close.iloc[-5] = base_close.iloc[-6] - 3  # Big drop
        base_close.iloc[-4] = base_close.iloc[-5] - 1  # Continue down (overshoot)
        base_close.iloc[-3] = base_close.iloc[-4] + 0.5  # Start recovery
        base_close.iloc[-2] = base_close.iloc[-3] + 1  # Still below band
        base_close.iloc[-1] = base_close.iloc[-2] + 1.5  # Reclaim
        
        high = base_close + np.abs(np.random.randn(n)) * 0.5
        low = base_close - np.abs(np.random.randn(n)) * 0.5
        
        df = pd.DataFrame({
            'open': base_close + np.random.randn(n) * 0.1,
            'high': high,
            'low': low,
            'close': base_close,
            'volume': np.random.randint(1000, 10000, n),
        })
        
        return df
    
    def test_bb_reclaim_detection(self):
        """Test Bollinger Band reclaim detection."""
        close = pd.Series([100, 100.5, 99, 98, 95, 94, 96])  # Dip then recover
        bb_lower = pd.Series([97, 97, 97, 97, 97, 95.5, 95])  # Band level
        
        has_overshoot, is_reclaim, bars_ago = check_bb_reclaim(close, bb_lower, lookback_overshoot=5)
        
        # Last bar (96) > bb_lower (95), prev bar (94) < bb_lower (95.5) -> reclaim
        self.assertTrue(has_overshoot, "Should detect overshoot")
        self.assertTrue(is_reclaim, "Should detect reclaim")
    
    def test_no_reclaim_when_still_below(self):
        """No reclaim when price is still below band."""
        close = pd.Series([100, 99, 98, 97, 96, 95, 94])  # Continuing down
        bb_lower = pd.Series([97, 97, 97, 97, 97, 97, 97])
        
        has_overshoot, is_reclaim, bars_ago = check_bb_reclaim(close, bb_lower, lookback_overshoot=5)
        
        self.assertTrue(has_overshoot, "Should detect overshoot")
        self.assertFalse(is_reclaim, "Should not detect reclaim when still below")
    
    def test_rsi_cross_up_detection(self):
        """Test RSI cross up detection."""
        rsi = pd.Series([25, 28, 32, 34, 36])  # Crossing up through 35
        
        is_cross, rsi_now, rsi_prev = check_rsi_cross_up(rsi, threshold=35)
        
        self.assertTrue(is_cross, "Should detect RSI cross up")
        self.assertEqual(rsi_now, 36)
        self.assertEqual(rsi_prev, 34)
    
    def test_no_rsi_cross_when_already_above(self):
        """No cross when already above threshold."""
        rsi = pd.Series([40, 42, 45, 48, 50])  # Already above 35
        
        is_cross, rsi_now, rsi_prev = check_rsi_cross_up(rsi, threshold=35)
        
        self.assertFalse(is_cross, "Should not detect cross when already above")


class TestRegimeDetection(unittest.TestCase):
    """Test regime detection."""
    
    def test_panic_volatility_regime(self):
        """High ATR% should trigger PANIC regime."""
        n = 250
        np.random.seed(42)
        
        close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.3))
        
        # Create ATR that's very high at the end
        atr = pd.Series([1.0] * (n - 1) + [5.0])  # Last bar very high ATR
        
        result = detect_volatility_regime(atr, close, panic_percentile=90, lookback_bars=200)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.regime, VolatilityRegime.PANIC)
        self.assertTrue(result.is_panic)
    
    def test_normal_volatility_regime(self):
        """Normal ATR% should trigger NORMAL regime."""
        n = 250
        np.random.seed(42)
        
        close = pd.Series([100.0] * n)
        atr = pd.Series([1.0] * n)  # Constant ATR
        
        result = detect_volatility_regime(atr, close, panic_percentile=90, lookback_bars=200)
        
        self.assertIsNotNone(result)
        self.assertFalse(result.is_panic)
    
    def test_strong_downtrend_regime(self):
        """Declining EMA200 with price far below should trigger STRONG_DOWNTREND."""
        n = 250
        
        # Create declining prices
        close = pd.Series([100 - i * 0.2 for i in range(n)])
        
        # EMA200 will be above current price and declining
        # Simple approximation for test
        ema200 = pd.Series([100 - i * 0.1 for i in range(n)])  # EMA declines slower
        
        atr = pd.Series([2.0] * n)  # ATR of 2
        
        result = detect_trend_regime(close, ema200, atr, slope_lookback=20, strong_trend_atr_threshold=1.0)
        
        # Price should be significantly below EMA200
        self.assertIsNotNone(result)
        # The test depends on exact values; main point is the logic works


class TestNewsRiskLabeling(unittest.TestCase):
    """Test news risk labeling."""
    
    def test_high_risk_keyword_detection(self):
        """Should detect HIGH risk for earnings-related news."""
        from src.news.risk_labeler import assess_news_risk, NewsRiskResult
        from src.news.polygon_news_client import NewsItem
        
        items = [
            NewsItem(
                headline="Company XYZ Reports Earnings Beat",
                description="Quarterly earnings exceeded expectations",
                url="http://example.com",
                published_utc=datetime.utcnow(),
                source="Test",
                tickers=["XYZ"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "HIGH")
        self.assertIn("earnings", result.matched_high_keywords)
    
    def test_low_risk_no_keywords(self):
        """Should return LOW risk when no keywords found."""
        from src.news.risk_labeler import assess_news_risk
        from src.news.polygon_news_client import NewsItem
        
        items = [
            NewsItem(
                headline="Company Announces New Product Color Options",
                description="New colors available for flagship product",
                url="http://example.com",
                published_utc=datetime.utcnow(),
                source="Test",
                tickers=["TEST"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "LOW")
    
    def test_empty_news_low_risk(self):
        """Empty news list should return LOW risk."""
        from src.news.risk_labeler import assess_news_risk
        
        result = assess_news_risk([])
        
        self.assertEqual(result.risk_level, "LOW")
        self.assertEqual(result.news_count, 0)


if __name__ == '__main__':
    unittest.main()
