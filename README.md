# Stock Trading Strategy Application

A Python-based trading application that analyzes technical indicators and generates high-probability long/short trading signals for stocks based on proven chart patterns.

## Features

- **Multi-Indicator Analysis**: RSI, EMA, MACD, Volume, ATR, Bollinger Bands
- **Strategy Engine**: Combines 2-3 indicators for high-quality trade setups
- **Signal Generation**: Automated long/short alerts based on your strategy rules
- **Multiple Timeframes**: Support for 15m, 1H, 4H, 1D chart intervals
- **Risk Management**: ATR-based stop-loss and take-profit calculations
- **Live Monitoring**: Continuous stock monitoring with news sentiment validation
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
│   ├── indicators/       # Technical indicator calculations (RSI, EMA, MACD, etc.)
│   ├── strategy/         # Trading strategy engine & rules
│   ├── signals/          # Signal generation
│   ├── marketdata/       # Stock data fetching (Polygon.io API)
│   ├── news/             # News fetching & sentiment analysis
│   ├── state/            # SQLite state store for alert deduplication
│   ├── notify/           # Telegram & Email notifiers
│   ├── runner/           # Live monitoring orchestration
│   └── universe/         # Stock universe CSV loader
├── data/                 # Universe CSV and sample data
│   └── universe.csv      # List of stocks to monitor
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
```bash
# Required: Polygon.io API key for market data
POLYGON_API_KEY=your_polygon_api_key

# Optional: For news sentiment validation
NEWSAPI_KEY=your_newsapi_key

# Optional: For Telegram notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional: For Email notifications (in .env file)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email
SMTP_PASS=your_app_password
ALERT_RECIPIENT=recipient@email.com
```

## License

MIT License
