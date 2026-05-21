"""
Fetch 4H data for all symbols in the universe and cache as parquet.
Then run the thorough backtest on 4H timeframe.
"""

import os
import sys
import glob
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.marketdata.stocks import fetch_stock_ohlcv


def main():
    # Get all symbols from existing 1h cache
    cache_dir = "cache/parquet"
    files_1h = sorted(glob.glob(os.path.join(cache_dir, "*_1h.parquet")))
    symbols = [os.path.basename(f).split('_')[0] for f in files_1h]

    print(f"Found {len(symbols)} symbols. Fetching 4H data for each...")
    print(f"Looking back 730 days for sufficient bars (need 300+ for backtest)\n")

    fetched = 0
    skipped = 0
    failed = 0

    for i, symbol in enumerate(symbols):
        out_file = os.path.join(cache_dir, f"{symbol}_4h.parquet")

        # Skip if already cached
        if os.path.exists(out_file):
            skipped += 1
            continue

        print(f"[{i+1}/{len(symbols)}] Fetching {symbol} 4H ...", end=" ", flush=True)

        try:
            df = fetch_stock_ohlcv(symbol, interval="4h", lookback_days=730)
            if df is None or len(df) < 50:
                print(f"SKIP (only {len(df) if df is not None else 0} bars)")
                failed += 1
                continue

            df.to_parquet(out_file)
            print(f"OK ({len(df)} bars)")
            fetched += 1

            # Respect rate limits (5 req/min for free tier)
            time.sleep(0.5)

        except Exception as e:
            print(f"FAIL: {e}")
            failed += 1
            time.sleep(1)

    print(f"\nDone. Fetched: {fetched}, Skipped (cached): {skipped}, Failed: {failed}")
    print(f"4H parquet files are in {cache_dir}/")


if __name__ == "__main__":
    main()
