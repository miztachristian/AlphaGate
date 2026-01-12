# Trading App - Copilot Instructions

Python-based trading application analyzing US equities via Polygon.io API. Generates scored long/short signals using technical indicators with regime filtering.

## Project Structure
- `src/` - Main application code
  - `indicators/` - RSI, EMA, MACD, Volume, ATR, Bollinger Bands
  - `strategy/` - Trading strategy engine and rule definitions
  - `marketdata/` - Polygon.io OHLCV fetcher with DuckDB/Parquet caching
  - `news/` - Polygon.io news client + keyword-based risk labeling
  - `state/` - SQLite store for alert deduplication and logging
  - `notify/` - Telegram and email notification system
  - `runner/` - Live monitoring loop
  - `universe/` - Stock universe loader (CSV)
  - `evaluation/` - Outcome logger (MFE/MAE) and reporting
- `tests/` - Unit tests (pytest)
- `data/` - Stock universe CSV files

## Key Features
- Multi-indicator analysis (RSI, EMA, MACD, Volume, ATR, Bollinger Bands)
- Regime detection (trend + volatility)
- Mean reversion strategy with scored signals (0-100)
- OHLCV caching reduces API calls by ~90%
- News risk labeling (HIGH/MEDIUM/LOW keywords)
- Outcome evaluation (MFE/MAE tracking)
- Alert deduplication via SQLite state store

## Entry Points
- `main.py` - Single stock analysis
- `run_live_stocks.py` - Multi-stock live monitoring
- `python -m src.evaluation.outcome_logger` - Evaluate alert outcomes
- `python -m src.evaluation.reporting` - Generate performance reports

## Development Guidelines
- Follow PEP 8 style guide
- Use type hints for all functions
- Document trading logic with clear comments
- Test indicator calculations with known values
- Run `pytest -q` before committing
