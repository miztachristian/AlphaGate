# Stock Trading Strategy Application

A Python-based trading application that analyzes technical indicators and generates high-probability long/short trading signals for stocks based on proven chart patterns.

## Features

- **Multi-Indicator Analysis**: RSI, EMA, MACD, Volume, ATR, Bollinger Bands
- **Strategy Engine**: Combines 2-3 indicators for high-quality trade setups
- **Signal Generation**: Automated long/short alerts based on your strategy rules
- **Multiple Timeframes**: Support for 15m, 1H, 4H, 1D chart intervals
- **Risk Management**: ATR-based stop-loss and take-profit calculations
- **OHLCV Cache System**: DuckDB/Parquet caching with REST-incremental updates
- **News Risk Labeling**: Polygon.io news integration with keyword-based risk flags
- **Regime Detection**: Volatility (PANIC/NORMAL/DEAD) and trend (UPTREND/DOWNTREND/NEUTRAL) classification
- **Mean Reversion Setups**: Bollinger Band reclaim strategy with RSI confirmation
- **Outcome Evaluation**: MFE/MAE analysis and hit rate tracking for signal calibration
- **Live Monitoring**: Continuous stock monitoring with alert deduplication
- **Notifications**: Telegram and Email alerts for trading signals

## Strategy Logic

The app implements sophisticated trading patterns:

- **RSI Extremes**: Overbought (>70) and oversold (<30) reversals
- **EMA Trend Following**: 50/200 EMA crossovers with pullback entries
- **MACD Momentum**: Signal line crossovers for momentum shifts
- **Volume Confirmation**: High-volume breakouts vs low-volume fakeouts
- **Bollinger Band Extremes**: Volatility squeezes and mean reversion
- **Divergence Detection**: Price vs RSI divergence for reversals

## Installation

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Single Stock Analysis
```bash
# Analyze a stock
python main.py --symbol AAPL --timeframe 1h --days 60

# Get live signals for a single stock
python main.py --symbol TSLA --timeframe 1h --live
```

### Multi-Stock Live Monitoring
```bash
# Monitor multiple stocks from universe CSV
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60
```

## Project Structure

```
trade-app/
├── src/
│   ├── indicators/       # Technical indicators (RSI, EMA, MACD, ATR, Bollinger, Volume)
│   ├── strategy/         # Trading strategy engine & rule definitions
│   ├── marketdata/       # OHLCV fetching (Polygon.io) + cache system (DuckDB/SQLite)
│   ├── news/             # News API + risk labeling (HIGH/MEDIUM/LOW keywords)
│   ├── state/            # SQLite state store for alert deduplication
│   ├── notify/           # Telegram & Email notifiers
│   ├── runner/           # Live monitoring orchestration
│   ├── universe/         # Stock universe CSV loader
│   └── evaluation/       # Outcome analysis (MFE/MAE, hit rates, reports)
├── data/                 # Universe CSV files
├── reports/              # Generated outcome analysis reports
├── main.py               # Single stock analysis CLI
├── run_live_stocks.py    # Multi-stock live monitor CLI
├── config.yaml           # Configuration file
└── requirements.txt      # Python dependencies
```

## Configuration

Edit `config.yaml` to customize:
- Indicator parameters (RSI periods, EMA lengths, etc.)
- Risk management rules (stop-loss, take-profit multipliers)
- Signal requirements (min conditions needed)
- Alert preferences

### Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your API keys and credentials
```

> **⚠️ SECURITY WARNING:**  
> **Never commit `.env` to version control or include it in ZIP files.**  
> Use environment variables or a secrets manager in production.  
> The `.env` file contains sensitive credentials (API keys, passwords, tokens).

Required variables:
- `POLYGON_API_KEY` - Polygon.io API key for market data and news

Optional variables:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` - For Telegram alerts
- `SMTP_*` - For email alerts
- `MASSIVE_S3_*` - For S3 flat files backfill

## License

MIT License
