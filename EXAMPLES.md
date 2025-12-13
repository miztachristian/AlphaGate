# Example Usage Guide

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Basic Analysis
```bash
# Analyze BTC/USDT on 1-hour chart
python main.py --symbol BTC/USDT --timeframe 1h

# Analyze ETH/USDT on 4-hour chart
python main.py --symbol ETH/USDT --timeframe 4h
```

### 3. Live Monitoring
```bash
# Monitor BTC/USDT continuously
python main.py --symbol BTC/USDT --timeframe 1h --live
```

### 4. Save Data
```bash
# Fetch and save data to CSV
python main.py --symbol BTC/USDT --timeframe 1h --save
```

## Example Output

```
======================================================================
TRADING SIGNAL ANALYSIS - 2024-12-13 15:00:00
======================================================================
Current Price: $42,350.50

🎯 SIGNAL: LONG (HIGH confidence)
   Strength: 0.75
   Reason: Long setup: 3 conditions met

✅ Conditions Met:
   1. RSI oversold bounce (35.2 crossing above 30)
   2. Bullish trend + pullback to 20 EMA (trend support)
   3. MACD bullish crossover + price above 20 EMA

📊 Trade Levels:
   Entry: $42,350.50
   Stop Loss: $41,850.00
   Take Profit: $43,600.00
   Risk/Reward: 1:2.50

⚡ Risk Assessment: TRADE

📈 Market Context:
   Trend: BULLISH
   RSI: RSI oversold bounce
   MACD: MACD bullish crossover
   Volume: High volume (1.8x avg) - Strong confirmation
   Volatility: Normal volatility (105% of avg)
======================================================================
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with verbose output
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_indicators.py
```

## Configuration

Edit `config.yaml` to customize:
- Indicator parameters (RSI periods, EMA lengths)
- Risk management (stop-loss/take-profit multipliers)
- Signal requirements (minimum conditions)

## Supported Exchanges

- Binance (default)
- Coinbase Pro
- Kraken
- Bitfinex
- And 100+ others supported by CCXT

## Supported Timeframes

- 15m (15 minutes)
- 1h (1 hour)
- 4h (4 hours)
- 1d (1 day)
