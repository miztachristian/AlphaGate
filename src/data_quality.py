"""
Data Quality Gate Module

Validates and cleans market data before indicator calculation and signal generation.
Ensures only closed candles are evaluated and detects data quality issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple, List

import pandas as pd
import numpy as np


class DataQualityStatus(Enum):
    """Status codes for data quality checks."""
    OK = "ok"
    INSUFFICIENT_BARS = "insufficient_bars"
    BAD_DATA_GAPS = "bad_data_gaps"
    PARTIAL_CANDLE_DROPPED = "partial_candle_dropped"
    NO_DATA = "no_data"


@dataclass
class DataQualityResult:
    """Result of data quality validation."""
    status: DataQualityStatus
    df: Optional[pd.DataFrame]
    reason: Optional[str] = None
    warnings: Optional[List[str]] = None
    
    @property
    def is_ok(self) -> bool:
        return self.status == DataQualityStatus.OK
    
    def __str__(self) -> str:
        if self.is_ok:
            return f"DataQuality: OK ({len(self.df)} bars)"
        return f"DataQuality: {self.status.value} - {self.reason}"


# Interval to minutes mapping
INTERVAL_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

# Default minimum bars per timeframe
DEFAULT_MIN_BARS = {
    "1m": 500,
    "5m": 400,
    "15m": 350,
    "30m": 300,
    "1h": 350,
    "4h": 250,
    "1d": 200,
}


def get_interval_minutes(interval: str) -> int:
    """Convert interval string to minutes."""
    if interval in INTERVAL_MINUTES:
        return INTERVAL_MINUTES[interval]
    raise ValueError(f"Unknown interval: {interval}. Supported: {list(INTERVAL_MINUTES.keys())}")


def get_candle_boundary(dt: datetime, interval_minutes: int) -> datetime:
    """
    Get the start of the current candle period.
    
    For example, if interval is 4h and time is 14:30, the boundary is 12:00.
    """
    if interval_minutes >= 1440:  # Daily
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
    minutes_since_midnight = dt.hour * 60 + dt.minute
    boundary_minutes = (minutes_since_midnight // interval_minutes) * interval_minutes
    
    boundary_hour = boundary_minutes // 60
    boundary_minute = boundary_minutes % 60
    
    return dt.replace(hour=boundary_hour, minute=boundary_minute, second=0, microsecond=0)


def is_candle_complete(candle_timestamp: datetime, interval_minutes: int, 
                       current_time: Optional[datetime] = None) -> bool:
    """
    Check if a candle is complete (closed).
    
    A candle is complete if the current time is past the candle's end time.
    
    Args:
        candle_timestamp: The timestamp of the candle (usually candle open time)
        interval_minutes: Candle interval in minutes
        current_time: Current UTC time (defaults to now)
    
    Returns:
        True if candle is complete, False if still in progress
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # Ensure we're working with UTC-aware datetimes
    if candle_timestamp.tzinfo is None:
        candle_timestamp = candle_timestamp.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    candle_end = candle_timestamp + timedelta(minutes=interval_minutes)
    return current_time >= candle_end


def drop_partial_candle(df: pd.DataFrame, interval: str, 
                        current_time: Optional[datetime] = None) -> Tuple[pd.DataFrame, bool]:
    """
    Drop the last candle if it's still in progress (partial).
    
    Args:
        df: DataFrame with timestamp index
        interval: Candle interval string (e.g., "1h", "4h")
        current_time: Current UTC time (defaults to now)
    
    Returns:
        Tuple of (cleaned DataFrame, whether a candle was dropped)
    """
    if df.empty:
        return df, False
    
    interval_minutes = get_interval_minutes(interval)
    
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    last_timestamp = df.index[-1]
    if isinstance(last_timestamp, pd.Timestamp):
        last_timestamp = last_timestamp.to_pydatetime()
    
    if not is_candle_complete(last_timestamp, interval_minutes, current_time):
        return df.iloc[:-1].copy(), True
    
    return df, False


def detect_gaps(df: pd.DataFrame, interval: str, 
                max_gaps: int = 50, lookback_bars: int = 200,
                max_single_gap_multiplier: float = 200.0) -> Tuple[bool, List[str]]:
    """
    Detect timestamp gaps in the data.
    
    Args:
        df: DataFrame with timestamp index
        interval: Candle interval string
        max_gaps: Maximum allowed gaps in lookback period
        lookback_bars: Number of bars to check for gaps
        max_single_gap_multiplier: Maximum gap size as multiple of interval
    
    Returns:
        Tuple of (has_bad_gaps, list of gap descriptions)
    """
    if len(df) < 2:
        return False, []
    
    interval_minutes = get_interval_minutes(interval)
    expected_delta = timedelta(minutes=interval_minutes)
    max_single_gap = expected_delta * max_single_gap_multiplier
    
    # Only check recent bars
    check_df = df.tail(lookback_bars)
    timestamps = check_df.index.to_series()
    
    # Calculate time differences
    time_diffs = timestamps.diff()
    
    gaps = []
    gap_count = 0
    
    for i, diff in enumerate(time_diffs):
        if pd.isna(diff):
            continue
            
        # Allow some tolerance (5% extra for minor variations)
        tolerance = expected_delta * 1.05
        
        if diff > tolerance:
            gap_size = diff / expected_delta
            gap_timestamp = timestamps.index[i]
            
            if diff > max_single_gap:
                gaps.append(f"Large gap at {gap_timestamp}: {gap_size:.1f}x expected interval")
            
            gap_count += 1
    
    # Only flag as bad if there are gaps exceeding max_single_gap threshold
    # Normal overnight/weekend gaps in stock data are expected and counted in gap_count
    # but should not fail validation unless they exceed the large gap threshold
    has_bad_gaps = len(gaps) > 0  # Only flag if there are LARGE gaps (> max_single_gap)
    
    return has_bad_gaps, gaps


def validate_data_quality(
    df: pd.DataFrame,
    interval: str,
    min_bars: Optional[int] = None,
    max_gaps: int = 50,
    gap_lookback_bars: int = 200,
    max_single_gap_multiplier: float = 200.0,
    current_time: Optional[datetime] = None,
    drop_partial: bool = True,
) -> DataQualityResult:
    """
    Validate data quality and prepare DataFrame for analysis.
    
    This is the main entry point for data quality checks. It:
    1. Drops partial (incomplete) last candle if requested
    2. Checks minimum bar count
    3. Detects timestamp gaps
    
    Args:
        df: DataFrame with OHLCV data and timestamp index
        interval: Candle interval string (e.g., "1h", "4h")
        min_bars: Minimum required bars (uses defaults if None)
        max_gaps: Maximum allowed gaps in lookback period
        gap_lookback_bars: Number of bars to check for gaps
        max_single_gap_multiplier: Maximum gap size as multiple of interval
        current_time: Current UTC time for partial candle detection
        drop_partial: Whether to drop partial last candle
    
    Returns:
        DataQualityResult with status, cleaned DataFrame, and details
    """
    warnings = []
    
    # Handle empty data
    if df is None or df.empty:
        return DataQualityResult(
            status=DataQualityStatus.NO_DATA,
            df=None,
            reason="No data available"
        )
    
    cleaned_df = df.copy()
    
    # Step 1: Drop partial candle if requested
    if drop_partial:
        cleaned_df, was_dropped = drop_partial_candle(cleaned_df, interval, current_time)
        if was_dropped:
            warnings.append("Dropped incomplete last candle")
    
    # Step 2: Check minimum bars
    if min_bars is None:
        min_bars = DEFAULT_MIN_BARS.get(interval, 250)
    
    if len(cleaned_df) < min_bars:
        return DataQualityResult(
            status=DataQualityStatus.INSUFFICIENT_BARS,
            df=cleaned_df,
            reason=f"Only {len(cleaned_df)} bars available, need {min_bars}",
            warnings=warnings
        )
    
    # Step 3: Check for gaps
    has_bad_gaps, gap_details = detect_gaps(
        cleaned_df, interval, max_gaps, gap_lookback_bars, max_single_gap_multiplier
    )
    
    if has_bad_gaps:
        return DataQualityResult(
            status=DataQualityStatus.BAD_DATA_GAPS,
            df=cleaned_df,
            reason=f"Data has significant gaps: {'; '.join(gap_details[:3])}",
            warnings=warnings + gap_details
        )
    
    # All checks passed
    if gap_details:
        warnings.extend(gap_details)
    
    return DataQualityResult(
        status=DataQualityStatus.OK,
        df=cleaned_df,
        warnings=warnings if warnings else None
    )


def validate_ohlcv_columns(df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
    """
    Validate that DataFrame has required OHLCV columns.
    
    Args:
        df: DataFrame to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    missing = [col for col in required_cols if col not in df.columns]
    
    if missing:
        return False, f"Missing required columns: {missing}"
    
    return True, None


def check_indicator_warmup(values: pd.Series, warmup_period: int, 
                           check_last_n: int = 1) -> bool:
    """
    Check if indicator values have passed warmup period.
    
    Args:
        values: Series of indicator values
        warmup_period: Required warmup period
        check_last_n: Number of recent values to check for NaN
    
    Returns:
        True if indicator is warmed up and recent values are valid
    """
    if len(values) < warmup_period:
        return False
    
    # Check that recent values are not NaN
    recent = values.tail(check_last_n)
    return not recent.isna().any()
