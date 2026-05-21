"""
Production-Grade Backtesting Engine

Features:
- Per-bar event loop with stop/target/trailing-stop/time-based exits
- MFE/MAE tracking (Maximum Favorable / Adverse Excursion)
- Equity curve with drawdown tracking
- Comprehensive metrics: Sharpe, Sortino, Profit Factor, Expectancy, Max DD
- Friction/fees modeled realistically (entry + exit)
- Per-symbol and aggregate reporting
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    symbol: str
    setup: str
    direction: str  # LONG or SHORT
    entry_time: Any  # datetime-like
    entry_price: float

    # Risk management levels (set at entry)
    stop_price: float = 0.0
    target_price: float = 0.0
    trailing_stop: float = 0.0          # updated each bar
    atr_at_entry: float = 0.0           # for reference

    # Exit info (filled on close)
    exit_time: Any = None
    exit_price: float = 0.0
    exit_reason: str = ""

    # P&L
    pnl_dollar: float = 0.0
    pnl_pct: float = 0.0
    fees_paid: float = 0.0

    # MFE / MAE (Maximum Favorable / Adverse Excursion, in %)
    mfe_pct: float = 0.0
    mae_pct: float = 0.0

    # Duration
    bars_held: int = 0

    status: str = "OPEN"  # OPEN | CLOSED

    def to_dict(self) -> dict:
        return {
            "Symbol": self.symbol,
            "Setup": self.setup,
            "Direction": self.direction,
            "EntryTime": self.entry_time,
            "EntryPrice": round(self.entry_price, 4),
            "StopPrice": round(self.stop_price, 4),
            "TargetPrice": round(self.target_price, 4),
            "ExitTime": self.exit_time,
            "ExitPrice": round(self.exit_price, 4),
            "ExitReason": self.exit_reason,
            "PnL$": round(self.pnl_dollar, 4),
            "PnL%": round(self.pnl_pct * 100, 4),
            "Fees": round(self.fees_paid, 4),
            "MFE%": round(self.mfe_pct * 100, 4),
            "MAE%": round(self.mae_pct * 100, 4),
            "BarsHeld": self.bars_held,
            "ATR": round(self.atr_at_entry, 4),
        }


# ---------------------------------------------------------------------------
# Metrics calculator
# ---------------------------------------------------------------------------
def compute_metrics(trades: List[Trade], equity_curve: pd.DataFrame,
                    initial_capital: float) -> Dict[str, Any]:
    """Compute comprehensive backtest metrics from a list of closed trades."""
    closed = [t for t in trades if t.status == "CLOSED"]
    if not closed:
        return {"total_trades": 0}

    pnls = np.array([t.pnl_pct for t in closed])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    n = len(pnls)
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / n * 100 if n else 0

    avg_win = float(np.mean(wins) * 100) if n_wins else 0.0
    avg_loss = float(np.mean(losses) * 100) if n_losses else 0.0
    best_trade = float(np.max(pnls) * 100) if n else 0.0
    worst_trade = float(np.min(pnls) * 100) if n else 0.0

    gross_profit = float(np.sum(wins) * 100) if n_wins else 0.0
    gross_loss = float(np.sum(losses) * 100) if n_losses else 0.0
    profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')

    total_return_pct = float(np.sum(pnls) * 100)

    # Expectancy = avg_win * win_rate + avg_loss * (1-win_rate)  (in %)
    expectancy = (avg_win * (win_rate / 100)) + (avg_loss * (1 - win_rate / 100))

    # R:R
    risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    cw = cl = 0
    for p in pnls:
        if p > 0:
            cw += 1
            cl = 0
        else:
            cl += 1
            cw = 0
        max_consec_wins = max(max_consec_wins, cw)
        max_consec_losses = max(max_consec_losses, cl)

    # MFE / MAE averages
    avg_mfe = float(np.mean([t.mfe_pct for t in closed]) * 100)
    avg_mae = float(np.mean([t.mae_pct for t in closed]) * 100)
    avg_bars = float(np.mean([t.bars_held for t in closed]))

    # Drawdown from equity curve
    max_dd_pct = 0.0
    max_dd_duration = 0
    if len(equity_curve) > 0 and 'equity' in equity_curve.columns:
        eq = equity_curve['equity'].values
        peak = eq[0]
        dd_start = 0
        for i, e in enumerate(eq):
            if e > peak:
                peak = e
                dd_start = i
            dd = (peak - e) / peak * 100 if peak > 0 else 0
            if dd > max_dd_pct:
                max_dd_pct = dd
                max_dd_duration = i - dd_start

    # Sharpe (annualised, assuming ~6.5h trading day, 252 days)
    # For 1h bars: ~1638 bars/year
    sharpe = 0.0
    sortino = 0.0
    if len(pnls) > 1:
        pnl_std = np.std(pnls, ddof=1)
        if pnl_std > 0:
            sharpe = (np.mean(pnls) / pnl_std) * np.sqrt(min(len(pnls), 252))
        downside = pnls[pnls < 0]
        if len(downside) > 0:
            down_std = np.std(downside, ddof=1)
            if down_std > 0:
                sortino = (np.mean(pnls) / down_std) * np.sqrt(min(len(pnls), 252))

    # Exit reason breakdown
    exit_reasons = {}
    for t in closed:
        exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

    # Per-setup breakdown
    setup_stats = {}
    for t in closed:
        if t.setup not in setup_stats:
            setup_stats[t.setup] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        setup_stats[t.setup]["trades"] += 1
        if t.pnl_pct > 0:
            setup_stats[t.setup]["wins"] += 1
        setup_stats[t.setup]["total_pnl"] += t.pnl_pct * 100

    final_equity = equity_curve['equity'].iloc[-1] if len(equity_curve) > 0 else initial_capital

    return {
        "total_trades": n,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": round(win_rate, 2),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "risk_reward": round(risk_reward, 2),
        "best_trade_pct": round(best_trade, 3),
        "worst_trade_pct": round(worst_trade, 3),
        "gross_profit_pct": round(gross_profit, 3),
        "gross_loss_pct": round(gross_loss, 3),
        "profit_factor": round(profit_factor, 2),
        "total_return_pct": round(total_return_pct, 3),
        "expectancy_pct": round(expectancy, 3),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_dd_duration_bars": max_dd_duration,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        "avg_mfe_pct": round(avg_mfe, 3),
        "avg_mae_pct": round(avg_mae, 3),
        "avg_bars_held": round(avg_bars, 1),
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "exit_reasons": exit_reasons,
        "setup_stats": setup_stats,
    }


def format_metrics_report(name: str, m: Dict[str, Any]) -> str:
    """Format metrics dict into a human-readable string."""
    if m.get("total_trades", 0) == 0:
        return f"\n{'='*60}\n  {name}\n{'='*60}\n  No trades.\n"

    lines = [
        f"\n{'='*60}",
        f"  {name}",
        f"{'='*60}",
        f"  Trades:          {m['total_trades']}  (W:{m['wins']}  L:{m['losses']})",
        f"  Win Rate:        {m['win_rate']:.1f}%",
        f"  Avg Win:         +{m['avg_win_pct']:.2f}%",
        f"  Avg Loss:        {m['avg_loss_pct']:.2f}%",
        f"  Risk/Reward:     {m['risk_reward']:.2f}",
        f"  Best Trade:      +{m['best_trade_pct']:.2f}%",
        f"  Worst Trade:     {m['worst_trade_pct']:.2f}%",
        f"  Profit Factor:   {m['profit_factor']:.2f}",
        f"  Expectancy:      {m['expectancy_pct']:.3f}% per trade",
        f"  Total Return:    {m['total_return_pct']:.2f}%",
        f"  ----- Risk -----",
        f"  Sharpe:          {m['sharpe']:.2f}",
        f"  Sortino:         {m['sortino']:.2f}",
        f"  Max Drawdown:    {m['max_drawdown_pct']:.2f}%  ({m['max_dd_duration_bars']} bars)",
        f"  Max Consec W/L:  {m['max_consec_wins']} / {m['max_consec_losses']}",
        f"  ----- Trade Quality -----",
        f"  Avg MFE:         +{m['avg_mfe_pct']:.2f}%  (best possible exit)",
        f"  Avg MAE:         {m['avg_mae_pct']:.2f}%  (worst drawdown)",
        f"  Avg Hold:        {m['avg_bars_held']:.0f} bars",
        f"  ----- Equity -----",
        f"  Capital:         ${m['initial_capital']:,.0f} -> ${m['final_equity']:,.2f}",
        f"  ----- Exits -----",
    ]
    for reason, count in m.get("exit_reasons", {}).items():
        lines.append(f"    {reason}: {count}")
    lines.append(f"  ----- By Setup -----")
    for setup, stats in m.get("setup_stats", {}).items():
        wr = stats['wins'] / stats['trades'] * 100 if stats['trades'] else 0
        lines.append(f"    {setup}: {stats['trades']} trades, WR {wr:.0f}%, PnL {stats['total_pnl']:.2f}%")
    lines.append(f"{'='*60}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------
class BacktestEngine:
    """
    Production-grade event-driven backtesting engine.

    Exit hierarchy (checked every bar in order):
      1. Stop loss hit
      2. Target hit
      3. Trailing stop hit
      4. Max hold bars exceeded -> close at market
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        fee_bps: float = 15.0,
        trailing_stop_atr: float = 1.5,
        max_hold_bars: int = 50,
        position_size_pct: float = 100.0,  # % of capital per trade
    ):
        self.initial_capital = initial_capital
        self.fee_pct = fee_bps / 10_000.0  # one-way fee
        self.trailing_stop_atr = trailing_stop_atr
        self.max_hold_bars = max_hold_bars
        self.position_size_pct = position_size_pct / 100.0

        self.trades: List[Trade] = []

    # ------------------------------------------------------------------
    def run(
        self,
        df: pd.DataFrame,
        strategy_eval_func: Callable,
        indicators: Dict[str, pd.Series],
        symbol: str = "UNKNOWN",
        min_bars: int = 200,
        silent: bool = False,
    ) -> pd.DataFrame:
        """
        Run backtest bar by bar.

        Args:
            df: Full OHLCV DataFrame
            strategy_eval_func: (df_slice, ind_slice) -> SetupResult
            indicators: Pre-computed indicator dict
            symbol: Ticker symbol
            min_bars: Skip first N bars (warmup)
            silent: Suppress per-bar prints

        Returns:
            DataFrame with equity curve (time, equity, drawdown_pct)
        """
        self.trades = []
        open_trade: Optional[Trade] = None

        capital = self.initial_capital
        equity_curve = []
        peak_equity = capital

        n_bars = len(df)
        if not silent:
            print(f"  [{symbol}] Backtesting {n_bars - min_bars} bars...", flush=True)

        for i in range(min_bars, n_bars):
            bar_time = df.index[i]
            bar_open = float(df['open'].iloc[i])
            bar_high = float(df['high'].iloc[i])
            bar_low = float(df['low'].iloc[i])
            bar_close = float(df['close'].iloc[i])
            bar_atr = float(indicators['atr'].iloc[i]) if not pd.isna(indicators['atr'].iloc[i]) else 0

            # --- Equity tracking ---
            current_equity = capital
            if open_trade:
                if open_trade.direction == "LONG":
                    unrealized = (bar_close - open_trade.entry_price) / open_trade.entry_price
                else:
                    unrealized = (open_trade.entry_price - bar_close) / open_trade.entry_price
                trade_capital = capital * self.position_size_pct
                current_equity = capital + trade_capital * unrealized

            if current_equity > peak_equity:
                peak_equity = current_equity
            dd_pct = (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0.0

            equity_curve.append({
                'time': bar_time,
                'equity': round(current_equity, 2),
                'drawdown_pct': round(dd_pct, 4),
            })

            # --- Exit checks ---
            if open_trade:
                open_trade.bars_held += 1

                # Track MFE / MAE
                if open_trade.direction == "LONG":
                    excursion_fav = (bar_high - open_trade.entry_price) / open_trade.entry_price
                    excursion_adv = (open_trade.entry_price - bar_low) / open_trade.entry_price
                else:
                    excursion_fav = (open_trade.entry_price - bar_low) / open_trade.entry_price
                    excursion_adv = (bar_high - open_trade.entry_price) / open_trade.entry_price

                open_trade.mfe_pct = max(open_trade.mfe_pct, excursion_fav)
                open_trade.mae_pct = max(open_trade.mae_pct, excursion_adv)

                closed_this_bar = False

                # Exit 1: Stop loss
                if open_trade.direction == "LONG" and bar_low <= open_trade.stop_price:
                    self._close(open_trade, bar_time, open_trade.stop_price, "STOP_LOSS")
                    capital = self._settle(capital, open_trade)
                    open_trade = None
                    closed_this_bar = True
                elif open_trade.direction == "SHORT" and bar_high >= open_trade.stop_price:
                    self._close(open_trade, bar_time, open_trade.stop_price, "STOP_LOSS")
                    capital = self._settle(capital, open_trade)
                    open_trade = None
                    closed_this_bar = True

                # Exit 2: Target
                if not closed_this_bar and open_trade:
                    if open_trade.direction == "LONG" and bar_high >= open_trade.target_price:
                        self._close(open_trade, bar_time, open_trade.target_price, "TARGET_HIT")
                        capital = self._settle(capital, open_trade)
                        open_trade = None
                        closed_this_bar = True
                    elif open_trade.direction == "SHORT" and bar_low <= open_trade.target_price:
                        self._close(open_trade, bar_time, open_trade.target_price, "TARGET_HIT")
                        capital = self._settle(capital, open_trade)
                        open_trade = None
                        closed_this_bar = True

                # Exit 3: Trailing stop
                if not closed_this_bar and open_trade:
                    if open_trade.direction == "LONG":
                        new_trail = bar_high - self.trailing_stop_atr * bar_atr
                        if new_trail > open_trade.trailing_stop:
                            open_trade.trailing_stop = new_trail
                        if bar_low <= open_trade.trailing_stop and open_trade.trailing_stop > open_trade.entry_price:
                            self._close(open_trade, bar_time, open_trade.trailing_stop, "TRAILING_STOP")
                            capital = self._settle(capital, open_trade)
                            open_trade = None
                            closed_this_bar = True
                    else:
                        new_trail = bar_low + self.trailing_stop_atr * bar_atr
                        if new_trail < open_trade.trailing_stop or open_trade.trailing_stop == 0:
                            open_trade.trailing_stop = new_trail
                        if bar_high >= open_trade.trailing_stop and open_trade.trailing_stop < open_trade.entry_price:
                            self._close(open_trade, bar_time, open_trade.trailing_stop, "TRAILING_STOP")
                            capital = self._settle(capital, open_trade)
                            open_trade = None
                            closed_this_bar = True

                # Exit 4: Max hold
                if not closed_this_bar and open_trade:
                    if open_trade.bars_held >= self.max_hold_bars:
                        self._close(open_trade, bar_time, bar_close, "MAX_HOLD")
                        capital = self._settle(capital, open_trade)
                        open_trade = None
                        closed_this_bar = True

            # --- Entry check ---
            if open_trade is None:
                # Slice last 250 bars for efficiency
                sl_start = max(0, i + 1 - 250)
                df_slice = df.iloc[sl_start:i + 1]
                ind_slice = {
                    k: v.iloc[sl_start:i + 1]
                    for k, v in indicators.items()
                    if isinstance(v, pd.Series)
                }

                result = strategy_eval_func(df_slice, ind_slice)

                if result is not None and hasattr(result, 'status') and result.status.value == "SETUP_TRIGGERED":
                    alert = result.alert
                    entry_price = bar_close

                    # --- Compute target & stop from the alert ---
                    atr = alert.atr if alert.atr > 0 else bar_atr

                    # Target: setup-specific
                    if alert.setup == "TREND_CONTINUATION_PULLBACK":
                        target = alert.bb_middle if alert.bb_middle > entry_price else entry_price + 1.5 * atr
                    elif alert.setup == "VOLATILITY_SQUEEZE_BREAKOUT":
                        target = entry_price + 3.0 * atr
                    elif alert.setup == "MOMENTUM_BREAKOUT":
                        target = entry_price + 2.5 * atr
                    else:
                        target = entry_price + 2.0 * atr

                    # Stop: from alert invalidation or fallback
                    stop = alert.invalidation if alert.invalidation > 0 else entry_price - 1.5 * atr
                    if alert.direction == "SHORT":
                        target = entry_price - abs(entry_price - target)
                        stop = entry_price + abs(entry_price - stop)

                    # Initial trailing stop = same as stop
                    trail = stop

                    open_trade = Trade(
                        symbol=symbol,
                        setup=alert.setup,
                        direction=alert.direction,
                        entry_time=bar_time,
                        entry_price=entry_price,
                        stop_price=stop,
                        target_price=target,
                        trailing_stop=trail,
                        atr_at_entry=atr,
                    )

        # Force-close any remaining open trade
        if open_trade is not None:
            self._close(open_trade, df.index[-1], float(df['close'].iloc[-1]), "END_OF_DATA")
            capital = self._settle(capital, open_trade)

        return pd.DataFrame(equity_curve)

    # ------------------------------------------------------------------
    def _close(self, trade: Trade, exit_time, exit_price: float, reason: str):
        """Fill exit fields on a trade."""
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = reason

        if trade.direction == "LONG":
            trade.pnl_dollar = exit_price - trade.entry_price
        else:
            trade.pnl_dollar = trade.entry_price - exit_price

        trade.pnl_pct = trade.pnl_dollar / trade.entry_price if trade.entry_price else 0.0

        # Fees (round-trip)
        trade.fees_paid = trade.entry_price * self.fee_pct + exit_price * self.fee_pct

        trade.status = "CLOSED"
        self.trades.append(trade)

    def _settle(self, capital: float, trade: Trade) -> float:
        """Update capital after a closed trade."""
        trade_capital = capital * self.position_size_pct
        net_pnl_pct = trade.pnl_pct - (self.fee_pct * 2)  # round-trip fees
        return capital + trade_capital * net_pnl_pct

    # ------------------------------------------------------------------
    def get_metrics(self, equity_curve: pd.DataFrame) -> Dict[str, Any]:
        """Return comprehensive metrics dict."""
        return compute_metrics(self.trades, equity_curve, self.initial_capital)

    def get_trades_df(self) -> pd.DataFrame:
        """Return trades as a DataFrame."""
        closed = [t for t in self.trades if t.status == "CLOSED"]
        if not closed:
            return pd.DataFrame()
        return pd.DataFrame([t.to_dict() for t in closed])
