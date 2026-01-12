# Example Usage Guide

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Up Environment
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your Polygon.io API key
# POLYGON_API_KEY=your_polygon_api_key_here
```

### 3. Basic Stock Analysis
```bash
# Analyze Apple on 1-hour chart
python main.py --symbol AAPL --timeframe 1h

# Analyze Tesla on 4-hour chart
python main.py --symbol TSLA --timeframe 4h

# Analyze with more historical data
python main.py --symbol NVDA --timeframe 1h --days 90
```

### 4. Multi-Stock Live Monitoring
```bash
# Monitor stocks from universe file
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60

# With Telegram notifications
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --notify telegram
```

### 5. Outcome Evaluation
```bash
# Evaluate alert outcomes (after alerts are logged)
python -m src.evaluation.outcome_logger --db-path alerts_log.db --max-alerts 500

# Generate summary reports
python -m src.evaluation.reporting --db-path alerts_log.db --output-dir reports
```

---

## Example Output

### Single Stock Analysis
```
======================================================================
TRADING SIGNAL ANALYSIS - AAPL - 2026-01-12 15:00:00
======================================================================
Current Price: $185.50

🎯 SIGNAL: LONG (Score: 75)
   Setup: MEAN_REVERSION_BB_RECLAIM
   Direction: LONG

📊 Trade Levels:
   Entry Zone: $184.75 - $186.25
   Stop Loss: $183.75 (0.7x ATR)
   Take Profit: $188.00 (1.0x ATR)

📈 Market Context:
   Trend Regime: NEUTRAL
   Vol Regime: NORMAL
   RSI: 32.5 (oversold bounce)
   ATR%: 1.8%

📰 News Risk: LOW
   No significant news in last 24h

⚡ Risk Assessment: TRADE
======================================================================
```

### Live Monitor Output
```
============================================================
LIVE STOCK SCANNER - 2026-01-12 15:00:00
============================================================
Universe: 50 stocks | Timeframe: 1h | Interval: 60s

[15:00:01] Scanning AAPL... ✓ (cache hit)
[15:00:01] Scanning MSFT... ✓ (cache hit)
[15:00:02] Scanning NVDA... ✓ (REST incremental)
...
[15:00:15] Scan complete: 50 stocks in 14.2s

Signals Found:
  🟢 AAPL: LONG (Score: 75) - MEAN_REVERSION_BB_RECLAIM
  🔴 XOM: SHORT (Score: 68) - MEAN_REVERSION_BB_RECLAIM

Metrics:
  Cache Hits: 45 | Misses: 5 | REST Calls: 8
  Bars Fetched: 1,250 | Errors: 0
============================================================
```

### Outcome Report
```
======================================================================
OUTCOME ANALYSIS REPORT
======================================================================
Database: alerts_log.db
Complete outcomes: 150

OUTCOMES BY SCORE BUCKET
----------------------------------------------------------------------
Bucket     Count   Hit@4h   FwdRet@4h   MFE@4h    MAE@4h
----------------------------------------------------------------------
0-40          12    25.0%      -0.50%    1.20%    -1.80%
40-60         38    42.1%       0.25%    1.80%    -1.20%
60-80         65    58.5%       1.10%    2.50%    -0.90%
80-100        35    71.4%       1.85%    3.20%    -0.60%

OUTCOMES BY REGIME (Hit Rate @ 24h)
----------------------------------------------------------------------
Trend           Vol        Count    Hit Rate
----------------------------------------------------------------------
UPTREND         NORMAL        45       65.0%
NEUTRAL         NORMAL        38       52.6%
DOWNTREND       PANIC         12       33.3%
```

---

## Running Tests

```bash
# Run all tests
pytest -q

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_indicators.py -v

# Run outcome evaluation tests
pytest tests/test_outcome_evaluation.py -v
```

---

## Configuration Examples

### `config.yaml` - Key Settings

```yaml
# Indicator parameters
indicators:
  rsi:
    period: 14
    overbought: 70
    oversold: 30
  ema:
    short: 20
    medium: 50
    long: 200

# Data quality
data_quality:
  min_bars:
    "1h": 350
    "4h": 250
    "1d": 200
  drop_partial_candles: true
  use_adjusted: false

# Mean reversion setup
mean_reversion:
  enabled: true
  bb_period: 20
  bb_std_dev: 2.0
  rsi_cross_threshold: 35

# Outcome evaluation
outcome_eval:
  horizons_1h: [4, 12, 24, 48]
  horizons_4h: [24, 48, 72]
  hit_rule:
    target_atr: 1.0
    stop_atr: 0.7

# Alert settings
alerts:
  cooldown_minutes: 60
  log_alerts: true
```

### `.env` - Environment Variables
```bash
# Required
POLYGON_API_KEY=your_polygon_api_key_here

# Optional - Notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional - Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
SMTP_FROM=your_email@gmail.com
SMTP_TO=recipient@email.com

# Optional - Cache settings
MAX_REQUESTS_PER_SECOND=5
MAX_WORKERS=32
```

---

## Data Sources

### Polygon.io API
- **Market Data**: Real-time and historical OHLCV
- **News**: Company news with caching
- **Plans**: Starter ($29/mo) recommended for live scanning

### Cache System
- **Backend**: DuckDB/Parquet (preferred) or SQLite fallback
- **Strategy**: Cache-first, REST-incremental updates
- **Benefit**: ~90% reduction in API calls after warmup

---

## Supported Timeframes

| Timeframe | Description | Typical Use |
|-----------|-------------|-------------|
| `15m` | 15 minutes | Day trading |
| `1h` | 1 hour | Intraday swings |
| `4h` | 4 hours | Swing trading |
| `1d` | 1 day | Position trading |

---

## Common Workflows

### 1. Initial Setup
```bash
# Clone and setup
git clone <repo>
cd trade-app
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env with API key
```

### 2. Backfill Cache (Optional)
```bash
# Run initial scans to warm cache
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 300
# Wait for full pass, then cache is warm
```

### 3. Production Monitoring
```bash
# Run with alerts
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60 --notify telegram
```

### 4. Review Performance
```bash
# After some alerts have been logged
python -m src.evaluation.outcome_logger --db-path alerts_log.db
python -m src.evaluation.reporting --db-path alerts_log.db
# Check reports/outcomes_by_bucket.csv
```
