"""Fetch all US stock tickers from Polygon.io and save to universe CSV.

Usage:
    python scripts/fetch_us_tickers.py --output data/universe.csv

This fetches all active US stock tickers (common stocks) from Polygon.io.
Requires POLYGON_API_KEY environment variable.
"""

import os
import sys
import argparse
import time
import requests
import csv
from typing import List, Dict


def fetch_all_us_tickers(api_key: str, market: str = "stocks") -> List[Dict]:
    """
    Fetch all US stock tickers from Polygon.io.
    
    Args:
        api_key: Polygon.io API key
        market: Market type (stocks, crypto, fx, otc)
        
    Returns:
        List of ticker dictionaries
    """
    base_url = "https://api.polygon.io/v3/reference/tickers"
    
    all_tickers = []
    next_url = None
    page = 0
    
    while True:
        page += 1
        
        if next_url:
            url = next_url
            params = {"apiKey": api_key}
        else:
            url = base_url
            params = {
                "apiKey": api_key,
                "market": market,
                "active": "true",
                "locale": "us",
                "limit": 1000,
                "order": "asc",
                "sort": "ticker",
            }
        
        print(f"Fetching page {page}... ({len(all_tickers)} tickers so far)")
        
        # Retry logic for rate limits
        for attempt in range(3):
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 429:
                wait_time = 60 * (attempt + 1)
                print(f"   ⚠️  Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            break
        
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") not in ("OK", "DELAYED"):
            print(f"API Error: {data}")
            break
        
        results = data.get("results", [])
        if not results:
            break
        
        # Filter to common stocks only (exclude ETFs, warrants, etc.)
        for ticker in results:
            ticker_type = ticker.get("type", "")
            # CS = Common Stock, ADRC = ADR Common
            if ticker_type in ("CS", "ADRC"):
                all_tickers.append({
                    "ticker": ticker.get("ticker"),
                    "name": ticker.get("name"),
                    "type": ticker_type,
                    "exchange": ticker.get("primary_exchange"),
                    "currency": ticker.get("currency_name"),
                    "market_cap": ticker.get("market_cap"),
                })
        
        # Check for next page
        next_url = data.get("next_url")
        if not next_url:
            break
        
        # Rate limit (free tier: 5 calls/min = 12s between calls)
        time.sleep(13)
    
    return all_tickers


def save_to_csv(tickers: List[Dict], output_path: str) -> None:
    """Save tickers to CSV file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "name", "type", "exchange"])
        
        for t in tickers:
            writer.writerow([
                t["ticker"],
                t["name"],
                t["type"],
                t["exchange"],
            ])
    
    print(f"✅ Saved {len(tickers)} tickers to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Fetch all US stock tickers from Polygon.io")
    parser.add_argument("--output", type=str, default="data/universe.csv", help="Output CSV path")
    parser.add_argument("--include-etfs", action="store_true", help="Include ETFs in output")
    args = parser.parse_args()
    
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("❌ POLYGON_API_KEY environment variable required")
        sys.exit(1)
    
    print("🔄 Fetching all US stock tickers from Polygon.io...")
    print("   This may take a few minutes...\n")
    
    tickers = fetch_all_us_tickers(api_key)
    
    print(f"\n📊 Found {len(tickers)} US common stocks")
    
    # Sort by ticker
    tickers.sort(key=lambda x: x["ticker"])
    
    save_to_csv(tickers, args.output)
    
    # Show some stats
    exchanges = {}
    for t in tickers:
        ex = t.get("exchange", "Unknown")
        exchanges[ex] = exchanges.get(ex, 0) + 1
    
    print("\n📈 Breakdown by exchange:")
    for ex, count in sorted(exchanges.items(), key=lambda x: -x[1])[:10]:
        print(f"   {ex}: {count}")


if __name__ == "__main__":
    main()
