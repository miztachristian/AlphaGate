"""Rate limiter for API calls.

Implements token bucket rate limiting with configurable requests per second.
Thread-safe for concurrent use.
"""

from __future__ import annotations

import time
import logging
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(
        self,
        max_requests_per_second: float = 10.0,
        burst_size: Optional[int] = None,
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests_per_second: Maximum sustained request rate
            burst_size: Max burst tokens (default: 2x rate)
        """
        self.rate = max_requests_per_second
        self.burst_size = burst_size or int(max_requests_per_second * 2)
        
        self._tokens = float(self.burst_size)
        self._last_update = time.monotonic()
        self._lock = Lock()
        
        logger.debug(f"Rate limiter initialized: {self.rate} req/s, burst={self.burst_size}")
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire a token, blocking if necessary.
        
        Args:
            timeout: Maximum time to wait for a token (None = wait forever)
        
        Returns:
            True if token acquired, False if timeout
        """
        start_time = time.monotonic()
        
        while True:
            with self._lock:
                # Refill tokens based on elapsed time
                now = time.monotonic()
                elapsed = now - self._last_update
                self._tokens = min(
                    self.burst_size,
                    self._tokens + elapsed * self.rate
                )
                self._last_update = now
                
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                
                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) / self.rate
            
            # Check timeout
            if timeout is not None:
                elapsed_total = time.monotonic() - start_time
                if elapsed_total + wait_time > timeout:
                    return False
            
            # Wait for token
            time.sleep(min(wait_time, 0.1))  # Check every 100ms max
    
    def try_acquire(self) -> bool:
        """Try to acquire a token without blocking."""
        return self.acquire(timeout=0)


class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(
        self,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
        retry_on_status: tuple = (429, 500, 502, 503, 504),
    ):
        """
        Initialize retry configuration.
        
        Args:
            max_retries: Maximum number of retry attempts
            backoff_base: Base delay for exponential backoff
            backoff_max: Maximum backoff delay
            retry_on_status: HTTP status codes to retry on
        """
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.retry_on_status = retry_on_status
    
    def get_delay(self, attempt: int) -> float:
        """Get delay for given attempt number (0-indexed)."""
        delay = self.backoff_base * (2 ** attempt)
        return min(delay, self.backoff_max)


def should_retry(status_code: int, config: RetryConfig) -> bool:
    """Check if request should be retried based on status code."""
    return status_code in config.retry_on_status
