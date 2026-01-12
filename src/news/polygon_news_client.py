"""Polygon.io News API client.

Replaces NewsAPI.org with Polygon's news endpoint.
Uses the same POLYGON_API_KEY used for market data.

API Endpoint: GET https://api.polygon.io/v2/reference/news
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from threading import Lock
import time

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsItem:
    """News article item from Polygon API.
    
    Maintains backward compatibility with the old NewsAPI NewsItem structure.
    """
    headline: str
    description: str  # Polygon doesn't always have description, may be empty
    url: str
    published_utc: datetime  # Timezone-aware UTC datetime
    source: str
    tickers: List[str] = field(default_factory=list)
    
    # Aliases for backward compatibility
    @property
    def title(self) -> str:
        """Alias for headline (backward compatibility)."""
        return self.headline
    
    @property
    def published_at(self) -> datetime:
        """Alias for published_utc (backward compatibility)."""
        return self.published_utc


@dataclass
class NewsCacheEntry:
    """Cache entry for news items."""
    items: List[NewsItem]
    fetched_at: datetime
    ttl_minutes: int = 30


class PolygonNewsClient:
    """Polygon.io News API client with caching."""
    
    BASE_URL = "https://api.polygon.io/v2/reference/news"
    DEFAULT_TIMEOUT = 15
    MAX_RETRIES = 2
    RETRY_DELAY = 1.0
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        cache_ttl_minutes: int = 30,
    ):
        """
        Initialize Polygon News client.
        
        Args:
            api_key: Polygon.io API key. If not provided, reads from POLYGON_API_KEY env var.
            cache_ttl_minutes: How long to cache news items (default: 30 minutes)
        """
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        self.cache_ttl_minutes = cache_ttl_minutes
        
        # In-memory cache: {(ticker, lookback_hours): NewsCacheEntry}
        self._cache: Dict[tuple, NewsCacheEntry] = {}
        self._cache_lock = Lock()
    
    def _is_cache_valid(self, entry: NewsCacheEntry) -> bool:
        """Check if cache entry is still valid."""
        age = datetime.now(timezone.utc) - entry.fetched_at
        return age < timedelta(minutes=entry.ttl_minutes)
    
    def _get_from_cache(self, ticker: str, lookback_hours: int) -> Optional[List[NewsItem]]:
        """Get news items from cache if valid."""
        cache_key = (ticker.upper(), lookback_hours)
        
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry and self._is_cache_valid(entry):
                logger.debug(f"Cache hit for {ticker} news")
                return entry.items
        
        return None
    
    def _store_in_cache(self, ticker: str, lookback_hours: int, items: List[NewsItem]) -> None:
        """Store news items in cache."""
        cache_key = (ticker.upper(), lookback_hours)
        
        with self._cache_lock:
            self._cache[cache_key] = NewsCacheEntry(
                items=items,
                fetched_at=datetime.now(timezone.utc),
                ttl_minutes=self.cache_ttl_minutes,
            )
    
    def _clear_expired_cache(self) -> None:
        """Remove expired entries from cache."""
        with self._cache_lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if not self._is_cache_valid(entry)
            ]
            for key in expired_keys:
                del self._cache[key]
    
    def fetch_ticker_news(
        self,
        ticker: str,
        lookback_hours: int = 24,
        limit: int = 20,
        use_cache: bool = True,
    ) -> List[NewsItem]:
        """
        Fetch recent news for a ticker from Polygon.io.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            lookback_hours: How many hours back to fetch news
            limit: Maximum number of articles to fetch
            use_cache: Whether to use cached results if available
        
        Returns:
            List of NewsItem objects, empty list on error
        """
        if not self.api_key:
            logger.warning("POLYGON_API_KEY not configured, skipping news fetch")
            return []
        
        # Check cache first
        if use_cache:
            cached = self._get_from_cache(ticker, lookback_hours)
            if cached is not None:
                return cached
        
        # Calculate date range
        end_utc = datetime.now(timezone.utc)
        start_utc = end_utc - timedelta(hours=lookback_hours)
        
        # Build request
        params = {
            "ticker": ticker.upper(),
            "published_utc.gte": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "published_utc.lte": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": limit,
            "sort": "published_utc",
            "order": "desc",
            "apiKey": self.api_key,
        }
        
        # Make request with retries
        items: List[NewsItem] = []
        
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # Log without API key
                logger.debug(f"Fetching news for {ticker} (attempt {attempt + 1})")
                
                response = requests.get(
                    self.BASE_URL,
                    params=params,
                    timeout=self.DEFAULT_TIMEOUT,
                )
                
                if response.status_code == 429:
                    # Rate limited
                    logger.warning(f"Rate limited on news API, attempt {attempt + 1}")
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * (attempt + 1))
                        continue
                    return []
                
                response.raise_for_status()
                data = response.json()
                
                items = self._parse_response(data, ticker)
                
                # Cache successful response
                if use_cache:
                    self._store_in_cache(ticker, lookback_hours, items)
                
                return items
                
            except requests.exceptions.Timeout:
                logger.warning(f"News API timeout for {ticker}, attempt {attempt + 1}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"News API error for {ticker}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                    
            except Exception as e:
                logger.error(f"Unexpected error fetching news for {ticker}: {e}")
                break
        
        # On failure, return empty list (don't crash the signal engine)
        return []
    
    def _parse_response(self, data: dict, default_ticker: str) -> List[NewsItem]:
        """
        Parse Polygon news API response into NewsItem objects.
        
        Args:
            data: JSON response from Polygon API
            default_ticker: Ticker to use if article doesn't have tickers field
        
        Returns:
            List of NewsItem objects
        """
        items: List[NewsItem] = []
        results = data.get("results", [])
        
        for article in results:
            try:
                # Parse published timestamp
                published_str = article.get("published_utc", "")
                try:
                    # Polygon uses ISO format: "2024-01-15T14:30:00Z"
                    if published_str.endswith("Z"):
                        published_utc = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    else:
                        published_utc = datetime.fromisoformat(published_str)
                        if published_utc.tzinfo is None:
                            published_utc = published_utc.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    published_utc = datetime.now(timezone.utc)
                
                # Extract source/publisher
                publisher = article.get("publisher", {})
                source = publisher.get("name", "") if isinstance(publisher, dict) else str(publisher)
                
                # Extract tickers
                tickers = article.get("tickers", [])
                if not tickers:
                    tickers = [default_ticker.upper()]
                
                item = NewsItem(
                    headline=article.get("title", "") or "",
                    description=article.get("description", "") or "",
                    url=article.get("article_url", "") or article.get("url", "") or "",
                    published_utc=published_utc,
                    source=source,
                    tickers=tickers,
                )
                items.append(item)
                
            except Exception as e:
                logger.warning(f"Failed to parse news article: {e}")
                continue
        
        return items


# Module-level singleton client instance
_client: Optional[PolygonNewsClient] = None
_client_lock = Lock()


def get_news_client(cache_ttl_minutes: int = 30) -> PolygonNewsClient:
    """Get the singleton news client instance."""
    global _client
    
    with _client_lock:
        if _client is None:
            _client = PolygonNewsClient(cache_ttl_minutes=cache_ttl_minutes)
        return _client


def fetch_ticker_news(
    ticker: str,
    lookback_hours: int = 24,
    limit: int = 20,
    use_cache: bool = True,
) -> List[NewsItem]:
    """
    Convenience function to fetch news for a ticker.
    
    Uses the singleton client instance.
    
    Args:
        ticker: Stock ticker symbol
        lookback_hours: How many hours back to fetch
        limit: Max articles to fetch
        use_cache: Whether to use cache
    
    Returns:
        List of NewsItem objects
    """
    client = get_news_client()
    return client.fetch_ticker_news(ticker, lookback_hours, limit, use_cache)


# Backward compatibility alias
def fetch_company_news(
    query: str,
    lookback_hours: int = 24,
    max_items: int = 10,
) -> List[NewsItem]:
    """
    Fetch company news (backward compatibility with old NewsAPI client).
    
    Note: The 'query' parameter is now treated as a ticker symbol.
    For best results, pass the ticker symbol directly.
    
    Args:
        query: Ticker symbol (or company name, but ticker works better with Polygon)
        lookback_hours: How many hours back to fetch
        max_items: Maximum number of articles
    
    Returns:
        List of NewsItem objects
    """
    # Treat query as ticker - Polygon API works better with exact ticker
    return fetch_ticker_news(ticker=query, lookback_hours=lookback_hours, limit=max_items)
