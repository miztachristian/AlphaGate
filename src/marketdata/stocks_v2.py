"""Stock market data fetcher with local cache.

v2: Implements cache-first, REST-incremental fetching for dramatically
reduced API calls and faster scanning.

Flow:
1. Check local cache for existing bars
2. If sufficient cached data exists, fetch only incremental updates
3. Merge new bars with cache, deduplicate, prune old data
4. Run data quality gate on result
5. Return cleaned DataFrame
"""

from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import yaml

from .cache_store import get_cache_store, get_keep_bars, CacheStore
from .rate_limiter import RateLimiter, RetryConfig, should_retry
from .scan_metrics import get_current_metrics

logger = logging.getLogger(__name__)


Interval = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

# Polygon.io timespan mapping
POLYGON_TIMESPAN_MAP = {
    "1m": ("1", "minute"),
    "5m": ("5", "minute"),
    "15m": ("15", "minute"),
    "30m": ("30", "minute"),
    "1h": ("1", "hour"),
    "4h": ("4", "hour"),
    "1d": ("1", "day"),
}

# Interval to timedelta mapping
INTERVAL_TIMEDELTA = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


# Config cache (loaded once)
_config_cache: Optional[dict] = None


def _load_config() -> dict:
    """Load config.yaml once and cache it."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                _config_cache = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config.yaml: {e}")
            _config_cache = {}
    else:
        _config_cache = {}
    
    return _config_cache


def get_min_bars_required(interval: Interval) -> int:
    """Get minimum bars required for an interval from config.yaml."""
    config = _load_config()
    min_bars_config = config.get("data_quality", {}).get("min_bars", {})
    
    # Config defaults
    defaults = {"1m": 300, "5m": 250, "15m": 220, "30m": 220, "1h": 350, "4h": 250, "1d": 200}
    
    return min_bars_config.get(interval, defaults.get(interval, 220))


def get_use_adjusted() -> bool:
    """Get use_adjusted setting from config.yaml."""
    config = _load_config()
    return config.get("data_quality", {}).get("use_adjusted", False)


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        max_rps = float(os.getenv("MAX_REQUESTS_PER_SECOND", "10"))
        _rate_limiter = RateLimiter(max_requests_per_second=max_rps)
    return _rate_limiter


def get_retry_config() -> RetryConfig:
    """Get retry configuration from environment."""
    return RetryConfig(
        max_retries=int(os.getenv("RETRY_MAX", "5")),
        backoff_base=float(os.getenv("RETRY_BACKOFF_BASE", "0.5")),
    )


class PolygonClient:
    """Polygon.io API client for stock market data."""
    
    BASE_URL = "https://api.polygon.io"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Polygon client.
        
        Args:
            api_key: Polygon.io API key. If not provided, reads from env vars.
        """
        self.api_key = api_key or os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
        self.base_url = os.getenv("REST_BASE_URL", self.BASE_URL)
        
        if not self.api_key:
            raise ValueError(
                "Polygon.io API key required. Set POLYGON_API_KEY or MASSIVE_API_KEY "
                "environment variable."
            )
    
    def get_aggregates(
        self,
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str,
        to_date: str,
        limit: int = 50000,
        adjusted: bool = False,
    ) -> Tuple[pd.DataFrame, int]:
        """
        Fetch aggregate bars from Polygon.io with retry and rate limiting.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            multiplier: Size of the timespan multiplier
            timespan: Size of the time window ('minute', 'hour', 'day', etc.)
            from_date: Start date (YYYY-MM-DD or ISO timestamp)
            to_date: End date (YYYY-MM-DD or ISO timestamp)
            limit: Max number of results
            adjusted: Whether to use adjusted prices (default: False for intraday)
            
        Returns:
            Tuple of (DataFrame with OHLCV data, number of bars fetched)
        """
        url = (
            f"{self.base_url}/v2/aggs/ticker/{ticker.upper()}/range/"
            f"{multiplier}/{timespan}/{from_date}/{to_date}"
        )
        
        params = {
            "apiKey": self.api_key,
            "adjusted": "true" if adjusted else "false",
            "sort": "asc",
            "limit": limit,
        }
        
        rate_limiter = get_rate_limiter()
        retry_config = get_retry_config()
        metrics = get_current_metrics()
        
        for attempt in range(retry_config.max_retries + 1):
            try:
                # Rate limit
                rate_limiter.acquire(timeout=30)
                
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 429:
                    # Rate limited
                    if metrics:
                        metrics.record_rest_retry()
                    delay = retry_config.get_delay(attempt)
                    logger.warning(f"Rate limited for {ticker}, waiting {delay:.1f}s")
                    time.sleep(delay)
                    continue
                
                if should_retry(response.status_code, retry_config) and attempt < retry_config.max_retries:
                    if metrics:
                        metrics.record_rest_retry()
                    delay = retry_config.get_delay(attempt)
                    logger.warning(f"HTTP {response.status_code} for {ticker}, retry in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                # Record successful call
                if metrics:
                    metrics.record_rest_call()
                
                # Check response status
                if data.get("status") not in ("OK", "DELAYED"):
                    if data.get("resultsCount", 0) == 0:
                        return pd.DataFrame(), 0
                    error_msg = data.get("error", data.get("message", "Unknown error"))
                    raise ValueError(f"Polygon API error: {error_msg}")
                
                results = data.get("results", [])
                if not results:
                    return pd.DataFrame(), 0
                
                df = pd.DataFrame(results)
                
                # Polygon returns: o, h, l, c, v, vw, t, n
                # t = timestamp in milliseconds
                df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True)
                df = df.rename(columns={
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "v": "volume",
                })
                
                df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                df = df.set_index("timestamp")
                df.index.name = "timestamp"
                
                # Update metrics with bars fetched
                if metrics:
                    metrics.bars_fetched_total += len(df)
                
                return df, len(df)
                
            except requests.exceptions.Timeout:
                if metrics:
                    metrics.record_rest_retry()
                if attempt < retry_config.max_retries:
                    delay = retry_config.get_delay(attempt)
                    logger.warning(f"Timeout for {ticker}, retry in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise
            
            except requests.exceptions.HTTPError as e:
                # HTTP errors (4xx, 5xx) - don't retry client errors (4xx)
                if metrics:
                    metrics.record_rest_error()
                if e.response is not None and e.response.status_code >= 500:
                    # Server error - retry
                    if attempt < retry_config.max_retries:
                        delay = retry_config.get_delay(attempt)
                        logger.warning(f"Server error for {ticker}: {e}, retry in {delay:.1f}s")
                        time.sleep(delay)
                        continue
                # Client error (4xx) or max retries exceeded - raise immediately
                raise
                
            except requests.exceptions.RequestException as e:
                # Network errors (timeout, connection, etc.) - retry
                if metrics:
                    metrics.record_rest_error()
                if attempt < retry_config.max_retries:
                    delay = retry_config.get_delay(attempt)
                    logger.warning(f"Request error for {ticker}: {e}, retry in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise
        
        # Should not reach here
        if metrics:
            metrics.record_rest_error()
        return pd.DataFrame(), 0


def _drop_partial_candle(df: pd.DataFrame, interval: Interval) -> pd.DataFrame:
    """Drop the last candle if it's likely incomplete (partial)."""
    if df.empty:
        return df
    
    now = datetime.now(timezone.utc)
    interval_td = INTERVAL_TIMEDELTA.get(interval, timedelta(hours=1))
    
    last_ts = df.index[-1]
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    
    # If last candle started within the interval duration, it's partial
    candle_age = now - last_ts
    if candle_age < interval_td:
        return df.iloc[:-1]
    
    return df


def fetch_stock_ohlcv(
    ticker: str,
    interval: Interval = "1h",
    lookback_days: int = 60,
    api_key: Optional[str] = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch stock OHLCV data with cache-first, REST-incremental logic.
    
    Dramatically reduces API calls by:
    1. Checking local cache for existing bars
    2. Fetching only incremental updates via REST
    3. Merging, deduplicating, and pruning cache
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        interval: Candle interval ('1m', '5m', '15m', '30m', '1h', '4h', '1d')
        lookback_days: Number of days of historical data (for cache miss)
        api_key: Polygon.io API key (optional, uses env var if not provided)
        use_cache: Whether to use local cache (default: True)
        
    Returns:
        DataFrame with columns: open, high, low, close, volume
        Index: datetime timestamp (UTC)
    """
    if interval not in POLYGON_TIMESPAN_MAP:
        raise ValueError(f"Invalid interval '{interval}'. Must be one of: {list(POLYGON_TIMESPAN_MAP.keys())}")
    
    metrics = get_current_metrics()
    cache = get_cache_store() if use_cache else None
    min_bars = get_min_bars_required(interval)
    keep_bars = get_keep_bars(interval)
    use_adjusted = get_use_adjusted()
    
    multiplier, timespan = POLYGON_TIMESPAN_MAP[interval]
    client = PolygonClient(api_key=api_key)
    
    # Check cache
    cached_df = None
    latest_cached_ts = None
    
    if cache:
        cached_df = cache.get_bars(ticker, interval)
        if cached_df is not None and len(cached_df) >= min_bars:
            latest_cached_ts = cache.get_latest_timestamp(ticker, interval)
            if metrics:
                metrics.record_cache_hit()
        else:
            if metrics:
                metrics.record_cache_miss()
            cached_df = None  # Not enough bars, treat as miss
    
    now = datetime.now(timezone.utc)
    interval_td = INTERVAL_TIMEDELTA.get(interval, timedelta(hours=1))
    
    if cached_df is not None and latest_cached_ts is not None:
        # CACHE HIT: Fetch only incremental bars
        # Start from 2 intervals before last cached timestamp (overlap buffer)
        fetch_start = latest_cached_ts - (interval_td * 2)
        fetch_start_str = fetch_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Use date format for end date - works better when market is closed
        fetch_end_str = now.strftime("%Y-%m-%d")
        
        logger.debug(f"{ticker}: Cache hit, fetching incremental from {fetch_start_str}")
        
        try:
            new_df, bars_fetched = client.get_aggregates(
                ticker=ticker,
                multiplier=int(multiplier),
                timespan=timespan,
                from_date=fetch_start_str,
                to_date=fetch_end_str,
                adjusted=use_adjusted,
            )
            
            if not new_df.empty:
                # Merge with cached data
                combined = pd.concat([cached_df, new_df])
                combined = combined[~combined.index.duplicated(keep='last')]
                combined = combined.sort_index()
                df = combined
            else:
                df = cached_df
        except requests.exceptions.HTTPError as e:
            # If incremental fetch fails (e.g., market closed, no new data),
            # gracefully fall back to cached data
            if e.response is not None and e.response.status_code == 400:
                logger.debug(f"{ticker}: No new data available (market may be closed), using cache")
                df = cached_df
            else:
                raise
    else:
        # CACHE MISS: Fetch full history needed for warmup
        # Request slightly more bars than needed
        bars_to_fetch = int(keep_bars * 1.1)
        
        # Calculate date range
        fetch_start = now - timedelta(days=lookback_days)
        fetch_start_str = fetch_start.strftime("%Y-%m-%d")
        fetch_end_str = now.strftime("%Y-%m-%d")
        
        logger.debug(f"{ticker}: Cache miss, fetching {lookback_days} days of history")
        
        df, bars_fetched = client.get_aggregates(
            ticker=ticker,
            multiplier=int(multiplier),
            timespan=timespan,
            from_date=fetch_start_str,
            to_date=fetch_end_str,
            adjusted=use_adjusted,
        )
    
    if df.empty:
        logger.warning(f"No data returned for {ticker}")
        return pd.DataFrame()
    
    # Ensure proper dtypes
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = df.dropna()
    
    # Drop partial (incomplete) last candle
    df = _drop_partial_candle(df, interval)
    
    # Save to cache and prune
    if cache and not df.empty:
        cache.upsert_bars(ticker, interval, df)
        cache.prune_old(ticker, interval, keep_bars)
    
    return df


def fetch_stock_ohlcv_batch(
    tickers: list[str],
    interval: Interval = "1h",
    lookback_days: int = 60,
    max_workers: Optional[int] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for multiple tickers in parallel.
    
    Uses thread pool for concurrent fetching with rate limiting.
    
    Args:
        tickers: List of ticker symbols
        interval: Candle interval
        lookback_days: Days of history for cache miss
        max_workers: Max concurrent workers (default from env)
    
    Returns:
        Dict mapping ticker -> DataFrame
    """
    if max_workers is None:
        max_workers = int(os.getenv("MAX_WORKERS", "32"))
    
    results = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_stock_ohlcv,
                ticker=ticker,
                interval=interval,
                lookback_days=lookback_days,
            ): ticker
            for ticker in tickers
        }
        
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                df = future.result()
                results[ticker] = df
            except Exception as e:
                logger.error(f"Failed to fetch {ticker}: {e}")
                results[ticker] = pd.DataFrame()
    
    return results


def get_last_quote(ticker: str, api_key: Optional[str] = None) -> dict:
    """
    Get the last quote for a stock.
    
    Args:
        ticker: Stock ticker symbol
        api_key: Polygon.io API key
        
    Returns:
        Dict with bid, ask, last price info
    """
    api_key = api_key or os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("API key required")
    
    base_url = os.getenv("REST_BASE_URL", "https://api.polygon.io")
    url = f"{base_url}/v2/last/trade/{ticker.upper()}"
    params = {"apiKey": api_key}
    
    rate_limiter = get_rate_limiter()
    rate_limiter.acquire(timeout=30)
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    
    data = response.json()
    
    if data.get("status") != "OK":
        raise ValueError(f"Failed to get quote: {data}")
    
    result = data.get("results", {})
    return {
        "ticker": ticker.upper(),
        "price": result.get("p"),
        "size": result.get("s"),
        "timestamp": result.get("t"),
    }
