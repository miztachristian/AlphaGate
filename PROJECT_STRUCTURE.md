# 📁 Project Structure

```
trade-app/
│
├── 📄 main.py                    # Main application entry point
├── 📄 config.yaml                # Configuration file (customize here!)
├── 📄 requirements.txt           # Python dependencies
├── 📄 setup.bat                  # Windows setup script
├── 📄 setup.sh                   # Linux/Mac setup script
│
├── 📚 README.md                  # Main documentation
├── 📚 STRATEGY_GUIDE.md          # Detailed strategy explanation
├── 📚 QUICK_REFERENCE.md         # Quick command reference
├── 📚 EXAMPLES.md                # Usage examples
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
│   │   ├── atr.py               # ATR & risk management
│   │   └── bollinger.py         # Bollinger Bands
│   │
│   ├── 📂 strategy/              # Trading strategy engine
│   │   ├── __init__.py
│   │   ├── engine.py            # Main strategy orchestrator
│   │   └── rules.py             # Strategy rule definitions
│   │
│   └── 📂 utils/                 # Utility functions
│       ├── __init__.py
│       └── data_fetcher.py      # Market data fetching
│
├── 📂 tests/                     # Unit tests
│   ├── __init__.py
│   └── test_indicators.py       # Indicator tests
│
├── 📂 data/                      # Market data (created on first run)
│   └── (CSV files saved here)
│
└── 📂 .venv/                     # Virtual environment (auto-created)
    └── (Python packages)
```

---

## 🔍 File Descriptions

### Core Files

#### `main.py`
- Application entry point
- Command-line interface
- Orchestrates data fetching and analysis
- Displays colored output

**Run with:** `python main.py --symbol BTC/USDT --timeframe 1h`

---

#### `config.yaml`
- All configurable parameters
- Indicator settings (RSI levels, EMA periods, etc.)
- Risk management (stop-loss, take-profit multipliers)
- Signal requirements

**Customize this to match your trading style!**

---

### Source Code (`src/`)

#### `indicators/` - Technical Analysis
Each file calculates a specific indicator:

- **`rsi.py`** - RSI calculation, overbought/oversold detection, divergence
- **`ema.py`** - EMA calculation, trend detection, pullback signals
- **`macd.py`** - MACD calculation, crossovers, momentum analysis
- **`volume.py`** - Volume spikes, breakout confirmation, exhaustion
- **`atr.py`** - Volatility measurement, stop-loss/take-profit calculation
- **`bollinger.py`** - Bollinger Bands, squeeze detection, mean reversion

---

#### `strategy/` - Trading Logic

- **`engine.py`** - Main brain of the app
  - Calculates all indicators
  - Analyzes current market state
  - Generates trading signals
  - Formats output reports

- **`rules.py`** - Strategy rules
  - Evaluates long setups
  - Evaluates short setups
  - Combines multiple signals
  - Risk filtering logic

---

#### `utils/` - Helper Functions

- **`data_fetcher.py`** - Market data management
  - Fetches live data from exchanges (via CCXT)
  - Generates synthetic data for testing
  - Saves/loads CSV files
  - Resamples timeframes

---

### Tests (`tests/`)

#### `test_indicators.py`
- Unit tests for all indicators
- Validates calculations
- Tests strategy logic
- Ensures accuracy

**Run with:** `python -m pytest tests/ -v`

---

### Documentation

#### `README.md`
- Project overview
- Installation instructions
- Basic usage
- Feature list

#### `STRATEGY_GUIDE.md`
- Complete strategy explanation
- Every indicator detailed
- High-probability setups
- Sample outputs

#### `QUICK_REFERENCE.md`
- Command cheat sheet
- Signal interpretation
- Configuration tips
- Troubleshooting

#### `EXAMPLES.md`
- Practical usage examples
- Common commands
- Output examples

---

## 🔧 Configuration File Structure

### `config.yaml` sections:

```yaml
indicators:      # Indicator parameters
  rsi:          # RSI settings
  ema:          # EMA periods
  macd:         # MACD parameters
  bollinger:    # Bollinger Band settings
  atr:          # ATR period

risk:           # Risk management
  stop_loss_atr_multiplier    # Stop distance
  take_profit_atr_multiplier  # Target distance
  position_size_percent       # Position sizing

volume:         # Volume analysis
  spike_multiplier            # Volume threshold

trading:        # Trading preferences
  default_timeframe           # Default chart
  default_symbols             # Default pairs

signal_strength: # Signal requirements
  minimum_conditions          # Min indicators needed
  strong_signal_conditions    # High confidence threshold
```

---

## 📊 Data Flow

```
1. main.py (User runs command)
   ↓
2. utils/data_fetcher.py (Fetch market data)
   ↓
3. strategy/engine.py (Calculate all indicators)
   ↓
4. indicators/*.py (Individual calculations)
   ↓
5. strategy/rules.py (Evaluate setups)
   ↓
6. strategy/engine.py (Generate final signal)
   ↓
7. main.py (Display formatted output)
```

---

## 🎨 Code Organization Philosophy

### Modular Design
Each indicator is self-contained in its own file. Easy to:
- Test independently
- Modify without breaking others
- Add new indicators
- Understand individually

### Clear Separation
- **Indicators** = Pure calculations (math)
- **Strategy** = Business logic (rules)
- **Utils** = Data handling (I/O)
- **Main** = User interface (CLI)

### Extensibility
Want to add a new indicator?
1. Create `src/indicators/new_indicator.py`
2. Implement calculation function
3. Add analysis function
4. Import in `strategy/engine.py`
5. Add to rules in `strategy/rules.py`

---

## 🚀 Getting Started

1. **Setup environment:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```

2. **Run first analysis:**
   ```bash
   python main.py --symbol BTC/USDT --timeframe 1h
   ```

3. **Customize config:**
   Edit `config.yaml` to your preferences

4. **Run tests:**
   ```bash
   python -m pytest tests/ -v
   ```

5. **Start live monitoring:**
   ```bash
   python main.py --symbol BTC/USDT --timeframe 1h --live
   ```

---

## 📝 Notes

- Virtual environment (`.venv/`) keeps dependencies isolated
- Data folder (`data/`) created automatically when saving data
- All configuration in `config.yaml` - no code changes needed!
- Tests ensure calculations are accurate
- Color-coded output: Green (LONG), Red (SHORT), Yellow (NEUTRAL)

---

Happy Trading! 🎯📈
