"""Market data sources."""

from .stocks import fetch_stock_ohlcv
from .market_status import (
    MarketStatus,
    get_market_status,
    should_scan_market,
    format_market_status_message,
)

# v2 cache-backed imports (optional - use if caching enabled)
try:
    from .stocks_v2 import (
        fetch_stock_ohlcv as fetch_stock_ohlcv_cached,
        fetch_stock_ohlcv_batch,
    )
    from .cache_store import get_cache_store, CacheStore
    from .rate_limiter import RateLimiter, RetryConfig
    from .scan_metrics import (
        ScanMetrics,
        start_scan_metrics,
        get_current_metrics,
        finish_scan_metrics,
    )
    
    CACHE_AVAILABLE = True
except ImportError as e:
    # DuckDB or other optional deps not installed
    CACHE_AVAILABLE = False
    fetch_stock_ohlcv_cached = fetch_stock_ohlcv  # Fallback
    fetch_stock_ohlcv_batch = None
    get_cache_store = None
    CacheStore = None
    RateLimiter = None
    RetryConfig = None
    ScanMetrics = None
    start_scan_metrics = None
    get_current_metrics = None
    finish_scan_metrics = None

__all__ = [
    # Original
    "fetch_stock_ohlcv",
    # v2 cache-backed
    "fetch_stock_ohlcv_cached",
    "fetch_stock_ohlcv_batch",
    "get_cache_store",
    "CacheStore",
    "RateLimiter",
    "RetryConfig",
    "ScanMetrics",
    "start_scan_metrics",
    "get_current_metrics",
    "finish_scan_metrics",
    "CACHE_AVAILABLE",
    # Market status
    "MarketStatus",
    "get_market_status",
    "should_scan_market",
    "format_market_status_message",
]
