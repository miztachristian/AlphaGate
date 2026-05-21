"""Notifier interfaces + fan-out notifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol


class Notifier(Protocol):
    def send(self, title: str, message: str) -> None:
        ...


@dataclass
class MultiNotifier:
    notifiers: List[Notifier]

    def send(self, title: str, message: str) -> None:
        for n in self.notifiers:
            try:
                n.send(title, message)
            except Exception as e:
                # Catch failures (like SMTP timeouts) so we don't crash the app
                # and still attempt other notifiers (like Telegram)
                print(f"⚠️  Notification failure ({type(n).__name__}): {e}")
