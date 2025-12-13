"""State store for deduping alerts."""

from .sqlite_store import SqliteStateStore

__all__ = ["SqliteStateStore"]
