"""News client.

Primary: NewsAPI.org if `NEWSAPI_KEY` is configured.
Fallback: returns empty list if not configured.

We keep it intentionally simple: fetch recent headlines + descriptions for a ticker/company name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import os
import requests


@dataclass(frozen=True)
class NewsItem:
    title: str
    description: str
    url: str
    published_at: datetime
    source: str


def fetch_company_news(
    query: str,
    lookback_hours: int = 24,
    max_items: int = 10,
) -> List[NewsItem]:
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        return []

    from_dt = datetime.utcnow() - timedelta(hours=lookback_hours)

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": max_items,
        "apiKey": api_key,
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    items: List[NewsItem] = []
    for a in payload.get("articles", [])[:max_items]:
        published = a.get("publishedAt") or ""
        try:
            published_at = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            published_at = datetime.utcnow()

        items.append(
            NewsItem(
                title=a.get("title") or "",
                description=a.get("description") or "",
                url=a.get("url") or "",
                published_at=published_at,
                source=(a.get("source") or {}).get("name") or "",
            )
        )

    return items
