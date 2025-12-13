"""SQLite-backed state store.

Used to prevent duplicate notifications (e.g., don't alert LONG every minute).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


class SqliteStateStore:
    def __init__(self, path: str = "state.db"):
        self.path = path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
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

    def record_alert(self, ticker: str, timeframe: str, signal: str, confidence: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO alerts(ticker, timeframe, signal, confidence, created_at) VALUES(?,?,?,?,?);",
                (ticker.upper(), timeframe, signal, confidence, datetime.utcnow().isoformat()),
            )
            conn.commit()
