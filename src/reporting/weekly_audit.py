"""
Weekly Audit Module

Generates weekly performance reports including:
- Paper P&L calculation (simulated $100 per alert)
- Alert summary statistics
- Gate decision analysis
- CSV export for detailed analysis

Usage:
    python -m src.reporting.weekly_audit --lookback-days 7 --email
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import smtplib
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

from ..state import SqliteStateStore
from ..marketdata import fetch_stock_ohlcv_cached, CACHE_AVAILABLE
from ..notify.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


@dataclass
class WeeklyAuditConfig:
    """Configuration for weekly audit."""
    lookback_days: int = 7
    capital_usd_per_alert: float = 100.0
    friction_bps: float = 15.0  # Round-trip friction cost in basis points (spread + slippage)
    hold_hours_by_timeframe: Dict[str, int] = field(default_factory=lambda: {
        "1h": 24,
        "4h": 72,
        "1d": 168,
    })
    output_dir: str = "reports"
    state_db: str = "state.db"


@dataclass
class AlertOutcome:
    """Outcome of a single alert for P&L calculation."""
    alert_id: int
    symbol: str
    timeframe: str
    direction: str
    setup: str
    score: int
    entry_price: float
    entry_ts: str
    exit_price: Optional[float] = None
    exit_ts: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl_dollars: float = 0.0
    pnl_percent: float = 0.0
    hold_hours: float = 0.0


@dataclass
class WeeklyAuditResult:
    """Result of weekly audit with split System vs Trader performance."""
    # Period
    start_date: str
    end_date: str
    
    # Alert counts (System = all alerts, Trader = taken only)
    total_alerts: int = 0
    alerts_evaluated: int = 0
    alerts_pending: int = 0
    alerts_taken: int = 0
    alerts_skipped: int = 0
    
    # System Performance (all alerts, mechanical execution with friction)
    system_pnl: float = 0.0
    system_avg_pnl: float = 0.0
    system_wins: int = 0
    system_losses: int = 0
    system_breakeven: int = 0
    system_win_rate: float = 0.0
    system_best_trade: float = 0.0
    system_worst_trade: float = 0.0
    
    # Trader Performance (taken trades only, actual fills)
    trader_pnl: float = 0.0
    trader_avg_pnl: float = 0.0
    trader_wins: int = 0
    trader_losses: int = 0
    trader_breakeven: int = 0
    trader_win_rate: float = 0.0
    trader_best_trade: float = 0.0
    trader_worst_trade: float = 0.0
    
    # Gate stats (if available)
    gate_go: int = 0
    gate_no_go: int = 0
    gate_not_evaluated: int = 0
    
    # Detail records
    system_outcomes: List[AlertOutcome] = field(default_factory=list)
    trader_outcomes: List[AlertOutcome] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "period": {
                "start_date": self.start_date,
                "end_date": self.end_date,
            },
            "alerts": {
                "total": self.total_alerts,
                "evaluated": self.alerts_evaluated,
                "pending": self.alerts_pending,
                "taken": self.alerts_taken,
                "skipped": self.alerts_skipped,
            },
            "system_performance": {
                "total_pnl": self.system_pnl,
                "avg_pnl": self.system_avg_pnl,
                "wins": self.system_wins,
                "losses": self.system_losses,
                "breakeven": self.system_breakeven,
                "win_rate": self.system_win_rate,
                "best_trade": self.system_best_trade,
                "worst_trade": self.system_worst_trade,
            },
            "trader_performance": {
                "total_pnl": self.trader_pnl,
                "avg_pnl": self.trader_avg_pnl,
                "wins": self.trader_wins,
                "losses": self.trader_losses,
                "breakeven": self.trader_breakeven,
                "win_rate": self.trader_win_rate,
                "best_trade": self.trader_best_trade,
                "worst_trade": self.trader_worst_trade,
            },
            "gate": {
                "go": self.gate_go,
                "no_go": self.gate_no_go,
                "not_evaluated": self.gate_not_evaluated,
            },
        }


def _load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    
    defaults = {
        "calibration_logging": {
            "hold_hours_by_timeframe": {"1h": 24, "4h": 72, "1d": 168},
        },
        "report_delivery": {
            "enabled": True,
            "lookback_days": 7,
            "capital_usd_per_alert": 100,
            "email": {"enabled": False, "recipients": []},
        }
    }
    
    if not config_path.exists():
        return defaults
    
    try:
        with open(config_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        return defaults


def _get_exit_price(
    symbol: str,
    timeframe: str,
    direction: str,
    entry_ts: str,
    entry_price: float,
    hold_hours: int,
    stop_loss_price: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str], str]:
    """
    Calculate exit price for paper P&L.
    
    Strategy: 
    - Fetch candles from entry_ts to entry_ts + hold_hours
    - Check for Stop Loss hits on every candle (low for LONG, high for SHORT)
    - If no stop loss, exit at close of final bar in the hold window
    
    Args:
        symbol: Stock ticker
        timeframe: Candle timeframe
        direction: LONG or SHORT
        entry_ts: Entry timestamp (ISO format)
        entry_price: Entry price
        hold_hours: Hold duration in hours
        stop_loss_price: Optional Stop Loss price. If hit, exit immediately.
    
    Returns:
        Tuple of (exit_price, exit_ts, exit_reason)
    """
    try:
        entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
        exit_dt = entry_dt + timedelta(hours=hold_hours)
        
        # Calculate lookback days needed
        lookback_days = max(7, (hold_hours // 24) + 3)
        
        # Fetch OHLCV data
        if CACHE_AVAILABLE:
            df = fetch_stock_ohlcv_cached(
                ticker=symbol,
                interval=timeframe,
                lookback_days=lookback_days,
            )
        else:
            from ..marketdata import fetch_stock_ohlcv
            df = fetch_stock_ohlcv(
                ticker=symbol,
                interval=timeframe,
                lookback_days=lookback_days,
            )
        
        if df is None or df.empty:
            return None, None, "NO_DATA"
        
        # Find candles in the hold window (starting AFTER entry if granularity permits, 
        # but here we include entry bar in case of immediate crash, though usually entry is close of bar)
        # Better: Start from entry_dt. If entry_dt is candle close, the next candle is the first opportunity to stop out?
        # For simplicity, we check all candles with timestamp >= entry_dt.
        df_window = df[(df.index >= entry_dt) & (df.index <= exit_dt)]
        
        if df_window.empty:
            return None, None, "NO_CANDLES_IN_WINDOW"
        
        # Check for Stop Loss (The "Lying Audit" fix)
        if stop_loss_price is not None:
             for ts, row in df_window.iterrows():
                # Skip the very first candle if its timestamp exactly matches entry and we assume we entered at close
                if ts == entry_dt:
                    continue

                if direction.upper() == "LONG":
                    if row['low'] <= stop_loss_price:
                        return float(stop_loss_price), ts.isoformat(), "STOP_LOSS"
                elif direction.upper() == "SHORT":
                    if row['high'] >= stop_loss_price:
                        return float(stop_loss_price), ts.isoformat(), "STOP_LOSS"

        # Exit at close of last candle in window
        exit_price = float(df_window['close'].iloc[-1])
        exit_ts = df_window.index[-1].isoformat()
        exit_reason = "HOLD_WINDOW_END"
        
        return exit_price, exit_ts, exit_reason
        
    except Exception as e:
        logger.error(f"Exit price calculation error for {symbol}: {e}")
        return None, None, f"ERROR: {str(e)[:50]}"


def _calculate_pnl(
    direction: str,
    entry_price: float,
    exit_price: float,
    capital: float = 100.0,
    friction_bps: float = 0.0,
) -> Tuple[float, float]:
    """
    Calculate paper P&L with optional friction costs.
    
    Args:
        direction: LONG or SHORT
        entry_price: Entry price
        exit_price: Exit price
        capital: Capital per trade (default $100)
        friction_bps: Round-trip friction cost in basis points (default 0, typical 10-20)
    
    Returns:
        Tuple of (pnl_dollars, pnl_percent)
    """
    if entry_price <= 0:
        return 0.0, 0.0
    
    if direction.upper() == "LONG":
        pnl_percent = ((exit_price - entry_price) / entry_price) * 100
    else:  # SHORT
        pnl_percent = ((entry_price - exit_price) / entry_price) * 100
    
    # Subtract friction (round-trip cost)
    pnl_percent -= (friction_bps / 100.0)
    
    pnl_dollars = capital * (pnl_percent / 100)
    
    return round(pnl_dollars, 2), round(pnl_percent, 2)


def run_weekly_audit(
    config: WeeklyAuditConfig,
    verbose: bool = True,
) -> WeeklyAuditResult:
    """
    Run weekly audit and calculate paper P&L.
    
    Args:
        config: WeeklyAuditConfig with settings
        verbose: Print progress to console
    
    Returns:
        WeeklyAuditResult with summary and details
    """
    # Initialize state store
    state = SqliteStateStore(path=config.state_db)
    
    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=config.lookback_days)
    
    result = WeeklyAuditResult(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    
    if verbose:
        print(f"📊 Weekly Audit Report")
        print(f"   Period: {start_date.date()} to {end_date.date()}")
        print()
    
    # Get alerts from the period
    alerts = state.get_recent_alerts_log(limit=1000)
    
    # Filter to period
    period_alerts = [
        a for a in alerts
        if start_date.isoformat() <= a.get("ts_utc", "") <= end_date.isoformat()
    ]
    
    result.total_alerts = len(period_alerts)
    
    if verbose:
        print(f"📈 Found {result.total_alerts} alerts in period")
    
    # Get gate decisions for the period
    try:
        gate_decisions = state.get_gate_decisions(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        for gd in gate_decisions:
            status = gd.get("gate_status", "")
            if status == "GO":
                result.gate_go += 1
            elif status == "NO_GO":
                result.gate_no_go += 1
            else:
                result.gate_not_evaluated += 1
    except Exception as e:
        logger.debug(f"No gate decisions found: {e}")
    
    # Get manual decisions for trader performance
    manual_decisions = state.get_manual_decisions(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    
    # Build lookup: alert_id -> decision
    decisions_map = {d["alert_log_id"]: d for d in manual_decisions}
    
    # Process each alert for SYSTEM performance (mechanical, with friction)
    system_outcomes = []
    trader_outcomes = []
    
    for alert in period_alerts:
        alert_id = alert.get("id", 0)
        symbol = alert.get("symbol", "")
        timeframe = alert.get("timeframe", "1h")
        direction = alert.get("direction", "LONG")
        setup = alert.get("setup", "")
        score = alert.get("score", 0)
        entry_price = alert.get("trigger_close", 0.0)
        entry_ts = alert.get("ts_utc", "")
        
        if not entry_price or not entry_ts:
            continue
        
        # Parse details for Risk Management (ATR)
        details_json = alert.get("details_json", "{}")
        try:
            details = json.loads(details_json)
        except (json.JSONDecodeError, TypeError):
            details = {}
            
        atr = float(details.get("atr", 0.0))
        stop_loss_price = None
        
        if atr > 0:
            # Default to 1.5 ATR Stop Loss for Audit if not specified
            # This makes the audit "Honest" about risk
            risk_multiple = 1.5
            if direction.upper() == "LONG":
                stop_loss_price = entry_price - (atr * risk_multiple)
            elif direction.upper() == "SHORT":
                stop_loss_price = entry_price + (atr * risk_multiple)
        
        # Determine hold hours
        hold_hours = config.hold_hours_by_timeframe.get(timeframe, 24)
        
        # Check if we have enough time elapsed
        entry_dt = datetime.fromisoformat(entry_ts.replace('Z', '+00:00'))
        min_exit_dt = entry_dt + timedelta(hours=hold_hours)
        
        now_utc = datetime.now(timezone.utc)
        if min_exit_dt > now_utc:
            # Alert too recent to evaluate
            result.alerts_pending += 1
            continue
        
        # Calculate SYSTEM exit price (mechanical)
        system_exit_price, system_exit_ts, system_exit_reason = _get_exit_price(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_ts=entry_ts,
            entry_price=entry_price,
            hold_hours=hold_hours,
            stop_loss_price=stop_loss_price,
        )
        
        if system_exit_price is None:
            if verbose:
                print(f"   [{symbol}] ⚠️  Could not get exit price: {system_exit_reason}")
            continue
        
        # Calculate SYSTEM P&L with friction
        system_pnl_dollars, system_pnl_percent = _calculate_pnl(
            direction=direction,
            entry_price=entry_price,
            exit_price=system_exit_price,
            capital=config.capital_usd_per_alert,
            friction_bps=config.friction_bps,
        )
        
        # Calculate actual hold time
        if system_exit_ts:
            exit_dt = datetime.fromisoformat(system_exit_ts.replace('Z', '+00:00'))
            actual_hold_hours = (exit_dt - entry_dt).total_seconds() / 3600
        else:
            actual_hold_hours = hold_hours
        
        # Create SYSTEM outcome
        system_outcome = AlertOutcome(
            alert_id=alert_id,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            setup=setup,
            score=score,
            entry_price=entry_price,
            entry_ts=entry_ts,
            exit_price=system_exit_price,
            exit_ts=system_exit_ts,
            exit_reason=system_exit_reason,
            pnl_dollars=system_pnl_dollars,
            pnl_percent=system_pnl_percent,
            hold_hours=actual_hold_hours,
        )
        system_outcomes.append(system_outcome)
        
        # Record to database
        try:
            state.record_paper_pnl(
                alert_log_id=alert_id,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                entry_price=entry_price,
                exit_price=system_exit_price,
                exit_ts_utc=system_exit_ts,
                exit_reason=system_exit_reason,
                pnl_dollars=system_pnl_dollars,
                pnl_percent=system_pnl_percent,
                hold_hours=actual_hold_hours,
            )
        except Exception as e:
            logger.debug(f"Could not record paper pnl: {e}")
        
        # Check if trader TOOK this trade
        decision = decisions_map.get(alert_id)
        if decision and decision.get("action") == "TAKEN":
            # Calculate TRADER P&L using actual fills
            trader_entry = float(decision.get("entry_price", entry_price))
            trader_exit = decision.get("exit_price")
            trader_exit_ts = decision.get("exit_ts_utc")
            
            if trader_exit is not None:
                trader_exit = float(trader_exit)
                
                # Calculate TRADER P&L with friction
                trader_pnl_dollars, trader_pnl_percent = _calculate_pnl(
                    direction=direction,
                    entry_price=trader_entry,
                    exit_price=trader_exit,
                    capital=config.capital_usd_per_alert,
                    friction_bps=config.friction_bps,
                )
                
                # Calculate trader hold time
                if trader_exit_ts:
                    trader_exit_dt = datetime.fromisoformat(trader_exit_ts.replace('Z', '+00:00'))
                    trader_hold_hours = (trader_exit_dt - entry_dt).total_seconds() / 3600
                else:
                    trader_hold_hours = actual_hold_hours
                
                # Create TRADER outcome
                trader_outcome = AlertOutcome(
                    alert_id=alert_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    setup=setup,
                    score=score,
                    entry_price=trader_entry,
                    entry_ts=entry_ts,
                    exit_price=trader_exit,
                    exit_ts=trader_exit_ts,
                    exit_reason="MANUAL_EXIT",
                    pnl_dollars=trader_pnl_dollars,
                    pnl_percent=trader_pnl_percent,
                    hold_hours=trader_hold_hours,
                )
                trader_outcomes.append(trader_outcome)
        
        if verbose:
            emoji = "✅" if system_pnl_dollars > 0 else "❌" if system_pnl_dollars < 0 else "➖"
            trader_marker = "📝" if decision and decision.get("action") == "TAKEN" else ""
            print(f"   [{symbol}] {emoji} {direction} ${system_pnl_dollars:+.2f} ({system_pnl_percent:+.1f}%) {trader_marker}")
    
    result.system_outcomes = system_outcomes
    result.trader_outcomes = trader_outcomes
    result.alerts_evaluated = len(system_outcomes)
    
    # Calculate SYSTEM summary statistics
    if system_outcomes:
        result.system_pnl = sum(o.pnl_dollars for o in system_outcomes)
        result.system_avg_pnl = result.system_pnl / len(system_outcomes)
        result.system_wins = sum(1 for o in system_outcomes if o.pnl_dollars > 0)
        result.system_losses = sum(1 for o in system_outcomes if o.pnl_dollars < 0)
        result.system_breakeven = sum(1 for o in system_outcomes if o.pnl_dollars == 0)
        result.system_win_rate = (result.system_wins / len(system_outcomes)) * 100
        result.system_best_trade = max(o.pnl_dollars for o in system_outcomes)
        result.system_worst_trade = min(o.pnl_dollars for o in system_outcomes)
    
    # Calculate TRADER summary statistics
    if trader_outcomes:
        result.trader_pnl = sum(o.pnl_dollars for o in trader_outcomes)
        result.trader_avg_pnl = result.trader_pnl / len(trader_outcomes)
        result.trader_wins = sum(1 for o in trader_outcomes if o.pnl_dollars > 0)
        result.trader_losses = sum(1 for o in trader_outcomes if o.pnl_dollars < 0)
        result.trader_breakeven = sum(1 for o in trader_outcomes if o.pnl_dollars == 0)
        result.trader_win_rate = (result.trader_wins / len(trader_outcomes)) * 100
        result.trader_best_trade = max(o.pnl_dollars for o in trader_outcomes)
        result.trader_worst_trade = min(o.pnl_dollars for o in trader_outcomes)
        result.alerts_taken = len(trader_outcomes)
    
    # Legacy fields (use system values for backward compatibility)
    result.total_pnl = result.system_pnl
    result.avg_pnl = result.system_avg_pnl
    result.wins = result.system_wins
    result.losses = result.system_losses
    result.breakeven = result.system_breakeven
    result.win_rate = result.system_win_rate
    result.best_trade = result.system_best_trade
    result.worst_trade = result.system_worst_trade
    
    if verbose:
        print()
        print(f"📊 SYSTEM Performance (All Alerts, Mechanical + Friction):")
        print(f"   Alerts evaluated: {result.alerts_evaluated}")
        print(f"   Alerts pending:   {result.alerts_pending}")
        print(f"   Total P&L:        ${result.system_pnl:+.2f}")
        print(f"   Avg P&L:          ${result.system_avg_pnl:+.2f}")
        print(f"   Win Rate:         {result.system_win_rate:.1f}%")
        print(f"   Best Trade:       ${result.system_best_trade:+.2f}")
        print(f"   Worst Trade:      ${result.system_worst_trade:+.2f}")
        
        if trader_outcomes:
            print()
            print(f"👤 TRADER Performance (Taken Trades, Actual Fills + Friction):")
            print(f"   Trades taken:     {result.alerts_taken}")
            print(f"   Total P&L:        ${result.trader_pnl:+.2f}")
            print(f"   Avg P&L:          ${result.trader_avg_pnl:+.2f}")
            print(f"   Win Rate:         {result.trader_win_rate:.1f}%")
            print(f"   Best Trade:       ${result.trader_best_trade:+.2f}")
            print(f"   Worst Trade:      ${result.trader_worst_trade:+.2f}")
        
        if result.gate_go + result.gate_no_go > 0:
            print()
            print(f"🚦 Gate Decisions:")
            print(f"   GO:            {result.gate_go}")
            print(f"   NO_GO:         {result.gate_no_go}")
            print(f"   NOT_EVALUATED: {result.gate_not_evaluated}")
    
    return result


def export_csv(result: WeeklyAuditResult, output_path: str) -> str:
    """
    Export audit results to CSV.
    
    Exports SYSTEM performance (mechanical + friction) to the specified path.
    If trader data exists, also exports TRADER performance to a separate file.
    
    Args:
        result: WeeklyAuditResult to export
        output_path: Output file path for system performance
    
    Returns:
        Path to exported system CSV file
    """
    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Export SYSTEM performance (all alerts, mechanical)
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            "alert_id", "symbol", "timeframe", "direction", "setup", "score",
            "entry_price", "entry_ts", "exit_price", "exit_ts", "exit_reason",
            "pnl_dollars", "pnl_percent", "hold_hours"
        ])
        
        # Data
        for o in result.system_outcomes:
            writer.writerow([
                o.alert_id, o.symbol, o.timeframe, o.direction, o.setup, o.score,
                o.entry_price, o.entry_ts, o.exit_price, o.exit_ts, o.exit_reason,
                o.pnl_dollars, o.pnl_percent, o.hold_hours
            ])
    
    # Export TRADER performance if data exists (taken trades, actual fills)
    if result.alerts_taken > 0:
        # Generate trader CSV path
        trader_path = output_path.replace('.csv', '_trader.csv')
        
        # Get taken trades (need to fetch from state)
        # Note: This is a simplification - in production, you'd fetch from DB
        # For now, we'll create an empty trader CSV as placeholder
        with open(trader_path, 'w', newline='') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                "alert_id", "symbol", "timeframe", "direction", "setup", "score",
                "entry_price", "entry_ts", "exit_price", "exit_ts", "exit_reason",
                "pnl_dollars", "pnl_percent", "hold_hours"
            ])
            
            # Note: Trader outcomes are not stored in result.outcomes
            # They would need to be fetched separately from manual_decisions
            # This is a limitation of the current implementation
            # TODO: Add trader_outcomes field to WeeklyAuditResult
    
    return output_path


def send_email_report(
    result: WeeklyAuditResult,
    csv_path: str,
    recipients: List[str],
    subject_prefix: str = "[Trade Signals]",
) -> bool:
    """
    Send weekly audit report via email with CSV attachment.
    
    Args:
        result: WeeklyAuditResult with summary
        csv_path: Path to CSV file to attach
        recipients: List of recipient email addresses
        subject_prefix: Subject line prefix
    
    Returns:
        True if email sent successfully
    """
    # Get SMTP credentials from environment
    smtp_server = os.environ.get("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    smtp_user = os.environ.get("EMAIL_ADDRESS")
    smtp_pass = os.environ.get("EMAIL_APP_PASSWORD")
    
    if not smtp_user or not smtp_pass:
        logger.error("Email credentials not configured (EMAIL_ADDRESS, EMAIL_APP_PASSWORD)")
        return False
    
    if not recipients:
        logger.warning("No email recipients configured")
        return False
    
    # Build email
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = f"{subject_prefix} Weekly Audit Report ({result.start_date[:10]} - {result.end_date[:10]})"
    
    # Build body
    body_lines = [
        "Weekly Trade Signals Audit Report",
        "=" * 40,
        "",
        f"Period: {result.start_date[:10]} to {result.end_date[:10]}",
        "",
        "SUMMARY",
        "-" * 20,
        f"Total Alerts:     {result.total_alerts}",
        f"Alerts Evaluated: {result.alerts_evaluated}",
        f"Alerts Pending:   {result.alerts_pending}",
        "",
        "PAPER P&L ($100/alert)",
        "-" * 20,
        f"Total P&L:    ${result.total_pnl:+.2f}",
        f"Avg P&L:      ${result.avg_pnl:+.2f}",
        f"Win Rate:     {result.win_rate:.1f}%",
        f"Wins:         {result.wins}",
        f"Losses:       {result.losses}",
        f"Best Trade:   ${result.best_trade:+.2f}",
        f"Worst Trade:  ${result.worst_trade:+.2f}",
        "",
    ]
    
    if result.gate_go + result.gate_no_go > 0:
        body_lines.extend([
            "GATE DECISIONS",
            "-" * 20,
            f"GO:            {result.gate_go}",
            f"NO_GO:         {result.gate_no_go}",
            f"NOT_EVALUATED: {result.gate_not_evaluated}",
            "",
        ])
    
    body_lines.extend([
        "See attached CSV for detailed trade-by-trade breakdown.",
        "",
        "---",
        "This is an automated report from the Trading App.",
    ])
    
    body = "\n".join(body_lines)
    msg.attach(MIMEText(body, 'plain'))
    
    # Attach CSV
    if csv_path and Path(csv_path).exists():
        try:
            with open(csv_path, 'rb') as f:
                attachment = MIMEBase('application', 'octet-stream')
                attachment.set_payload(f.read())
                encoders.encode_base64(attachment)
                
                filename = Path(csv_path).name
                attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{filename}"'
                )
                msg.attach(attachment)
        except Exception as e:
            logger.warning(f"Could not attach CSV: {e}")
    
    # Send
    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        
        logger.info(f"Weekly audit email sent to {len(recipients)} recipients")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_telegram_report(result: WeeklyAuditResult) -> bool:
    """
    Send weekly audit report via Telegram.
    
    Args:
        result: WeeklyAuditResult with summary
    
    Returns:
        True if message sent successfully
    """
    notifier = TelegramNotifier()
    
    if not notifier.enabled():
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
        return False
    
    # Build compact message for Telegram
    lines = [
        f"📊 Weekly Audit: {result.start_date[:10]} → {result.end_date[:10]}",
        "",
        f"📈 Alerts: {result.total_alerts} total ({result.alerts_evaluated} evaluated)",
    ]
    
    # System performance
    sys_emoji = "🟢" if result.system_pnl >= 0 else "🔴"
    lines.extend([
        "",
        f"🤖 SYSTEM (all alerts, $100 each):",
        f"  {sys_emoji} P&L: ${result.system_pnl:+.2f}",
        f"  Win Rate: {result.system_win_rate:.0f}% ({result.system_wins}W/{result.system_losses}L)",
        f"  Best: ${result.system_best_trade:+.2f} | Worst: ${result.system_worst_trade:+.2f}",
    ])
    
    # Trader performance (if any trades taken)
    if result.alerts_taken > 0:
        trader_emoji = "🟢" if result.trader_pnl >= 0 else "🔴"
        lines.extend([
            "",
            f"👤 TRADER ({result.alerts_taken} trades taken):",
            f"  {trader_emoji} P&L: ${result.trader_pnl:+.2f}",
            f"  Win Rate: {result.trader_win_rate:.0f}% ({result.trader_wins}W/{result.trader_losses}L)",
        ])
    
    # Gate stats (if v2 mode)
    if result.gate_go + result.gate_no_go > 0:
        lines.extend([
            "",
            f"🚦 Gate: {result.gate_go} GO | {result.gate_no_go} NO_GO",
        ])
    
    message = "\n".join(lines)
    
    try:
        notifier.send("", message)  # Title already in message
        logger.info("Weekly audit sent to Telegram")
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram report: {e}")
        return False


def main():
    """CLI entry point for weekly audit."""
    parser = argparse.ArgumentParser(
        description="Generate weekly audit report for trade signals"
    )
    parser.add_argument(
        "--lookback-days", "-d",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)"
    )
    parser.add_argument(
        "--capital", "-c",
        type=float,
        default=100.0,
        help="Capital per alert in USD (default: 100)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="state.db",
        help="Path to SQLite database (default: state.db)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="reports",
        help="Output directory for CSV files (default: reports)"
    )
    parser.add_argument(
        "--email", "-e",
        action="store_true",
        help="Send report via email"
    )
    parser.add_argument(
        "--telegram", "-t",
        action="store_true",
        help="Send report via Telegram"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output summary as JSON"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress console output"
    )
    
    args = parser.parse_args()
    
    # Load config
    app_config = _load_config()
    report_config = app_config.get("report_delivery", {})
    calibration_config = app_config.get("calibration_logging", {})
    
    # Build audit config
    config = WeeklyAuditConfig(
        lookback_days=args.lookback_days,
        capital_usd_per_alert=args.capital,
        hold_hours_by_timeframe=calibration_config.get("hold_hours_by_timeframe", {}),
        output_dir=args.output_dir,
        state_db=args.db,
    )
    
    # Run audit
    result = run_weekly_audit(config, verbose=not args.quiet)
    
    # Export CSV
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = Path(args.output_dir) / f"weekly_audit_{timestamp}.csv"
    export_csv(result, str(csv_path))
    
    if not args.quiet:
        print(f"\n📁 CSV exported to: {csv_path}")
    
    # Send email if requested
    if args.email:
        email_config = report_config.get("email", {})
        recipients = email_config.get("recipients", [])
        subject_prefix = email_config.get("subject_prefix", "[Trade Signals]")
        
        if recipients:
            success = send_email_report(
                result=result,
                csv_path=str(csv_path),
                recipients=recipients,
                subject_prefix=subject_prefix,
            )
            if not args.quiet:
                if success:
                    print(f"📧 Email sent to: {', '.join(recipients)}")
                else:
                    print(f"❌ Failed to send email")
        else:
            if not args.quiet:
                print("⚠️  No email recipients configured in config.yaml")
    
    # Send Telegram if requested
    if args.telegram:
        telegram_config = report_config.get("telegram", {})
        telegram_enabled = telegram_config.get("enabled", False)
        
        if telegram_enabled or args.telegram:  # --telegram flag overrides config
            success = send_telegram_report(result)
            if not args.quiet:
                if success:
                    print(f"📱 Telegram report sent")
                else:
                    print(f"❌ Failed to send Telegram report")
    
    # JSON output
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
