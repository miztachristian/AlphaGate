# 📁 Project Structure

```
trade-app/
│
├── 📄 main.py                    # Single stock analysis CLI
├── 📄 run_live_stocks.py         # Multi-stock live monitor CLI
├── 📄 config.yaml                # Configuration file (customize here!)
├── 📄 requirements.txt           # Python dependencies
├── 📄 .env.example               # Environment variable template
├── 📄 setup.bat                  # Windows setup script
├── 📄 setup.sh                   # Linux/Mac setup script
│
├── 📚 README.md                  # Main documentation
├── 📚 STRATEGY_GUIDE.md          # Detailed strategy explanation
├── 📚 QUICK_REFERENCE.md         # Quick command reference
├── 📚 EXAMPLES.md                # Usage examples
├── 📚 GET_STARTED.md             # Getting started guide
│
├── 📂 .github/
│   └── copilot-instructions.md   # GitHub Copilot configuration
│
├── 📂 src/                       # Source code
│   ├── __init__.py
│   │
│   ├── 📂 indicators/            # Technical indicator calculations
│   │   ├── __init__.py
│   │   ├── rsi.py               # RSI calculation & analysis
│   │   ├── ema.py               # EMA calculation & trends
│   │   ├── macd.py              # MACD calculation & signals
│   │   ├── volume.py            # Volume analysis
│   │   ├── atr.py               # ATR & volatility regime
│   │   └── bollinger.py         # Bollinger Bands & mean reversion
│   │
│   ├── 📂 strategy/              # Trading strategy engine
│   │   ├── __init__.py
│   │   ├── engine.py            # Main strategy orchestrator
│   │   └── rules.py             # Strategy rule definitions
│   │
│   ├── 📂 marketdata/            # Market data fetching & caching
│   │   ├── __init__.py
│   │   ├── stocks.py            # Basic Polygon.io OHLCV fetcher
│   │   ├── stocks_v2.py         # Cache-first OHLCV with REST-incremental updates
│   │   ├── cache_store.py       # DuckDB/Parquet + SQLite cache backend
│   │   ├── rate_limiter.py      # API rate limiting & retry logic
│   │   ├── scan_metrics.py      # Scan performance metrics tracking
│   │   └── flat_files_backfill.py  # S3 bulk historical data backfill
│   │
│   ├── 📂 news/                  # News API & risk labeling
│   │   ├── __init__.py
│   │   ├── polygon_news_client.py  # Polygon.io news fetcher with caching
│   │   └── risk_labeler.py      # Keyword-based risk level (HIGH/MEDIUM/LOW)
│   │
│   ├── 📂 state/                 # Persistent state management
│   │   ├── __init__.py
│   │   └── sqlite_store.py      # Alert deduplication & calibration logging
│   │
│   ├── 📂 notify/                # Alert notifications
│   │   ├── __init__.py
│   │   ├── notifier.py          # Notification orchestrator
│   │   ├── telegram.py          # Telegram bot integration
│   │   └── email.py             # SMTP email alerts
│   │
│   ├── 📂 runner/                # Live monitoring orchestration
│   │   ├── __init__.py
│   │   └── live_runner.py       # Multi-stock scan loop
│   │
│   ├── 📂 universe/              # Stock universe management
│   │   ├── __init__.py
│   │   └── loader.py            # CSV universe loader
│   │
│   ├── 📂 evaluation/            # Post-alert outcome analysis
│   │   ├── __init__.py
│   │   ├── outcome_logger.py    # MFE/MAE computation, hit rule evaluation
│   │   └── reporting.py         # Summary reports by score bucket & regime
│   │
│   └── 📂 utils/                 # Utility functions
│       └── __init__.py
│
├── 📂 tests/                     # Unit tests
│   ├── __init__.py
│   ├── test_indicators.py       # Indicator calculation tests
│   ├── test_cache_system.py     # Cache system tests
│   ├── test_polygon_news.py     # News API tests
│   ├── test_v2_hardened.py      # Integration tests
│   ├── test_outcome_evaluation.py  # Outcome logger tests
│   └── test_outcome_reporting.py   # Reporting tests
│
├── 📂 reports/                   # Generated analysis reports
│   └── (CSV files from outcome analysis)
│
├── 📂 data/                      # Stock universe files
│   ├── universe.csv             # Default stock watchlist
│   └── universe_all_us.csv      # All US stocks
│
├── 📂 scripts/                   # Utility scripts
│   └── fetch_us_tickers.py      # Fetch all US stock tickers
│
└── 📂 .venv/                     # Virtual environment (auto-created)
```

---

## 🔍 Module Descriptions

### Entry Points

| File | Description |
|------|-------------|
| `main.py` | Single stock analysis CLI. Run with `python main.py --symbol AAPL --timeframe 1h` |
| `run_live_stocks.py` | Multi-stock live monitor. Run with `python run_live_stocks.py --universe data/universe.csv` |

---

### Source Modules (`src/`)

#### `indicators/` - Technical Analysis

| File | Purpose |
|------|---------|
| `rsi.py` | RSI calculation, overbought/oversold detection |
| `ema.py` | EMA calculation (20/50/200), trend detection |
| `macd.py` | MACD histogram, signal line crossovers |
| `volume.py` | Volume SMA, spike detection |
| `atr.py` | ATR calculation, volatility regime classification |
| `bollinger.py` | Bollinger Bands, mean reversion signals |

#### `strategy/` - Trading Logic

| File | Purpose |
|------|---------|
| `engine.py` | Main orchestrator: calculates indicators, detects setups, generates signals |
| `rules.py` | Strategy rules: mean reversion, momentum, regime filtering |

#### `marketdata/` - Data Layer

| File | Purpose |
|------|---------|
| `stocks.py` | Basic Polygon.io OHLCV fetcher |
| `stocks_v2.py` | **Primary**: Cache-first fetching with REST-incremental updates |
| `cache_store.py` | DuckDB/Parquet cache backend (SQLite fallback) |
| `rate_limiter.py` | API rate limiting, exponential backoff retry |
| `scan_metrics.py` | Track cache hits/misses, API calls, bars fetched |
| `flat_files_backfill.py` | Bulk S3 historical data import |

#### `news/` - News Integration

| File | Purpose |
|------|---------|
| `polygon_news_client.py` | Fetch news from Polygon.io with TTL caching |
| `risk_labeler.py` | Keyword-based risk classification (HIGH/MEDIUM/LOW) |

#### `state/` - Persistence

| File | Purpose |
|------|---------|
| `sqlite_store.py` | Alert deduplication (cooldown), calibration logging |

#### `notify/` - Alerts

| File | Purpose |
|------|---------|
| `notifier.py` | Notification orchestrator |
| `telegram.py` | Telegram bot integration |
| `email.py` | SMTP email alerts |

#### `runner/` - Live Monitoring

| File | Purpose |
|------|---------|
| `live_runner.py` | Multi-stock scan loop, metric tracking |

#### `evaluation/` - Outcome Analysis

| File | Purpose |
|------|---------|
| `outcome_logger.py` | Compute MFE/MAE, forward returns, hit rates |
| `reporting.py` | Generate CSV reports by score bucket & regime |

---

## 🧪 Tests

Run all tests:
```bash
pytest -q
```

| Test File | Coverage |
|-----------|----------|
| `test_indicators.py` | RSI, EMA, MACD, ATR, Bollinger calculations |
| `test_cache_system.py` | Cache read/write, data quality gate |
| `test_polygon_news.py` | News API, risk labeling |
| `test_v2_hardened.py` | Integration tests |
| `test_outcome_evaluation.py` | MFE/MAE math, hit rules, alert_id |
| `test_outcome_reporting.py` | Bucket stats, regime stats |

---

## ⚙️ Configuration

### `config.yaml`

Key sections:
- `indicators`: RSI period, EMA lengths, MACD settings
- `data_quality`: Minimum bars, gap detection, partial candle handling
- `mean_reversion`: BB reclaim setup parameters
- `news`: Lookback hours, risk keywords
- `alerts`: Cooldown, logging settings
- `outcome_eval`: Horizons, hit rule ATR multiples

### Environment Variables (`.env`)

Required:
- `POLYGON_API_KEY` - Polygon.io API key

Optional:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` - Telegram alerts
- `SMTP_*` - Email alerts
- `MASSIVE_S3_*` - S3 flat files backfill
