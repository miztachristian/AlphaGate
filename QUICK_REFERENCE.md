# 🎯 Quick Reference - Stock Trading Signals

## Command Cheat Sheet

```bash
# Single stock analysis
python main.py --symbol AAPL --timeframe 1h
python main.py --symbol TSLA --timeframe 4h --days 90

# Multi-stock live monitoring
python run_live_stocks.py --universe data/universe.csv --timeframe 1h --interval 60

# Outcome evaluation (after alerts are logged)
python -m src.evaluation.outcome_logger --db-path alerts_log.db --max-alerts 500

# Generate outcome reports
python -m src.evaluation.reporting --db-path alerts_log.db --output-dir reports
```

---

## Signal Interpretation

### 🟢 LONG Signal
**What it means:** Strong buying opportunity

**When it appears:**
- RSI bouncing from oversold (<30)
- Price reclaiming Bollinger Band lower band
- MACD turning positive
- Volume confirming
- Trend regime not strongly bearish

**Action:** Consider long entry near entry zone

---

### 🔴 SHORT Signal
**What it means:** Strong selling opportunity

**When it appears:**
- RSI falling from overbought (>70)
- Price breaking below Bollinger Band upper band
- MACD turning negative
- Volume confirming
- Trend regime not strongly bullish

**Action:** Consider short entry near entry zone

---

### 🟡 NEUTRAL
**What it means:** No clear edge, wait for better setup

**When it appears:**
- Less than 2 conditions met
- Conflicting signals
- Low volume
- Dead volatility regime

**Action:** Wait and monitor

---

## Score & Confidence Levels

| Score Range | Confidence | Action |
|-------------|-----------|--------|
| **80-100** | HIGH | Strong setup - take the trade |
| **60-80** | MEDIUM | Valid setup - trade with caution |
| **40-60** | LOW | Marginal edge - consider skipping |
| **0-40** | VERY LOW | Not enough edge - skip |

---

## Regime Classification

### Volatility Regime (ATR%)
| Regime | Meaning | Trading Implications |
|--------|---------|---------------------|
| **PANIC** | ATR% >= 90th percentile | Wide stops, high risk |
| **NORMAL** | Between 20th-90th | Standard trading |
| **DEAD** | ATR% <= 20th percentile | Low volatility, skip |

### Trend Regime (EMA200)
| Regime | Meaning | Trading Implications |
|--------|---------|---------------------|
| **STRONG_UPTREND** | Price > EMA200 + 1 ATR | Favor longs |
| **UPTREND** | Price > EMA200 | Slight long bias |
| **NEUTRAL** | Price near EMA200 | No bias |
| **DOWNTREND** | Price < EMA200 | Slight short bias |
| **STRONG_DOWNTREND** | Price < EMA200 - 1 ATR | Favor shorts |

---

## News Risk Levels

| Risk Level | Meaning | Action |
|------------|---------|--------|
| **HIGH** | Earnings, SEC, lawsuits | Caution - binary event risk |
| **MEDIUM** | Upgrades/downgrades, M&A | Monitor closely |
| **LOW** | No significant news | Standard trading |

---

## Entry/Exit Levels

### Stop Loss
- Calculated at **0.7x ATR** from entry (configurable)
- Protects against adverse moves

### Take Profit (Target)
- Calculated at **1.0x ATR** from entry (configurable)
- Conservative target based on hit rule

### Example (AAPL at $185):
```
Entry: $185.00
ATR: $2.50
Stop Loss: $183.25 (-$1.75, 0.7x ATR)
Take Profit: $187.50 (+$2.50, 1.0x ATR)
Risk/Reward: 1:1.43
```

---

## Timeframe Guide

| Timeframe | Best For | Hold Window | Horizons |
|-----------|----------|-------------|----------|
| **1h** | Intraday swings | 6-24 hours | 4h, 12h, 24h, 48h |
| **4h** | Swing trading | 1-3 days | 24h, 48h, 72h |
| **1d** | Position trading | 3-7 days | 24h, 72h, 168h |

---

## Popular Stock Commands

```bash
# Tech giants
python main.py --symbol AAPL --timeframe 1h
python main.py --symbol MSFT --timeframe 1h
python main.py --symbol NVDA --timeframe 4h
python main.py --symbol GOOGL --timeframe 4h

# High-beta stocks
python main.py --symbol TSLA --timeframe 1h
python main.py --symbol AMD --timeframe 1h

# ETFs
python main.py --symbol SPY --timeframe 4h
python main.py --symbol QQQ --timeframe 4h
```

---

## Configuration Quick Tips

Edit `config.yaml` to change:

```yaml
# Make RSI more/less sensitive
indicators:
  rsi:
    overbought: 70  # Lower = more short signals
    oversold: 30    # Higher = more long signals

# Data quality
data_quality:
  min_bars:
    "1h": 350  # Minimum bars needed for indicators
    "4h": 250
    "1d": 200

# Hit rule (target/stop levels)
outcome_eval:
  hit_rule:
    target_atr: 1.0  # 1x ATR target
    stop_atr: 0.7    # 0.7x ATR stop

# Alert cooldown
alerts:
  cooldown_minutes: 60  # Don't repeat same alert within this window
```

---

## Troubleshooting

### No signals appearing?
- Check if market is open (US market hours: 9:30 AM - 4:00 PM ET)
- Try different timeframe (4h usually better for swing trades)
- Verify stock has sufficient volume and volatility

### Cache issues?
- Cache is stored in `cache/` directory (DuckDB/Parquet)
- Delete cache folder to force full refresh
- Check `data_quality.min_bars` settings

### API rate limits?
- Polygon Starter plan: ~5 requests/second
- Set `MAX_REQUESTS_PER_SECOND` in .env
- Enable caching to reduce API calls

---

## Best Practices

1. **Use the cache system**
   - Dramatically reduces API calls
   - Faster scanning for large universes

2. **Review outcome reports**
   - Check hit rates by score bucket
   - Understand which regimes work best

3. **Respect regime filters**
   - Avoid DEAD volatility regime
   - Consider trend alignment

4. **Use alert deduplication**
   - SQLite state store prevents spam
   - Configure cooldown_minutes

5. **Monitor news risk**
   - HIGH risk = earnings/SEC/legal
   - Consider reducing size or skipping

---

## Need Help?

- Check [README.md](README.md) for full documentation
- See [STRATEGY_GUIDE.md](STRATEGY_GUIDE.md) for strategy details
- Review [EXAMPLES.md](EXAMPLES.md) for usage examples
- See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) for codebase overview
