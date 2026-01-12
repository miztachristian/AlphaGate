"""News fetching + risk labeling.

v3: Now uses Polygon.io News API instead of NewsAPI.org.
Uses the same POLYGON_API_KEY as market data.

Key components:
- PolygonNewsClient: Fetches news from Polygon.io with caching
- NewsRiskResult: Risk labeling output (LOW/MEDIUM/HIGH)
- assess_news_risk: Keyword-based risk labeling (no sentiment scoring)
"""

from .polygon_news_client import (
    PolygonNewsClient,
    NewsItem,
    fetch_ticker_news,
    fetch_company_news,  # Backward compatibility alias
    get_news_client,
)

from .risk_labeler import (
    assess_news_risk,
    NewsRiskResult,
    RiskLevel,
    create_unknown_risk_result,
    get_lookback_hours_for_timeframe,
    DEFAULT_HIGH_RISK_KEYWORDS,
    DEFAULT_MEDIUM_RISK_KEYWORDS,
)

__all__ = [
    # Client
    "PolygonNewsClient",
    "NewsItem",
    "fetch_ticker_news",
    "fetch_company_news",
    "get_news_client",
    # Risk labeling
    "assess_news_risk",
    "NewsRiskResult",
    "RiskLevel",
    "create_unknown_risk_result",
    "get_lookback_hours_for_timeframe",
    "DEFAULT_HIGH_RISK_KEYWORDS",
    "DEFAULT_MEDIUM_RISK_KEYWORDS",
]
