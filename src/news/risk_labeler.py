"""News risk labeling module.

Provides keyword-based risk labeling (LOW/MEDIUM/HIGH) for news headlines.
Does NOT produce sentiment scores or veto signals - only annotates alerts with risk levels.

v2: Updated to work with Polygon news API response format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Literal, Set, Optional

from .polygon_news_client import NewsItem


# Risk level type
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]


# Default keyword sets (can be overridden via config)
DEFAULT_HIGH_RISK_KEYWORDS: Set[str] = {
    "earnings",
    "guidance", 
    "sec",
    "investigation",
    "lawsuit",
    "fraud",
    "restatement",
    "offering",
    "bankruptcy",
    "delisting",
    "subpoena",
    "indictment",
    "recall",
    "default",
}

DEFAULT_MEDIUM_RISK_KEYWORDS: Set[str] = {
    "downgrade",
    "upgrade",
    "price target",
    "macro",
    "tariff",
    "inflation",
    "rates",
    "acquisition",
    "merger",
    "restructuring",
    "layoffs",
    "strike",
    "shortage",
}


@dataclass
class NewsRiskResult:
    """Result of news risk assessment."""
    risk_level: RiskLevel
    reasons: List[str] = field(default_factory=list)
    matched_high_keywords: List[str] = field(default_factory=list)
    matched_medium_keywords: List[str] = field(default_factory=list)
    news_count: int = 0
    top_headline: Optional[str] = None
    top_headline_source: Optional[str] = None
    top_headline_time: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "reasons": self.reasons,
            "matched_high_keywords": self.matched_high_keywords,
            "matched_medium_keywords": self.matched_medium_keywords,
            "news_count": self.news_count,
            "top_headline": self.top_headline,
            "top_headline_source": self.top_headline_source,
            "top_headline_time": self.top_headline_time,
        }


def _tokenize(text: str) -> List[str]:
    """Tokenize text for keyword matching."""
    return [
        t.strip(".,:;!?()[]{}\"'`).-").lower()
        for t in (text or "").split()
        if t.strip()
    ]


def _find_keywords_in_text(
    text: str, 
    keywords: Set[str]
) -> List[str]:
    """Find which keywords appear in text."""
    text_lower = text.lower() if text else ""
    found = []
    
    for keyword in keywords:
        # Handle multi-word keywords (e.g., "price target")
        if " " in keyword:
            if keyword.lower() in text_lower:
                found.append(keyword)
        else:
            tokens = _tokenize(text)
            if keyword.lower() in tokens:
                found.append(keyword)
    
    return found


def assess_news_risk(
    items: Iterable[NewsItem],
    high_risk_keywords: Optional[Set[str]] = None,
    medium_risk_keywords: Optional[Set[str]] = None,
) -> NewsRiskResult:
    """
    Assess news risk level based on keyword detection in headlines.
    
    This does NOT produce sentiment scores or veto signals.
    It only labels news with risk levels for manual trading decisions.
    
    Args:
        items: NewsItem objects to analyze
        high_risk_keywords: Keywords that indicate HIGH risk
        medium_risk_keywords: Keywords that indicate MEDIUM risk
    
    Returns:
        NewsRiskResult with risk level, reasons, and matched keywords
    """
    if high_risk_keywords is None:
        high_risk_keywords = DEFAULT_HIGH_RISK_KEYWORDS
    if medium_risk_keywords is None:
        medium_risk_keywords = DEFAULT_MEDIUM_RISK_KEYWORDS
    
    all_high_matches: Set[str] = set()
    all_medium_matches: Set[str] = set()
    reasons: List[str] = []
    news_count = 0
    
    items_list = list(items)
    news_count = len(items_list)
    
    # Track top headline (most recent)
    top_headline = None
    top_headline_source = None
    top_headline_time = None
    
    for item in items_list:
        # Store first (most recent) headline
        if top_headline is None and item.headline:
            top_headline = item.headline
            top_headline_source = item.source
            if item.published_utc:
                top_headline_time = item.published_utc.strftime("%Y-%m-%d %H:%M UTC")
        
        # Check headline only (not description) - headlines are more reliable
        text = item.headline
        if not text:
            continue
        
        high_found = _find_keywords_in_text(text, high_risk_keywords)
        medium_found = _find_keywords_in_text(text, medium_risk_keywords)
        
        all_high_matches.update(high_found)
        all_medium_matches.update(medium_found)
    
    # Determine risk level
    if all_high_matches:
        risk_level: RiskLevel = "HIGH"
        reasons.append(f"High-risk keywords: {', '.join(sorted(all_high_matches))}")
    elif all_medium_matches:
        risk_level = "MEDIUM"
        reasons.append(f"Medium-risk keywords: {', '.join(sorted(all_medium_matches))}")
    else:
        risk_level = "LOW"
        if news_count > 0:
            reasons.append(f"No risk keywords in {news_count} recent articles")
        else:
            reasons.append("No recent news found")
    
    return NewsRiskResult(
        risk_level=risk_level,
        reasons=reasons,
        matched_high_keywords=sorted(all_high_matches),
        matched_medium_keywords=sorted(all_medium_matches),
        news_count=news_count,
        top_headline=top_headline,
        top_headline_source=top_headline_source,
        top_headline_time=top_headline_time,
    )


def create_unknown_risk_result(reason: str = "news_unavailable") -> NewsRiskResult:
    """
    Create an UNKNOWN risk result for when news fetch fails.
    
    This allows the alert to proceed without news data.
    
    Args:
        reason: Reason for unknown status
    
    Returns:
        NewsRiskResult with UNKNOWN level
    """
    return NewsRiskResult(
        risk_level="UNKNOWN",
        reasons=[reason],
        matched_high_keywords=[],
        matched_medium_keywords=[],
        news_count=0,
    )


def get_lookback_hours_for_timeframe(timeframe: str) -> int:
    """
    Get appropriate news lookback hours for a given timeframe.
    
    Longer timeframes get longer news lookback.
    
    Args:
        timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
    
    Returns:
        Lookback hours for news fetch
    """
    lookback_map = {
        "1m": 6,
        "5m": 6,
        "15m": 12,
        "30m": 12,
        "1h": 24,
        "4h": 48,
        "1d": 72,
    }
    return lookback_map.get(timeframe, 24)
