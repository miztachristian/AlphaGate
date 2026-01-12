# 📊 Trading App - Strategy Guide

## Overview

This app implements a **mean reversion strategy** with regime filters to identify high-probability trade setups in US equities.

---

## 🎯 What This App Does

Analyzes real-time stock data via Polygon.io and generates **scored trading signals** by combining multiple technical indicators with regime awareness.

### Signal Types
- **🟢 LONG** - Buy signal (expect price to rise)
- **🔴 SHORT** - Sell/Short signal (expect price to fall)
- **⚪ NEUTRAL** - No clear setup (wait)

### Confidence Levels (Score 0-100)
- **HIGH (80-100)** - Strong setup, 3+ conditions aligned
- **MEDIUM (60-80)** - Valid setup, 2 conditions aligned
- **LOW (40-60)** - Marginal edge
- **VERY LOW (<40)** - Skip this trade

---

## 📈 Indicators Implemented

### 1. **RSI (Relative Strength Index)**
- Period: 14 (configurable)
- Overbought: >70, Oversold: <30
- Identifies reversal conditions

**Trading Rules:**
- Long: RSI < 30 crosses up (oversold recovery)
- Short: RSI > 70 crosses down (overbought exhaustion)

### 2. **EMA (Exponential Moving Averages)**
- 20, 50, 200-period EMAs
- Trend structure detection
- Pullback entry identification

**Trading Rules:**
- Long: EMA50 > EMA200 (bullish) + pullback to EMA20
- Short: EMA50 < EMA200 (bearish) + rally to EMA20

### 3. **MACD**
- Fast: 12, Slow: 26, Signal: 9
- Crossover detection
- Momentum confirmation

**Trading Rules:**
- Long: MACD crosses above signal line
- Short: MACD crosses below signal line

### 4. **Volume Analysis**
- 20-period SMA baseline
- Spike threshold: 1.5x average
- Confirms conviction on moves

**Trading Rules:**
- High volume breakout = real move (trade it)
- Low volume breakout = weak move (skip it)

### 5. **ATR (Average True Range)**
- Period: 14
- Used for stop-loss and take-profit levels
- Volatility regime detection

**Trading Rules:**
- Stop-loss: 1.5-2x ATR below/above entry
- Take-profit: 2-3x ATR for 1:1.5+ R:R

### 6. **Bollinger Bands**
- Period: 20, StdDev: 2.0
- Mean reversion signals
- Squeeze detection

**Trading Rules:**
- Long: Price touches/breaks lower band
- Short: Price touches/breaks upper band
- Squeeze: Narrow bands signal imminent breakout

---

## 🎛️ Regime Detection

The app uses regime filters to avoid low-probability environments:

### Trend Regime
Based on price relative to EMA200:
- **UPTREND**: Price > EMA200 (favor longs)
- **DOWNTREND**: Price < EMA200 (favor shorts)
- **NEUTRAL**: Price near EMA200

### Volatility Regime
Based on ATR percentile (14-period ATR vs 100-period lookback):
- **PANIC** (>80th percentile): High volatility, wider stops
- **NORMAL** (20-80th): Standard conditions
- **DEAD** (<20th percentile): Low volatility, skip trades

---

## 🔥 High-Probability Setups

### Mean Reversion Long
```
✅ EMA50 > EMA200 (bullish structure)
✅ RSI bounces from <35 (oversold)
✅ Price at/below lower Bollinger Band
✅ Volume above average (confirmation)
✅ Vol regime: NORMAL (not DEAD)
→ STRONG LONG SIGNAL (score 80+)
```

### Mean Reversion Short
```
✅ EMA50 < EMA200 (bearish structure)
✅ RSI falls from >65 (overbought)
✅ Price at/above upper Bollinger Band
✅ Volume above average (confirmation)
✅ Vol regime: NORMAL (not PANIC)
→ STRONG SHORT SIGNAL (score 80+)
```

---

## 🎮 Usage Examples

### Single Stock Analysis
```bash
# Analyze Apple on 1-hour chart
python main.py --symbol AAPL --timeframe 1h

# Analyze Tesla on 4-hour chart
python main.py --symbol TSLA --timeframe 4h

# Analyze Microsoft on daily chart
python main.py --symbol MSFT --timeframe 1d
```

### Multi-Stock Monitoring
```bash
# Monitor universe of stocks
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60
```

---

## 📊 Sample Output

```
======================================================================
  📊 TRADING STRATEGY ANALYZER - AAPL
======================================================================

🎯 SIGNAL: LONG
   Score: 82/100 (HIGH confidence)
   Reason: Mean reversion long - oversold bounce + trend support

✅ Conditions Met:
   1. RSI oversold bounce (28.5 → 34)
   2. Bullish trend (EMA50 > EMA200)
   3. Price at lower Bollinger Band
   4. Volume spike (1.6x average)

📊 Trade Levels:
   Entry: $185.50
   Stop Loss: $183.25 (1.5x ATR)
   Take Profit: $189.88 (2.5x ATR)
   Risk/Reward: 1:1.95

🌡️ Regime Context:
   Trend: UPTREND
   Volatility: NORMAL (ATR 42nd percentile)
   News Risk: LOW
======================================================================
```

---

## 📰 News Risk Assessment

The app checks recent Polygon.io news for risk events:

### Risk Levels
- **HIGH**: Earnings, SEC filings, lawsuits, FDA decisions
- **MEDIUM**: Analyst upgrades/downgrades, M&A rumors
- **LOW**: No significant news

### How It Works
1. Fetches news from past 24-48 hours via Polygon.io
2. Scans headlines for HIGH/MEDIUM risk keywords
3. Attaches risk label to signal output
4. Warns before binary event risk

---

## ⚙️ Configuration

Edit `config.yaml` to customize:

```yaml
indicators:
  rsi:
    period: 14
    overbought: 70
    oversold: 30
  
  ema:
    periods: [20, 50, 200]
  
  atr:
    period: 14
    stop_multiplier: 1.5
    target_multiplier: 2.5

strategy:
  min_score: 60          # Minimum score to generate signal
  min_conditions: 2      # Minimum conditions for valid setup
```

---

## 📈 Outcome Evaluation

After running the app and collecting alerts, evaluate performance:

```bash
# Evaluate outcomes for logged alerts
python -m src.evaluation.outcome_logger --db-path alerts_log.db --lookback-hours 168

# Generate performance reports
python -m src.evaluation.reporting --db-path alerts_log.db
```

### Metrics Tracked
- **MFE (Max Favorable Excursion)**: Best unrealized P&L
- **MAE (Max Adverse Excursion)**: Worst unrealized drawdown
- **Hit Rate**: % of signals that reached target
- **Win/Loss Ratio**: Average win size vs average loss

---

## 💡 Strategy Philosophy

> "Combine 2-3 conditions at once to catch 80% of high-quality trades."

The app ensures you never miss a setup by:
1. Monitoring all indicators simultaneously
2. Identifying when 2+ conditions align
3. Filtering with regime awareness
4. Calculating optimal entry/exit levels
5. Assessing news risk before signals

---

## 🛡️ Risk Management

### Position Sizing (Recommended)
- Risk 1-2% of account per trade
- Use ATR-based stops (1.5-2x ATR)
- Minimum 1:1.5 reward-to-risk ratio

### Environment Filters
- Skip DEAD volatility regime (no edge)
- Reduce size in PANIC regime
- Check news risk before earnings

---

## 📚 Related Documentation

- [GET_STARTED.md](GET_STARTED.md) - Quick start guide
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Command cheat sheet
- [EXAMPLES.md](EXAMPLES.md) - Usage examples
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Code organization

---

## 🛡️ Disclaimer

This is an **analysis tool** for educational purposes. Always:
- Verify signals manually before trading
- Practice proper risk management
- Test thoroughly in paper trading first
- Past performance doesn't guarantee future results
