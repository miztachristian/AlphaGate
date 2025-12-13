# 🎯 Quick Reference - Trading Signals

## Command Cheat Sheet

```bash
# Quick analysis
python main.py --symbol BTC/USDT --timeframe 1h

# Live monitoring
python main.py --symbol BTC/USDT --timeframe 1h --live

# Save data
python main.py --symbol ETH/USDT --timeframe 4h --save

# Different exchange
python main.py --symbol BTC/USDT --timeframe 1h --exchange kraken

# More data
python main.py --symbol BTC/USDT --timeframe 1h --limit 1000
```

---

## Signal Interpretation

### 🟢 LONG Signal
**What it means:** Strong buying opportunity

**When it appears:**
- RSI bouncing from oversold (<30)
- Price at 20 EMA support in uptrend
- MACD turning positive
- Volume confirming

**Action:** Consider long entry at current price

---

### 🔴 SHORT Signal
**What it means:** Strong selling opportunity

**When it appears:**
- RSI falling from overbought (>70)
- Price at 20 EMA resistance in downtrend
- MACD turning negative
- Volume confirming

**Action:** Consider short entry at current price

---

### 🟡 NEUTRAL
**What it means:** No clear edge, wait for better setup

**When it appears:**
- Less than 2 conditions met
- Conflicting signals
- Low volume
- Low volatility

**Action:** Wait and monitor

---

## Confidence Levels

| Level | Conditions | Action |
|-------|-----------|--------|
| **HIGH** | 3+ indicators align | Strong setup - take the trade |
| **MEDIUM** | 2 indicators align | Valid setup - trade with caution |
| **LOW** | 1 indicator only | Not enough edge - skip |

---

## Risk Assessment

| Status | Meaning | Action |
|--------|---------|--------|
| **TRADE** | All filters passed | Safe to trade |
| **CAUTION** | 1 warning flag | Trade with reduced size |
| **SKIP** | 2+ warning flags | Don't trade, wait |

### Warning Flags:
- ⚠️ Low volatility (market too quiet)
- ⚠️ Trading against main trend (risky)
- ⚠️ Low volume (weak confirmation)

---

## Entry/Exit Levels

### Stop Loss
- Calculated at **1.5-2x ATR** from entry
- Protects against adverse moves
- Adjustable in config.yaml

### Take Profit
- Calculated at **2.5-3x ATR** from entry
- Targets realistic profit
- Gives ~2.5:1 risk/reward ratio

### Example:
```
Entry: $42,350
Stop Loss: $41,875 (-$475, 1.5x ATR)
Take Profit: $43,538 (+$1,188, 2.5x ATR)
Risk/Reward: 1:2.50
```

---

## Timeframe Guide

| Timeframe | Best For | Update Frequency |
|-----------|----------|------------------|
| **15m** | Day trading, scalping | Every 15 minutes |
| **1h** | Intraday swings | Every hour |
| **4h** | Swing trading | Every 4 hours |
| **1d** | Position trading | Daily |

**Pro Tip:** Confirm 1h signals with 4h trend!

---

## Popular Trading Pairs

```bash
# Bitcoin
python main.py --symbol BTC/USDT --timeframe 1h

# Ethereum
python main.py --symbol ETH/USDT --timeframe 1h

# Solana
python main.py --symbol SOL/USDT --timeframe 1h

# Cardano
python main.py --symbol ADA/USDT --timeframe 1h

# Ripple
python main.py --symbol XRP/USDT --timeframe 1h
```

---

## Configuration Quick Tips

Edit `config.yaml` to change:

```yaml
# Make RSI more/less sensitive
rsi:
  overbought: 70  # Lower = more short signals
  oversold: 30    # Higher = more long signals

# Adjust stop-loss tightness
risk:
  stop_loss_atr_multiplier: 1.5  # Lower = tighter stops

# Change volume sensitivity
volume:
  spike_multiplier: 1.5  # Lower = more signals

# Require more confirmation
signal_strength:
  minimum_conditions: 3  # Higher = fewer but stronger signals
```

---

## Troubleshooting

### No signals appearing?
- Try different timeframe (4h usually better)
- Lower minimum_conditions in config
- Check if market is consolidating (expected)

### Too many signals?
- Increase minimum_conditions to 3
- Use stricter RSI levels (25/75)
- Only trade HIGH confidence signals

### App not connecting?
- Check internet connection
- Try different exchange (--exchange kraken)
- App will use synthetic data if connection fails

---

## Best Practices

1. **Multi-timeframe confirmation**
   - Check 1h signal against 4h trend
   - Don't short into rising 4h trend

2. **Wait for volume**
   - High volume = real move
   - Low volume = often fake

3. **Respect the trend**
   - Long in uptrends (50>200)
   - Short in downtrends (50<200)

4. **Use proper position sizing**
   - Risk 1-2% per trade
   - Use provided stop-loss levels

5. **Keep a trading journal**
   - Track your signals
   - Learn what works best for you

---

## Need Help?

- Check [README.md](README.md) for full documentation
- See [STRATEGY_GUIDE.md](STRATEGY_GUIDE.md) for strategy details
- Review [EXAMPLES.md](EXAMPLES.md) for usage examples
- Run `python main.py --help` for command options
