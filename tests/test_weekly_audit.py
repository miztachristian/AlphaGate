"""
Unit tests for Weekly Audit Module.

Tests the weekly audit functionality including:
- P&L calculation
- CSV export
- Summary statistics
- Report generation
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

from src.reporting.weekly_audit import (
    WeeklyAuditConfig,
    WeeklyAuditResult,
    AlertOutcome,
    run_weekly_audit,
    export_csv,
    _calculate_pnl,
    _get_exit_price,
)


class TestPnLCalculation:
    """Tests for P&L calculation."""
    
    def test_long_profit(self):
        """Test P&L for profitable LONG trade."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="LONG",
            entry_price=100.0,
            exit_price=110.0,
            capital=100.0,
        )
        
        assert pnl_percent == pytest.approx(10.0, rel=0.01)
        assert pnl_dollars == pytest.approx(10.0, rel=0.01)
    
    def test_long_loss(self):
        """Test P&L for losing LONG trade."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="LONG",
            entry_price=100.0,
            exit_price=95.0,
            capital=100.0,
        )
        
        assert pnl_percent == pytest.approx(-5.0, rel=0.01)
        assert pnl_dollars == pytest.approx(-5.0, rel=0.01)
    
    def test_short_profit(self):
        """Test P&L for profitable SHORT trade."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="SHORT",
            entry_price=100.0,
            exit_price=90.0,
            capital=100.0,
        )
        
        assert pnl_percent == pytest.approx(10.0, rel=0.01)
        assert pnl_dollars == pytest.approx(10.0, rel=0.01)
    
    def test_short_loss(self):
        """Test P&L for losing SHORT trade."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="SHORT",
            entry_price=100.0,
            exit_price=105.0,
            capital=100.0,
        )
        
        assert pnl_percent == pytest.approx(-5.0, rel=0.01)
        assert pnl_dollars == pytest.approx(-5.0, rel=0.01)
    
    def test_custom_capital(self):
        """Test P&L with custom capital amount."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="LONG",
            entry_price=100.0,
            exit_price=110.0,
            capital=200.0,
        )
        
        assert pnl_percent == pytest.approx(10.0, rel=0.01)
        assert pnl_dollars == pytest.approx(20.0, rel=0.01)  # 10% of $200
    
    def test_zero_entry_price(self):
        """Test P&L with zero entry price returns zero."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="LONG",
            entry_price=0.0,
            exit_price=100.0,
            capital=100.0,
        )
        
        assert pnl_dollars == 0.0
        assert pnl_percent == 0.0
    
    def test_breakeven(self):
        """Test P&L for breakeven trade."""
        pnl_dollars, pnl_percent = _calculate_pnl(
            direction="LONG",
            entry_price=100.0,
            exit_price=100.0,
            capital=100.0,
        )
        
        assert pnl_percent == pytest.approx(0.0)
        assert pnl_dollars == pytest.approx(0.0)


class TestWeeklyAuditConfig:
    """Tests for WeeklyAuditConfig."""
    
    def test_default_config(self):
        """Test default audit configuration."""
        config = WeeklyAuditConfig()
        
        assert config.lookback_days == 7
        assert config.capital_usd_per_alert == 100.0
        assert config.output_dir == "reports"
        assert config.state_db == "state.db"
        assert "1h" in config.hold_hours_by_timeframe
    
    def test_custom_config(self):
        """Test custom audit configuration."""
        config = WeeklyAuditConfig(
            lookback_days=14,
            capital_usd_per_alert=50.0,
            output_dir="custom_reports",
        )
        
        assert config.lookback_days == 14
        assert config.capital_usd_per_alert == 50.0
        assert config.output_dir == "custom_reports"


class TestWeeklyAuditResult:
    """Tests for WeeklyAuditResult."""
    
    def test_empty_result(self):
        """Test empty audit result."""
        result = WeeklyAuditResult(
            start_date="2024-01-01",
            end_date="2024-01-08",
        )
        result.system_outcomes = []
        
        assert result.total_alerts == 0
        assert result.system_pnl == 0.0
        assert result.system_win_rate == 0.0
    
    def test_result_with_outcomes(self):
        """Test audit result with outcomes."""
        outcomes = [
            AlertOutcome(
                alert_id=1,
                symbol="AAPL",
                timeframe="1h",
                direction="LONG",
                setup="TEST",
                score=80,
                entry_price=100.0,
                entry_ts="2024-01-01T10:00:00",
                exit_price=110.0,
                exit_ts="2024-01-02T10:00:00",
                exit_reason="HOLD_WINDOW_END",
                pnl_dollars=10.0,
                pnl_percent=10.0,
                hold_hours=24,
            ),
            AlertOutcome(
                alert_id=2,
                symbol="MSFT",
                timeframe="1h",
                direction="LONG",
                setup="TEST",
                score=75,
                entry_price=200.0,
                entry_ts="2024-01-02T10:00:00",
                exit_price=190.0,
                exit_ts="2024-01-03T10:00:00",
                exit_reason="HOLD_WINDOW_END",
                pnl_dollars=-5.0,
                pnl_percent=-5.0,
                hold_hours=24,
            ),
        ]
        
        result = WeeklyAuditResult(
            start_date="2024-01-01",
            end_date="2024-01-08",
            total_alerts=2,
            alerts_evaluated=2,
        )
        result.system_outcomes = outcomes
        
        # Calculate stats
        result.system_pnl = sum(o.pnl_dollars for o in outcomes)
        result.system_wins = sum(1 for o in outcomes if o.pnl_dollars > 0)
        result.system_losses = sum(1 for o in outcomes if o.pnl_dollars < 0)
        
        assert result.system_pnl == 5.0
        assert result.system_wins == 1
        assert result.system_losses == 1
    
    def test_to_dict(self):
        """Test to_dict method."""
        result = WeeklyAuditResult(
            start_date="2024-01-01",
            end_date="2024-01-08",
            total_alerts=10,
            system_pnl=50.0,
            system_wins=7,
            system_losses=3,
        )
        
        result_dict = result.to_dict()
        
        assert "period" in result_dict
        assert "alerts" in result_dict
        assert "system_performance" in result_dict
        assert "gate" in result_dict
        assert result_dict["system_performance"]["total_pnl"] == 50.0


class TestCSVExport:
    """Tests for CSV export functionality."""
    
    def test_export_empty_results(self):
        """Test exporting empty results."""
        result = WeeklyAuditResult(
            start_date="2024-01-01",
            end_date="2024-01-08",
        )
        result.system_outcomes = []
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            output_path = f.name
        
        try:
            exported_path = export_csv(result, output_path)
            
            assert exported_path == output_path
            assert Path(output_path).exists()
            
            # Verify header is present
            with open(output_path) as f:
                header = f.readline().strip()
                assert "alert_id" in header
                assert "symbol" in header
                assert "pnl_dollars" in header
        finally:
            os.unlink(output_path)
    
    def test_export_with_outcomes(self):
        """Test exporting results with outcomes."""
        outcomes = [
            AlertOutcome(
                alert_id=1,
                symbol="AAPL",
                timeframe="1h",
                direction="LONG",
                setup="TEST",
                score=80,
                entry_price=100.0,
                entry_ts="2024-01-01T10:00:00",
                exit_price=110.0,
                exit_ts="2024-01-02T10:00:00",
                exit_reason="HOLD_WINDOW_END",
                pnl_dollars=10.0,
                pnl_percent=10.0,
                hold_hours=24,
            ),
        ]
        
        result = WeeklyAuditResult(
            start_date="2024-01-01",
            end_date="2024-01-08",
        )
        result.system_outcomes = outcomes
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            output_path = f.name
        
        try:
            export_csv(result, output_path)
            
            # Verify content
            with open(output_path) as f:
                lines = f.readlines()
                assert len(lines) == 2  # Header + 1 row
                assert "AAPL" in lines[1]
                assert "10.0" in lines[1]
        finally:
            os.unlink(output_path)


class TestGetExitPrice:
    """Tests for _get_exit_price logic."""

    @patch('src.reporting.weekly_audit.fetch_stock_ohlcv_cached')
    @patch('src.reporting.weekly_audit.CACHE_AVAILABLE', True)
    def test_stop_loss_hit(self, mock_fetch):
        """Test that exit occurs at stop loss if hit."""
        # Create a dataframe where price drops below Stop Loss
        dates = pd.date_range(start="2024-01-01 10:00", periods=5, freq="1h")
        data = {
            'open': [100, 99, 98, 97, 96],
            'high': [101, 100, 99, 98, 97],
            'low': [99, 98, 90, 96, 95], # Drop to 90 in 3rd candle
            'close': [100, 99, 91, 97, 96],
            'volume': [1000] * 5
        }
        df = pd.DataFrame(data, index=dates)
        mock_fetch.return_value = df
        
        entry_price = 100.0
        stop_loss = 95.0 # Check low=90 < 95
        
        # Call with stopped out scenario
        exit_price, exit_ts, reason = _get_exit_price(
            symbol="TEST",
            timeframe="1h",
            direction="LONG",
            entry_ts="2024-01-01T10:00:00",
            entry_price=entry_price,
            hold_hours=4,
            stop_loss_price=stop_loss
        )
        
        assert reason == "STOP_LOSS"
        assert exit_price == 95.0
        # Should be the 3rd candle (12:00)
        assert "12:00:00" in exit_ts

    @patch('src.reporting.weekly_audit.fetch_stock_ohlcv_cached')
    @patch('src.reporting.weekly_audit.CACHE_AVAILABLE', True)
    def test_no_stop_loss_hit(self, mock_fetch):
        """Test that exit occurs at window end if stop loss NOT hit."""
        dates = pd.date_range(start="2024-01-01 10:00", periods=5, freq="1h")
        data = {
            'open': [100, 101, 102, 103, 104],
            'high': [101, 102, 103, 104, 105],
            'low': [99, 100, 101, 102, 103], # Low never drops below 95
            'close': [100, 101, 102, 103, 104],
            'volume': [1000] * 5
        }
        df = pd.DataFrame(data, index=dates)
        mock_fetch.return_value = df
        
        entry_price = 100.0
        stop_loss = 95.0
        
        exit_price, exit_ts, reason = _get_exit_price(
            symbol="TEST",
            timeframe="1h",
            direction="LONG",
            entry_ts="2024-01-01T10:00:00",
            entry_price=entry_price,
            hold_hours=4,
            stop_loss_price=stop_loss
        )
        
        assert reason == "HOLD_WINDOW_END"
        assert exit_price == 104.0 # Last close
        assert "14:00:00" in exit_ts # 5th candle (10, 11, 12, 13, 14)


class TestAlertOutcome:
    """Tests for AlertOutcome dataclass."""
    
    def test_create_outcome(self):
        """Test creating an alert outcome."""
        outcome = AlertOutcome(
            alert_id=1,
            symbol="AAPL",
            timeframe="1h",
            direction="LONG",
            setup="MEAN_REVERSION_BB_RECLAIM",
            score=85,
            entry_price=150.0,
            entry_ts="2024-01-15T10:00:00",
            exit_price=155.0,
            exit_ts="2024-01-16T10:00:00",
            exit_reason="HOLD_WINDOW_END",
            pnl_dollars=3.33,
            pnl_percent=3.33,
            hold_hours=24,
        )
        
        assert outcome.symbol == "AAPL"
        assert outcome.pnl_dollars == 3.33
        assert outcome.hold_hours == 24


class TestRunWeeklyAudit:
    """Tests for run_weekly_audit function with mocked dependencies."""
    
    @pytest.fixture
    def mock_state(self):
        """Create mock state store."""
        state = Mock()
        state.get_recent_alerts_log.return_value = []
        state.get_gate_decisions.return_value = []
        state.record_paper_pnl = Mock()
        return state
    
    @patch('src.reporting.weekly_audit.SqliteStateStore')
    def test_empty_audit(self, mock_store_class):
        """Test audit with no alerts."""
        mock_store = Mock()
        mock_store.get_recent_alerts_log.return_value = []
        mock_store.get_gate_decisions.return_value = []
        mock_store.get_manual_decisions.return_value = []
        mock_store_class.return_value = mock_store
        
        config = WeeklyAuditConfig(state_db=":memory:")
        result = run_weekly_audit(config, verbose=False)
        
        assert result.total_alerts == 0
        assert result.alerts_evaluated == 0
        assert result.system_pnl == 0.0
    
    @patch('src.reporting.weekly_audit.SqliteStateStore')
    @patch('src.reporting.weekly_audit._get_exit_price')
    def test_audit_with_alerts(self, mock_get_exit, mock_store_class):
        """Test audit with alerts."""
        # Setup mock
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        
        mock_store = Mock()
        mock_store.get_recent_alerts_log.return_value = [
            {
                "id": 1,
                "symbol": "AAPL",
                "timeframe": "1h",
                "direction": "LONG",
                "setup": "TEST",
                "score": 80,
                "trigger_close": 150.0,
                "ts_utc": (now - timedelta(days=3)).isoformat(),
            }
        ]
        mock_store.get_gate_decisions.return_value = []
        mock_store.get_manual_decisions.return_value = []
        mock_store.record_paper_pnl = Mock()
        mock_store_class.return_value = mock_store
        
        # Mock exit price
        mock_get_exit.return_value = (155.0, now.isoformat(), "HOLD_WINDOW_END")
        
        config = WeeklyAuditConfig(state_db=":memory:")
        result = run_weekly_audit(config, verbose=False)
        
        assert result.total_alerts == 1
        assert result.alerts_evaluated == 1


class TestWinRateCalculation:
    """Tests for win rate calculation."""
    
    def test_all_wins(self):
        """Test win rate with all winning trades."""
        outcomes = [
            AlertOutcome(
                alert_id=i,
                symbol=f"STOCK{i}",
                timeframe="1h",
                direction="LONG",
                setup="TEST",
                score=80,
                entry_price=100.0,
                entry_ts="2024-01-01T10:00:00",
                pnl_dollars=5.0,
                pnl_percent=5.0,
                hold_hours=24,
            )
            for i in range(5)
        ]
        
        wins = sum(1 for o in outcomes if o.pnl_dollars > 0)
        losses = sum(1 for o in outcomes if o.pnl_dollars < 0)
        win_rate = (wins / len(outcomes)) * 100 if outcomes else 0
        
        assert wins == 5
        assert losses == 0
        assert win_rate == 100.0
    
    def test_mixed_results(self):
        """Test win rate with mixed results."""
        outcomes = [
            AlertOutcome(
                alert_id=1, symbol="W1", timeframe="1h", direction="LONG",
                setup="TEST", score=80, entry_price=100.0, entry_ts="2024-01-01",
                pnl_dollars=10.0, pnl_percent=10.0, hold_hours=24,
            ),
            AlertOutcome(
                alert_id=2, symbol="W2", timeframe="1h", direction="LONG",
                setup="TEST", score=80, entry_price=100.0, entry_ts="2024-01-01",
                pnl_dollars=5.0, pnl_percent=5.0, hold_hours=24,
            ),
            AlertOutcome(
                alert_id=3, symbol="L1", timeframe="1h", direction="LONG",
                setup="TEST", score=80, entry_price=100.0, entry_ts="2024-01-01",
                pnl_dollars=-3.0, pnl_percent=-3.0, hold_hours=24,
            ),
            AlertOutcome(
                alert_id=4, symbol="B1", timeframe="1h", direction="LONG",
                setup="TEST", score=80, entry_price=100.0, entry_ts="2024-01-01",
                pnl_dollars=0.0, pnl_percent=0.0, hold_hours=24,  # Breakeven
            ),
        ]
        
        wins = sum(1 for o in outcomes if o.pnl_dollars > 0)
        losses = sum(1 for o in outcomes if o.pnl_dollars < 0)
        breakeven = sum(1 for o in outcomes if o.pnl_dollars == 0)
        win_rate = (wins / len(outcomes)) * 100
        
        assert wins == 2
        assert losses == 1
        assert breakeven == 1
        assert win_rate == 50.0
