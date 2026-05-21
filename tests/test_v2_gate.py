"""
Unit tests for V2 Gate Module.

Tests the gate evaluation logic including:
- GateStatus decisions (GO, NO_GO, NOT_EVALUATED)
- ScrutinyLevel assignments
- Hard exclusion rules (penny stock, illiquid, panic vol, falling knife)
- Regime-based filtering
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.v2 import (
    GateStatus,
    ScrutinyLevel,
    GateResult,
    GateFeatures,
    GateConfig,
    evaluate_gate,
    compute_gate_features,
)


class TestGateFeatures:
    """Tests for GateFeatures computation."""
    
    def test_compute_features_from_ohlcv(self):
        """Test feature computation from OHLCV DataFrame."""
        # Create sample OHLCV data
        dates = pd.date_range(start='2024-01-01', periods=30, freq='1h')
        df = pd.DataFrame({
            'open': np.linspace(100, 110, 30),
            'high': np.linspace(101, 111, 30),
            'low': np.linspace(99, 109, 30),
            'close': np.linspace(100, 110, 30),
            'volume': np.full(30, 1_000_000),
        }, index=dates)
        
        features = compute_gate_features(
            df=df,
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
        )
        
        assert features.last_price is not None
        assert features.last_price == pytest.approx(110.0, rel=0.01)
        assert features.trend_regime == "UPTREND"
        assert features.vol_regime == "NORMAL"
        assert features.chop_regime == "TRENDING"
    
    def test_compute_features_empty_df(self):
        """Test feature computation with empty DataFrame."""
        df = pd.DataFrame()
        
        features = compute_gate_features(df=df)
        
        assert features.last_price is None
        assert not features.is_complete()
        assert "last_price" in features.missing_features()
    
    def test_is_complete_all_present(self):
        """Test is_complete with all features present."""
        features = GateFeatures(
            last_price=100.0,
            avg_dollar_volume_20d=25_000_000,
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
        )
        
        assert features.is_complete()
        assert features.missing_features() == []
    
    def test_is_complete_missing_features(self):
        """Test is_complete with missing features."""
        features = GateFeatures(
            last_price=100.0,
            avg_dollar_volume_20d=None,  # Missing
            trend_regime="UPTREND",
            vol_regime=None,  # Missing
            chop_regime="TRENDING",
        )
        
        assert not features.is_complete()
        missing = features.missing_features()
        assert "avg_dollar_volume_20d" in missing
        assert "vol_regime" in missing


class TestGateConfig:
    """Tests for GateConfig."""
    
    def test_default_config(self):
        """Test default gate configuration."""
        config = GateConfig()
        
        assert config.min_price == 5.0
        assert config.min_avg_dollar_volume_20d == 20_000_000
        assert config.allow_weak_downtrend is True
        assert config.strict_earnings_block is False
        assert config.min_score == 70
        assert config.downtrend_min_score == 80
        assert config.max_atr_pct == 5.0
        assert config.block_downtrend_high_vol is True
        assert config.block_high_news_risk is False
    
    def test_custom_config(self):
        """Test custom gate configuration."""
        config = GateConfig(
            min_price=10.0,
            min_avg_dollar_volume_20d=50_000_000,
            allow_weak_downtrend=False,
            block_downtrend_high_vol=False,
            min_score=75,
            downtrend_min_score=85,
        )
        
        assert config.min_price == 10.0
        assert config.min_avg_dollar_volume_20d == 50_000_000
        assert config.allow_weak_downtrend is False
        assert config.block_downtrend_high_vol is False
        assert config.min_score == 75
        assert config.downtrend_min_score == 85


class TestEvaluateGate:
    """Tests for evaluate_gate function."""
    
    @pytest.fixture
    def default_config(self):
        return GateConfig()
    
    @pytest.fixture
    def complete_features(self):
        return GateFeatures(
            last_price=50.0,
            avg_dollar_volume_20d=25_000_000,
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
            score=75,  # Required for V2 gate
        )
    
    def test_missing_features_returns_not_evaluated(self, default_config):
        """Test that missing features returns NOT_EVALUATED."""
        features = GateFeatures(
            last_price=50.0,
            avg_dollar_volume_20d=None,  # Missing
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
        )
        
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="MEAN_REVERSION_BB_RECLAIM",
            direction="LONG",
            features=features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.NOT_EVALUATED
        assert "MISSING_FEATURES" in result.reasons[0]
    
    def test_penny_stock_returns_no_go(self, default_config, complete_features):
        """Test that penny stocks are rejected."""
        complete_features.last_price = 3.50  # Below $5 threshold
        
        result = evaluate_gate(
            symbol="PENNY",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "PENNY_STOCK" in result.reasons[0]
    
    def test_illiquid_returns_no_go(self, default_config, complete_features):
        """Test that illiquid stocks are rejected."""
        complete_features.avg_dollar_volume_20d = 5_000_000  # Below $20M
        
        result = evaluate_gate(
            symbol="ILLIQUID",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "ILLIQUID" in result.reasons[0]
    
    def test_panic_vol_returns_no_go(self, default_config, complete_features):
        """Test that PANIC volatility is rejected."""
        complete_features.vol_regime = "PANIC"
        
        result = evaluate_gate(
            symbol="VOLATILE",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "PANIC_VOL" in result.reasons[0]
    
    def test_falling_knife_returns_no_go(self, default_config, complete_features):
        """Test that falling knife regime is rejected."""
        complete_features.trend_regime = "STRONG_DOWNTREND"
        complete_features.vol_regime = "HIGH"
        
        result = evaluate_gate(
            symbol="FALLING",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "FALLING_KNIFE" in result.reasons[0]
    
    def test_good_regime_returns_go(self, default_config, complete_features):
        """Test that good regime combinations return GO."""
        complete_features.trend_regime = "UPTREND"
        complete_features.vol_regime = "NORMAL"
        
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="MEAN_REVERSION_BB_RECLAIM",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.GO
        assert result.scrutiny_level == ScrutinyLevel.NORMAL
        assert "REGIME_ALLOWED" in result.reasons[0]
    
    def test_weak_downtrend_with_chop_returns_no_go_squeeze_risk(self, default_config, complete_features):
        """Test weak downtrend with chop is REJECTED (Squeeze Risk)."""
        complete_features.trend_regime = "DOWNTREND"
        complete_features.vol_regime = "NORMAL"
        complete_features.chop_regime = "CHOP"  # Squeeze!
        complete_features.score = 85
        
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="MEAN_REVERSION_BB_RECLAIM",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        # Should be blocked because we don't buy during a squeeze in a downtrend
        assert result.status == GateStatus.NO_GO
        assert "REGIME_BLOCK" in result.reasons[0]
    
    def test_weak_downtrend_without_chop_returns_go_high_scrutiny(self, default_config, complete_features):
        """Test weak downtrend without chop is ALLOWED (No Squeeze) with sufficient score."""
        complete_features.trend_regime = "DOWNTREND"
        complete_features.vol_regime = "NORMAL"
        complete_features.chop_regime = "TRENDING"  # Expanded bands
        complete_features.score = 85  # Must be >= downtrend_min_score (80)
        
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        assert result.status == GateStatus.GO
        assert result.scrutiny_level == ScrutinyLevel.HIGH
        assert "WEAK_DOWNTREND_ALLOWED" in result.reasons[0]
    
    def test_weak_downtrend_disabled_returns_no_go(self, complete_features):
        """Test weak downtrend with config disabled returns NO_GO."""
        config = GateConfig(allow_weak_downtrend=False)
        
        complete_features.trend_regime = "DOWNTREND"
        complete_features.vol_regime = "NORMAL"
        complete_features.chop_regime = "CHOP"
        complete_features.score = 85  # Even with high score, should block
        
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NO_GO
    
    def test_gate_result_to_dict(self, default_config, complete_features):
        """Test GateResult.to_dict() method."""
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        result_dict = result.to_dict()
        
        assert "status" in result_dict
        assert "reasons" in result_dict
        assert "scrutiny_level" in result_dict
        assert "tags" in result_dict
        assert result_dict["status"] in ["GO", "NO_GO", "NOT_EVALUATED"]
    
    def test_gate_result_to_json(self, default_config, complete_features):
        """Test GateResult.to_json() method."""
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=complete_features,
            gate_config=default_config,
        )
        
        json_str = result.to_json()
        
        assert isinstance(json_str, str)
        import json
        parsed = json.loads(json_str)
        assert "status" in parsed


class TestGateRuleOrdering:
    """Tests to verify gate rules are applied in correct order."""
    
    @pytest.fixture
    def config(self):
        return GateConfig()
    
    def test_penny_stock_before_liquidity(self, config):
        """Penny stock rule should fire before liquidity check."""
        features = GateFeatures(
            last_price=2.0,  # Penny stock
            avg_dollar_volume_20d=1_000_000,  # Also illiquid
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
            score=75,
        )
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=features,
            gate_config=config,
        )
        
        # Should fail on penny stock first
        assert result.status == GateStatus.NO_GO
        assert "PENNY_STOCK" in result.reasons[0]
    
    def test_panic_vol_before_falling_knife(self, config):
        """PANIC vol rule should fire before falling knife check."""
        features = GateFeatures(
            last_price=100.0,
            avg_dollar_volume_20d=50_000_000,
            trend_regime="STRONG_DOWNTREND",  # Would be falling knife
            vol_regime="PANIC",  # But PANIC hits first
            chop_regime="TRENDING",
            score=75,
        )
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=features,
            gate_config=config,
        )
        
        # Should fail on PANIC vol first
        assert result.status == GateStatus.NO_GO
        assert "PANIC_VOL" in result.reasons[0]


class TestGateTags:
    """Tests for gate result tags."""
    
    def test_tags_contain_regimes(self):
        """Test that tags include regime information."""
        features = GateFeatures(
            last_price=50.0,
            avg_dollar_volume_20d=25_000_000,
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
            score=75,
        )
        
        result = evaluate_gate(
            symbol="AAPL",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=features,
            gate_config=GateConfig(),
        )
        
        assert "trend_regime" in result.tags
        assert "vol_regime" in result.tags
        assert "chop_regime" in result.tags
        assert result.tags["trend_regime"] == "UPTREND"
        assert result.tags["vol_regime"] == "NORMAL"
        assert result.tags["score"] == 75


class TestV2GateRefinements:
    """Tests for V2.1 gate refinements: score filters and toxic regime blocking."""
    
    @pytest.fixture
    def config(self):
        return GateConfig(
            min_score=70,
            downtrend_min_score=80,
            block_downtrend_high_vol=True,
            max_atr_pct=5.0,
        )
    
    @pytest.fixture
    def base_features(self):
        """Features that would normally pass the gate."""
        return GateFeatures(
            last_price=50.0,
            avg_dollar_volume_20d=25_000_000,
            trend_regime="UPTREND",
            vol_regime="NORMAL",
            chop_regime="TRENDING",
            score=75,
            atr_pct=2.0,
        )
    
    def test_gate_min_score_blocks(self, config, base_features):
        """Test score=60 => NO_GO LOW_SCORE."""
        base_features.score = 60  # Below min_score=70
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "LOW_SCORE" in result.reasons[0]
        assert "60" in result.reasons[0]
    
    def test_gate_blocks_downtrend_high_vol(self, config, base_features):
        """Test DOWNTREND + HIGH vol => NO_GO DOWNTREND_HIGH_VOL_BLOCK even with high score."""
        base_features.trend_regime = "DOWNTREND"
        base_features.vol_regime = "HIGH"
        base_features.score = 90  # High score doesn't save it
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "DOWNTREND_HIGH_VOL_BLOCK" in result.reasons[0]
    
    def test_gate_downtrend_requires_higher_score_blocks(self, config, base_features):
        """Test DOWNTREND + NORMAL vol + score=75 => NO_GO DOWNTREND_SCORE_TOO_LOW."""
        base_features.trend_regime = "DOWNTREND"
        base_features.vol_regime = "NORMAL"
        base_features.chop_regime = "TRENDING"
        base_features.score = 75  # Below downtrend_min_score=80
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "DOWNTREND_SCORE_TOO_LOW" in result.reasons[0]
    
    def test_gate_downtrend_high_score_passes(self, config, base_features):
        """Test DOWNTREND + NORMAL vol + score=85 => GO with HIGH scrutiny."""
        base_features.trend_regime = "DOWNTREND"
        base_features.vol_regime = "NORMAL"
        base_features.chop_regime = "TRENDING"
        base_features.score = 85  # Above downtrend_min_score=80
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.GO
        assert result.scrutiny_level == ScrutinyLevel.HIGH
    
    def test_gate_normal_regime_allows(self, config, base_features):
        """Test NEUTRAL + NORMAL vol + score=70 => GO."""
        base_features.trend_regime = "NEUTRAL"
        base_features.vol_regime = "NORMAL"
        base_features.score = 70  # Exactly at min_score
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.GO
        assert result.scrutiny_level == ScrutinyLevel.NORMAL
    
    def test_missing_score_returns_not_evaluated(self, config, base_features):
        """Test score=None => NOT_EVALUATED MISSING_FEATURES."""
        base_features.score = None
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NOT_EVALUATED
        assert "MISSING_FEATURES" in result.reasons[0]
        assert "score" in result.reasons[0]
    
    def test_missing_trend_regime_returns_not_evaluated(self, config, base_features):
        """Test missing trend_regime => NOT_EVALUATED MISSING_FEATURES."""
        base_features.trend_regime = None
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NOT_EVALUATED
        assert "MISSING_FEATURES" in result.reasons[0]
    
    def test_high_atr_blocks(self, config, base_features):
        """Test ATR% > max => NO_GO HIGH_ATR."""
        base_features.atr_pct = 6.5  # Above max_atr_pct=5.0
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.NO_GO
        assert "HIGH_ATR" in result.reasons[0]
    
    def test_uptrend_high_vol_passes_with_high_scrutiny(self, config, base_features):
        """Test UPTREND + HIGH vol => GO with HIGH scrutiny (not blocked)."""
        base_features.trend_regime = "UPTREND"
        base_features.vol_regime = "HIGH"
        base_features.score = 75
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert result.status == GateStatus.GO
        assert result.scrutiny_level == ScrutinyLevel.HIGH
    
    def test_block_downtrend_high_vol_disabled(self, base_features):
        """Test block_downtrend_high_vol=false allows DOWNTREND + HIGH vol."""
        config = GateConfig(
            min_score=70,
            downtrend_min_score=80,
            block_downtrend_high_vol=False,  # Disabled
        )
        base_features.trend_regime = "DOWNTREND"
        base_features.vol_regime = "HIGH"
        base_features.chop_regime = "TRENDING"
        base_features.score = 85
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        # With block disabled, should check other rules (weak downtrend with HIGH vol)
        # Since it's HIGH vol, not NORMAL, it won't hit the downtrend_min_score rule
        # It will fall through to REGIME_BLOCK
        assert result.status == GateStatus.NO_GO
        assert "REGIME_BLOCK" in result.reasons[0]
    
    def test_tags_include_score_and_atr(self, config, base_features):
        """Test that gate tags include score and atr_pct for reporting."""
        base_features.score = 82
        base_features.atr_pct = 1.5
        
        result = evaluate_gate(
            symbol="TEST",
            timeframe="1h",
            setup_name="TEST",
            direction="LONG",
            features=base_features,
            gate_config=config,
        )
        
        assert "score" in result.tags
        assert "atr_pct" in result.tags
        assert result.tags["score"] == 82
        assert result.tags["atr_pct"] == 1.5
