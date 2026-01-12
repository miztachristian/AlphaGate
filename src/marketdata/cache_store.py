"""OHLCV Local Cache Store.

Provides a local cache layer for OHLCV data using DuckDB + Parquet (preferred)
or SQLite as fallback. Dramatically reduces REST API calls by storing historical
bars locally and only fetching incremental updates.

Cache keeps only required history (configurable bars per timeframe) and prunes
old data automatically.
"""

from __future__ import annotations

import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Literal
from threading import Lock

import pandas as pd

logger = logging.getLogger(__name__)


# Default configuration
DEFAULT_KEEP_BARS = {
    "1m": 1000,
    "5m": 800,
    "15m": 600,
    "30m": 500,
    "1h": 500,
    "4h": 400,
    "1d": 365,
}


class CacheStore(ABC):
    """Abstract base class for OHLCV cache storage."""
    
    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached bars for a symbol/timeframe. Returns None if not cached."""
        pass
    
    @abstractmethod
    def upsert_bars(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """Insert or update bars for a symbol/timeframe."""
        pass
    
    @abstractmethod
    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get the most recent timestamp in cache for symbol/timeframe."""
        pass
    
    @abstractmethod
    def prune_old(self, symbol: str, timeframe: str, keep_last_n: int) -> int:
        """Remove old bars, keeping only the most recent N. Returns count removed."""
        pass
    
    @abstractmethod
    def get_bar_count(self, symbol: str, timeframe: str) -> int:
        """Get count of cached bars for symbol/timeframe."""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close any open connections."""
        pass


class DuckDBCacheStore(CacheStore):
    """DuckDB-backed cache store using Parquet files."""
    
    def __init__(
        self,
        db_path: str = "cache/ohlcv_cache.duckdb",
        data_dir: str = "cache/parquet",
    ):
        """
        Initialize DuckDB cache store.
        
        Args:
            db_path: Path to DuckDB database file
            data_dir: Directory for Parquet data files
        """
        try:
            import duckdb
        except ImportError:
            raise ImportError("DuckDB not installed. Run: pip install duckdb")
        
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        
        # Create directories
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = Lock()
        self._conn = duckdb.connect(str(self.db_path))
        
        # Create metadata table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                symbol VARCHAR,
                timeframe VARCHAR,
                bar_count INTEGER,
                oldest_ts TIMESTAMP,
                newest_ts TIMESTAMP,
                updated_at TIMESTAMP,
                PRIMARY KEY (symbol, timeframe)
            )
        """)
        
        logger.info(f"DuckDB cache initialized at {self.db_path}")
    
    def _get_parquet_path(self, symbol: str, timeframe: str) -> Path:
        """Get path to Parquet file for symbol/timeframe."""
        return self.data_dir / f"{symbol.upper()}_{timeframe}.parquet"
    
    def get_bars(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached bars from Parquet file."""
        parquet_path = self._get_parquet_path(symbol, timeframe)
        
        if not parquet_path.exists():
            return None
        
        try:
            with self._lock:
                df = self._conn.execute(
                    f"SELECT * FROM read_parquet('{parquet_path}') ORDER BY timestamp"
                ).fetchdf()
            
            if df.empty:
                return None
            
            # Ensure timestamp is index
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                df = df.set_index('timestamp')
            
            return df
            
        except Exception as e:
            logger.warning(f"Failed to read cache for {symbol}/{timeframe}: {e}")
            return None
    
    def upsert_bars(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """Write bars to Parquet file, merging with existing data."""
        if df.empty:
            return
        
        parquet_path = self._get_parquet_path(symbol, timeframe)
        
        # Prepare dataframe
        df_write = df.copy()
        if df_write.index.name == 'timestamp':
            df_write = df_write.reset_index()
        
        # Ensure timestamp column exists and is UTC
        if 'timestamp' in df_write.columns:
            df_write['timestamp'] = pd.to_datetime(df_write['timestamp'], utc=True)
        
        with self._lock:
            # Read existing data if present
            if parquet_path.exists():
                try:
                    existing = self._conn.execute(
                        f"SELECT * FROM read_parquet('{parquet_path}')"
                    ).fetchdf()
                    existing['timestamp'] = pd.to_datetime(existing['timestamp'], utc=True)
                    
                    # Merge and deduplicate
                    combined = pd.concat([existing, df_write], ignore_index=True)
                    combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                    combined = combined.sort_values('timestamp')
                    df_write = combined
                except Exception as e:
                    logger.warning(f"Failed to read existing cache, overwriting: {e}")
            
            # Write to Parquet
            df_write.to_parquet(parquet_path, index=False, engine='pyarrow')
            
            # Update metadata
            self._conn.execute("""
                INSERT OR REPLACE INTO cache_meta 
                (symbol, timeframe, bar_count, oldest_ts, newest_ts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                symbol.upper(),
                timeframe,
                len(df_write),
                df_write['timestamp'].min(),
                df_write['timestamp'].max(),
                datetime.now(timezone.utc),
            ])
    
    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get most recent timestamp from metadata."""
        with self._lock:
            result = self._conn.execute("""
                SELECT newest_ts FROM cache_meta 
                WHERE symbol = ? AND timeframe = ?
            """, [symbol.upper(), timeframe]).fetchone()
        
        if result and result[0]:
            ts = result[0]
            if isinstance(ts, str):
                ts = pd.to_datetime(ts, utc=True)
            elif ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        return None
    
    def prune_old(self, symbol: str, timeframe: str, keep_last_n: int) -> int:
        """Remove old bars, keeping only most recent N."""
        parquet_path = self._get_parquet_path(symbol, timeframe)
        
        if not parquet_path.exists():
            return 0
        
        with self._lock:
            try:
                df = self._conn.execute(
                    f"SELECT * FROM read_parquet('{parquet_path}') ORDER BY timestamp DESC LIMIT {keep_last_n}"
                ).fetchdf()
                
                if df.empty:
                    return 0
                
                original_count = self._conn.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
                ).fetchone()[0]
                
                # Re-sort ascending and write back
                df = df.sort_values('timestamp')
                df.to_parquet(parquet_path, index=False, engine='pyarrow')
                
                # Update metadata
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                self._conn.execute("""
                    INSERT OR REPLACE INTO cache_meta 
                    (symbol, timeframe, bar_count, oldest_ts, newest_ts, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, [
                    symbol.upper(),
                    timeframe,
                    len(df),
                    df['timestamp'].min(),
                    df['timestamp'].max(),
                    datetime.now(timezone.utc),
                ])
                
                removed = original_count - len(df)
                return max(0, removed)
                
            except Exception as e:
                logger.warning(f"Failed to prune cache for {symbol}/{timeframe}: {e}")
                return 0
    
    def get_bar_count(self, symbol: str, timeframe: str) -> int:
        """Get count of cached bars."""
        with self._lock:
            result = self._conn.execute("""
                SELECT bar_count FROM cache_meta 
                WHERE symbol = ? AND timeframe = ?
            """, [symbol.upper(), timeframe]).fetchone()
        
        return result[0] if result else 0
    
    def close(self) -> None:
        """Close DuckDB connection."""
        with self._lock:
            self._conn.close()


class SQLiteCacheStore(CacheStore):
    """SQLite-backed cache store (fallback)."""
    
    def __init__(self, db_path: str = "cache/ohlcv_cache.sqlite"):
        """
        Initialize SQLite cache store.
        
        Args:
            db_path: Path to SQLite database file
        """
        import sqlite3
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        
        # Create tables
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv_bars (
                symbol TEXT,
                timeframe TEXT,
                timestamp TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf 
            ON ohlcv_bars(symbol, timeframe, timestamp)
        """)
        self._conn.commit()
        
        logger.info(f"SQLite cache initialized at {self.db_path}")
    
    def get_bars(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached bars."""
        with self._lock:
            df = pd.read_sql_query(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM ohlcv_bars
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp
                """,
                self._conn,
                params=[symbol.upper(), timeframe],
            )
        
        if df.empty:
            return None
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.set_index('timestamp')
        return df
    
    def upsert_bars(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """Insert or update bars."""
        if df.empty:
            return
        
        df_write = df.copy()
        if df_write.index.name == 'timestamp':
            df_write = df_write.reset_index()
        
        df_write['timestamp'] = pd.to_datetime(df_write['timestamp'], utc=True)
        df_write['symbol'] = symbol.upper()
        df_write['timeframe'] = timeframe
        
        with self._lock:
            for _, row in df_write.iterrows():
                self._conn.execute("""
                    INSERT OR REPLACE INTO ohlcv_bars 
                    (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    row['symbol'],
                    row['timeframe'],
                    row['timestamp'].isoformat(),
                    row['open'],
                    row['high'],
                    row['low'],
                    row['close'],
                    row['volume'],
                ])
            self._conn.commit()
    
    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get most recent timestamp."""
        with self._lock:
            cursor = self._conn.execute("""
                SELECT MAX(timestamp) FROM ohlcv_bars
                WHERE symbol = ? AND timeframe = ?
            """, [symbol.upper(), timeframe])
            result = cursor.fetchone()
        
        if result and result[0]:
            return pd.to_datetime(result[0], utc=True)
        return None
    
    def prune_old(self, symbol: str, timeframe: str, keep_last_n: int) -> int:
        """Remove old bars."""
        with self._lock:
            # Get timestamps to keep
            cursor = self._conn.execute("""
                SELECT timestamp FROM ohlcv_bars
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, [symbol.upper(), timeframe, keep_last_n])
            keep_timestamps = [row[0] for row in cursor.fetchall()]
            
            if not keep_timestamps:
                return 0
            
            oldest_to_keep = min(keep_timestamps)
            
            cursor = self._conn.execute("""
                DELETE FROM ohlcv_bars
                WHERE symbol = ? AND timeframe = ? AND timestamp < ?
            """, [symbol.upper(), timeframe, oldest_to_keep])
            
            removed = cursor.rowcount
            self._conn.commit()
            
            return removed
    
    def get_bar_count(self, symbol: str, timeframe: str) -> int:
        """Get count of cached bars."""
        with self._lock:
            cursor = self._conn.execute("""
                SELECT COUNT(*) FROM ohlcv_bars
                WHERE symbol = ? AND timeframe = ?
            """, [symbol.upper(), timeframe])
            result = cursor.fetchone()
        
        return result[0] if result else 0
    
    def close(self) -> None:
        """Close SQLite connection."""
        with self._lock:
            self._conn.close()


# Global cache instance
_cache_instance: Optional[CacheStore] = None
_cache_lock = Lock()


def get_cache_store() -> CacheStore:
    """Get the singleton cache store instance."""
    global _cache_instance
    
    with _cache_lock:
        if _cache_instance is None:
            backend = os.getenv("CACHE_BACKEND", "duckdb").lower()
            
            if backend == "duckdb":
                try:
                    cache_path = os.getenv("CACHE_PATH", "cache/ohlcv_cache.duckdb")
                    data_dir = os.getenv("CACHE_DATA_DIR", "cache/parquet")
                    _cache_instance = DuckDBCacheStore(db_path=cache_path, data_dir=data_dir)
                except ImportError:
                    logger.warning("DuckDB not available, falling back to SQLite")
                    cache_path = os.getenv("CACHE_PATH", "cache/ohlcv_cache.sqlite")
                    _cache_instance = SQLiteCacheStore(db_path=cache_path)
            else:
                cache_path = os.getenv("CACHE_PATH", "cache/ohlcv_cache.sqlite")
                _cache_instance = SQLiteCacheStore(db_path=cache_path)
        
        return _cache_instance


def get_keep_bars(timeframe: str) -> int:
    """Get number of bars to keep for a timeframe."""
    env_map = {
        "1h": "CACHE_KEEP_BARS_1H",
        "4h": "CACHE_KEEP_BARS_4H",
        "1d": "CACHE_KEEP_BARS_1D",
    }
    
    env_var = env_map.get(timeframe)
    if env_var:
        value = os.getenv(env_var)
        if value:
            return int(value)
    
    return DEFAULT_KEEP_BARS.get(timeframe, 500)
