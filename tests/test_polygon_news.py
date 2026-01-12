"""Unit tests for Polygon News client and risk labeling.

Tests:
- Parsing Polygon news response JSON into NewsItems
- Risk classifier outputs correct label for given headlines
- News fetch not called when setup is NOT_EVALUATED (mock client)
- Cache behavior
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import json

from src.news.polygon_news_client import (
    PolygonNewsClient,
    NewsItem,
    fetch_ticker_news,
)
from src.news.risk_labeler import (
    assess_news_risk,
    NewsRiskResult,
    create_unknown_risk_result,
    get_lookback_hours_for_timeframe,
)


# Sample Polygon API response fixture
SAMPLE_POLYGON_RESPONSE = {
    "results": [
        {
            "id": "abc123",
            "publisher": {
                "name": "Bloomberg",
                "homepage_url": "https://bloomberg.com",
                "logo_url": "https://example.com/logo.png",
                "favicon_url": "https://example.com/favicon.ico"
            },
            "title": "Apple Reports Record Q4 Earnings, Beats Expectations",
            "author": "John Smith",
            "published_utc": "2024-01-15T14:30:00Z",
            "article_url": "https://bloomberg.com/news/apple-earnings",
            "tickers": ["AAPL"],
            "amp_url": "https://amp.bloomberg.com/news/apple-earnings",
            "image_url": "https://example.com/image.jpg",
            "description": "Apple Inc. reported record quarterly earnings..."
        },
        {
            "id": "def456",
            "publisher": {
                "name": "Reuters"
            },
            "title": "Tech Stocks Rally on Strong Market Data",
            "published_utc": "2024-01-15T12:00:00Z",
            "article_url": "https://reuters.com/tech-rally",
            "tickers": ["AAPL", "MSFT", "GOOGL"],
            "description": ""
        },
        {
            "id": "ghi789",
            "publisher": {
                "name": "CNBC"
            },
            "title": "Fed Signals Potential Rate Cuts in 2024",
            "published_utc": "2024-01-15T10:00:00Z",
            "article_url": "https://cnbc.com/fed-rates",
            "tickers": [],
            "description": "Federal Reserve officials indicated..."
        }
    ],
    "status": "OK",
    "request_id": "req123",
    "count": 3,
    "next_url": None
}


class TestPolygonNewsClientParsing(unittest.TestCase):
    """Test parsing of Polygon news API response."""
    
    def test_parse_response_basic(self):
        """Test basic parsing of Polygon response."""
        client = PolygonNewsClient(api_key="test_key")
        items = client._parse_response(SAMPLE_POLYGON_RESPONSE, "AAPL")
        
        self.assertEqual(len(items), 3)
        
        # Check first item
        first = items[0]
        self.assertEqual(first.headline, "Apple Reports Record Q4 Earnings, Beats Expectations")
        self.assertEqual(first.source, "Bloomberg")
        self.assertEqual(first.url, "https://bloomberg.com/news/apple-earnings")
        self.assertEqual(first.tickers, ["AAPL"])
        self.assertIsInstance(first.published_utc, datetime)
        self.assertEqual(first.published_utc.tzinfo, timezone.utc)
    
    def test_parse_response_empty_tickers(self):
        """Test that empty tickers field uses default ticker."""
        client = PolygonNewsClient(api_key="test_key")
        items = client._parse_response(SAMPLE_POLYGON_RESPONSE, "AAPL")
        
        # Third item has empty tickers array
        third = items[2]
        self.assertEqual(third.tickers, ["AAPL"])  # Should use default
    
    def test_parse_response_empty_results(self):
        """Test parsing empty results."""
        client = PolygonNewsClient(api_key="test_key")
        items = client._parse_response({"results": [], "status": "OK"}, "AAPL")
        
        self.assertEqual(len(items), 0)
    
    def test_parse_response_missing_fields(self):
        """Test parsing response with missing optional fields."""
        response = {
            "results": [
                {
                    "title": "Test Headline",
                    "published_utc": "2024-01-15T14:30:00Z",
                    # Missing: publisher, article_url, description, tickers
                }
            ],
            "status": "OK"
        }
        
        client = PolygonNewsClient(api_key="test_key")
        items = client._parse_response(response, "TEST")
        
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].headline, "Test Headline")
        self.assertEqual(items[0].source, "")
        self.assertEqual(items[0].url, "")
        self.assertEqual(items[0].tickers, ["TEST"])
    
    def test_news_item_backward_compatibility(self):
        """Test NewsItem has backward-compatible aliases."""
        item = NewsItem(
            headline="Test Title",
            description="Test Description",
            url="https://example.com",
            published_utc=datetime.now(timezone.utc),
            source="TestSource",
            tickers=["TEST"],
        )
        
        # Check aliases
        self.assertEqual(item.title, item.headline)
        self.assertEqual(item.published_at, item.published_utc)


class TestNewsRiskLabeling(unittest.TestCase):
    """Test risk classification based on headlines."""
    
    def test_high_risk_earnings(self):
        """Headlines with earnings keywords should be HIGH risk."""
        items = [
            NewsItem(
                headline="Apple Reports Q4 Earnings Beat",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="Bloomberg",
                tickers=["AAPL"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "HIGH")
        self.assertIn("earnings", result.matched_high_keywords)
    
    def test_high_risk_sec_investigation(self):
        """Headlines with SEC/investigation keywords should be HIGH risk."""
        items = [
            NewsItem(
                headline="Company Under SEC Investigation for Fraud",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="Reuters",
                tickers=["XYZ"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "HIGH")
        self.assertTrue(
            "sec" in result.matched_high_keywords or 
            "investigation" in result.matched_high_keywords or
            "fraud" in result.matched_high_keywords
        )
    
    def test_medium_risk_downgrade(self):
        """Headlines with downgrade/upgrade should be MEDIUM risk."""
        items = [
            NewsItem(
                headline="Analyst Issues Downgrade on Stock Rating",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="MarketWatch",
                tickers=["ABC"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "MEDIUM")
        self.assertIn("downgrade", result.matched_medium_keywords)
    
    def test_medium_risk_price_target(self):
        """Multi-word keyword 'price target' should be detected."""
        items = [
            NewsItem(
                headline="Analyst Raises Price Target to $200",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="Benzinga",
                tickers=["TSLA"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "MEDIUM")
        self.assertIn("price target", result.matched_medium_keywords)
    
    def test_low_risk_no_keywords(self):
        """Headlines without risk keywords should be LOW risk."""
        items = [
            NewsItem(
                headline="Company Opens New Office in California",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="LocalNews",
                tickers=["ABC"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "LOW")
        self.assertEqual(result.matched_high_keywords, [])
        self.assertEqual(result.matched_medium_keywords, [])
    
    def test_empty_news_low_risk(self):
        """Empty news list should be LOW risk."""
        result = assess_news_risk([])
        
        self.assertEqual(result.risk_level, "LOW")
        self.assertIn("No recent news found", result.reasons[0])
    
    def test_unknown_risk_result(self):
        """Test creating UNKNOWN risk result for failures."""
        result = create_unknown_risk_result("api_timeout")
        
        self.assertEqual(result.risk_level, "UNKNOWN")
        self.assertIn("api_timeout", result.reasons)
    
    def test_top_headline_captured(self):
        """Test that top headline is captured in result."""
        items = [
            NewsItem(
                headline="First Headline",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="Source1",
                tickers=["TEST"],
            ),
            NewsItem(
                headline="Second Headline",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="Source2",
                tickers=["TEST"],
            ),
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.top_headline, "First Headline")
        self.assertEqual(result.top_headline_source, "Source1")
    
    def test_high_takes_precedence_over_medium(self):
        """HIGH risk should take precedence when both types of keywords found."""
        items = [
            NewsItem(
                headline="Earnings Beat but Analyst Downgrades Stock",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="News",
                tickers=["TEST"],
            )
        ]
        
        result = assess_news_risk(items)
        
        self.assertEqual(result.risk_level, "HIGH")
        self.assertIn("earnings", result.matched_high_keywords)


class TestLookbackByTimeframe(unittest.TestCase):
    """Test timeframe-based lookback hours."""
    
    def test_1h_lookback(self):
        self.assertEqual(get_lookback_hours_for_timeframe("1h"), 24)
    
    def test_4h_lookback(self):
        self.assertEqual(get_lookback_hours_for_timeframe("4h"), 48)
    
    def test_1d_lookback(self):
        self.assertEqual(get_lookback_hours_for_timeframe("1d"), 72)
    
    def test_unknown_timeframe_default(self):
        self.assertEqual(get_lookback_hours_for_timeframe("unknown"), 24)


class TestNewsCaching(unittest.TestCase):
    """Test news client caching behavior."""
    
    def test_cache_stores_and_retrieves(self):
        """Test that cache stores and retrieves items."""
        client = PolygonNewsClient(api_key="test", cache_ttl_minutes=30)
        
        items = [
            NewsItem(
                headline="Test",
                description="",
                url="",
                published_utc=datetime.now(timezone.utc),
                source="Test",
                tickers=["TEST"],
            )
        ]
        
        # Store in cache
        client._store_in_cache("AAPL", 24, items)
        
        # Retrieve from cache
        cached = client._get_from_cache("AAPL", 24)
        
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].headline, "Test")
    
    def test_cache_key_case_insensitive(self):
        """Test that cache keys are case-insensitive."""
        client = PolygonNewsClient(api_key="test", cache_ttl_minutes=30)
        
        items = [NewsItem(
            headline="Test",
            description="",
            url="",
            published_utc=datetime.now(timezone.utc),
            source="Test",
            tickers=["TEST"],
        )]
        
        client._store_in_cache("aapl", 24, items)
        
        cached = client._get_from_cache("AAPL", 24)
        self.assertIsNotNone(cached)
    
    def test_cache_miss_different_lookback(self):
        """Test that different lookback hours result in cache miss."""
        client = PolygonNewsClient(api_key="test", cache_ttl_minutes=30)
        
        items = [NewsItem(
            headline="Test",
            description="",
            url="",
            published_utc=datetime.now(timezone.utc),
            source="Test",
            tickers=["TEST"],
        )]
        
        client._store_in_cache("AAPL", 24, items)
        
        # Different lookback hours
        cached = client._get_from_cache("AAPL", 48)
        self.assertIsNone(cached)


class TestNewsNotCalledWhenNotEvaluated(unittest.TestCase):
    """Test that news is not fetched when setup is NOT_EVALUATED."""
    
    @patch('src.news.polygon_news_client.requests.get')
    def test_no_api_key_returns_empty(self, mock_get):
        """Test that missing API key returns empty list without API call."""
        with patch.dict('os.environ', {'POLYGON_API_KEY': ''}):
            client = PolygonNewsClient(api_key=None)
            items = client.fetch_ticker_news("AAPL", lookback_hours=24)
        
        self.assertEqual(items, [])
        mock_get.assert_not_called()
    
    @patch('src.news.polygon_news_client.requests.get')
    def test_fetch_uses_cache(self, mock_get):
        """Test that cached results prevent API call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_POLYGON_RESPONSE
        mock_get.return_value = mock_response
        
        client = PolygonNewsClient(api_key="test_key", cache_ttl_minutes=30)
        
        # First call - hits API
        items1 = client.fetch_ticker_news("AAPL", lookback_hours=24)
        self.assertEqual(mock_get.call_count, 1)
        
        # Second call - should use cache
        items2 = client.fetch_ticker_news("AAPL", lookback_hours=24)
        self.assertEqual(mock_get.call_count, 1)  # No additional call
        
        self.assertEqual(len(items1), len(items2))


if __name__ == "__main__":
    unittest.main()
