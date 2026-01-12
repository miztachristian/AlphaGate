"""Market status checker using Polygon.io API.

Provides real-time market status information to optimize API usage
by skipping scans during market closed hours.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class MarketStatus:
    """Current market status information."""
    
    market: str  # "open", "closed", "extended-hours"
    nyse: str
    nasdaq: str
    otc: str
    early_hours: bool  # Pre-market
    after_hours: bool  # Post-market
    server_time: str
    
    @property
    def is_open(self) -> bool:
        """Returns True if regular market hours are active."""
        return self.market == "open"
    
    @property
    def is_extended_hours(self) -> bool:
        """Returns True if in pre-market or after-hours session."""
        return self.market == "extended-hours" or self.early_hours or self.after_hours
    
    @property
    def is_closed(self) -> bool:
        """Returns True if market is fully closed."""
        return self.market == "closed" and not self.early_hours and not self.after_hours
    
    @property
    def is_tradeable(self) -> bool:
        """Returns True if market is open OR in extended hours."""
        return self.is_open or self.is_extended_hours
    
    def __str__(self) -> str:
        status = f"Market: {self.market}"
        if self.early_hours:
            status += " (Pre-Market)"
        if self.after_hours:
            status += " (After-Hours)"
        return status


def get_market_status(api_key: Optional[str] = None) -> Optional[MarketStatus]:
    """
    Fetch current market status from Polygon.io.
    
    Args:
        api_key: Polygon.io API key. If not provided, reads from env vars.
    
    Returns:
        MarketStatus object or None if request fails.
    """
    api_key = api_key or os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
    
    if not api_key:
        logger.warning("No API key available for market status check")
        return None
    
    url = f"https://api.polygon.io/v1/marketstatus/now?apiKey={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            logger.warning(f"Market status request failed: {response.status_code}")
            return None
        
        data = response.json()
        
        exchanges = data.get("exchanges", {})
        
        return MarketStatus(
            market=data.get("market", "unknown"),
            nyse=exchanges.get("nyse", "unknown"),
            nasdaq=exchanges.get("nasdaq", "unknown"),
            otc=exchanges.get("otc", "unknown"),
            early_hours=data.get("earlyHours", False),
            after_hours=data.get("afterHours", False),
            server_time=data.get("serverTime", ""),
        )
        
    except requests.RequestException as e:
        logger.warning(f"Market status request error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching market status: {e}")
        return None


def should_scan_market(
    api_key: Optional[str] = None,
    allow_extended_hours: bool = True,
    fallback_on_error: bool = True,
) -> tuple[bool, Optional[MarketStatus]]:
    """
    Determine if we should run a market scan based on current market status.
    
    Args:
        api_key: Polygon.io API key
        allow_extended_hours: If True, allows scanning during pre/post market
        fallback_on_error: If True, returns True when status check fails
    
    Returns:
        Tuple of (should_scan: bool, status: MarketStatus or None)
    """
    status = get_market_status(api_key)
    
    if status is None:
        # API call failed - use fallback behavior
        if fallback_on_error:
            logger.info("Market status unavailable, proceeding with scan (fallback=True)")
            return True, None
        else:
            logger.info("Market status unavailable, skipping scan (fallback=False)")
            return False, None
    
    if status.is_open:
        return True, status
    
    if allow_extended_hours and status.is_extended_hours:
        return True, status
    
    return False, status


def format_market_status_message(status: MarketStatus) -> str:
    """Format a human-readable market status message."""
    lines = [
        f"📊 Market Status: {status.market.upper()}",
        f"   NYSE: {status.nyse}",
        f"   NASDAQ: {status.nasdaq}",
    ]
    
    if status.early_hours:
        lines.append("   📈 Pre-Market Session Active")
    if status.after_hours:
        lines.append("   📉 After-Hours Session Active")
    
    if status.server_time:
        lines.append(f"   🕐 Server Time: {status.server_time}")
    
    return "\n".join(lines)
