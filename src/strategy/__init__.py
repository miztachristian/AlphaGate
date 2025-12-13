"""
Strategy Package
Trading strategy engine and rule definitions.
"""

from .engine import StrategyEngine
from .rules import evaluate_long_setup, evaluate_short_setup, combine_signals

__all__ = [
    'StrategyEngine',
    'evaluate_long_setup',
    'evaluate_short_setup',
    'combine_signals'
]
