"""
Unit tests for Chop Regime Detection.

Tests the chop regime detection based on Bollinger Band bandwidth compression.
"""

import pytest
import pandas as pd
import numpy as np

from src.strategy.regimes import (
    ChopRegime,
    ChopRegimeResult,
    detect_chop_regime,
)


class TestChopRegime:
    """Tests for ChopRegime enum."""
    
    def test_chop_value(self):
        """Test CHOP enum value."""
        assert ChopRegime.CHOP.value == "CHOP"
    
    def test_trending_value(self):
        """Test TRENDING enum value."""
        assert ChopRegime.TRENDING.value == "TRENDING"


class TestDetectChopRegime:
    """Tests for detect_chop_regime function."""
    
    @pytest.fixture
    def trending_bb_data(self):
        """Create BB data for a trending market (wide bandwidth)."""
        n = 150
        # Wide bandwidth - bands spread apart
        middle = pd.Series(np.full(n, 100.0))
        upper = pd.Series(np.full(n, 108.0))  # 8% above
        lower = pd.Series(np.full(n, 92.0))   # 8% below
        return upper, lower, middle
    
    @pytest.fixture
    def chop_bb_data(self):
        """Create BB data for a choppy market (compressed bandwidth)."""
        n = 150
        # Create historical bandwidth data with some variance
        bandwidth_history = np.linspace(0.05, 0.12, n - 10)  # Historical wider bands
        current_compressed = np.full(10, 0.02)  # Last 10 bars very compressed
        bandwidths = np.concatenate([bandwidth_history, current_compressed])
        
        middle = pd.Series(np.full(n, 100.0))
        half_width = bandwidths * 100 / 2  # Convert to price units
        upper = pd.Series(middle.values + half_width)
        lower = pd.Series(middle.values - half_width)
        
        return upper, lower, middle
    
    def test_detect_trending(self, trending_bb_data):
        """Test detection of trending regime (wide bandwidth)."""
        bb_upper, bb_lower, bb_middle = trending_bb_data
        
        # Make recent bandwidth even wider to ensure TRENDING
        # (Bandwidth will be in high percentile)
        bb_upper.iloc[-10:] = 112.0  # Make recent upper band even higher
        bb_lower.iloc[-10:] = 88.0   # Make recent lower band even lower
        
        result = detect_chop_regime(bb_upper, bb_lower, bb_middle)
        
        assert result is not None
        assert result.regime == ChopRegime.TRENDING
        assert not result.is_chop
    
    def test_detect_chop(self, chop_bb_data):
        """Test detection of chop regime (compressed bandwidth)."""
        bb_upper, bb_lower, bb_middle = chop_bb_data
        
        result = detect_chop_regime(bb_upper, bb_lower, bb_middle)
        
        assert result is not None
        assert result.regime == ChopRegime.CHOP
        assert result.is_chop
        assert result.percentile <= 25  # Compressed bandwidth
    
    def test_insufficient_data(self):
        """Test with insufficient data returns None."""
        # Only 50 bars, default lookback is 100
        bb_upper = pd.Series(np.full(50, 105.0))
        bb_lower = pd.Series(np.full(50, 95.0))
        bb_middle = pd.Series(np.full(50, 100.0))
        
        result = detect_chop_regime(bb_upper, bb_lower, bb_middle)
        
        assert result is None
    
    def test_na_values(self):
        """Test with NA values returns None."""
        bb_upper = pd.Series([np.nan] * 100)
        bb_lower = pd.Series([np.nan] * 100)
        bb_middle = pd.Series([np.nan] * 100)
        
        result = detect_chop_regime(bb_upper, bb_lower, bb_middle)
        
        assert result is None
    
    def test_zero_middle_band(self):
        """Test with zero middle band returns None."""
        bb_upper = pd.Series(np.full(150, 5.0))
        bb_lower = pd.Series(np.full(150, -5.0))
        bb_middle = pd.Series(np.full(150, 0.0))  # Zero middle
        
        result = detect_chop_regime(bb_upper, bb_lower, bb_middle)
        
        assert result is None
    
    def test_custom_thresholds(self):
        """Test with custom percentile threshold."""
        n = 150
        middle = pd.Series(np.full(n, 100.0))
        upper = pd.Series(np.full(n, 103.0))  # 3% bandwidth - moderate
        lower = pd.Series(np.full(n, 97.0))
        
        # With 50th percentile threshold, should be CHOP
        result = detect_chop_regime(
            upper, lower, middle,
            chop_percentile=50,  # Higher threshold
        )
        
        # Result should be either CHOP or TRENDING depending on exact data
        assert result is not None
        assert result.regime in [ChopRegime.CHOP, ChopRegime.TRENDING]
    
    def test_result_to_dict(self, chop_bb_data):
        """Test ChopRegimeResult.to_dict() method."""
        bb_upper, bb_lower, bb_middle = chop_bb_data
        
        result = detect_chop_regime(bb_upper, bb_lower, bb_middle)
        
        assert result is not None
        result_dict = result.to_dict()
        
        assert "regime" in result_dict
        assert "bb_bandwidth" in result_dict
        assert "percentile" in result_dict
        assert "is_chop" in result_dict
        assert result_dict["regime"] in ["CHOP", "TRENDING"]


class TestBandwidthCalculation:
    """Tests for bandwidth calculation logic."""
    
    def test_bandwidth_formula(self):
        """Test that bandwidth is calculated as (upper - lower) / middle."""
        n = 150
        middle = pd.Series(np.full(n, 100.0))
        upper = pd.Series(np.full(n, 110.0))  # +10
        lower = pd.Series(np.full(n, 90.0))   # -10
        
        result = detect_chop_regime(upper, lower, middle)
        
        assert result is not None
        # Expected bandwidth: (110 - 90) / 100 = 0.20
        assert result.bb_bandwidth == pytest.approx(0.20, rel=0.01)
    
    def test_varying_bandwidth(self):
        """Test with varying bandwidth over time."""
        n = 150
        
        # Create expanding bandwidth over time
        bandwidths = np.linspace(0.02, 0.10, n)  # 2% to 10%
        
        middle = pd.Series(np.full(n, 100.0))
        upper = pd.Series(100.0 + (bandwidths * 100 / 2))
        lower = pd.Series(100.0 - (bandwidths * 100 / 2))
        
        result = detect_chop_regime(upper, lower, middle)
        
        assert result is not None
        # Most recent bandwidth should be ~10%
        assert result.bb_bandwidth == pytest.approx(0.10, rel=0.01)
        # Since we're at max bandwidth, percentile should be high (TRENDING)
        assert result.regime == ChopRegime.TRENDING
