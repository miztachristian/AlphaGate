"""Stock market data fetcher.

Uses Polygon.io API for stock market data.

Returns a DataFrame with columns: open, high, low, close, volume and a datetime index.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Literal, Optional

import pandas as pd
import requests


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


class PolygonClient:
    """Polygon.io API client for stock market data."""
    
    BASE_URL = "https://api.polygon.io"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Polygon client.
        
        Args:
            api_key: Polygon.io API key. If not provided, reads from POLYGON_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Polygon.io API key required. Set POLYGON_API_KEY environment variable "
                "or pass api_key parameter."
            )
    
    def get_aggregates(
        self,
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str,
        to_date: str,
        limit: int = 50000,
    ) -> pd.DataFrame:
        """
        Fetch aggregate bars from Polygon.io.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            multiplier: Size of the timespan multiplier
            timespan: Size of the time window ('minute', 'hour', 'day', etc.)
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            limit: Max number of results
            
        Returns:
            DataFrame with OHLCV data
        """
        url = (
            f"{self.BASE_URL}/v2/aggs/ticker/{ticker.upper()}/range/"
            f"{multiplier}/{timespan}/{from_date}/{to_date}"
        )
        
        params = {
            "apiKey": self.api_key,
            "adjusted": "true",
            "sort": "asc",
            "limit": limit,
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Polygon returns "OK" for real-time, "DELAYED" for free tier
        if data.get("status") not in ("OK", "DELAYED") or "results" not in data:
            error_msg = data.get("error", data.get("message", "Unknown error"))
            if data.get("resultsCount", 0) == 0:
                return pd.DataFrame()  # No data for this period
            raise ValueError(f"Polygon API error: {error_msg}")
        
        results = data["results"]
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        
        # Polygon returns: o, h, l, c, v, vw, t, n
        # t = timestamp in milliseconds
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms")
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
        
        return df


def fetch_stock_ohlcv(
    ticker: str,
    interval: Interval = "1h",
    lookback_days: int = 60,
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch stock OHLCV data from Polygon.io.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        interval: Candle interval ('1m', '5m', '15m', '30m', '1h', '4h', '1d')
        lookback_days: Number of days of historical data
        api_key: Polygon.io API key (optional, uses env var if not provided)
        
    Returns:
        DataFrame with columns: open, high, low, close, volume
        Index: datetime timestamp
    """
    if interval not in POLYGON_TIMESPAN_MAP:
        raise ValueError(f"Invalid interval '{interval}'. Must be one of: {list(POLYGON_TIMESPAN_MAP.keys())}")
    
    multiplier, timespan = POLYGON_TIMESPAN_MAP[interval]
    
    # Calculate date range
    to_date = datetime.now()
    from_date = to_date - timedelta(days=lookback_days)
    
    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")
    
    client = PolygonClient(api_key=api_key)
    
    df = client.get_aggregates(
        ticker=ticker,
        multiplier=int(multiplier),
        timespan=timespan,
        from_date=from_str,
        to_date=to_str,
    )
    
    if df.empty:
        print(f"Warning: No data returned for {ticker}")
        return pd.DataFrame()
    
    # Ensure proper dtypes
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = df.dropna()
    
    return df


def get_last_quote(ticker: str, api_key: Optional[str] = None) -> dict:
    """
    Get the last quote for a stock.
    
    Args:
        ticker: Stock ticker symbol
        api_key: Polygon.io API key
        
    Returns:
        Dict with bid, ask, last price info
    """
    api_key = api_key or os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("POLYGON_API_KEY required")
    
    url = f"https://api.polygon.io/v2/last/trade/{ticker.upper()}"
    params = {"apiKey": api_key}
    
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

