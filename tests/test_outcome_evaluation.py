"""Tests for outcome evaluation module.

Tests cover:
- Outcome math (forward return, MFE, MAE)
- Hit rule ordering + tie-break behavior
- Horizon selection (last closed candle at/before horizon_end)
- PENDING status when insufficient future candles
- alert_id stability and collision resistance
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

import pandas as pd
import pytest

from src.evaluation.outcome_logger import (
    EvaluationStatus,
    OutcomeConfig,
    OutcomeRecord,
    compute_outcomes_for_alert,
    generate_alert_id,
    get_interval_minutes,
    load_alerts_needing_evaluation,
    upsert_outcome,
    _check_hit,
    _compute_mfe_mae,
    _find_close_at_horizon,
)


class TestAlertIdGeneration:
    """Test deterministic alert ID generation."""
    
    def test_alert_id_stability(self):
        """Same inputs should produce same ID."""
        id1 = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.5678,
        )
        id2 = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.5678,
        )
        assert id1 == id2
        assert len(id1) == 32  # Truncated SHA-256
    
    def test_alert_id_no_collision_different_trigger_close(self):
        """Different trigger_close should produce different IDs."""
        id1 = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.5678,
        )
        id2 = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.5679,  # Slightly different
        )
        assert id1 != id2
    
    def test_alert_id_no_collision_different_direction(self):
        """Different direction should produce different IDs."""
        id_long = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.50,
        )
        id_short = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="SHORT",
            trigger_close=185.50,
        )
        assert id_long != id_short
    
    def test_alert_id_rounding(self):
        """Trigger close should be rounded to 4 decimal places."""
        id1 = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.56781234,
        )
        id2 = generate_alert_id(
            ts_utc="2024-01-15T10:00:00",
            symbol="AAPL",
            timeframe="1h",
            setup="MEAN_REVERSION",
            direction="LONG",
            trigger_close=185.56784999,  # Rounds to same 4 decimals (185.5678)
        )
        assert id1 == id2


class TestIntervalMinutes:
    """Test interval to minutes conversion."""
    
    def test_known_intervals(self):
        assert get_interval_minutes("1h") == 60
        assert get_interval_minutes("4h") == 240
        assert get_interval_minutes("1d") == 1440
        assert get_interval_minutes("15m") == 15
    
    def test_unknown_interval_defaults_to_60(self):
        assert get_interval_minutes("unknown") == 60


class TestForwardReturn:
    """Test forward return calculations."""
    
    def _create_ohlcv_df(self, bars: list) -> pd.DataFrame:
        """Helper to create OHLCV DataFrame from list of dicts."""
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df
    
    def test_forward_return_long_positive(self):
        """LONG with price increase = positive return."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 100.0,
            "atr": 2.0,
        }
        
        # Create OHLCV data: price goes from 100 to 105 over 4 hours
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 102, "high": 105, "low": 101, "close": 104, "volume": 1000},
            {"timestamp": "2024-01-15T14:00:00", "open": 104, "high": 106, "low": 103, "close": 105, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        # Forward return at 4h horizon: (105 - 100) / 100 * 100 = 5%
        assert outcome.forward_returns[4] == pytest.approx(5.0, rel=0.01)
    
    def test_forward_return_long_negative(self):
        """LONG with price decrease = negative return."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 100.0,
            "atr": 2.0,
        }
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 98, "high": 99, "low": 96, "close": 96, "volume": 1000},
            {"timestamp": "2024-01-15T14:00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        # Forward return at 4h: (95 - 100) / 100 * 100 = -5%
        assert outcome.forward_returns[4] == pytest.approx(-5.0, rel=0.01)
    
    def test_forward_return_short_positive(self):
        """SHORT with price decrease = positive return."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "SHORT",
            "score": 70,
            "trigger_close": 100.0,
            "atr": 2.0,
        }
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 99, "high": 100, "low": 97, "close": 97, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 1000},
            {"timestamp": "2024-01-15T14:00:00", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        # SHORT: (entry - close) / entry * 100 = (100 - 95) / 100 * 100 = 5%
        assert outcome.forward_returns[4] == pytest.approx(5.0, rel=0.01)


class TestMFEMAE:
    """Test MFE/MAE calculations."""
    
    def _create_ohlcv_df(self, bars: list) -> pd.DataFrame:
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df
    
    def test_mfe_mae_long(self):
        """Test MFE/MAE for LONG position."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 102, "high": 105, "low": 98, "close": 101, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 101, "high": 104, "low": 97, "close": 103, "volume": 1000},
            {"timestamp": "2024-01-15T14:00:00", "open": 103, "high": 106, "low": 100, "close": 104, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        mfe, mae = _compute_mfe_mae(ohlcv_df, alert_ts, 4, entry_price, "LONG", use_high_low=True)
        
        # Max high = 106, MFE = (106 - 100) / 100 * 100 = 6%
        assert mfe == pytest.approx(6.0, rel=0.01)
        
        # Min low = 97, MAE = (97 - 100) / 100 * 100 = -3%
        assert mae == pytest.approx(-3.0, rel=0.01)
    
    def test_mfe_mae_short(self):
        """Test MFE/MAE for SHORT position."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 103, "low": 97, "close": 98, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 98, "high": 101, "low": 95, "close": 96, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 96, "high": 99, "low": 94, "close": 95, "volume": 1000},
            {"timestamp": "2024-01-15T14:00:00", "open": 95, "high": 98, "low": 93, "close": 94, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        mfe, mae = _compute_mfe_mae(ohlcv_df, alert_ts, 4, entry_price, "SHORT", use_high_low=True)
        
        # SHORT MFE: (entry - min_low) / entry * 100 = (100 - 93) / 100 * 100 = 7%
        assert mfe == pytest.approx(7.0, rel=0.01)
        
        # SHORT MAE: (entry - max_high) / entry * 100 = (100 - 103) / 100 * 100 = -3%
        assert mae == pytest.approx(-3.0, rel=0.01)
    
    def test_mfe_mae_close_only(self):
        """Test MFE/MAE using close prices only."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 110, "low": 90, "close": 102, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 102, "high": 115, "low": 85, "close": 98, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        mfe, mae = _compute_mfe_mae(ohlcv_df, alert_ts, 4, entry_price, "LONG", use_high_low=False)
        
        # Using close only: max_close=102, min_close=98
        # MFE = (102 - 100) / 100 * 100 = 2%
        assert mfe == pytest.approx(2.0, rel=0.01)
        # MAE = (98 - 100) / 100 * 100 = -2%
        assert mae == pytest.approx(-2.0, rel=0.01)


class TestHitRule:
    """Test hit detection with ATR-based targets."""
    
    def _create_ohlcv_df(self, bars: list) -> pd.DataFrame:
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df
    
    def test_hit_long_target_reached(self):
        """LONG: Target reached before stop."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        atr = 2.0
        target_atr = 1.0  # Target at 102
        stop_atr = 0.7    # Stop at 98.6
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 99, "close": 101, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 101, "high": 102.5, "low": 100, "close": 102, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        result = _check_hit(ohlcv_df, alert_ts, 4, entry_price, atr, "LONG", target_atr, stop_atr)
        assert result is True
    
    def test_hit_long_stop_reached(self):
        """LONG: Stop reached before target."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        atr = 2.0
        target_atr = 1.0  # Target at 102
        stop_atr = 0.7    # Stop at 98.6
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        result = _check_hit(ohlcv_df, alert_ts, 4, entry_price, atr, "LONG", target_atr, stop_atr)
        assert result is False
    
    def test_hit_long_tie_break_conservative(self):
        """LONG: Both target and stop touched in same candle = stop wins (conservative)."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        atr = 2.0
        target_atr = 1.0  # Target at 102
        stop_atr = 0.7    # Stop at 98.6
        
        # Candle that touches both target (102) and stop (98.6)
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 103, "low": 98, "close": 101, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        result = _check_hit(ohlcv_df, alert_ts, 4, entry_price, atr, "LONG", target_atr, stop_atr)
        # Conservative: tie-break counts as stop-first
        assert result is False
    
    def test_hit_long_neither(self):
        """LONG: Neither target nor stop touched."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        atr = 2.0
        target_atr = 1.0  # Target at 102
        stop_atr = 0.7    # Stop at 98.6
        
        # Price stays in narrow range
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 100.5, "high": 101.5, "low": 99.5, "close": 101, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        result = _check_hit(ohlcv_df, alert_ts, 4, entry_price, atr, "LONG", target_atr, stop_atr)
        assert result is False
    
    def test_hit_short_target_reached(self):
        """SHORT: Target reached before stop."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        atr = 2.0
        target_atr = 1.0  # Target at 98
        stop_atr = 0.7    # Stop at 101.4
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 100.5, "low": 99, "close": 99, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 99, "high": 99.5, "low": 97.5, "close": 98, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        result = _check_hit(ohlcv_df, alert_ts, 4, entry_price, atr, "SHORT", target_atr, stop_atr)
        assert result is True
    
    def test_hit_short_stop_reached(self):
        """SHORT: Stop reached before target."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry_price = 100.0
        atr = 2.0
        target_atr = 1.0  # Target at 98
        stop_atr = 0.7    # Stop at 101.4
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 102, "low": 99.5, "close": 101.5, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        result = _check_hit(ohlcv_df, alert_ts, 4, entry_price, atr, "SHORT", target_atr, stop_atr)
        assert result is False


class TestHorizonSelection:
    """Test horizon end time and closed candle selection."""
    
    def _create_ohlcv_df(self, bars: list) -> pd.DataFrame:
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df
    
    def test_close_at_horizon_exact(self):
        """Last candle at exactly horizon_end."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 100.5, "high": 102, "low": 100, "close": 101, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 101, "high": 103, "low": 100.5, "close": 102, "volume": 1000},
            {"timestamp": "2024-01-15T14:00:00", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        # horizon_end = 10:00 + 4h = 14:00
        close_price, is_complete = _find_close_at_horizon(ohlcv_df, alert_ts, 4, 60, tolerance_bars=1)
        
        assert close_price == 103
        assert is_complete is True
    
    def test_close_at_horizon_before(self):
        """Last candle before horizon_end."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
            {"timestamp": "2024-01-15T12:00:00", "open": 100.5, "high": 102, "low": 100, "close": 101, "volume": 1000},
            {"timestamp": "2024-01-15T13:00:00", "open": 101, "high": 103, "low": 100.5, "close": 102, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        # horizon_end = 10:00 + 4h = 14:00, but last bar is at 13:00
        close_price, is_complete = _find_close_at_horizon(ohlcv_df, alert_ts, 4, 60, tolerance_bars=1)
        
        assert close_price == 102
        assert is_complete is True  # Within tolerance (1 bar)
    
    def test_close_at_horizon_too_far(self):
        """Last candle too far before horizon_end."""
        alert_ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        # horizon_end = 10:00 + 4h = 14:00, but last bar is at 11:00 (3 bars away)
        close_price, is_complete = _find_close_at_horizon(ohlcv_df, alert_ts, 4, 60, tolerance_bars=1)
        
        assert close_price == 100.5
        assert is_complete is False  # Beyond tolerance


class TestPendingStatus:
    """Test PENDING status when data is incomplete."""
    
    def _create_ohlcv_df(self, bars: list) -> pd.DataFrame:
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df
    
    def test_pending_when_insufficient_future_candles(self):
        """Alert should be PENDING when future data is incomplete."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 100.0,
            "atr": 2.0,
        }
        
        # Only 1 bar after alert, but horizons require more
        bars = [
            {"timestamp": "2024-01-15T11:00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4, 12, 24])  # Need more bars
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        # Should be PENDING because not all horizons are complete
        assert outcome.evaluation_status == EvaluationStatus.PENDING
    
    def test_complete_when_all_horizons_have_data(self):
        """Alert should be COMPLETE when all horizons have sufficient data."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 100.0,
            "atr": 2.0,
        }
        
        # Generate enough bars for all horizons
        bars = []
        base_time = datetime(2024, 1, 15, 11, 0, 0)
        for i in range(50):  # 50 hours of data
            bar_time = (base_time + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S")
            bars.append({
                "timestamp": bar_time,
                "open": 100 + i * 0.1,
                "high": 101 + i * 0.1,
                "low": 99 + i * 0.1,
                "close": 100.5 + i * 0.1,
                "volume": 1000,
            })
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4, 12, 24, 48])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        assert outcome.evaluation_status == EvaluationStatus.COMPLETE
    
    def test_insufficient_data_when_no_ohlcv(self):
        """Alert should be INSUFFICIENT_DATA when no OHLCV available."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 100.0,
            "atr": 2.0,
        }
        
        ohlcv_df = pd.DataFrame()  # Empty
        
        config = OutcomeConfig(horizons_1h=[4])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        assert outcome.evaluation_status == EvaluationStatus.INSUFFICIENT_DATA


class TestEntryPrice:
    """Test entry price determination."""
    
    def _create_ohlcv_df(self, bars: list) -> pd.DataFrame:
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        return df
    
    def test_entry_price_from_trigger_close(self):
        """Entry price uses trigger_close when no entry_zone."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 150.0,
            "atr": 2.0,
        }
        
        bars = [
            {"timestamp": "2024-01-15T14:00:00", "open": 150, "high": 155, "low": 149, "close": 154, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        assert outcome.entry_price == 150.0
    
    def test_entry_price_from_entry_zone_midpoint(self):
        """Entry price uses entry_zone midpoint when available."""
        alert = {
            "alert_id": "test123",
            "ts_utc": "2024-01-15T10:00:00",
            "symbol": "AAPL",
            "timeframe": "1h",
            "setup": "MEAN_REVERSION",
            "direction": "LONG",
            "score": 70,
            "trigger_close": 150.0,
            "entry_zone_low": 148.0,
            "entry_zone_high": 152.0,
            "atr": 2.0,
        }
        
        bars = [
            {"timestamp": "2024-01-15T14:00:00", "open": 150, "high": 155, "low": 149, "close": 154, "volume": 1000},
        ]
        ohlcv_df = self._create_ohlcv_df(bars)
        
        config = OutcomeConfig(horizons_1h=[4])
        outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
        
        # Midpoint of entry zone: (148 + 152) / 2 = 150
        assert outcome.entry_price == 150.0


class TestDatabaseOperations:
    """Test database operations for outcomes."""
    
    def test_upsert_outcome(self):
        """Test inserting and updating outcome records."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            record = OutcomeRecord(
                alert_id="test123",
                ts_utc="2024-01-15T10:00:00",
                symbol="AAPL",
                timeframe="1h",
                setup="MEAN_REVERSION",
                direction="LONG",
                score=70,
                entry_price=150.0,
                atr_at_alert=2.0,
                bar_interval_minutes=60,
                forward_returns={4: 2.5, 12: 5.0},
                mfe={4: 3.0, 12: 6.0},
                mae={4: -1.0, 12: -2.0},
                hit={4: True, 12: True},
                evaluation_status=EvaluationStatus.COMPLETE,
                evaluated_at_utc="2024-01-16T10:00:00",
                notes="Test outcome",
                trend_regime="NEUTRAL",
                vol_regime="NORMAL",
            )
            
            # Insert
            upsert_outcome(db_path, record)
            
            # Verify
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM alert_outcomes WHERE alert_id = ?", 
                ("test123",)
            ).fetchone()
            conn.close()
            
            assert row is not None
            assert row["symbol"] == "AAPL"
            assert row["entry_price"] == 150.0
            assert row["evaluation_status"] == "COMPLETE"
            
            # Parse JSON
            fwd_returns = json.loads(row["forward_returns_json"])
            assert fwd_returns["4"] == 2.5
            
            # Update (same alert_id)
            record.notes = "Updated notes"
            record.forward_returns[4] = 3.0
            upsert_outcome(db_path, record)
            
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM alert_outcomes WHERE alert_id = ?", 
                ("test123",)
            ).fetchone()
            conn.close()
            
            assert row["notes"] == "Updated notes"
            fwd_returns = json.loads(row["forward_returns_json"])
            assert fwd_returns["4"] == 3.0
            
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_load_alerts_needing_evaluation(self):
        """Test loading alerts that need evaluation."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            
            # Create alerts_log table
            conn.execute("""
                CREATE TABLE alerts_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    setup TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    score INTEGER,
                    trigger_close REAL,
                    atr REAL
                )
            """)
            
            # Insert test alerts
            now = datetime.utcnow()
            for i in range(5):
                ts = (now - timedelta(hours=i * 24)).isoformat()
                conn.execute(
                    """INSERT INTO alerts_log 
                       (ts_utc, symbol, timeframe, setup, direction, score, trigger_close, atr)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ts, f"TICK{i}", "1h", "MEAN_REVERSION", "LONG", 70 + i, 100.0 + i, 2.0)
                )
            conn.commit()
            conn.close()
            
            # Load alerts
            alerts = load_alerts_needing_evaluation(db_path, lookback_hours=168, max_alerts=10)
            
            assert len(alerts) == 5
            assert all("alert_id" in a for a in alerts)
            assert all(a["timeframe"] == "1h" for a in alerts)
            
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestOutcomeConfig:
    """Test OutcomeConfig loading and horizon selection."""
    
    def test_default_horizons(self):
        config = OutcomeConfig()
        assert config.horizons_1h == [4, 12, 24, 48]
        assert config.horizons_4h == [24, 48, 72]
    
    def test_get_horizons_by_timeframe(self):
        config = OutcomeConfig(
            horizons_1h=[2, 4, 8],
            horizons_4h=[12, 24],
            horizons_1d=[48, 96],
        )
        
        assert config.get_horizons("1h") == [2, 4, 8]
        assert config.get_horizons("4h") == [12, 24]
        assert config.get_horizons("1d") == [48, 96]
        assert config.get_horizons("15m") == [2, 4, 8]  # Defaults to 1h
    
    def test_from_config_dict(self):
        config_dict = {
            "outcome_eval": {
                "horizons_1h": [1, 2, 3],
                "horizons_4h": [6, 12],
                "mfe_mae_use_high_low": False,
                "hit_rule": {
                    "target_atr": 1.5,
                    "stop_atr": 0.5,
                },
            }
        }
        
        config = OutcomeConfig.from_config(config_dict)
        
        assert config.horizons_1h == [1, 2, 3]
        assert config.horizons_4h == [6, 12]
        assert config.mfe_mae_use_high_low is False
        assert config.hit_target_atr == 1.5
        assert config.hit_stop_atr == 0.5
