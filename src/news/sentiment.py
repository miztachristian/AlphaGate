"""Very small news sentiment scorer.

This is intentionally lightweight (no ML) so it runs anywhere.
You can later swap it for a real sentiment model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Literal, Tuple

from .client import NewsItem


POS_WORDS = {
    "beats",
    "beat",
    "strong",
    "surge",
    "soar",
    "soars",
    "upgrades",
    "upgrade",
    "record",
    "growth",
    "profit",
    "profits",
    "bullish",
    "buy",
    "raises",
    "raise",
    "rebound",
    "partnership",
    "approved",
    "approval",
}

NEG_WORDS = {
    "miss",
    "misses",
    "weak",
    "plunge",
    "plunges",
    "down",
    "downgrade",
    "downgrades",
    "lawsuit",
    "investigation",
    "fraud",
    "bearish",
    "sell",
    "cuts",
    "cut",
    "warning",
    "recall",
    "halt",
    "bankruptcy",
}


SentimentLabel = Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]


def _tokenize(text: str) -> List[str]:
    return [
        t.strip(".,:;!?()[]{}\"'`).-").lower()
        for t in (text or "").split()
        if t.strip()
    ]


def score_text(text: str) -> float:
    tokens = _tokenize(text)
    if not tokens:
        return 0.0

    pos = sum(1 for t in tokens if t in POS_WORDS)
    neg = sum(1 for t in tokens if t in NEG_WORDS)

    # Normalize by length a bit; keep range roughly [-1, +1]
    raw = (pos - neg) / max(len(tokens), 12)
    return max(min(raw, 1.0), -1.0)


def score_news_sentiment(items: Iterable[NewsItem]) -> float:
    scores = []
    for it in items:
        scores.append(score_text(it.title))
        scores.append(score_text(it.description))

    if not scores:
        return 0.0

    return sum(scores) / len(scores)


def classify_sentiment(score: float, pos_threshold: float = 0.05, neg_threshold: float = -0.05) -> SentimentLabel:
    if score >= pos_threshold:
        return "POSITIVE"
    if score <= neg_threshold:
        return "NEGATIVE"
    return "NEUTRAL"
