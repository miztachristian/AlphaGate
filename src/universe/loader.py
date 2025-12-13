"""Universe loader.

Expected CSV columns:
- ticker (required)
- name (optional)

Example:
    ticker,name
    AAPL,Apple Inc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass(frozen=True)
class UniverseItem:
    ticker: str
    name: Optional[str] = None


def load_universe_csv(path: str) -> List[UniverseItem]:
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        raise ValueError("Universe CSV must contain a 'ticker' column")

    items: List[UniverseItem] = []
    for _, row in df.iterrows():
        ticker = str(row["ticker"]).strip()
        if not ticker:
            continue
        name = None
        if "name" in df.columns and pd.notna(row.get("name")):
            name = str(row.get("name")).strip()
        items.append(UniverseItem(ticker=ticker, name=name or None))

    # De-dup, preserve order
    seen = set()
    unique: List[UniverseItem] = []
    for item in items:
        key = item.ticker.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(UniverseItem(ticker=key, name=item.name))

    return unique

    return unique
