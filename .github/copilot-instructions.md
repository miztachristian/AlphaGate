# Trading App - Copilot Instructions

This is a Python-based trading application that analyzes technical indicators and generates long/short trading signals.

## Project Structure
- `src/` - Main application code
  - `indicators/` - Technical indicator calculations (RSI, EMA, MACD, Volume, ATR, Bollinger Bands)
  - `strategy/` - Trading strategy engine and rule definitions
  - `signals/` - Signal generation and alert system
- `tests/` - Unit tests
- `data/` - Sample market data for testing

## Key Features
- Multi-indicator analysis (RSI, EMA, MACD, Volume, ATR, Bollinger Bands)
- Strategy rules combining multiple indicators for high-probability setups
- Long/short signal generation
- Support for multiple timeframes (1H, 4H, etc.)

## Development Guidelines
- Follow Python best practices and PEP 8 style guide
- Use type hints for better code clarity
- Document trading logic clearly with comments
- Test indicator calculations with known values
