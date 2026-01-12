"""Massive Flat Files (S3) Backfill Tool.

OPTIONAL utility for bulk-loading historical OHLCV data from Massive's
S3-compatible flat files endpoint into the local cache.

This is NOT part of the live scanning loop - it's a separate CLI tool
for research, calibration, and backtesting.

IMPORTANT:
- Flat Files are NOT real-time; do not rely on them for today's candles
- S3 credentials are separate from REST API key
- Never print or log secret keys

Usage:
    python -m src.marketdata.flat_files_backfill --check
    python -m src.marketdata.flat_files_backfill --dataset stocks_minute --start 2025-01-01 --end 2025-01-31
    python -m src.marketdata.flat_files_backfill --dataset stocks_day --start 2025-01-01 --end 2025-01-31 --symbols AAPL,MSFT
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import logging
import sys
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional, List, Iterator, Tuple
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BackfillConfig:
    """Configuration for flat files backfill."""
    
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    bucket: str
    prefix: str = ""
    
    @classmethod
    def from_env(cls) -> Optional["BackfillConfig"]:
        """Load configuration from environment variables."""
        access_key = os.getenv("MASSIVE_S3_ACCESS_KEY_ID")
        secret_key = os.getenv("MASSIVE_S3_SECRET_ACCESS_KEY")
        endpoint = os.getenv("MASSIVE_S3_ENDPOINT_URL", "https://files.massive.com")
        bucket = os.getenv("MASSIVE_S3_BUCKET", "flatfiles")
        prefix = os.getenv("MASSIVE_S3_PREFIX", "")
        
        if not access_key or not secret_key:
            return None
        
        return cls(
            access_key_id=access_key,
            secret_access_key=secret_key,
            endpoint_url=endpoint,
            bucket=bucket,
            prefix=prefix,
        )


class FlatFilesClient:
    """S3-compatible client for Massive Flat Files."""
    
    def __init__(self, config: BackfillConfig):
        """
        Initialize Flat Files client.
        
        Args:
            config: BackfillConfig with S3 credentials
        """
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError:
            raise ImportError("boto3 required for flat files. Run: pip install boto3")
        
        self.config = config
        
        # Create S3 client with signature v4
        self._session = boto3.Session(
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
        )
        
        self._client = self._session.client(
            "s3",
            endpoint_url=config.endpoint_url,
            config=BotoConfig(signature_version="s3v4"),
        )
        
        logger.info(f"Flat Files client initialized (endpoint: {config.endpoint_url})")
    
    def check_connectivity(self) -> Tuple[bool, str]:
        """
        Check S3 connectivity by listing bucket contents.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            response = self._client.list_objects_v2(
                Bucket=self.config.bucket,
                Prefix=self.config.prefix,
                MaxKeys=10,
            )
            
            count = response.get("KeyCount", 0)
            objects = response.get("Contents", [])
            
            if objects:
                sample_keys = [obj["Key"][:50] + "..." for obj in objects[:3]]
                return True, f"Connected. Found {count}+ objects. Sample: {sample_keys}"
            else:
                return True, f"Connected. Bucket appears empty or prefix not found."
                
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def list_available_datasets(self) -> List[str]:
        """List available dataset prefixes in the bucket."""
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            
            datasets = set()
            for page in paginator.paginate(
                Bucket=self.config.bucket,
                Prefix=self.config.prefix,
                Delimiter="/",
            ):
                for prefix in page.get("CommonPrefixes", []):
                    datasets.add(prefix["Prefix"].rstrip("/"))
            
            return sorted(datasets)
            
        except Exception as e:
            logger.error(f"Failed to list datasets: {e}")
            return []
    
    def list_files_for_date_range(
        self,
        dataset: str,
        start_date: date,
        end_date: date,
    ) -> Iterator[str]:
        """
        List S3 keys for files in a date range.
        
        Args:
            dataset: Dataset type (e.g., "us_stocks_sip/minute_aggs_v1")
            start_date: Start date
            end_date: End date
            
        Yields:
            S3 object keys
        """
        from datetime import timedelta
        
        paginator = self._client.get_paginator("list_objects_v2")
        
        # Iterate through dates day by day
        current = start_date
        while current <= end_date:
            # Common prefix patterns
            prefixes_to_try = [
                f"{dataset}/{current.year}/{current.month:02d}/{current.strftime('%Y-%m-%d')}",
                f"{dataset}/{current.strftime('%Y-%m-%d')}",
                f"{dataset}/{current.year}/{current.strftime('%Y-%m-%d')}",
            ]
            
            for prefix in prefixes_to_try:
                try:
                    for page in paginator.paginate(
                        Bucket=self.config.bucket,
                        Prefix=prefix,
                    ):
                        for obj in page.get("Contents", []):
                            yield obj["Key"]
                except Exception as e:
                    logger.debug(f"Prefix {prefix} not found: {e}")
            
            # Correct day-by-day increment
            current = current + timedelta(days=1)
    
    def download_and_parse_file(
        self,
        key: str,
        symbol_filter: Optional[set] = None,
    ) -> pd.DataFrame:
        """
        Download and parse a flat file (streaming decompression).
        
        Args:
            key: S3 object key
            symbol_filter: Optional set of symbols to filter (None = all)
            
        Returns:
            DataFrame with OHLCV data
        """
        try:
            response = self._client.get_object(
                Bucket=self.config.bucket,
                Key=key,
            )
            
            body = response["Body"]
            
            # Check if gzipped
            is_gzipped = key.endswith(".gz") or key.endswith(".gzip")
            
            if is_gzipped:
                # Stream decompress
                with gzip.GzipFile(fileobj=body) as gz:
                    content = gz.read().decode("utf-8")
            else:
                content = body.read().decode("utf-8")
            
            # Parse CSV
            df = pd.read_csv(io.StringIO(content))
            
            # Standardize column names
            column_map = {
                "ticker": "symbol",
                "sym": "symbol",
                "symbol": "symbol",
                "o": "open",
                "open": "open",
                "h": "high",
                "high": "high",
                "l": "low",
                "low": "low",
                "c": "close",
                "close": "close",
                "v": "volume",
                "volume": "volume",
                "vol": "volume",
                "t": "timestamp",
                "timestamp": "timestamp",
                "window_start": "timestamp",
            }
            
            df = df.rename(columns={
                k: v for k, v in column_map.items() if k in df.columns
            })
            
            # Filter by symbols if specified
            if symbol_filter and "symbol" in df.columns:
                df = df[df["symbol"].str.upper().isin(symbol_filter)]
            
            # Parse timestamp
            if "timestamp" in df.columns:
                # Try different formats
                try:
                    # Milliseconds
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                except:
                    try:
                        # Nanoseconds
                        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ns", utc=True)
                    except:
                        # ISO format
                        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            
            # Keep only required columns
            required_cols = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
            available_cols = [c for c in required_cols if c in df.columns]
            df = df[available_cols]
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to parse {key}: {e}")
            return pd.DataFrame()


def run_backfill(
    dataset: str,
    start_date: date,
    end_date: date,
    symbols: Optional[List[str]] = None,
    dry_run: bool = False,
) -> None:
    """
    Run backfill from flat files to local cache.
    
    Args:
        dataset: Dataset type (e.g., "us_stocks_sip/minute_aggs_v1")
        start_date: Start date
        end_date: End date
        symbols: Optional list of symbols to filter
        dry_run: If True, only list files without downloading
    """
    config = BackfillConfig.from_env()
    if not config:
        print("ERROR: S3 credentials not configured.")
        print("Set MASSIVE_S3_ACCESS_KEY_ID and MASSIVE_S3_SECRET_ACCESS_KEY")
        sys.exit(1)
    
    client = FlatFilesClient(config)
    
    # Check connectivity
    success, msg = client.check_connectivity()
    print(f"Connectivity: {msg}")
    if not success:
        sys.exit(1)
    
    # Prepare symbol filter
    symbol_filter = set(s.upper() for s in symbols) if symbols else None
    
    print(f"\nBackfill Configuration:")
    print(f"  Dataset: {dataset}")
    print(f"  Date Range: {start_date} to {end_date}")
    print(f"  Symbols: {symbol_filter or 'ALL'}")
    print(f"  Dry Run: {dry_run}")
    print()
    
    # Get cache store
    if not dry_run:
        from .cache_store import get_cache_store
        cache = get_cache_store()
    
    # Process files
    files_processed = 0
    rows_total = 0
    
    for key in client.list_files_for_date_range(dataset, start_date, end_date):
        print(f"Processing: {key}")
        
        if dry_run:
            files_processed += 1
            continue
        
        df = client.download_and_parse_file(key, symbol_filter)
        
        if df.empty:
            continue
        
        files_processed += 1
        rows_total += len(df)
        
        # Group by symbol and write to cache
        if "symbol" in df.columns:
            for symbol, group_df in df.groupby("symbol"):
                # Determine timeframe from data
                if len(group_df) > 1:
                    time_diff = (group_df["timestamp"].iloc[1] - group_df["timestamp"].iloc[0]).total_seconds()
                    if time_diff <= 60:
                        timeframe = "1m"
                    elif time_diff <= 300:
                        timeframe = "5m"
                    elif time_diff <= 900:
                        timeframe = "15m"
                    elif time_diff <= 3600:
                        timeframe = "1h"
                    elif time_diff <= 14400:
                        timeframe = "4h"
                    else:
                        timeframe = "1d"
                else:
                    timeframe = "1d"  # Default for single row
                
                # Prepare for cache
                ohlcv_df = group_df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
                ohlcv_df = ohlcv_df.set_index("timestamp")
                
                cache.upsert_bars(symbol, timeframe, ohlcv_df)
        
        print(f"  Loaded {len(df)} rows")
    
    print(f"\nBackfill Complete:")
    print(f"  Files Processed: {files_processed}")
    print(f"  Total Rows: {rows_total:,}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Massive Flat Files Backfill Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Check S3 connectivity
    python -m src.marketdata.flat_files_backfill --check
    
    # List available datasets
    python -m src.marketdata.flat_files_backfill --list-datasets
    
    # Backfill minute data for January 2025
    python -m src.marketdata.flat_files_backfill \\
        --dataset us_stocks_sip/minute_aggs_v1 \\
        --start 2025-01-01 \\
        --end 2025-01-31
    
    # Backfill specific symbols only
    python -m src.marketdata.flat_files_backfill \\
        --dataset us_stocks_sip/minute_aggs_v1 \\
        --start 2025-01-01 \\
        --end 2025-01-31 \\
        --symbols AAPL,MSFT,TSLA
    
    # Dry run (list files without downloading)
    python -m src.marketdata.flat_files_backfill \\
        --dataset us_stocks_sip/day_aggs_v1 \\
        --start 2025-01-01 \\
        --end 2025-01-31 \\
        --dry-run
        """,
    )
    
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check S3 connectivity and exit",
    )
    
    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="List available datasets and exit",
    )
    
    parser.add_argument(
        "--dataset",
        type=str,
        help="Dataset path (e.g., us_stocks_sip/minute_aggs_v1)",
    )
    
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD)",
    )
    
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD)",
    )
    
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated list of symbols to filter",
    )
    
    parser.add_argument(
        "--symbols-file",
        type=str,
        help="Path to file with symbols (one per line or CSV with 'ticker' column)",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without downloading",
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    # Load dotenv
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Check mode
    if args.check:
        config = BackfillConfig.from_env()
        if not config:
            print("ERROR: S3 credentials not configured.")
            print("Required environment variables:")
            print("  MASSIVE_S3_ACCESS_KEY_ID")
            print("  MASSIVE_S3_SECRET_ACCESS_KEY")
            print("  MASSIVE_S3_ENDPOINT_URL (optional, default: https://files.massive.com)")
            print("  MASSIVE_S3_BUCKET (optional, default: flatfiles)")
            sys.exit(1)
        
        client = FlatFilesClient(config)
        success, msg = client.check_connectivity()
        print(f"Connectivity: {msg}")
        sys.exit(0 if success else 1)
    
    # List datasets mode
    if args.list_datasets:
        config = BackfillConfig.from_env()
        if not config:
            print("ERROR: S3 credentials not configured.")
            sys.exit(1)
        
        client = FlatFilesClient(config)
        datasets = client.list_available_datasets()
        
        print("Available Datasets:")
        for ds in datasets:
            print(f"  {ds}")
        
        sys.exit(0)
    
    # Backfill mode
    if not args.dataset:
        parser.error("--dataset required for backfill")
    if not args.start:
        parser.error("--start required for backfill")
    if not args.end:
        parser.error("--end required for backfill")
    
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    
    # Load symbols
    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    elif args.symbols_file:
        symbols_path = Path(args.symbols_file)
        if symbols_path.suffix == ".csv":
            df = pd.read_csv(symbols_path)
            if "ticker" in df.columns:
                symbols = df["ticker"].tolist()
            else:
                symbols = df.iloc[:, 0].tolist()
        else:
            symbols = symbols_path.read_text().strip().split("\n")
    
    run_backfill(
        dataset=args.dataset,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
