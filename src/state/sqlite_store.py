"""SQLite-backed state store.

Used to prevent duplicate notifications (e.g., don't alert LONG every minute).
Also logs alerts for calibration purposes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class SqliteStateStore:
    def __init__(self, path: str = "state.db"):
        self.path = path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
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

