# Getting Started Guide

## 🚀 Quick Start (5 minutes)

### Step 1: Install Dependencies
```bash
# Create virtual environment (if not done)
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure API Key
```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your Polygon.io API key
# POLYGON_API_KEY=your_api_key_here
```

Get your API key from [Polygon.io](https://polygon.io/) - Starter plan ($29/mo) recommended.

### Step 3: Run Your First Analysis
```bash
python main.py --symbol AAPL --timeframe 1h
```

---

## 📦 What's Included

### Core Features
- **Technical Indicators**: RSI, EMA (20/50/200), MACD, ATR, Bollinger Bands, Volume
- **Strategy Engine**: Mean reversion setups with regime filtering
- **Signal Generation**: Scored alerts (0-100) with entry zones
- **Risk Management**: ATR-based stops and targets
- **OHLCV Caching**: DuckDB/Parquet cache reduces API calls by ~90%
- **News Integration**: Polygon.io news with keyword-based risk labeling
- **Outcome Evaluation**: MFE/MAE tracking for signal calibration

### Entry Points
| Command | Description |
|---------|-------------|
| `python main.py` | Single stock analysis |
| `python run_live_stocks.py` | Multi-stock live monitor |
| `python -m src.evaluation.outcome_logger` | Evaluate alert outcomes |
| `python -m src.evaluation.reporting` | Generate performance reports |

---

## 💡 Example Commands

### Single Stock Analysis
```bash
# Analyze Apple on 1-hour chart
python main.py --symbol AAPL --timeframe 1h

# Analyze Tesla on 4-hour chart with more history
python main.py --symbol TSLA --timeframe 4h --days 90

# Analyze NVIDIA on daily chart
python main.py --symbol NVDA --timeframe 1d
```

### Multi-Stock Live Monitoring
```bash
# Monitor stocks from universe file
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60

# With Telegram notifications
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --notify telegram
```

### Outcome Evaluation
```bash
# After alerts have been logged, evaluate outcomes
python -m src.evaluation.outcome_logger --db-path alerts_log.db --lookback-hours 168

# Generate summary reports
python -m src.evaluation.reporting --db-path alerts_log.db --output-dir reports
```

---

## 📖 Understanding the Output

### Signal Score
- **80-100**: HIGH confidence - strong setup
- **60-80**: MEDIUM confidence - valid setup
- **40-60**: LOW confidence - marginal edge
- **0-40**: VERY LOW - skip this trade

### Regimes
- **Trend Regime**: UPTREND / NEUTRAL / DOWNTREND (based on EMA200)
- **Vol Regime**: PANIC / NORMAL / DEAD (based on ATR percentile)

### News Risk
- **HIGH**: Earnings, SEC filings, lawsuits - binary event risk
- **MEDIUM**: Upgrades/downgrades, M&A news
- **LOW**: No significant news

---

## ⚙️ Configuration

### `config.yaml` - Key Settings
```yaml
# Indicator parameters
indicators:
  rsi:
    period: 14
    overbought: 70
    oversold: 30

# Data quality
data_quality:
  min_bars:
    "1h": 350
    "4h": 250
  use_adjusted: false

# Alert settings
alerts:
  cooldown_minutes: 60
  log_alerts: true
```

### `.env` - Environment Variables
```bash
# Required
POLYGON_API_KEY=your_key_here

# Optional - Notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 🧪 Running Tests

```bash
# Run all tests
pytest -q

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_indicators.py
```

---

## 📚 Next Steps

1. **Review the strategy**: See [STRATEGY_GUIDE.md](STRATEGY_GUIDE.md)
2. **Customize settings**: Edit `config.yaml` for your preferences
3. **Set up alerts**: Configure Telegram in `.env` for notifications
4. **Run live monitoring**: Use `run_live_stocks.py` for continuous scanning
5. **Evaluate performance**: Use outcome evaluation after collecting alerts

---

## 🆘 Troubleshooting

### API Key Issues
- Ensure `POLYGON_API_KEY` is set in `.env`
- Check your Polygon.io subscription is active

### No Signals
- Market may be closed (US hours: 9:30 AM - 4:00 PM ET)
- Stock may be in DEAD volatility regime
- Try different timeframe

### Cache Issues
- Cache stored in `cache/` directory
- Delete folder to force refresh
- Check `data_quality.min_bars` settings

---

## 📖 Documentation

- [README.md](README.md) - Project overview
- [STRATEGY_GUIDE.md](STRATEGY_GUIDE.md) - Strategy details
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Command cheat sheet
- [EXAMPLES.md](EXAMPLES.md) - Usage examples
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Code organization
