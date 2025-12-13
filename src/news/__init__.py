"""News fetching + sentiment analysis."""

from .client import fetch_company_news
from .sentiment import score_news_sentiment, classify_sentiment

__all__ = ["fetch_company_news", "score_news_sentiment", "classify_sentiment"]
