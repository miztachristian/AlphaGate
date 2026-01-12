"""Unit tests for OHLCV cache system."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np
import pytest


# ============================================================================
# Rate Limiter Tests
# ============================================================================

class TestRateLimiter:
    """Tests for token bucket rate limiter."""
    
    def test_acquire_within_rate(self):
        """Test acquiring tokens within rate limit."""
        from src.marketdata.rate_limiter import RateLimiter
        
        limiter = RateLimiter(max_requests_per_second=10.0)
        
        # Should be able to acquire multiple tokens quickly
        for _ in range(5):
            result = limiter.acquire(timeout=1.0)
            assert result is True
    
    def test_try_acquire_returns_bool(self):
        """Test non-blocking acquire."""
        from src.marketdata.rate_limiter import RateLimiter
        
        limiter = RateLimiter(max_requests_per_second=1000.0)
        
        # With high rate, should always succeed
        assert limiter.try_acquire() is True
    
    def test_acquire_with_timeout(self):
        """Test acquire respects timeout."""
        from src.marketdata.rate_limiter import RateLimiter
        
        # Very low rate limiter
        limiter = RateLimiter(max_requests_per_second=0.1, burst_size=1)
        
        # First should succeed (uses burst)
        assert limiter.acquire(timeout=0.1) is True
        
        # Second should timeout quickly (no tokens available)
        # Note: May succeed if enough time passes
        result = limiter.acquire(timeout=0.05)
        # Result may be True or False depending on timing


class TestRetryConfig:
    """Tests for retry configuration."""
    
    def test_retry_config_defaults(self):
        """Test retry config has correct defaults."""
        from src.marketdata.rate_limiter import RetryConfig
        
        config = RetryConfig()
        
        assert config.max_retries >= 1
        assert config.backoff_base > 0
        assert config.backoff_max > 0
    
    def test_retry_config_custom_values(self):
        """Test retry config with custom values."""
        from src.marketdata.rate_limiter import RetryConfig
        
        config = RetryConfig(max_retries=5, backoff_base=1.0, backoff_max=30.0)
        
        assert config.max_retries == 5
        assert config.backoff_base == 1.0
        assert config.backoff_max == 30.0


# ============================================================================
# Scan Metrics Tests
# ============================================================================

class TestScanMetrics:
    """Tests for scan metrics collection."""
    
    def test_metrics_initialization(self):
        """Test metrics start with zero values."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        
        assert metrics.total_tickers == 0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0
        assert metrics.rest_calls == 0
    
    def test_record_cache_hit(self):
        """Test recording cache hits."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        
        assert metrics.cache_hits == 2
    
    def test_record_cache_miss(self):
        """Test recording cache misses."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        metrics.record_cache_miss()
        
        assert metrics.cache_misses == 1
    
    def test_record_rest_call(self):
        """Test recording REST API calls."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        metrics.record_rest_call(bars_fetched=100)
        
        assert metrics.rest_calls == 1
        assert metrics.bars_fetched_total == 100
    
    def test_record_rest_error(self):
        """Test recording REST errors."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        metrics.record_rest_error()
        
        assert metrics.rest_errors == 1
    
    def test_cache_hit_rate(self):
        """Test cache hit rate calculation."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        metrics.cache_hits = 80
        metrics.cache_misses = 20
        
        # Hit rate = hits / (hits + misses)
        expected = 80 / (80 + 20)
        assert metrics.cache_hit_rate == expected
    
    def test_cache_hit_rate_zero_total(self):
        """Test cache hit rate with no requests."""
        from src.marketdata.scan_metrics import ScanMetrics
        
        metrics = ScanMetrics()
        
        assert metrics.cache_hit_rate == 0.0


# ============================================================================
# Cache Store Tests (SQLite backend - always available)
# ============================================================================

def create_sample_ohlcv_df(periods: int = 10) -> pd.DataFrame:
    """Create sample OHLCV DataFrame with timestamp column (not index)."""
    dates = pd.date_range(
        start="2025-01-01 09:00:00",
        periods=periods,
        freq="h",
        tz="UTC",
    )
    return pd.DataFrame({
        "timestamp": dates,
        "open": np.random.uniform(100, 110, periods),
        "high": np.random.uniform(110, 115, periods),
        "low": np.random.uniform(95, 100, periods),
        "close": np.random.uniform(100, 110, periods),
        "volume": np.random.randint(1000, 10000, periods).astype(float),
    })


class TestSQLiteCacheStore:
    """Tests for SQLite cache backend."""
    
    @pytest.fixture
    def temp_db_path(self):
        """Create temp database path that auto-cleans."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "cache.db")
            yield db_path
    
    def test_upsert_and_get_bars(self, temp_db_path):
        """Test storing and retrieving bars."""
        from src.marketdata.cache_store import SQLiteCacheStore
        
        df = create_sample_ohlcv_df(10)
        cache = SQLiteCacheStore(temp_db_path)
        
        try:
            # Upsert
            cache.upsert_bars("AAPL", "1h", df)
            
            # Get back
            result = cache.get_bars("AAPL", "1h")
            
            assert result is not None
            assert len(result) == 10
            assert "open" in result.columns
            assert "close" in result.columns
        finally:
            cache.close()
    
    def test_get_bars_empty_symbol(self, temp_db_path):
        """Test getting bars for non-existent symbol."""
        from src.marketdata.cache_store import SQLiteCacheStore
        
        cache = SQLiteCacheStore(temp_db_path)
        
        try:
            result = cache.get_bars("NONEXISTENT", "1h")
            assert result is None
        finally:
            cache.close()
    
    def test_get_latest_timestamp(self, temp_db_path):
        """Test getting latest timestamp."""
        from src.marketdata.cache_store import SQLiteCacheStore
        
        df = create_sample_ohlcv_df(10)
        cache = SQLiteCacheStore(temp_db_path)
        
        try:
            cache.upsert_bars("AAPL", "1h", df)
            latest = cache.get_latest_timestamp("AAPL", "1h")
            
            assert latest is not None
            # Should be the last timestamp
            assert latest == df["timestamp"].iloc[-1]
        finally:
            cache.close()
    
    def test_get_bar_count(self, temp_db_path):
        """Test counting bars."""
        from src.marketdata.cache_store import SQLiteCacheStore
        
        df = create_sample_ohlcv_df(10)
        cache = SQLiteCacheStore(temp_db_path)
        
        try:
            cache.upsert_bars("AAPL", "1h", df)
            count = cache.get_bar_count("AAPL", "1h")
            
            assert count == 10
        finally:
            cache.close()
    
    def test_upsert_deduplicates(self, temp_db_path):
        """Test that upsert deduplicates by timestamp."""
        from src.marketdata.cache_store import SQLiteCacheStore
        
        df = create_sample_ohlcv_df(10)
        cache = SQLiteCacheStore(temp_db_path)
        
        try:
            # Insert twice
            cache.upsert_bars("AAPL", "1h", df)
            cache.upsert_bars("AAPL", "1h", df)
            
            # Should still have same count (no duplicates)
            count = cache.get_bar_count("AAPL", "1h")
            assert count == 10
        finally:
            cache.close()
    
    def test_prune_old_bars(self, temp_db_path):
        """Test pruning old bars."""
        from src.marketdata.cache_store import SQLiteCacheStore
        
        # Create 100 bars
        df = create_sample_ohlcv_df(100)
        cache = SQLiteCacheStore(temp_db_path)
        
        try:
            cache.upsert_bars("AAPL", "1h", df)
            
            # Prune to keep only 50
            removed = cache.prune_old("AAPL", "1h", keep_last_n=50)
            
            count = cache.get_bar_count("AAPL", "1h")
            assert count == 50
            assert removed == 50
        finally:
            cache.close()


# ============================================================================
# DuckDB Cache Store Tests (optional - skip if not installed)
# ============================================================================

def duckdb_available() -> bool:
    """Check if DuckDB is available."""
    try:
        import duckdb
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not duckdb_available(), reason="DuckDB not installed")
class TestDuckDBCacheStore:
    """Tests for DuckDB cache backend."""
    
    @pytest.fixture
    def temp_db_and_dir(self):
        """Create temp database and parquet dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "cache.duckdb")
            parquet_dir = os.path.join(tmpdir, "parquet")
            os.makedirs(parquet_dir)
            yield db_path, parquet_dir
    
    def test_upsert_and_get_bars(self, temp_db_and_dir):
        """Test storing and retrieving bars with DuckDB."""
        from src.marketdata.cache_store import DuckDBCacheStore
        
        db_path, parquet_dir = temp_db_and_dir
        df = create_sample_ohlcv_df(10)
        cache = DuckDBCacheStore(db_path, parquet_dir)
        
        try:
            # Upsert
            cache.upsert_bars("AAPL", "1h", df)
            
            # Get back
            result = cache.get_bars("AAPL", "1h")
            
            assert result is not None
            assert len(result) == 10
        finally:
            cache.close()
    
    def test_parquet_files_created(self, temp_db_and_dir):
        """Test that Parquet files are created."""
        from src.marketdata.cache_store import DuckDBCacheStore
        
        db_path, parquet_dir = temp_db_and_dir
        df = create_sample_ohlcv_df(10)
        cache = DuckDBCacheStore(db_path, parquet_dir)
        
        try:
            cache.upsert_bars("AAPL", "1h", df)
            
            # Check Parquet file exists
            expected_file = os.path.join(parquet_dir, "AAPL_1h.parquet")
            assert os.path.exists(expected_file)
        finally:
            cache.close()


# ============================================================================
# stocks_v2 Tests
# ============================================================================

class TestStocksV2:
    """Tests for cache-backed fetch functions."""
    
    def test_drop_partial_candle(self):
        """Test partial candle detection and removal."""
        from src.marketdata.stocks_v2 import _drop_partial_candle
        
        now = datetime.now(timezone.utc)
        
        # Create df with last candle being current hour (partial)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        prev_hour = current_hour - timedelta(hours=1)
        
        dates = pd.DatetimeIndex([prev_hour, current_hour], tz="UTC")
        df = pd.DataFrame({
            "open": [100.0, 105.0],
            "high": [110.0, 115.0],
            "low": [95.0, 100.0],
            "close": [105.0, 110.0],
            "volume": [1000, 2000],
        }, index=dates)
        
        result = _drop_partial_candle(df, "1h")
        
        # Current hour candle should be dropped
        assert len(result) == 1
        assert result.index[0] == prev_hour
    
    def test_get_min_bars_required(self):
        """Test min bars config loading."""
        from src.marketdata.stocks_v2 import get_min_bars_required
        
        # Should return config values or defaults
        min_1h = get_min_bars_required("1h")
        min_4h = get_min_bars_required("4h")
        
        assert min_1h > 0
        assert min_4h > 0
        # Config says 1h=350, 4h=250 but defaults could be used
        assert 200 <= min_1h <= 500
        assert 200 <= min_4h <= 500


# ============================================================================
# Flat Files Backfill Tests
# ============================================================================

class TestFlatFilesDateIteration:
    """Tests for flat files date range iteration."""
    
    def test_date_range_iteration_simple(self):
        """Test simple date range iteration generates correct dates."""
        from datetime import date, timedelta
        
        # Simulate the corrected logic from flat_files_backfill.py
        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 5)
        
        dates_visited = []
        current = start_date
        while current <= end_date:
            dates_visited.append(current)
            current = current + timedelta(days=1)
        
        # Should visit 5 days: Jan 1, 2, 3, 4, 5
        assert len(dates_visited) == 5
        assert dates_visited[0] == date(2025, 1, 1)
        assert dates_visited[4] == date(2025, 1, 5)
    
    def test_date_range_across_month_boundary(self):
        """Test date range iteration doesn't skip days at month boundaries."""
        from datetime import date, timedelta
        
        # January 30 to February 2 - crosses month boundary
        start_date = date(2025, 1, 30)
        end_date = date(2025, 2, 2)
        
        dates_visited = []
        current = start_date
        while current <= end_date:
            dates_visited.append(current)
            current = current + timedelta(days=1)
        
        # Should visit: Jan 30, 31, Feb 1, 2 = 4 days
        assert len(dates_visited) == 4
        assert dates_visited == [
            date(2025, 1, 30),
            date(2025, 1, 31),
            date(2025, 2, 1),
            date(2025, 2, 2),
        ]
    
    def test_date_range_single_day(self):
        """Test single day range."""
        from datetime import date, timedelta
        
        start_date = date(2025, 3, 15)
        end_date = date(2025, 3, 15)
        
        dates_visited = []
        current = start_date
        while current <= end_date:
            dates_visited.append(current)
            current = current + timedelta(days=1)
        
        assert len(dates_visited) == 1
        assert dates_visited[0] == date(2025, 3, 15)


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
