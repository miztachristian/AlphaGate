"""
V2 Engine Module - Enhanced trade filtering with go/no-go gate.

This module provides secondary filtering for trade setups:
- GateStatus: GO, NO_GO, NOT_EVALUATED
- ScrutinyLevel: NORMAL, HIGH
- GateResult: Complete gate decision with reasons and tags

Engine Modes:
- v1: Legacy mode, gate is NOT evaluated (production default)
- shadow: Gate is evaluated and logged, but does NOT suppress alerts
- v2: Gate is enforced, NO_GO alerts are suppressed
"""

from src.v2.gate import (
    GateStatus,
    ScrutinyLevel,
    GateResult,
    GateFeatures,
    GateConfig,
    evaluate_gate,
    compute_gate_features,
)

__all__ = [
    "GateStatus",
    "ScrutinyLevel",
    "GateResult",
    "GateFeatures",
    "GateConfig",
    "evaluate_gate",
    "compute_gate_features",
]
