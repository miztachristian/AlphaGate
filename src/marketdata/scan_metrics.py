"""Scan metrics and observability.

Collects and reports metrics during universe scanning.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from threading import Lock
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class ScanMetrics:
    """Metrics collected during a scan run."""
    
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    
    total_tickers: int = 0
    tickers_scanned: int = 0
    
    cache_hits: int = 0
    cache_misses: int = 0
    
    rest_calls: int = 0
    rest_errors: int = 0
    rest_retries: int = 0
    
    bars_fetched_total: int = 0
    
    not_evaluated_reasons: Counter = field(default_factory=Counter)
    setups_triggered: int = 0
    alerts_sent: int = 0
    
    _lock: Lock = field(default_factory=Lock)
    
    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1
    
    def record_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1
    
    def record_rest_call(self, bars_fetched: int = 0) -> None:
        with self._lock:
            self.rest_calls += 1
            self.bars_fetched_total += bars_fetched
    
    def record_rest_error(self) -> None:
        with self._lock:
            self.rest_errors += 1
    
    def record_rest_retry(self) -> None:
        with self._lock:
            self.rest_retries += 1
    
    def record_not_evaluated(self, reason: str) -> None:
        with self._lock:
            self.not_evaluated_reasons[reason] += 1
    
    def record_setup_triggered(self) -> None:
        with self._lock:
            self.setups_triggered += 1
    
    def record_alert_sent(self) -> None:
        with self._lock:
            self.alerts_sent += 1
    
    def record_ticker_scanned(self) -> None:
        with self._lock:
            self.tickers_scanned += 1
    
    def finish(self) -> None:
        self.end_time = datetime.now(timezone.utc)
    
    @property
    def duration_seconds(self) -> float:
        if self.end_time is None:
            end = datetime.now(timezone.utc)
        else:
            end = self.end_time
        return (end - self.start_time).total_seconds()
    
    @property
    def avg_bars_per_call(self) -> float:
        if self.rest_calls == 0:
            return 0.0
        return self.bars_fetched_total / self.rest_calls
    
    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total
    
    def print_summary(self) -> None:
        """Print scan summary to console."""
        duration = self.duration_seconds
        minutes = int(duration // 60)
        seconds = duration % 60
        
        print("\n" + "=" * 60)
        print("📊 SCAN SUMMARY")
        print("=" * 60)
        
        print(f"\n⏱️  Duration: {minutes}m {seconds:.1f}s")
        print(f"📈 Tickers: {self.tickers_scanned}/{self.total_tickers} scanned")
        
        print(f"\n💾 Cache Performance:")
        print(f"   Hits: {self.cache_hits} | Misses: {self.cache_misses}")
        print(f"   Hit Rate: {self.cache_hit_rate:.1%}")
        
        print(f"\n🌐 REST API:")
        print(f"   Calls: {self.rest_calls}")
        print(f"   Errors: {self.rest_errors} | Retries: {self.rest_retries}")
        print(f"   Avg Bars/Call: {self.avg_bars_per_call:.1f}")
        print(f"   Total Bars Fetched: {self.bars_fetched_total:,}")
        
        print(f"\n🎯 Results:")
        print(f"   Setups Triggered: {self.setups_triggered}")
        print(f"   Alerts Sent: {self.alerts_sent}")
        
        if self.not_evaluated_reasons:
            print(f"\n⚠️  NOT_EVALUATED Reasons:")
            for reason, count in self.not_evaluated_reasons.most_common(10):
                print(f"   {reason}: {count}")
        
        print("=" * 60 + "\n")
    
    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_tickers": self.total_tickers,
            "tickers_scanned": self.tickers_scanned,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.cache_hit_rate,
            "rest_calls": self.rest_calls,
            "rest_errors": self.rest_errors,
            "rest_retries": self.rest_retries,
            "bars_fetched_total": self.bars_fetched_total,
            "avg_bars_per_call": self.avg_bars_per_call,
            "not_evaluated_reasons": dict(self.not_evaluated_reasons),
            "setups_triggered": self.setups_triggered,
            "alerts_sent": self.alerts_sent,
        }


# Global metrics instance for current scan
_current_metrics: Optional[ScanMetrics] = None
_metrics_lock = Lock()


def start_scan_metrics(total_tickers: int) -> ScanMetrics:
    """Start a new scan metrics collection."""
    global _current_metrics
    with _metrics_lock:
        _current_metrics = ScanMetrics(total_tickers=total_tickers)
        return _current_metrics


def get_current_metrics() -> Optional[ScanMetrics]:
    """Get the current scan metrics instance."""
    return _current_metrics


def finish_scan_metrics() -> Optional[ScanMetrics]:
    """Finish current scan metrics and return them."""
    global _current_metrics
    with _metrics_lock:
        if _current_metrics:
            _current_metrics.finish()
            return _current_metrics
        return None
