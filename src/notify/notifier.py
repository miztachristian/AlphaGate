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
            n.send(title, message)
