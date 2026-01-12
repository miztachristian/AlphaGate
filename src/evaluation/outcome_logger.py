"""Outcome Logger: Post-alert evaluation pipeline.

Reads triggered alerts from SQLite, computes MFE/MAE and forward returns
over configurable horizons, and writes results to alert_outcomes table.

Usage:
    python -m src.evaluation.outcome_logger --db-path alerts_log.db --max-alerts 500
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


class EvaluationStatus(str, Enum):
    """Evaluation status for an alert outcome."""
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Interval to minutes mapping
INTERVAL_MINUTES: Dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def get_interval_minutes(timeframe: str) -> int:
    """Get interval duration in minutes from timeframe string."""
    return INTERVAL_MINUTES.get(timeframe, 60)


def generate_alert_id(
    ts_utc: str,
    symbol: str,
    timeframe: str,
    setup: str,
    direction: str,
    trigger_close: float,
) -> str:
    """
    Generate deterministic alert_id using SHA-256 hash.
    
    Format: sha256(ts_utc|symbol|timeframe|setup|direction|trigger_close_rounded)
    """
    trigger_rounded = round(trigger_close, 4)
    key = f"{ts_utc}|{symbol}|{timeframe}|{setup}|{direction}|{trigger_rounded}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


@dataclass
class OutcomeConfig:
    """Configuration for outcome evaluation."""
    horizons_1h: List[int] = field(default_factory=lambda: [4, 12, 24, 48])
    horizons_4h: List[int] = field(default_factory=lambda: [24, 48, 72])
    horizons_1d: List[int] = field(default_factory=lambda: [24, 72, 168])
    mfe_mae_use_high_low: bool = True
    hit_target_atr: float = 1.0
    hit_stop_atr: float = 0.7
    horizon_tolerance_bars: int = 1

    @classmethod
    def from_config(cls, config: Dict) -> "OutcomeConfig":
        """Load from config.yaml structure."""
        outcome = config.get("outcome_eval", {})
        hit_rule = outcome.get("hit_rule", {})
        return cls(
            horizons_1h=outcome.get("horizons_1h", [4, 12, 24, 48]),
            horizons_4h=outcome.get("horizons_4h", [24, 48, 72]),
            horizons_1d=outcome.get("horizons_1d", [24, 72, 168]),
            mfe_mae_use_high_low=outcome.get("mfe_mae_use_high_low", True),
            hit_target_atr=hit_rule.get("target_atr", 1.0),
            hit_stop_atr=hit_rule.get("stop_atr", 0.7),
            horizon_tolerance_bars=outcome.get("horizon_tolerance_bars", 1),
        )

    def get_horizons(self, timeframe: str) -> List[int]:
        """Get horizons for a given timeframe."""
        if timeframe == "1h":
            return self.horizons_1h
        elif timeframe == "4h":
            return self.horizons_4h
        elif timeframe == "1d":
            return self.horizons_1d
        else:
            # Default to 1h horizons for unknown timeframes
            return self.horizons_1h


@dataclass
class OutcomeRecord:
    """Single outcome record for an alert."""
    alert_id: str
    ts_utc: str
    symbol: str
    timeframe: str
    setup: str
    direction: str
    score: Optional[int]
    entry_price: float
    atr_at_alert: float
    bar_interval_minutes: int
    
    # Per-horizon results (horizon_hours -> value)
    forward_returns: Dict[int, Optional[float]] = field(default_factory=dict)
    mfe: Dict[int, Optional[float]] = field(default_factory=dict)
    mae: Dict[int, Optional[float]] = field(default_factory=dict)
    hit: Dict[int, Optional[bool]] = field(default_factory=dict)
    
    evaluation_status: EvaluationStatus = EvaluationStatus.PENDING
    evaluated_at_utc: Optional[str] = None
    notes: str = ""
    
    # Regime tags from original alert
    trend_regime: Optional[str] = None
    vol_regime: Optional[str] = None


def _load_config() -> Dict:
    """Load config.yaml."""
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _init_outcomes_table(conn: sqlite3.Connection) -> None:
    """Create alert_outcomes table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_outcomes (
            alert_id TEXT PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            setup TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER,
            entry_price REAL NOT NULL,
            atr_at_alert REAL NOT NULL,
            bar_interval_minutes INTEGER NOT NULL,
            
            -- Forward returns (JSON encoded for flexibility)
            forward_returns_json TEXT,
            mfe_json TEXT,
            mae_json TEXT,
            hit_json TEXT,
            
            evaluation_status TEXT NOT NULL,
            evaluated_at_utc TEXT,
            notes TEXT,
            
            -- Regime tags
            trend_regime TEXT,
            vol_regime TEXT
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outcomes_symbol ON alert_outcomes(symbol, timeframe);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outcomes_status ON alert_outcomes(evaluation_status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outcomes_ts ON alert_outcomes(ts_utc);"
    )
    conn.commit()


def load_alerts_needing_evaluation(
    db_path: str,
    lookback_hours: int = 168,
    max_alerts: int = 500,
) -> List[Dict[str, Any]]:
    """
    Load alerts that need outcome evaluation.
    
    Returns alerts that:
    1. Have no outcome record yet, OR
    2. Have evaluation_status = PENDING
    
    Args:
        db_path: Path to SQLite database
        lookback_hours: How far back to look for alerts (default 7 days)
        max_alerts: Maximum number of alerts to return
        
    Returns:
        List of alert dictionaries
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Ensure outcomes table exists
    _init_outcomes_table(conn)
    
    cutoff = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    
    # Find alerts without outcomes or with PENDING status
    query = """
        SELECT al.* FROM alerts_log al
        LEFT JOIN alert_outcomes ao ON (
            -- Match by deterministic ID components
            ao.ts_utc = al.ts_utc
            AND ao.symbol = al.symbol
            AND ao.timeframe = al.timeframe
            AND ao.setup = al.setup
            AND ao.direction = al.direction
        )
        WHERE al.ts_utc >= ?
        AND (ao.alert_id IS NULL OR ao.evaluation_status = 'PENDING')
        ORDER BY al.ts_utc ASC
        LIMIT ?
    """
    
    rows = conn.execute(query, (cutoff, max_alerts)).fetchall()
    conn.close()
    
    alerts = []
    for row in rows:
        alert = dict(row)
        # Use existing id if available, otherwise generate deterministic ID
        if alert.get("id"):
            alert["alert_id"] = f"db_{alert['id']}"
        else:
            alert["alert_id"] = generate_alert_id(
                ts_utc=alert["ts_utc"],
                symbol=alert["symbol"],
                timeframe=alert["timeframe"],
                setup=alert["setup"],
                direction=alert["direction"],
                trigger_close=alert.get("trigger_close", 0),
            )
        alerts.append(alert)
    
    return alerts


def _find_close_at_horizon(
    ohlcv_df: pd.DataFrame,
    alert_ts: datetime,
    horizon_hours: int,
    interval_minutes: int,
    tolerance_bars: int = 1,
) -> Tuple[Optional[float], bool]:
    """
    Find the close price at or before the horizon end time.
    
    Returns:
        (close_price, is_complete) - None if no data available
    """
    horizon_end = alert_ts + timedelta(hours=horizon_hours)
    
    # Filter to bars at or before horizon_end
    valid_bars = ohlcv_df[ohlcv_df.index <= horizon_end]
    
    if valid_bars.empty:
        return None, False
    
    last_bar_ts = valid_bars.index[-1]
    last_close = float(valid_bars.iloc[-1]["close"])
    
    # Check if we have enough bars (within tolerance)
    tolerance_td = timedelta(minutes=interval_minutes * tolerance_bars)
    gap = horizon_end - last_bar_ts
    
    is_complete = gap <= tolerance_td
    
    return last_close, is_complete


def _compute_mfe_mae(
    ohlcv_df: pd.DataFrame,
    alert_ts: datetime,
    horizon_hours: int,
    entry_price: float,
    direction: str,
    use_high_low: bool = True,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute MFE (Maximum Favorable Excursion) and MAE (Maximum Adverse Excursion).
    
    For LONG:
        MFE = (max_high - entry) / entry * 100
        MAE = (min_low - entry) / entry * 100 (negative)
    
    For SHORT: inverted
    
    Returns:
        (mfe_pct, mae_pct)
    """
    horizon_end = alert_ts + timedelta(hours=horizon_hours)
    
    # Window: from alert time to horizon end
    window = ohlcv_df[(ohlcv_df.index > alert_ts) & (ohlcv_df.index <= horizon_end)]
    
    if window.empty:
        return None, None
    
    if use_high_low:
        max_price = float(window["high"].max())
        min_price = float(window["low"].min())
    else:
        max_price = float(window["close"].max())
        min_price = float(window["close"].min())
    
    if direction.upper() == "LONG":
        mfe = (max_price - entry_price) / entry_price * 100
        mae = (min_price - entry_price) / entry_price * 100
    else:  # SHORT
        mfe = (entry_price - min_price) / entry_price * 100
        mae = (entry_price - max_price) / entry_price * 100
    
    return mfe, mae


def _check_hit(
    ohlcv_df: pd.DataFrame,
    alert_ts: datetime,
    horizon_hours: int,
    entry_price: float,
    atr: float,
    direction: str,
    target_atr: float,
    stop_atr: float,
) -> Optional[bool]:
    """
    Check if target was hit before stop within the horizon window.
    
    CRITICAL tie-break: If same candle touches both target and stop,
    count as stop-first (hit=False) to be conservative.
    
    Returns:
        True if target hit first, False if stop hit first or neither, None if no data
    """
    horizon_end = alert_ts + timedelta(hours=horizon_hours)
    window = ohlcv_df[(ohlcv_df.index > alert_ts) & (ohlcv_df.index <= horizon_end)]
    
    if window.empty:
        return None
    
    if direction.upper() == "LONG":
        target_price = entry_price + (target_atr * atr)
        stop_price = entry_price - (stop_atr * atr)
        
        for ts, bar in window.iterrows():
            high = float(bar["high"])
            low = float(bar["low"])
            
            target_touched = high >= target_price
            stop_touched = low <= stop_price
            
            # Tie-break: if both touched in same candle, stop wins (conservative)
            if target_touched and stop_touched:
                return False
            if stop_touched:
                return False
            if target_touched:
                return True
    else:  # SHORT
        target_price = entry_price - (target_atr * atr)
        stop_price = entry_price + (stop_atr * atr)
        
        for ts, bar in window.iterrows():
            high = float(bar["high"])
            low = float(bar["low"])
            
            target_touched = low <= target_price
            stop_touched = high >= stop_price
            
            if target_touched and stop_touched:
                return False
            if stop_touched:
                return False
            if target_touched:
                return True
    
    # Neither target nor stop hit within window
    return False


def compute_outcomes_for_alert(
    alert: Dict[str, Any],
    ohlcv_df: pd.DataFrame,
    config: OutcomeConfig,
) -> OutcomeRecord:
    """
    Compute outcome metrics for a single alert.
    
    Args:
        alert: Alert dictionary from database
        ohlcv_df: OHLCV DataFrame with data covering the evaluation window
        config: Outcome evaluation configuration
        
    Returns:
        OutcomeRecord with computed metrics
    """
    # Parse alert timestamp
    ts_utc_str = alert["ts_utc"]
    try:
        alert_ts = datetime.fromisoformat(ts_utc_str.replace("Z", "+00:00"))
        if alert_ts.tzinfo is None:
            alert_ts = alert_ts.replace(tzinfo=timezone.utc)
    except Exception:
        alert_ts = datetime.fromisoformat(ts_utc_str)
        if alert_ts.tzinfo is None:
            alert_ts = alert_ts.replace(tzinfo=timezone.utc)
    
    timeframe = alert["timeframe"]
    direction = alert["direction"]
    interval_minutes = get_interval_minutes(timeframe)
    
    # Determine entry price
    entry_zone_low = alert.get("entry_zone_low")
    entry_zone_high = alert.get("entry_zone_high")
    trigger_close = alert.get("trigger_close", 0)
    
    if entry_zone_low and entry_zone_high:
        entry_price = (float(entry_zone_low) + float(entry_zone_high)) / 2
    else:
        entry_price = float(trigger_close)
    
    atr = float(alert.get("atr", 0))
    
    # Create outcome record
    outcome = OutcomeRecord(
        alert_id=alert["alert_id"],
        ts_utc=ts_utc_str,
        symbol=alert["symbol"],
        timeframe=timeframe,
        setup=alert["setup"],
        direction=direction,
        score=alert.get("score"),
        entry_price=entry_price,
        atr_at_alert=atr,
        bar_interval_minutes=interval_minutes,
        trend_regime=alert.get("trend_regime"),
        vol_regime=alert.get("vol_regime"),
    )
    
    # Check data availability
    if ohlcv_df.empty:
        outcome.evaluation_status = EvaluationStatus.INSUFFICIENT_DATA
        outcome.notes = "No OHLCV data available"
        outcome.evaluated_at_utc = datetime.utcnow().isoformat()
        return outcome
    
    # Ensure index is timezone-aware
    if ohlcv_df.index.tzinfo is None:
        ohlcv_df = ohlcv_df.copy()
        ohlcv_df.index = ohlcv_df.index.tz_localize(timezone.utc)
    
    # Get horizons for this timeframe
    horizons = config.get_horizons(timeframe)
    
    all_complete = True
    any_computed = False
    
    for horizon_hours in horizons:
        # Forward return
        close_at_h, is_complete = _find_close_at_horizon(
            ohlcv_df, alert_ts, horizon_hours, interval_minutes,
            config.horizon_tolerance_bars
        )
        
        if close_at_h is not None:
            if direction.upper() == "LONG":
                fwd_return = (close_at_h - entry_price) / entry_price * 100
            else:
                fwd_return = (entry_price - close_at_h) / entry_price * 100
            outcome.forward_returns[horizon_hours] = round(fwd_return, 4)
            any_computed = True
        else:
            outcome.forward_returns[horizon_hours] = None
        
        if not is_complete:
            all_complete = False
        
        # MFE/MAE
        mfe_val, mae_val = _compute_mfe_mae(
            ohlcv_df, alert_ts, horizon_hours, entry_price, direction,
            config.mfe_mae_use_high_low
        )
        outcome.mfe[horizon_hours] = round(mfe_val, 4) if mfe_val is not None else None
        outcome.mae[horizon_hours] = round(mae_val, 4) if mae_val is not None else None
        
        # Hit detection
        if atr > 0:
            hit_val = _check_hit(
                ohlcv_df, alert_ts, horizon_hours, entry_price, atr, direction,
                config.hit_target_atr, config.hit_stop_atr
            )
            outcome.hit[horizon_hours] = hit_val
        else:
            outcome.hit[horizon_hours] = None
    
    # Set final status
    if not any_computed:
        outcome.evaluation_status = EvaluationStatus.INSUFFICIENT_DATA
        outcome.notes = "No future candles available for evaluation"
    elif all_complete:
        outcome.evaluation_status = EvaluationStatus.COMPLETE
    else:
        outcome.evaluation_status = EvaluationStatus.PENDING
        outcome.notes = "Some horizons incomplete - will retry"
    
    outcome.evaluated_at_utc = datetime.utcnow().isoformat()
    return outcome


def upsert_outcome(db_path: str, record: OutcomeRecord) -> None:
    """
    Insert or update an outcome record.
    
    Uses INSERT OR REPLACE to handle both new and updated records.
    """
    conn = sqlite3.connect(db_path)
    _init_outcomes_table(conn)
    
    conn.execute("""
        INSERT OR REPLACE INTO alert_outcomes (
            alert_id, ts_utc, symbol, timeframe, setup, direction, score,
            entry_price, atr_at_alert, bar_interval_minutes,
            forward_returns_json, mfe_json, mae_json, hit_json,
            evaluation_status, evaluated_at_utc, notes,
            trend_regime, vol_regime
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record.alert_id,
        record.ts_utc,
        record.symbol,
        record.timeframe,
        record.setup,
        record.direction,
        record.score,
        record.entry_price,
        record.atr_at_alert,
        record.bar_interval_minutes,
        json.dumps(record.forward_returns),
        json.dumps(record.mfe),
        json.dumps(record.mae),
        json.dumps(record.hit),
        record.evaluation_status.value,
        record.evaluated_at_utc,
        record.notes,
        record.trend_regime,
        record.vol_regime,
    ))
    conn.commit()
    conn.close()


def run_outcome_evaluation(
    db_path: str,
    lookback_hours: int = 168,
    max_alerts: int = 500,
    config: Optional[OutcomeConfig] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Run the full outcome evaluation pipeline.
    
    Args:
        db_path: Path to SQLite database
        lookback_hours: How far back to look for alerts
        max_alerts: Maximum alerts to evaluate
        config: Outcome configuration (loads from config.yaml if None)
        verbose: Print progress to console
        
    Returns:
        Summary stats dict with counts by status
    """
    # Import here to avoid circular imports
    from ..marketdata.stocks_v2 import fetch_stock_ohlcv, INTERVAL_TIMEDELTA
    
    if config is None:
        config = OutcomeConfig.from_config(_load_config())
    
    if verbose:
        print(f"\n{'='*60}")
        print("OUTCOME EVALUATION PIPELINE")
        print(f"{'='*60}")
        print(f"Database: {db_path}")
        print(f"Lookback: {lookback_hours} hours")
        print(f"Max alerts: {max_alerts}")
    
    # Load alerts needing evaluation
    alerts = load_alerts_needing_evaluation(db_path, lookback_hours, max_alerts)
    
    if verbose:
        print(f"\nFound {len(alerts)} alerts to evaluate")
    
    if not alerts:
        return {
            "total": 0,
            "complete": 0,
            "pending": 0,
            "insufficient_data": 0,
            "errors": 0,
        }
    
    stats = {
        "total": len(alerts),
        "complete": 0,
        "pending": 0,
        "insufficient_data": 0,
        "errors": 0,
    }
    
    # Group alerts by symbol/timeframe for efficient OHLCV fetching
    from collections import defaultdict
    by_symbol_tf = defaultdict(list)
    for alert in alerts:
        key = (alert["symbol"], alert["timeframe"])
        by_symbol_tf[key].append(alert)
    
    if verbose:
        print(f"Grouped into {len(by_symbol_tf)} symbol/timeframe combinations")
    
    # Process each group
    for (symbol, timeframe), group_alerts in by_symbol_tf.items():
        if verbose:
            print(f"\nProcessing {symbol}/{timeframe}: {len(group_alerts)} alerts")
        
        # Determine time range needed
        horizons = config.get_horizons(timeframe)
        max_horizon_hours = max(horizons) if horizons else 48
        
        # Get earliest alert timestamp
        earliest_ts = min(a["ts_utc"] for a in group_alerts)
        try:
            earliest_dt = datetime.fromisoformat(earliest_ts.replace("Z", "+00:00"))
        except:
            earliest_dt = datetime.utcnow() - timedelta(hours=lookback_hours)
        
        # Fetch OHLCV covering alert time + max horizon
        # Add extra buffer for safety
        lookback_days = (datetime.utcnow() - earliest_dt).days + (max_horizon_hours // 24) + 3
        lookback_days = max(lookback_days, 7)
        
        try:
            ohlcv_df = fetch_stock_ohlcv(
                ticker=symbol,
                interval=timeframe,
                lookback_days=lookback_days,
            )
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}/{timeframe}: {e}")
            for alert in group_alerts:
                outcome = OutcomeRecord(
                    alert_id=alert["alert_id"],
                    ts_utc=alert["ts_utc"],
                    symbol=symbol,
                    timeframe=timeframe,
                    setup=alert["setup"],
                    direction=alert["direction"],
                    score=alert.get("score"),
                    entry_price=float(alert.get("trigger_close", 0)),
                    atr_at_alert=float(alert.get("atr", 0)),
                    bar_interval_minutes=get_interval_minutes(timeframe),
                    evaluation_status=EvaluationStatus.INSUFFICIENT_DATA,
                    notes=f"OHLCV fetch error: {str(e)[:100]}",
                    evaluated_at_utc=datetime.utcnow().isoformat(),
                )
                try:
                    upsert_outcome(db_path, outcome)
                except Exception as db_err:
                    logger.error(f"DB error: {db_err}")
                    stats["errors"] += 1
                stats["insufficient_data"] += 1
            continue
        
        # Evaluate each alert in the group
        for alert in group_alerts:
            try:
                outcome = compute_outcomes_for_alert(alert, ohlcv_df, config)
                upsert_outcome(db_path, outcome)
                
                if outcome.evaluation_status == EvaluationStatus.COMPLETE:
                    stats["complete"] += 1
                elif outcome.evaluation_status == EvaluationStatus.PENDING:
                    stats["pending"] += 1
                else:
                    stats["insufficient_data"] += 1
                    
            except Exception as e:
                logger.error(f"Error evaluating alert {alert.get('alert_id')}: {e}")
                stats["errors"] += 1
    
    if verbose:
        print(f"\n{'='*60}")
        print("EVALUATION SUMMARY")
        print(f"{'='*60}")
        print(f"Total alerts:       {stats['total']}")
        print(f"Complete:           {stats['complete']}")
        print(f"Pending:            {stats['pending']}")
        print(f"Insufficient data:  {stats['insufficient_data']}")
        print(f"Errors:             {stats['errors']}")
    
    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate outcomes for triggered alerts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Evaluate all alerts from last 7 days
    python -m src.evaluation.outcome_logger --db-path alerts_log.db
    
    # Evaluate with custom lookback
    python -m src.evaluation.outcome_logger --db-path alerts_log.db --lookback-hours 336
    
    # Limit number of alerts
    python -m src.evaluation.outcome_logger --db-path alerts_log.db --max-alerts 100
        """,
    )
    
    parser.add_argument(
        "--db-path",
        default="alerts_log.db",
        help="Path to SQLite database (default: alerts_log.db)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=168,
        help="How far back to look for alerts in hours (default: 168 = 7 days)",
    )
    parser.add_argument(
        "--max-alerts",
        type=int,
        default=500,
        help="Maximum number of alerts to evaluate (default: 500)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO if not args.quiet else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Run evaluation
    stats = run_outcome_evaluation(
        db_path=args.db_path,
        lookback_hours=args.lookback_hours,
        max_alerts=args.max_alerts,
        verbose=not args.quiet,
    )
    
    # Return code based on errors
    exit_code = 0 if stats["errors"] == 0 else 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
