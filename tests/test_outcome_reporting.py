"""Tests for outcome reporting module."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.evaluation.reporting import (
    BucketStats,
    RegimeStats,
    compute_bucket_stats,
    compute_regime_stats,
    generate_reports,
    _get_score_bucket,
)


class TestScoreBucket:
    """Test score bucket mapping."""
    
    def test_score_buckets(self):
        assert _get_score_bucket(0) == "0-40"
        assert _get_score_bucket(39) == "0-40"
        assert _get_score_bucket(40) == "40-60"
        assert _get_score_bucket(59) == "40-60"
        assert _get_score_bucket(60) == "60-80"
        assert _get_score_bucket(79) == "60-80"
        assert _get_score_bucket(80) == "80-100"
        assert _get_score_bucket(100) == "80-100"
        assert _get_score_bucket(None) == "N/A"


class TestBucketStats:
    """Test bucket statistics computation."""
    
    def test_compute_bucket_stats_empty(self):
        stats = compute_bucket_stats([])
        assert stats == {}
    
    def test_compute_bucket_stats_single_bucket(self):
        outcomes = [
            {
                "score": 75,
                "forward_returns": {4: 2.0, 12: 5.0},
                "mfe": {4: 3.0, 12: 6.0},
                "mae": {4: -1.0, 12: -2.0},
                "hit": {4: True, 12: True},
            },
            {
                "score": 70,
                "forward_returns": {4: -1.0, 12: 2.0},
                "mfe": {4: 1.0, 12: 3.0},
                "mae": {4: -2.0, 12: -3.0},
                "hit": {4: False, 12: True},
            },
        ]
        
        stats = compute_bucket_stats(outcomes, horizons=[4, 12])
        
        assert "60-80" in stats
        bucket = stats["60-80"]
        assert bucket.count == 2
        
        # Hit rate at horizon 4: 1/2 = 50%
        assert bucket.hit_rate[4] == pytest.approx(50.0, rel=0.01)
        # Hit rate at horizon 12: 2/2 = 100%
        assert bucket.hit_rate[12] == pytest.approx(100.0, rel=0.01)
    
    def test_compute_bucket_stats_multiple_buckets(self):
        outcomes = [
            {"score": 30, "forward_returns": {4: 1.0}, "mfe": {4: 2.0}, "mae": {4: -1.0}, "hit": {4: True}},
            {"score": 50, "forward_returns": {4: 2.0}, "mfe": {4: 3.0}, "mae": {4: -1.5}, "hit": {4: True}},
            {"score": 70, "forward_returns": {4: 3.0}, "mfe": {4: 4.0}, "mae": {4: -0.5}, "hit": {4: True}},
            {"score": 90, "forward_returns": {4: 4.0}, "mfe": {4: 5.0}, "mae": {4: -0.3}, "hit": {4: True}},
        ]
        
        stats = compute_bucket_stats(outcomes, horizons=[4])
        
        assert "0-40" in stats
        assert "40-60" in stats
        assert "60-80" in stats
        assert "80-100" in stats
        
        assert stats["0-40"].count == 1
        assert stats["40-60"].count == 1
        assert stats["60-80"].count == 1
        assert stats["80-100"].count == 1


class TestRegimeStats:
    """Test regime statistics computation."""
    
    def test_compute_regime_stats_empty(self):
        stats = compute_regime_stats([])
        assert stats == []
    
    def test_compute_regime_stats_basic(self):
        outcomes = [
            {"trend_regime": "UPTREND", "vol_regime": "NORMAL", "hit": {24: True}},
            {"trend_regime": "UPTREND", "vol_regime": "NORMAL", "hit": {24: True}},
            {"trend_regime": "UPTREND", "vol_regime": "NORMAL", "hit": {24: False}},
            {"trend_regime": "DOWNTREND", "vol_regime": "PANIC", "hit": {24: False}},
        ]
        
        stats = compute_regime_stats(outcomes, primary_horizon=24)
        
        # Should have 2 regime combinations
        assert len(stats) == 2
        
        # UPTREND/NORMAL should be first (most count)
        uptrend_normal = stats[0]
        assert uptrend_normal.trend_regime == "UPTREND"
        assert uptrend_normal.vol_regime == "NORMAL"
        assert uptrend_normal.count == 3
        # Hit rate: 2/3 = 66.67%
        assert uptrend_normal.hit_rate_primary == pytest.approx(66.67, rel=0.01)
    
    def test_compute_regime_stats_unknown_regime(self):
        outcomes = [
            {"trend_regime": None, "vol_regime": None, "hit": {24: True}},
        ]
        
        stats = compute_regime_stats(outcomes, primary_horizon=24)
        
        assert len(stats) == 1
        assert stats[0].trend_regime == "UNKNOWN"
        assert stats[0].vol_regime == "UNKNOWN"


class TestGenerateReports:
    """Test report generation."""
    
    def test_generate_reports_empty_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            # Create empty outcomes table
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE alert_outcomes (
                    alert_id TEXT PRIMARY KEY,
                    ts_utc TEXT,
                    symbol TEXT,
                    timeframe TEXT,
                    setup TEXT,
                    direction TEXT,
                    score INTEGER,
                    entry_price REAL,
                    atr_at_alert REAL,
                    bar_interval_minutes INTEGER,
                    forward_returns_json TEXT,
                    mfe_json TEXT,
                    mae_json TEXT,
                    hit_json TEXT,
                    evaluation_status TEXT,
                    evaluated_at_utc TEXT,
                    notes TEXT,
                    trend_regime TEXT,
                    vol_regime TEXT
                )
            """)
            conn.commit()
            conn.close()
            
            with tempfile.TemporaryDirectory() as output_dir:
                bucket_csv, regime_csv = generate_reports(
                    db_path=db_path,
                    output_dir=output_dir,
                    verbose=False,
                )
                
                # Should return empty strings for no data
                assert bucket_csv == ""
                assert regime_csv == ""
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_generate_reports_with_data(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE alert_outcomes (
                    alert_id TEXT PRIMARY KEY,
                    ts_utc TEXT,
                    symbol TEXT,
                    timeframe TEXT,
                    setup TEXT,
                    direction TEXT,
                    score INTEGER,
                    entry_price REAL,
                    atr_at_alert REAL,
                    bar_interval_minutes INTEGER,
                    forward_returns_json TEXT,
                    mfe_json TEXT,
                    mae_json TEXT,
                    hit_json TEXT,
                    evaluation_status TEXT,
                    evaluated_at_utc TEXT,
                    notes TEXT,
                    trend_regime TEXT,
                    vol_regime TEXT
                )
            """)
            
            # Insert test outcomes
            for i in range(5):
                conn.execute("""
                    INSERT INTO alert_outcomes (
                        alert_id, ts_utc, symbol, timeframe, setup, direction, score,
                        entry_price, atr_at_alert, bar_interval_minutes,
                        forward_returns_json, mfe_json, mae_json, hit_json,
                        evaluation_status, trend_regime, vol_regime
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"alert_{i}",
                    f"2024-01-{15+i}T10:00:00",
                    "AAPL",
                    "1h",
                    "MEAN_REVERSION",
                    "LONG",
                    60 + i * 10,  # Scores: 60, 70, 80, 90, 100
                    150.0 + i,
                    2.0,
                    60,
                    json.dumps({4: 2.0 + i, 12: 4.0 + i}),
                    json.dumps({4: 3.0 + i, 12: 5.0 + i}),
                    json.dumps({4: -1.0 - i * 0.1, 12: -2.0 - i * 0.1}),
                    json.dumps({4: i % 2 == 0, 12: True}),
                    "COMPLETE",
                    "UPTREND" if i < 3 else "NEUTRAL",
                    "NORMAL",
                ))
            
            conn.commit()
            conn.close()
            
            with tempfile.TemporaryDirectory() as output_dir:
                bucket_csv, regime_csv = generate_reports(
                    db_path=db_path,
                    output_dir=output_dir,
                    verbose=False,
                )
                
                # Should have created CSV files
                assert bucket_csv != ""
                assert regime_csv != ""
                assert Path(bucket_csv).exists()
                assert Path(regime_csv).exists()
                
                # Check bucket CSV content
                import pandas as pd
                bucket_df = pd.read_csv(bucket_csv)
                assert len(bucket_df) > 0
                assert "bucket" in bucket_df.columns
                assert "count" in bucket_df.columns
                
                # Check regime CSV content
                regime_df = pd.read_csv(regime_csv)
                assert len(regime_df) > 0
                assert "trend_regime" in regime_df.columns
                assert "vol_regime" in regime_df.columns
                
        finally:
            Path(db_path).unlink(missing_ok=True)
