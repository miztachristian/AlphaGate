"""
Data Fetcher
Fetches market data from exchanges or loads sample data.
"""

import pandas as pd
import ccxt
from datetime import datetime, timedelta
from typing import Optional
import os
import signal


class TimeoutError(Exception):
    """Custom timeout error."""
    pass


def _timeout_handler(signum, frame):
    raise TimeoutError("Request timed out")


def fetch_market_data(symbol: str = 'BTC/USDT', timeframe: str = '1h',
                     limit: int = 500, exchange: str = 'binance',
                     timeout: int = 10) -> pd.DataFrame:
    """
    Fetch market data from cryptocurrency exchange.
    
    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        limit: Number of candles to fetch
        exchange: Exchange name (default: 'binance')
        timeout: Request timeout in seconds (default: 10)
    
    Returns:
        DataFrame with OHLCV data
    """
    try:
        print(f"   Connecting to {exchange}... (timeout: {timeout}s)")
        
        # Initialize exchange with timeout in milliseconds
        exchange_class = getattr(ccxt, exchange)
        exchange_obj = exchange_class({
            'enableRateLimit': True,
            'timeout': timeout * 1000,  # ccxt uses milliseconds
        })
        
        # Fetch OHLCV data
        ohlcv = exchange_obj.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # Convert to DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        
        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        return df
    
    except Exception as e:
        print(f"Error fetching data from {exchange}: {e}")
        print("Loading sample data instead...")
        return load_sample_data()


def load_sample_data(filepath: str = 'data/sample_btcusdt_1h.csv') -> pd.DataFrame:
    """
    Load sample market data from CSV file.
    
    Args:
        filepath: Path to CSV file
    
    Returns:
        DataFrame with OHLCV data
    """
    if os.path.exists(filepath):
        df = pd.read_csv(filepath, index_col='timestamp', parse_dates=True)
        return df
    else:
        # Generate synthetic data for testing
        print("No sample data found. Generating synthetic data...")
        return generate_synthetic_data()


def generate_synthetic_data(days: int = 30, timeframe: str = '1h') -> pd.DataFrame:
    """
    Generate synthetic OHLCV data for testing.
    
    Args:
        days: Number of days of data to generate
        timeframe: Timeframe ('1h', '4h', etc.)
    
    Returns:
        DataFrame with synthetic OHLCV data
    """
    import numpy as np
    
    # Calculate number of candles
    if timeframe == '1h':
        periods = days * 24
    elif timeframe == '4h':
        periods = days * 6
    elif timeframe == '15m':
        periods = days * 96
    else:
        periods = days * 24  # Default to 1h
    
    # Generate timestamps
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    timestamps = pd.date_range(start=start_time, end=end_time, periods=periods)
    
    # Generate price data with trend and noise
    base_price = 40000  # Starting price (like BTC)
    trend = np.linspace(0, 5000, periods)  # Upward trend
    noise = np.random.normal(0, 500, periods).cumsum()
    
    close_prices = base_price + trend + noise
    
    # Generate OHLC from close
    open_prices = close_prices + np.random.normal(0, 100, periods)
    high_prices = np.maximum(open_prices, close_prices) + np.abs(np.random.normal(0, 150, periods))
    low_prices = np.minimum(open_prices, close_prices) - np.abs(np.random.normal(0, 150, periods))
    
    # Generate volume
    base_volume = 1000
    volume = base_volume + np.abs(np.random.normal(0, 300, periods))
    
    # Create DataFrame
    df = pd.DataFrame({
        'open': open_prices,
        'high': high_prices,
        'low': low_prices,
        'close': close_prices,
        'volume': volume
    }, index=timestamps)
    
    df.index.name = 'timestamp'
    
    return df


def save_data_to_csv(df: pd.DataFrame, filepath: str = 'data/market_data.csv'):
    """
    Save market data to CSV file.
    
    Args:
        df: DataFrame with market data
        filepath: Output file path
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath)
    print(f"Data saved to {filepath}")


def resample_timeframe(df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
    """
    Resample data to different timeframe.
    
    Args:
        df: DataFrame with OHLCV data
        target_timeframe: Target timeframe ('1h', '4h', '1d', etc.)
    
    Returns:
        Resampled DataFrame
    """
    resampled = df.resample(target_timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })
    
    return resampled.dropna()
