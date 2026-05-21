"""SQLite-backed state store.

Used to prevent duplicate notifications (e.g., don't alert LONG every minute).
Also logs alerts for calibration purposes.
Also stores V2 gate decisions and paper P&L tracking.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List


class SqliteStateStore:
    def __init__(self, path: str = "state.db"):
        self.path = path
        # For in-memory databases, use file::memory:?cache=shared URI
        # This allows multiple connections to share the same in-memory DB
        if path == ":memory:":
            self._uri = "file::memory:?cache=shared"
        else:
            self._uri = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._uri:
            return sqlite3.connect(self._uri, uri=True)
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            # Original alerts table for cooldown tracking
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_ticker_time ON alerts(ticker, timeframe, created_at);"
            )
            
            # New alerts_log table for calibration
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    setup TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    score INTEGER,
                    trigger_close REAL,
                    rsi REAL,
                    rsi_prev REAL,
                    atr REAL,
                    atr_pct REAL,
                    ema200 REAL,
                    ema200_slope REAL,
                    trend_regime TEXT,
                    vol_regime TEXT,
                    bb_lower REAL,
                    bb_middle REAL,
                    bb_upper REAL,
                    entry_zone_low REAL,
                    entry_zone_high REAL,
                    invalidation REAL,
                    news_risk TEXT,
                    news_reasons_json TEXT,
                    alert_payload_json TEXT
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_log_symbol ON alerts_log(symbol, timeframe, ts_utc);"
            )
            
            # V2 gate decisions table - logs all gate evaluations
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gate_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    setup TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    gate_status TEXT NOT NULL,
                    gate_reasons_json TEXT,
                    scrutiny_level TEXT,
                    gate_tags_json TEXT,
                    alert_log_id INTEGER,
                    FOREIGN KEY (alert_log_id) REFERENCES alerts_log(id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gate_decisions_symbol ON gate_decisions(symbol, ts_utc);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gate_decisions_status ON gate_decisions(gate_status, ts_utc);"
            )
            
            # V2 alerts table - only alerts that passed the gate (engine.mode=v2)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    setup TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    score INTEGER,
                    trigger_close REAL,
                    scrutiny_level TEXT,
                    gate_decision_id INTEGER,
                    alert_log_id INTEGER,
                    FOREIGN KEY (gate_decision_id) REFERENCES gate_decisions(id),
                    FOREIGN KEY (alert_log_id) REFERENCES alerts_log(id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_alerts_symbol ON v2_alerts(symbol, ts_utc);"
            )
            
            # Paper P&L table - tracks simulated $100-per-alert outcomes
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_pnl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_log_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    exit_ts_utc TEXT,
                    exit_reason TEXT,
                    pnl_dollars REAL,
                    pnl_percent REAL,
                    hold_hours REAL,
                    evaluated_at TEXT,
                    FOREIGN KEY (alert_log_id) REFERENCES alerts_log(id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_pnl_alert ON paper_pnl(alert_log_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_pnl_evaluated ON paper_pnl(evaluated_at);"
            )
            
            # Manual trade journal - tracks trader's actual TAKEN/SKIPPED decisions
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_log_id INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    decision_ts_utc TEXT NOT NULL,
                    entry_ts_utc TEXT,
                    entry_price REAL,
                    stop_price REAL,
                    size_usd REAL,
                    exit_price REAL,
                    exit_ts_utc TEXT,
                    skip_reason TEXT,
                    note TEXT,
                    UNIQUE(alert_log_id),
                    FOREIGN KEY (alert_log_id) REFERENCES alerts_log(id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_manual_decisions_alert ON manual_decisions(alert_log_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_manual_decisions_decision ON manual_decisions(decision, decision_ts_utc);"
            )
            
            conn.commit()

    def recently_alerted(
        self,
        ticker: str,
        timeframe: str,
        signal: str,
        cooldown_minutes: int = 60,
    ) -> bool:
        cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT created_at FROM alerts
                WHERE ticker = ? AND timeframe = ? AND signal = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (ticker.upper(), timeframe, signal),
            ).fetchone()

        if not row:
            return False

        try:
            last = datetime.fromisoformat(row[0])
        except Exception:
            return False

        return last >= cutoff
    
    def get_last_alert_time(
        self,
        ticker: str,
        timeframe: str,
        signal: str,
    ) -> Optional[datetime]:
        """Get the timestamp of the last alert for this ticker/timeframe/signal."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT created_at FROM alerts
                WHERE ticker = ? AND timeframe = ? AND signal = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (ticker.upper(), timeframe, signal),
            ).fetchone()
        
        if not row:
            return None
        
        try:
            return datetime.fromisoformat(row[0])
        except Exception:
            return None

    def record_alert(self, ticker: str, timeframe: str, signal: str, confidence: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO alerts(ticker, timeframe, signal, confidence, created_at) VALUES(?,?,?,?,?);",
                (ticker.upper(), timeframe, signal, confidence, datetime.utcnow().isoformat()),
            )
            conn.commit()
    
    def log_alert_for_calibration(
        self,
        symbol: str,
        timeframe: str,
        setup: str,
        direction: str,
        score: int,
        trigger_close: float,
        rsi: float,
        rsi_prev: float,
        atr: float,
        atr_pct: float,
        ema200: float,
        ema200_slope: float,
        trend_regime: str,
        vol_regime: str,
        bb_lower: float,
        bb_middle: float,
        bb_upper: float,
        entry_zone_low: float,
        entry_zone_high: float,
        invalidation: float,
        news_risk: str,
        news_reasons: list,
        alert_payload: Dict[str, Any],
    ) -> int:
        """
        Log alert details for later calibration analysis.
        
        Returns the inserted row ID.
        """
        ts_utc = datetime.utcnow().isoformat()
        news_reasons_json = json.dumps(news_reasons)
        alert_payload_json = json.dumps(alert_payload)
        
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO alerts_log (
                    ts_utc, symbol, timeframe, setup, direction, score,
                    trigger_close, rsi, rsi_prev, atr, atr_pct,
                    ema200, ema200_slope, trend_regime, vol_regime,
                    bb_lower, bb_middle, bb_upper,
                    entry_zone_low, entry_zone_high, invalidation,
                    news_risk, news_reasons_json, alert_payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
                """,
                (
                    ts_utc, symbol.upper(), timeframe, setup, direction, score,
                    trigger_close, rsi, rsi_prev, atr, atr_pct,
                    ema200, ema200_slope, trend_regime, vol_regime,
                    bb_lower, bb_middle, bb_upper,
                    entry_zone_low, entry_zone_high, invalidation,
                    news_risk, news_reasons_json, alert_payload_json,
                ),
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_recent_alerts_log(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """Retrieve recent alert logs for analysis."""
        query = "SELECT * FROM alerts_log"
        params = []
        conditions = []
        
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY ts_utc DESC LIMIT ?"
        params.append(limit)
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]
    
    # ============ V2 Gate Methods ============
    
    def log_gate_decision(
        self,
        symbol: str,
        timeframe: str,
        setup: str,
        direction: str,
        gate_status: str,
        gate_reasons: List[str],
        scrutiny_level: str,
        gate_tags: Dict[str, Any],
        alert_log_id: Optional[int] = None,
    ) -> int:
        """
        Log a V2 gate decision.
        
        Returns the inserted row ID.
        """
        ts_utc = datetime.utcnow().isoformat()
        gate_reasons_json = json.dumps(gate_reasons)
        gate_tags_json = json.dumps(gate_tags)
        
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO gate_decisions (
                    ts_utc, symbol, timeframe, setup, direction,
                    gate_status, gate_reasons_json, scrutiny_level,
                    gate_tags_json, alert_log_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?);
                """,
                (
                    ts_utc, symbol.upper(), timeframe, setup, direction,
                    gate_status, gate_reasons_json, scrutiny_level,
                    gate_tags_json, alert_log_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid
    
    def log_v2_alert(
        self,
        symbol: str,
        timeframe: str,
        setup: str,
        direction: str,
        score: int,
        trigger_close: float,
        scrutiny_level: str,
        gate_decision_id: int,
        alert_log_id: Optional[int] = None,
    ) -> int:
        """
        Log a V2 alert (only for alerts that passed the gate).
        
        Returns the inserted row ID.
        """
        ts_utc = datetime.utcnow().isoformat()
        
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO v2_alerts (
                    ts_utc, symbol, timeframe, setup, direction,
                    score, trigger_close, scrutiny_level,
                    gate_decision_id, alert_log_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?);
                """,
                (
                    ts_utc, symbol.upper(), timeframe, setup, direction,
                    score, trigger_close, scrutiny_level,
                    gate_decision_id, alert_log_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_gate_decisions(
        self,
        gate_status: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve gate decisions with optional filters.
        
        Args:
            gate_status: Filter by status (GO, NO_GO, NOT_EVALUATED)
            symbol: Filter by symbol
            start_date: Filter by start date (ISO format)
            end_date: Filter by end date (ISO format)
            limit: Maximum rows to return
        """
        query = "SELECT * FROM gate_decisions"
        params = []
        conditions = []
        
        if gate_status:
            conditions.append("gate_status = ?")
            params.append(gate_status)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        if start_date:
            conditions.append("ts_utc >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("ts_utc <= ?")
            params.append(end_date)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY ts_utc DESC LIMIT ?"
        params.append(limit)
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]
    
    # ============ Paper P&L Methods ============
    
    def record_paper_pnl(
        self,
        alert_log_id: int,
        symbol: str,
        timeframe: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        exit_ts_utc: str,
        exit_reason: str,
        pnl_dollars: float,
        pnl_percent: float,
        hold_hours: float,
    ) -> int:
        """
        Record paper P&L for an alert.
        
        Returns the inserted row ID.
        """
        evaluated_at = datetime.utcnow().isoformat()
        
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_pnl (
                    alert_log_id, symbol, timeframe, direction,
                    entry_price, exit_price, exit_ts_utc, exit_reason,
                    pnl_dollars, pnl_percent, hold_hours, evaluated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?);
                """,
                (
                    alert_log_id, symbol.upper(), timeframe, direction,
                    entry_price, exit_price, exit_ts_utc, exit_reason,
                    pnl_dollars, pnl_percent, hold_hours, evaluated_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_unevaluated_alerts_for_pnl(
        self,
        min_age_hours: float = 24,
        timeframe: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get alerts that haven't had paper P&L calculated yet.
        
        Args:
            min_age_hours: Minimum age of alert before evaluation
            timeframe: Optional filter by timeframe
        """
        cutoff = (datetime.utcnow() - timedelta(hours=min_age_hours)).isoformat()
        
        query = """
            SELECT al.* FROM alerts_log al
            LEFT JOIN paper_pnl pp ON al.id = pp.alert_log_id
            WHERE pp.id IS NULL AND al.ts_utc <= ?
        """
        params = [cutoff]
        
        if timeframe:
            query += " AND al.timeframe = ?"
            params.append(timeframe)
        
        query += " ORDER BY al.ts_utc ASC"
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]
    
    def get_paper_pnl_summary(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for paper P&L.
        
        Args:
            start_date: Filter by start date (ISO format)
            end_date: Filter by end date (ISO format)
        """
        query = """
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl_dollars < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN pnl_dollars = 0 THEN 1 ELSE 0 END) as breakeven,
                SUM(pnl_dollars) as total_pnl,
                AVG(pnl_dollars) as avg_pnl,
                AVG(pnl_percent) as avg_pnl_pct,
                AVG(hold_hours) as avg_hold_hours,
                MAX(pnl_dollars) as best_trade,
                MIN(pnl_dollars) as worst_trade
            FROM paper_pnl
        """
        params = []
        conditions = []
        
        if start_date:
            conditions.append("evaluated_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("evaluated_at <= ?")
            params.append(end_date)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, params).fetchone()
        
        if row:
            result = dict(row)
            # Calculate win rate
            total = result.get("total_trades", 0) or 0
            wins = result.get("wins", 0) or 0
            result["win_rate"] = (wins / total * 100) if total > 0 else 0
            return result
        
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "avg_pnl_pct": 0,
            "avg_hold_hours": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "win_rate": 0,
        }
    
    def get_paper_pnl_details(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Get detailed paper P&L records.
        
        Args:
            start_date: Filter by start date (ISO format)
            end_date: Filter by end date (ISO format)
            symbol: Filter by symbol
            limit: Maximum rows to return
        """
        query = """
            SELECT pp.*, al.setup, al.score, al.ts_utc as alert_ts
            FROM paper_pnl pp
            JOIN alerts_log al ON pp.alert_log_id = al.id
        """
        params = []
        conditions = []
        
        if start_date:
            conditions.append("pp.evaluated_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("pp.evaluated_at <= ?")
            params.append(end_date)
        if symbol:
            conditions.append("pp.symbol = ?")
            params.append(symbol.upper())
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY pp.evaluated_at DESC LIMIT ?"
        params.append(limit)
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]
    
    # =========================================================================
    # Manual Trade Journal Methods
    # =========================================================================
    
    def record_manual_decision(
        self,
        *,
        alert_log_id: int,
        decision: str,
        decision_ts_utc: Optional[str] = None,
        entry_ts_utc: Optional[str] = None,
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        size_usd: Optional[float] = None,
        skip_reason: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        """
        Record a manual trading decision (TAKEN or SKIPPED).
        
        Args:
            alert_log_id: ID from alerts_log table
            decision: "TAKEN" or "SKIPPED"
            decision_ts_utc: Timestamp of decision (default: now)
            entry_ts_utc: Actual entry timestamp (for TAKEN)
            entry_price: Actual entry fill price (required for TAKEN)
            stop_price: Actual stop loss price
            size_usd: Position size in USD
            skip_reason: Reason tag for skip (required for SKIPPED)
            note: Optional freeform note
        """
        decision_norm = (decision or "").strip().upper()
        if decision_norm not in {"TAKEN", "SKIPPED"}:
            raise ValueError("decision must be TAKEN or SKIPPED")
        
        if decision_norm == "TAKEN" and entry_price is None:
            raise ValueError("entry_price is required when decision is TAKEN")
        if decision_norm == "SKIPPED" and not (skip_reason or "").strip():
            raise ValueError("skip_reason is required when decision is SKIPPED")
        
        if decision_ts_utc is None:
            decision_ts_utc = datetime.utcnow().isoformat()
        
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO manual_decisions (
                    alert_log_id,
                    decision,
                    decision_ts_utc,
                    entry_ts_utc,
                    entry_price,
                    stop_price,
                    size_usd,
                    skip_reason,
                    note
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(alert_log_id) DO UPDATE SET
                    decision=excluded.decision,
                    decision_ts_utc=excluded.decision_ts_utc,
                    entry_ts_utc=excluded.entry_ts_utc,
                    entry_price=excluded.entry_price,
                    stop_price=excluded.stop_price,
                    size_usd=excluded.size_usd,
                    skip_reason=excluded.skip_reason,
                    note=excluded.note;
                """,
                (
                    int(alert_log_id),
                    decision_norm,
                    decision_ts_utc,
                    entry_ts_utc,
                    entry_price,
                    stop_price,
                    size_usd,
                    skip_reason,
                    note,
                ),
            )
            conn.commit()
    
    def record_manual_exit(
        self,
        *,
        alert_log_id: int,
        exit_price: float,
        exit_ts_utc: Optional[str] = None,
    ) -> None:
        """
        Record exit details for a taken trade.
        
        Args:
            alert_log_id: ID from alerts_log table
            exit_price: Actual exit fill price
            exit_ts_utc: Exit timestamp (default: now)
        """
        if exit_ts_utc is None:
            exit_ts_utc = datetime.utcnow().isoformat()
        
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE manual_decisions
                SET exit_price = ?, exit_ts_utc = ?
                WHERE alert_log_id = ?;
                """,
                (float(exit_price), exit_ts_utc, int(alert_log_id)),
            )
            conn.commit()
    
    def get_manual_decision(self, alert_log_id: int) -> Optional[Dict[str, Any]]:
        """Get a single manual decision by alert_log_id."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM manual_decisions WHERE alert_log_id = ?;",
                (int(alert_log_id),),
            ).fetchone()
        return dict(row) if row else None
    
    def get_manual_decisions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all manual decisions in a date range.
        
        Args:
            start_date: Start date (ISO format, default: all)
            end_date: End date (ISO format, default: all)
        
        Returns:
            List of manual decisions as dicts
        """
        query = "SELECT * FROM manual_decisions WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND decision_ts_utc >= ?"
            params.append(start_date)
        if end_date:
            query += " AND decision_ts_utc <= ?"
            params.append(end_date)
        
        query += " ORDER BY decision_ts_utc DESC"
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]
    
    def get_taken_trades(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_closed_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all taken trades with alert details.
        
        Args:
            start_date: Filter by decision timestamp (ISO format)
            end_date: Filter by decision timestamp (ISO format)
            include_closed_only: Only return trades with exit_price set
        
        Returns:
            List of dicts with combined manual_decisions + alerts_log data
        """
        query = """
            SELECT 
                md.*,
                al.symbol,
                al.timeframe,
                al.setup,
                al.direction,
                al.score,
                al.trigger_close,
                al.ts_utc as alert_ts,
                al.atr,
                al.invalidation
            FROM manual_decisions md
            JOIN alerts_log al ON md.alert_log_id = al.id
            WHERE md.decision = 'TAKEN'
        """
        params = []
        
        if start_date:
            query += " AND md.decision_ts_utc >= ?"
            params.append(start_date)
        if end_date:
            query += " AND md.decision_ts_utc <= ?"
            params.append(end_date)
        if include_closed_only:
            query += " AND md.exit_price IS NOT NULL"
        
        query += " ORDER BY md.decision_ts_utc DESC"
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        
        return [dict(row) for row in rows]
    
    def count_active_trades(
        self,
        hold_hours_by_timeframe: Dict[str, int],
        exclude_with_exit: bool = True,
    ) -> int:
        """
        Count currently "active" taken trades.
        
        A trade is active if:
        - decision = TAKEN
        - decision_ts + hold_window > now (not expired yet)
        - (optionally) exit_price IS NULL (not manually closed)
        
        Args:
            hold_hours_by_timeframe: Dict mapping timeframe to hold hours
            exclude_with_exit: If True, don't count trades with exit_price set
        
        Returns:
            Count of active trades
        """
        now = datetime.utcnow()
        
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            
            # Get all taken trades with their timeframe
            query = """
                SELECT md.decision_ts_utc, md.exit_price, al.timeframe
                FROM manual_decisions md
                JOIN alerts_log al ON md.alert_log_id = al.id
                WHERE md.decision = 'TAKEN'
            """
            
            if exclude_with_exit:
                query += " AND md.exit_price IS NULL"
            
            rows = conn.execute(query).fetchall()
        
        active_count = 0
        for row in rows:
            decision_ts = datetime.fromisoformat(row['decision_ts_utc'].replace('Z', '+00:00'))
            timeframe = row['timeframe']
            hold_hours = hold_hours_by_timeframe.get(timeframe, 24)
            
            # Check if still within hold window
            expiry = decision_ts + timedelta(hours=hold_hours)
            if now < expiry:
                active_count += 1
        
        return active_count
